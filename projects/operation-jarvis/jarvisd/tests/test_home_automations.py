"""Offline Home controls: private temp state, synthetic cloud peers, no writes to devices."""
import copy
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from jarvisd_core import automatic_voice as policy
from jarvisd_core.home_automations import HomeAutomations, validated

REF = '0' * 16
REV = 'a' * 64


class HomeAutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'automations'
        policy.initialize(self.root, enabled=True, barn_door_ref=REF)
        self.runner = Mock()
        self.manager = HomeAutomations(self.root, '/fixture/security', runner=self.runner, now=lambda: 100)
        self.addCleanup(self.manager.close)
        self.manager.cloud = {'enabled': False, 'revision': REV}
        self.manager.cloud_at = 100

    def command(self, control='automatic-voice', enabled=False, confirmed=False):
        revision = policy.current(self.root, legacy=False).revision if control == 'automatic-voice' else REV
        return {'control': control, 'enabled': enabled, 'revision': revision,
                'confirmed': confirmed, 'requestID': secrets.token_hex(16)}

    def send(self, command):
        return self.manager.submit(command, command['requestID'])

    def wait(self):
        for thread in list(self.manager.workers.values()):
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_master_only_changes_private_policy_and_preserves_binding(self):
        binding = (self.root / 'binding.json').read_bytes()
        result = self.send(self.command())
        self.assertEqual(result['homeAutomation']['status'], 'verified')
        self.assertFalse(policy.current(self.root, legacy=False).enabled)
        self.assertEqual(binding, (self.root / 'binding.json').read_bytes())
        self.runner.assert_not_called()

    def test_off_on_changes_generation_and_rejects_old_event(self):
        with patch.dict(os.environ, {'JARVIS_HOME_AUTOMATIONS_ROOT': str(self.root)}):
            revision = policy.current().revision
            self.assertTrue(policy.admitted('computer-arrival', revision))
            self.send(self.command())
            self.assertFalse(policy.admitted('computer-arrival', revision))
            self.send(self.command(enabled=True))
            self.assertFalse(policy.admitted('computer-arrival', revision))
            self.assertTrue(policy.admitted('doorbell-departure'))
            self.assertFalse(policy.admitted('interactive-response'))

    def test_missing_corrupt_and_insecure_policy_fail_closed_after_activation(self):
        for content in ('{}', '{invalid', json.dumps({'version': 1, 'enabled': 1, 'revision': 'a'*32})):
            (self.root / 'voice.json').write_text(content)
            self.assertIsNone(policy.current(self.root, legacy=False))
        (self.root / 'voice.json').unlink()
        self.assertIsNone(policy.current(self.root, legacy=False))
        missing = self.root / 'missing'
        self.assertIsNone(policy.current(missing, legacy=False))
        self.assertTrue(policy.current(missing, legacy=True).enabled)

    def test_private_paths_reject_symlinks_and_permissions(self):
        path = self.root / 'voice.json'
        path.chmod(0o644)
        self.assertIsNone(policy.current(self.root, legacy=False))
        path.unlink()
        path.symlink_to(self.root / 'binding.json')
        self.assertIsNone(policy.current(self.root, legacy=False))

    def test_stale_voice_revision_and_malformed_commands_do_not_write(self):
        command = self.command()
        self.send(self.command())
        with self.assertRaises(policy.PolicyError):
            self.send(command)
        for change in ({'control': 'execute'}, {'enabled': 0}, {'confirmed': 'yes'}, {'extra': True}):
            candidate = {**self.command(), **change}
            with self.assertRaises((ValueError, TypeError)):
                validated(candidate, candidate['requestID'])
        self.runner.assert_not_called()

    def test_duplicate_request_is_durable_and_cannot_be_repurposed(self):
        command = self.command()
        first = self.send(command)
        restarted = HomeAutomations(self.root, '/fixture/security', runner=self.runner)
        self.assertEqual(first, restarted.submit(command, command['requestID']))
        with self.assertRaises(policy.PolicyError):
            self.send({**command, 'enabled': True})
        self.runner.assert_not_called()

    def test_barn_enable_requires_confirmation_and_freshness(self):
        with self.assertRaises(policy.PolicyError):
            self.send(self.command('barn-door', enabled=True))
        self.manager.cloud_at = 0
        with self.assertRaises(policy.PolicyError):
            self.send(self.command('barn-door', enabled=True, confirmed=True))
        self.runner.assert_not_called()

    def test_barn_write_is_one_fixed_mutation_and_verified_readback(self):
        self.runner.return_value = {'result': 'write_verified', 'rule': {'ref': REF,
            'kind': 'automation', 'enabled': True, 'revision': 'b'*64}}
        command = self.command('barn-door', enabled=True, confirmed=True)
        result = self.send(command)
        self.assertEqual(result['homeAutomation']['status'], 'pending')
        self.wait()
        self.runner.assert_called_once_with(['enable', REF, '--revision', REV, '--confirm'])
        result = self.send(command)
        self.assertEqual(result['homeAutomation']['status'], 'verified')
        self.assertTrue(self.manager.snapshot()['barnDoor']['enabled'])

    def test_unknown_write_never_replayed_after_process_restart(self):
        self.runner.side_effect = TimeoutError()
        command = self.command('barn-door', enabled=True, confirmed=True)
        self.send(command)
        self.wait()
        self.assertEqual(self.send(command)['homeAutomation']['status'], 'unknown')
        restarted = HomeAutomations(self.root, '/fixture/security', runner=self.runner)
        restarted.submit(command, command['requestID'])
        self.runner.assert_called_once()

    def test_interrupted_pending_receipt_is_unknown_not_resumed(self):
        command = self.command('barn-door', enabled=True, confirmed=True)
        ledger = policy.read_json(self.root, 'requests.json')
        ledger['requests'][command['requestID']] = {**command, 'owner': 'old', 'at': 1, 'status': 'pending'}
        policy.save_json(self.root, 'requests.json', ledger)
        self.assertEqual(self.send(command)['homeAutomation']['status'], 'unknown')
        self.runner.assert_not_called()

    def test_missing_cloud_capability_never_promotes_read_only_security_launcher(self):
        manager = HomeAutomations(self.root, '', runner=self.runner, now=lambda: 100)
        self.assertFalse(manager.snapshot(active=True)['barnDoor']['available'])
        self.runner.assert_not_called()
        with self.assertRaises(policy.PolicyError):
            HomeAutomations(self.root, 'relative/launcher')

    def test_interrupted_resource_waits_for_fresh_read_not_cached_state(self):
        command = self.command('barn-door', enabled=True, confirmed=True)
        ledger = policy.read_json(self.root, 'requests.json')
        ledger['requests'][command['requestID']] = {**command, 'owner': 'prior-daemon', 'at': 1, 'status': 'pending'}
        policy.save_json(self.root, 'requests.json', ledger)
        self.assertTrue(self.manager.snapshot()['barnDoor']['blocked'])
        with self.assertRaises(policy.PolicyError):
            self.send(self.command('barn-door', enabled=True, confirmed=True))
        self.runner.assert_not_called()

    def test_fresh_cloud_read_retires_interrupted_receipt_without_replay(self):
        command = self.command('barn-door', enabled=True, confirmed=True)
        ledger = policy.read_json(self.root, 'requests.json')
        ledger['requests'][command['requestID']] = {**command, 'owner': 'prior-daemon', 'at': 1, 'status': 'pending'}
        policy.save_json(self.root, 'requests.json', ledger)
        self.runner.return_value = {'result': 'read_succeeded', 'rules': [{'ref': REF,
            'kind': 'automation', 'name': 'Barn Door Protocol', 'enabled': False, 'revision': REV}]}
        self.manager._read(REF)
        self.assertFalse(self.manager.snapshot()['barnDoor']['blocked'])
        self.assertEqual(self.send(command)['homeAutomation']['status'], 'unknown')
        self.runner.assert_called_once_with(['list'])

    def listing(self, enabled, revision=REV):
        return {'result': 'read_succeeded', 'rules': [{'ref': REF, 'kind': 'automation',
                'name': 'Barn door Protocol', 'enabled': enabled, 'revision': revision}]}

    def settled(self, status, enabled, at):
        command = self.command('barn-door', enabled=enabled, confirmed=True)
        ledger = policy.read_json(self.root, 'requests.json')
        ledger['requests'][command['requestID']] = {**command, 'owner': 'old', 'at': at, 'status': status}
        policy.save_json(self.root, 'requests.json', ledger)
        return command

    def test_pre_write_cli_rejection_is_rejected_not_unknown(self):
        self.runner.return_value = {'result': 'error', 'reason': 'smart_revision_conflict', 'writes_attempted': 0}
        command = self.command('barn-door', enabled=True, confirmed=True)
        self.send(command)
        self.wait()
        self.assertEqual(self.send(command)['homeAutomation']['status'], 'rejected')
        self.runner.assert_called_once()

    def test_later_read_matching_request_clears_stale_unknown_and_rejected(self):
        for status, at in (('unknown', 50), ('rejected', 60)):
            with self.subTest(status=status):
                command = self.settled(status, enabled=False, at=at)
                self.runner.reset_mock()
                self.runner.return_value = self.listing(False, 'c' * 64)
                self.manager._read(REF)
                op = self.manager.snapshot()['barnDoor']['operation']
                self.assertEqual((op['requestID'], op['status']), (command['requestID'], 'verified'))
                self.runner.assert_called_once_with(['list'])  # status only; never re-sent

    def test_later_read_mismatch_keeps_warning(self):
        command = self.settled('unknown', enabled=False, at=50)
        self.runner.return_value = self.listing(True)
        self.manager._read(REF)
        self.assertEqual(self.send(command)['homeAutomation']['status'], 'unknown')
        self.runner.assert_called_once_with(['list'])

    def test_read_not_strictly_after_receipt_does_not_clear_it(self):
        command = self.settled('unknown', enabled=False, at=100)  # now() is 100
        self.runner.return_value = self.listing(False)
        self.manager._read(REF)
        self.assertEqual(self.send(command)['homeAutomation']['status'], 'unknown')

    def test_local_policy_read_retires_old_receipt_without_toggling_voice(self):
        command = self.command(enabled=False)
        ledger = policy.read_json(self.root, 'requests.json')
        ledger['requests'][command['requestID']] = {**command, 'owner': 'prior-daemon', 'at': 1, 'status': 'pending'}
        policy.save_json(self.root, 'requests.json', ledger)
        before = (self.root / 'voice.json').read_bytes()
        self.assertFalse(self.manager.snapshot()['automaticVoice']['blocked'])
        self.assertEqual(self.send(command)['homeAutomation']['status'], 'unknown')
        self.assertEqual((self.root / 'voice.json').read_bytes(), before)
        self.runner.assert_not_called()

    def test_receipt_capacity_archives_without_forgetting_consumed_ids(self):
        ledger = policy.read_json(self.root, 'requests.json')
        commands = {}
        for _ in range(512):
            command = self.command()
            commands[command['requestID']] = command
            ledger['requests'][command['requestID']] = {**command, 'owner': self.manager.boot, 'at': 1, 'status': 'verified'}
        policy.save_json(self.root, 'requests.json', ledger)
        self.send(self.command())
        self.assertFalse(policy.current(self.root, legacy=False).enabled)
        self.assertEqual(len(policy.read_json(self.root, 'requests.json')['requests']), 512)
        archives = list(self.root.glob('receipt-*.json'))
        self.assertEqual(len(archives), 1)
        old_id = next(iter(json.loads(archives[0].read_text())['requests']))
        restarted = HomeAutomations(self.root, '/fixture/security', runner=self.runner)
        with patch.object(policy, 'set_enabled') as writer:
            self.assertEqual(restarted.submit(commands[old_id], old_id)['homeAutomation']['status'], 'verified')
            writer.assert_not_called()
        with self.assertRaises(policy.PolicyError):
            restarted.submit({**commands[old_id], 'enabled': True}, old_id)
        self.runner.assert_not_called()

    def test_archive_fsync_precedes_active_ledger_eviction(self):
        with patch('jarvisd_core.home_automations.MAX_REQUESTS', 1):
            first = self.command(enabled=True)
            self.send(first)
            save = policy.save_json
            def crash(root, name, value):
                if name == 'requests.json':
                    raise OSError('simulated crash before active replacement')
                return save(root, name, value)
            with patch.object(policy, 'save_json', side_effect=crash):
                with self.assertRaises(OSError):
                    self.send(self.command())
            self.assertTrue(policy.current(self.root, legacy=False).enabled)
            self.assertIn(first['requestID'], policy.read_json(self.root, 'requests.json')['requests'])
            self.assertTrue((self.root / ('receipt-' + first['requestID'] + '.json')).exists())
            self.send(self.command())  # Duplicate archive after crash is safe.
            self.assertFalse(policy.current(self.root, legacy=False).enabled)
            self.assertEqual(self.send(first)['homeAutomation']['status'], 'verified')

    def test_unreadable_archive_is_a_storage_problem_not_permission_to_replay(self):
        command = self.command()
        (self.root / ('receipt-' + command['requestID'] + '.json')).symlink_to(self.root / 'voice.json')
        with self.assertRaises(OSError):
            self.send(command)
        self.assertTrue(policy.current(self.root, legacy=False).enabled)
        self.runner.assert_not_called()

    def test_read_only_status_never_treats_off_as_failure(self):
        self.send(self.command())
        snapshot = self.manager.snapshot()
        self.assertTrue(snapshot['automaticVoice']['available'])
        self.assertFalse(snapshot['automaticVoice']['enabled'])
        self.assertFalse(snapshot['barnDoor']['enabled'])
        self.runner.assert_not_called()

    def test_shared_read_budget_pins_identity_and_never_logs_in(self):
        done = threading.Event()
        def listing(args):
            self.assertEqual(args, ['list'])
            done.set()
            return {'result': 'read_succeeded', 'rules': [{'ref': REF, 'kind': 'automation',
                'name': 'Barn door Protocol', 'enabled': True, 'revision': REV}]}
        self.runner.side_effect = listing
        self.manager.snapshot(active=True)
        self.assertTrue(done.wait(2))
        # Waiting through the coordinator lock observes settled read state.
        for _ in range(100):
            if not self.manager.reading:
                break
            threading.Event().wait(.001)
        self.manager.snapshot(active=True)
        self.assertTrue(self.manager.snapshot()['barnDoor']['enabled'])
        self.runner.assert_called_once()

    def test_missing_or_wrong_rule_never_falls_back_by_name(self):
        self.runner.return_value = {'result': 'read_succeeded', 'rules': [{'ref': '1'*16,
            'name': 'Barn door Protocol', 'enabled': True, 'kind': 'automation', 'revision': REV}]}
        self.manager._read(REF)
        self.assertIsNone(self.manager.snapshot()['barnDoor']['enabled'])

    def test_receipt_reservation_failure_prevents_any_mutation(self):
        with patch.object(policy, 'save_json', side_effect=OSError()):
            with self.assertRaises(OSError):
                self.send(self.command('barn-door', enabled=True, confirmed=True))
        self.runner.assert_not_called()


class HomeAutomationHTTPTests(unittest.TestCase):
    def setUp(self):
        import http.client
        from test_jarvisd import jarvisd
        self.http = http.client
        self.daemon = jarvisd
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / 'controls'
        policy.initialize(root, enabled=True, barn_door_ref=REF)
        self.runner = Mock()
        self.manager = HomeAutomations(root, '/fixture/security', runner=self.runner)
        self.server = jarvisd.ThreadingHTTPServer(('127.0.0.1', 0), jarvisd.Handler)
        self.server.home_automations = self.manager
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.log = patch.object(jarvisd.Handler, 'log_message')
        self.log.start(); self.addCleanup(self.log.stop)
        self.thread.start(); self.addCleanup(self.stop)
        self.command = {'control': 'automatic-voice', 'enabled': False, 'confirmed': False,
            'revision': policy.current(root, legacy=False).revision, 'requestID': secrets.token_hex(16)}

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2); self.manager.close()

    def exchange(self, payload=None, request_id=None):
        connection = self.http.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        connection.request('POST', '/api/v1/home-automation-command', json.dumps(payload or self.command),
            {'Content-Type': 'application/json', 'x-jarvis-request-id': request_id or self.command['requestID']})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_missing_auth_cannot_change_policy(self):
        with patch.object(self.daemon.Handler, '_authorized', return_value=False):
            self.assertIn(self.exchange()[0], (401, 403))
        self.assertTrue(policy.current(self.manager.root, legacy=False).enabled)

    def test_native_route_uses_persisted_identity_and_never_generic_dispatch(self):
        with patch.object(self.daemon.Handler, '_auth_or_respond', return_value=True), \
                patch.object(self.daemon, 'dispatch_command') as dispatch:
            first = self.exchange()
            second = self.exchange()
            self.assertEqual(first, second)
            self.assertEqual(first[0], 200)
            dispatch.assert_not_called()
            self.runner.assert_not_called()

    def test_bad_request_identity_and_extra_capabilities_never_dispatch(self):
        with patch.object(self.daemon.Handler, '_auth_or_respond', return_value=True):
            self.assertEqual(self.exchange(request_id='bad')[0], 400)
            self.assertEqual(self.exchange({**self.command, 'action': 'execute'})[0], 409)
        self.runner.assert_not_called()
        self.assertTrue(policy.current(self.manager.root, legacy=False).enabled)

    def test_cached_state_projection_does_not_trigger_cloud_refresh(self):
        with patch.object(self.daemon.Handler, '_auth_or_respond', return_value=True), \
                patch.object(self.daemon, '_with_system_health', side_effect=lambda value: value), \
                patch.object(self.daemon.STATE_COORDINATOR, 'snapshot', return_value={'ok': True}):
            connection = self.http.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
            connection.request('GET', '/api/v1/state?mode=cached')
            response = connection.getresponse()
            self.assertTrue(json.loads(response.read())['homeAutomations']['automaticVoice']['enabled'])
            connection.close()
        self.runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
