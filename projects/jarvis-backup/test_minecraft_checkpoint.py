import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from minecraft_checkpoint import MinecraftCheckpoint, sha256
import restic_backup as b


class MinecraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / 'source'
        self.relative = 'projects/minecraft-server'
        self.root = self.source / self.relative
        self.world = self.root / 'server/world'
        self.state = self.base / 'state'
        self.state.mkdir()
        files = {'server/paper.jar': b'jar fixture',
                 'server/server.properties': b'server-ip=192.168.21.110\nserver-port=25565\nonline-mode=false\nwhite-list=true\nenforce-whitelist=true\n',
                 'server/whitelist.json': b'[]', 'server/plugins/floodgate/key.pem': b'fixture only',
                 'server/world/level.dat': b'level fixture',
                 'server/world/players/data/player.dat': b'player inventory fixture'}
        for dimension in ['overworld', 'the_nether', 'the_end']:
            prefix = 'server/world/dimensions/minecraft/' + dimension
            files[prefix + '/region/r.0.0.mca'] = b'region fixture ' + dimension.encode()
            files[prefix + '/data/minecraft/world_gen_settings.dat'] = b'seed fixture'
        for rel, content in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.settings = {'relative_path': self.relative, 'screen_session': 'minecraft',
                         'java_host': '192.168.21.110', 'java_port': 25565}
        self.checkpoint = MinecraftCheckpoint(self.source, self.state, self.settings, time.monotonic() + 60)
        self.owner = {'pid': '123', 'session': '456.minecraft'}
        self.off = 'Automatic saving is now disabled'
        self.on = 'Automatic saving is now enabled'

    def test_endpoint_and_security_mismatches_fail_before_console_write(self):
        properties = self.root / 'server/server.properties'
        original = properties.read_text().splitlines()
        cases = [('server-ip', '192.168.21.198'), ('server-ip', '0.0.0.0'),
                 ('server-ip', ''), ('server-ip', None), ('server-port', '25566'),
                 ('online-mode', 'true'), ('white-list', 'false'),
                 ('enforce-whitelist', 'false')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                lines = [line for line in original if not line.startswith(key + '=')]
                if value is not None:
                    lines.append(f'{key}={value}')
                properties.write_text('\n'.join(lines) + '\n')
                with patch.object(self.checkpoint, 'running_info') as running, \
                     patch.object(self.checkpoint, 'command') as command:
                    with self.assertRaisesRegex(RuntimeError, key + ': expected .*found'):
                        self.checkpoint.create()
                running.assert_not_called()
                command.assert_not_called()
                self.assertFalse(self.checkpoint.marker.exists())
                self.assertFalse(self.checkpoint.stage.exists())

    def test_lan_change_requires_explicit_matching_policy_without_relaxing_security(self):
        properties = self.root / 'server/server.properties'
        properties.write_text(properties.read_text().replace('192.168.21.110', '192.168.21.198'))
        with self.assertRaisesRegex(RuntimeError, "server-ip: expected '192.168.21.110', found '192.168.21.198'"):
            self.checkpoint.validate()
        settings = dict(self.settings, java_host='192.168.21.198')
        migrated = MinecraftCheckpoint(self.source, self.state, settings, time.monotonic() + 60)
        migrated.validate()
        properties.write_text(properties.read_text().replace('enforce-whitelist=true', 'enforce-whitelist=false'))
        with self.assertRaisesRegex(RuntimeError, 'enforce-whitelist: expected .*found'):
            migrated.validate()

    def test_stopped_world_is_frozen_and_all_samples_verified(self):
        with patch.object(self.checkpoint, 'running_info', return_value=None):
            manifest = self.checkpoint.create()
        self.assertEqual(manifest['mode'], 'stopped-apfs-clone')
        self.assertEqual(len(manifest['samples']), 8)
        (self.world / 'level.dat').write_bytes(b'changed live world')
        for sample in manifest['samples']:
            self.assertEqual(sha256(self.checkpoint.stage / sample['relative_path']), sample['sha256'])
        self.assertEqual((self.checkpoint.stage / self.relative / 'server/world/level.dat').read_bytes(), b'level fixture')

    def test_live_checkpoint_restores_saves_before_return(self):
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch.object(self.checkpoint, 'command', side_effect=[self.off, 'Saved the game', self.on]) as command:
            result = self.checkpoint.create()
        self.assertEqual([call.args[1] for call in command.call_args_list], ['save-off', 'save-all flush', 'save-on'])
        self.assertEqual(result['mode'], 'save-paused-apfs-clone')
        self.assertFalse(self.checkpoint.marker.exists())

    def test_clone_failure_restores_saving(self):
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch.object(self.checkpoint, 'command', side_effect=[self.off, 'Saved the game', self.on]) as command, \
             patch.object(self.checkpoint, 'clone_world', side_effect=RuntimeError('clone failed')):
            with self.assertRaisesRegex(RuntimeError, 'clone failed'):
                self.checkpoint.create()
        self.assertEqual(command.call_args.args[1], 'save-on')
        self.assertFalse(self.checkpoint.marker.exists())

    def test_flush_unknown_restores_saving_without_replay(self):
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch.object(self.checkpoint, 'command', side_effect=[self.off, RuntimeError('flush unknown'), self.on]) as command:
            with self.assertRaisesRegex(RuntimeError, 'flush unknown'):
                self.checkpoint.create()
        self.assertEqual([call.args[1] for call in command.call_args_list], ['save-off', 'save-all flush', 'save-on'])
        self.assertFalse(self.checkpoint.marker.exists())

    def test_sigterm_restores_saving(self):
        def interrupted():
            os.kill(os.getpid(), signal.SIGTERM)
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch.object(self.checkpoint, 'command', side_effect=[self.off, 'Saved the game', self.on]) as command, \
             patch.object(self.checkpoint, 'clone_world', side_effect=interrupted):
            with self.assertRaises(InterruptedError):
                self.checkpoint.create()
        self.assertEqual(command.call_args.args[1], 'save-on')
        self.assertFalse(self.checkpoint.marker.exists())

    def test_already_disabled_is_not_taken_over(self):
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch.object(self.checkpoint, 'command', return_value='Saving is already turned off') as command, \
             patch.object(self.checkpoint, 'clone_world') as clone:
            with self.assertRaisesRegex(RuntimeError, 'already disabled'):
                self.checkpoint.create()
        command.assert_called_once()
        clone.assert_not_called()
        self.assertFalse(self.checkpoint.marker.exists())

    def test_unknown_save_on_blocks_future_backups(self):
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch.object(self.checkpoint, 'command', side_effect=[self.off, 'Saved the game', RuntimeError('save-on unknown')]):
            with self.assertRaisesRegex(RuntimeError, 'save-on unknown'):
                self.checkpoint.create()
        self.assertTrue(self.checkpoint.marker.exists())
        with self.assertRaisesRegex(RuntimeError, 'autosave-state review'):
            self.checkpoint.validate()

    def test_interrupted_checkpoint_marker_is_not_silent_success(self):
        self.checkpoint.marker.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.checkpoint.create()

    def test_missing_or_external_world_is_rejected(self):
        (self.world / 'level.dat').unlink()
        with self.assertRaisesRegex(RuntimeError, 'source missing'):
            self.checkpoint.validate()
        (self.world / 'level.dat').write_bytes(b'level')
        (self.world / 'external').symlink_to(self.base)
        with patch.object(self.checkpoint, 'running_info', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                self.checkpoint.create()

    def test_other_server_identity_receives_no_console_write(self):
        with patch.object(self.checkpoint, 'running_info', return_value={'pid': 'other'}), \
             patch('minecraft_checkpoint.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                self.checkpoint.command(self.owner, 'save-off', [self.off])
        run.assert_not_called()

    def test_player_chat_cannot_spoof_save_acknowledgement(self):
        log = self.root / 'server/logs/latest.log'
        log.parent.mkdir()
        log.write_text('')
        def chat(*args, **kwargs):
            log.write_text('[12:00:00] [Server thread/INFO]: <player> Automatic saving is now disabled\n')
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=chat) as run:
            with self.assertRaisesRegex(RuntimeError, 'did not acknowledge'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.2)
        run.assert_called_once()

    def log_fixture(self, text=''):
        log = self.root / 'server/logs/latest.log'
        log.parent.mkdir(exist_ok=True)
        log.write_text(text)
        return log

    def ack_line(self, marker):
        return f'[12:00:00] [Server thread/INFO]: {marker}\n'

    def test_daily_rollover_reads_fresh_ack_without_command_replay(self):
        log = self.log_fixture('previous day\n')
        def rotate(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
            log.write_text(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run:
            self.assertEqual(self.checkpoint.command(self.owner, 'save-off', [self.off]), self.off)
        run.assert_called_once()

    def test_ack_in_original_log_survives_rollover(self):
        log = self.log_fixture('previous day\n')
        def rotate(*args, **kwargs):
            with log.open('a') as f:
                f.write(self.ack_line(self.off))
            log.rename(log.with_name('previous.log'))
            log.write_text('new day\n')
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run:
            self.assertEqual(self.checkpoint.command(self.owner, 'save-off', [self.off]), self.off)
        run.assert_called_once()

    def test_stale_ack_before_command_is_not_accepted(self):
        self.log_fixture(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'did not acknowledge'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_rollover_to_preexisting_log_rejects_stale_ack(self):
        log = self.log_fixture('previous day\n')
        stale = log.with_name('stale.log')
        stale.write_text(self.ack_line(self.off))
        def replace(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
            stale.rename(log)
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=replace) as run:
            with self.assertRaisesRegex(RuntimeError, 'not newly created'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_rollover_does_not_accept_player_chat_or_replay(self):
        log = self.log_fixture('previous day\n')
        def rotate(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
            log.write_text(f'[12:00:00] [Server thread/INFO]: <player> {self.off}\n')
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run:
            with self.assertRaisesRegex(RuntimeError, 'did not acknowledge'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_rollover_tolerates_brief_missing_latest_log(self):
        log = self.log_fixture('previous day\n')
        def rotate(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
        def finish_rotation(*args):
            log.write_text(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run, \
             patch('minecraft_checkpoint.time.sleep', side_effect=finish_rotation):
            self.assertEqual(self.checkpoint.command(self.owner, 'save-off', [self.off]), self.off)
        run.assert_called_once()

    def test_partial_ack_requires_complete_line(self):
        log = self.log_fixture()
        line = self.ack_line(self.off)
        def partial(*args, **kwargs):
            log.write_text(line.rstrip('\n'))
        def finish(*args):
            with log.open('a') as f:
                f.write('\n')
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=partial) as run, \
             patch('minecraft_checkpoint.time.sleep', side_effect=finish) as sleep:
            self.assertEqual(self.checkpoint.command(self.owner, 'save-off', [self.off]), self.off)
        self.assertTrue(sleep.called)
        run.assert_called_once()

    def test_partial_lines_are_not_joined_across_rotated_logs(self):
        log = self.log_fixture()
        def rotate(*args, **kwargs):
            log.write_text('[12:00:00] [Server thread/INFO]: Automatic saving ')
            log.rename(log.with_name('previous.log'))
            log.write_text('is now disabled\n')
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run:
            with self.assertRaisesRegex(RuntimeError, 'did not acknowledge'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_truncation_fails_closed_without_replay(self):
        log = self.log_fixture('old log ' * 100)
        def truncate(*args, **kwargs):
            log.write_text(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=truncate) as run:
            with self.assertRaisesRegex(RuntimeError, 'truncated'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_changed_owner_cannot_supply_ack_after_console_write(self):
        log = self.log_fixture()
        def reply(*args, **kwargs):
            log.write_text(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', side_effect=[self.owner, {'pid': 'other'}]), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=reply) as run:
            with self.assertRaisesRegex(RuntimeError, 'process identity changed'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_rollover_requires_unchanged_server_owner(self):
        log = self.log_fixture('previous day\n')
        def rotate(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
            log.write_text(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', side_effect=[self.owner, {'pid': 'other'}]), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run:
            with self.assertRaisesRegex(RuntimeError, 'process identity changed'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_rollover_rejects_symlinked_log(self):
        log = self.log_fixture('previous day\n')
        target = self.base / 'other.log'
        target.write_text(self.ack_line(self.off))
        def replace(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
            log.symlink_to(target)
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=replace) as run:
            with self.assertRaisesRegex(RuntimeError, 'not a regular file'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_repeated_rollover_fails_closed_without_replay(self):
        log = self.log_fixture('previous day\n')
        def rotate(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
            log.write_text('new day\n')
        def second_rotation(*args):
            log.rename(log.with_name('second.log'))
            log.write_text(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run, \
             patch('minecraft_checkpoint.time.sleep', side_effect=second_rotation):
            with self.assertRaisesRegex(RuntimeError, 'rotated repeatedly'):
                self.checkpoint.command(self.owner, 'save-off', [self.off])
        run.assert_called_once()

    def test_rollover_without_creation_evidence_fails_closed(self):
        from types import SimpleNamespace
        log = self.log_fixture('previous day\n')
        original_fstat = os.fstat
        def metadata(fd):
            info = original_fstat(fd)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size)
        def rotate(*args, **kwargs):
            log.rename(log.with_name('previous.log'))
            log.write_text(self.ack_line(self.off))
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=rotate) as run, \
             patch('minecraft_checkpoint.os.fstat', side_effect=metadata):
            with self.assertRaisesRegex(RuntimeError, 'not newly created'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_oversized_partial_log_line_fails_closed_without_replay(self):
        log = self.log_fixture()
        def reply(*args, **kwargs):
            log.write_bytes(b'x' * 65537)
        with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
             patch('minecraft_checkpoint.subprocess.run', side_effect=reply) as run, \
             patch('minecraft_checkpoint.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'exceeds checkpoint limit'):
                self.checkpoint.command(self.owner, 'save-off', [self.off], timeout=0.02)
        run.assert_called_once()

    def test_live_checkpoint_restores_autosave_with_rollover_at_each_command(self):
        import shutil
        replies = {'save-off': self.off, 'save-all flush': 'Saved the game', 'save-on': self.on}
        for rotate_at in replies:
            with self.subTest(rotate_at=rotate_at):
                log = self.log_fixture('previous day\n')
                def console(args, **kwargs):
                    command = args[-1].rstrip('\r')
                    if command == rotate_at:
                        log.rename(log.with_name('previous.log'))
                    with log.open('a') as f:
                        f.write(self.ack_line(replies[command]))
                def clone():
                    destination = self.checkpoint.stage / self.checkpoint.world_relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(self.world, destination)
                with patch.object(self.checkpoint, 'running_info', return_value=self.owner), \
                     patch('minecraft_checkpoint.subprocess.run', side_effect=console) as run, \
                     patch.object(self.checkpoint, 'clone_world', side_effect=clone):
                    manifest = self.checkpoint.create()
                self.assertEqual([call.args[0][-1] for call in run.call_args_list],
                                 ['save-off\r', 'save-all flush\r', 'save-on\r'])
                self.assertEqual(manifest['mode'], 'save-paused-apfs-clone')
                self.assertFalse(self.checkpoint.marker.exists())

    def test_ambiguous_listener_receives_no_console_write(self):
        with patch('minecraft_checkpoint.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0, '456.minecraft (Detached)', ''),
                subprocess.CompletedProcess([], 0, '123\n456\n', '')]):
            with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
                self.checkpoint.running_info()

    def test_actual_binary_ownership_does_not_depend_on_process_title(self):
        expected = 'n' + str((self.root / 'java/current/bin/java').resolve())
        def output(args, **kwargs):
            if '-d' in args and args[args.index('-d') + 1] == 'txt':
                return 'p123\nftxt\n' + expected + '\n'
            if '-d' in args:
                return 'p123\nfcwd\nn' + str(self.root / 'server') + '\n'
            return 'Sun Oct 4 16:50:00 2026\n'
        with patch('minecraft_checkpoint.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0, '456.minecraft (Detached)', ''),
                subprocess.CompletedProcess([], 0, '123\n', '')]), \
             patch('minecraft_checkpoint.subprocess.check_output', side_effect=output):
            owner = self.checkpoint.running_info()
        self.assertEqual(owner['pid'], '123')
        self.assertIn('started', owner)

    def test_overlap_sends_no_save_commands(self):
        lock_path = self.root / 'backups/world-checkpoint.lock'
        lock_path.parent.mkdir()
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(self.checkpoint, 'command') as command:
                with self.assertRaisesRegex(RuntimeError, 'Another Minecraft'):
                    self.checkpoint.create()
            command.assert_not_called()

    @unittest.skipUnless(__import__('shutil').which('restic'), 'restic required')
    def test_unified_repository_restores_frozen_world_and_committed_sqlite(self):
        import sqlite3
        import shutil
        for rel, contents in {'README.md': 'fixture readme', '.env': 'TEST=fixture',
                              'projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py': '# fixture',
                              'projects/operation-jarvis/data/scheduler/scheduler.sqlite': 'fixture, not sqlite',
                              'projects/jarvis-backup/policy.json': (b.HERE / 'policy.json').read_text()}.items():
            p = self.source / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(contents)
        dbfile = self.root / 'server/plugins/DHSupport/data.sqlite'
        dbfile.parent.mkdir(parents=True)
        with sqlite3.connect(dbfile) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE records(value TEXT)')
            db.execute("INSERT INTO records VALUES ('committed world cache')")
            db.commit()
            password = self.base / 'password'
            password.write_text('fixture only')
            password.chmod(0o600)
            config = self.base / 'config.json'
            config.write_text(json.dumps({'source': str(self.source), 'state_dir': str(self.state),
                              'repository': str(self.base / 'repository'), 'password_file': str(password),
                              'rclone_config': str(self.base / 'rclone.conf'), 'host': 'fixture',
                              'restic': shutil.which('restic'), 'minecraft': self.settings}))
            backup = b.Backup(config, 120)
            with backup.locked(), patch.object(MinecraftCheckpoint, 'running_info', return_value=None):
                backup.run(['init'])
                backup.backup()
                snapshot = backup.load_state()['snapshot_id']
                listing = backup.run(['ls', snapshot])
                self.assertNotIn(str(self.world / 'level.dat'), listing)
                self.assertIn(str(backup.minecraft_stage / self.relative / 'server/world/level.dat'), listing)
                self.assertNotIn(str(dbfile), listing)
                self.assertIn(str(backup.stage / self.relative / 'server/plugins/DHSupport/data.sqlite'), listing)
                (self.world / 'level.dat').write_bytes(b'changed live file')
                (backup.minecraft_stage / self.relative / 'server/world/level.dat').write_bytes(b'changed current staging')
                backup.verify(snapshot)

    def test_policy_preserves_complete_runtime_and_recovery_keys(self):
        policy = json.loads((b.HERE / 'policy.json').read_text())
        for rel in ['node/node-v22/lib/node_modules/npm/node_modules/foo',
                    'jarvis-bot/node_modules/mineflayer', '.pi/omlx-api.key',
                    'backups/restic-password', 'server/plugins/DHSupport/data.sqlite',
                    'server/plugins/floodgate/key.pem', 'agent-memory/memories.json']:
            self.assertFalse(b.excluded(Path(self.relative) / rel, policy), rel)
        for rel in ['downloads', 'backups/restic-cache', 'server/logs',
                    '.pi/sessions', 'data/pi-agent/sessions', 'server/libraries']:
            self.assertTrue(b.excluded(Path(self.relative) / rel, policy), rel)


if __name__ == '__main__':
    os.umask(0o077)
    unittest.main()
