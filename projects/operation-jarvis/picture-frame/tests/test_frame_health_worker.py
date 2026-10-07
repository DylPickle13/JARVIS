"""Offline network-only worker proof; no ADB, live config, LAN or photos."""
import contextlib
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import health_worker

CONFIG = {'schema_version': 1, 'policy': 'owner_approved_frame_lan_presence',
          'ipv4': '192.168.1.99', 'mac_address': '02:00:00:00:00:09', 'interface': 'en1'}
SUMMARY = b'1 packets transmitted, 1 packets received, 0.0% packet loss\n'
ARP = b'? (192.168.1.99) at 2:0:0:0:0:9 on en1 ifscope [ethernet]\n'


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.config = self.root / 'network-health.json'
        self.lock = self.root / 'controller.lock'
        self.lock.touch(mode=0o600)
        self.value = copy.deepcopy(CONFIG)
        self.save()
        self.calls = []
        self.ping = subprocess.CompletedProcess([], 0, SUMMARY, b'')
        self.arp = subprocess.CompletedProcess([], 0, ARP, b'')

    def save(self):
        self.config.write_text(json.dumps(self.value))
        self.config.chmod(0o600)

    def run_command(self, argv, timeout):
        self.calls.append((argv, timeout))
        result = self.ping if argv[0] == '/sbin/ping' else self.arp
        if isinstance(result, Exception):
            raise result
        return result

    def check(self):
        original_import = __import__
        def guard(name, *args, **kwargs):
            if name in ('frame_control', 'frame_tcp') or name.startswith(('adb_shell', 'cryptography')):
                raise AssertionError('Network health must never load an ADB/control dependency')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guard), \
             patch.object(health_worker, '_run', side_effect=self.run_command):
            return health_worker.check_frame(self.config)

    def test_dry_run_no_import_read_state_dependency_or_network(self):
        original_import = __import__
        def guard(name, *args, **kwargs):
            if name in ('frame_control', 'frame_tcp', 'subprocess', 'pathlib', 'fcntl', 'ipaddress'):
                raise AssertionError('Dry-run has no deferred imports')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guard), \
             patch('builtins.open', side_effect=AssertionError), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError), \
             patch.object(Path, 'mkdir', side_effect=AssertionError), \
             patch.object(health_worker, '_run', side_effect=AssertionError):
            result = health_worker.main([])
        self.assertEqual(result['operation'], 'frame-network-reachability')
        self.assertFalse(result['device_contacted'])
        self.assertFalse(result['runtime_read'])

    def test_success_exact_interface_bound_single_echo_and_single_neighbor_query(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(self.check(), {'ok': True, 'reason': None})
        self.assertEqual(self.calls, [(['/sbin/ping', '-n', '-c', '1', '-t', '2', '-W',
            '1000', '-b', 'en1', CONFIG['ipv4']], 3.0),
            (['/usr/sbin/arp', '-n', '-i', 'en1', CONFIG['ipv4']], 1.0)])
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)
        self.assertNotIn(CONFIG['ipv4'], json.dumps(self.check()))

    def test_valid_packet_loss_is_unavailable_not_last_good(self):
        self.ping = subprocess.CompletedProcess([], 2,
            b'1 packets transmitted, 0 packets received, 100.0% packet loss\n', b'')
        self.assertEqual(self.check(), {'ok': False, 'reason': 'read_failed'})
        self.assertEqual(len(self.calls), 2)

    def test_wrong_mac_is_unknown_even_if_endpoint_answers_or_drops_echo(self):
        self.arp.stdout = ARP.replace(b'2:0:0:0:0:9', b'2:0:0:0:0:a')
        for code, count in ((0, b'1'), (2, b'0')):
            self.ping.returncode = code
            self.ping.stdout = b'1 packets transmitted, ' + count + b' packets received,\n'
            self.assertEqual(self.check(), {'ok': None, 'reason': 'identity_unverified'})

    def test_arp_cache_alone_never_proves_online(self):
        self.ping = subprocess.CompletedProcess([], 2,
            b'1 packets transmitted, 0 packets received, 100.0% packet loss\n', b'')
        self.assertFalse(self.check()['ok'])

    def test_fresh_reply_with_absent_os_neighbor_is_address_reachability_only(self):
        for arp in (subprocess.CompletedProcess([], 1,
                b'192.168.1.99 (192.168.1.99) -- no entry\n', b''),
                subprocess.CompletedProcess([], 1,
                b'192.168.1.99 (192.168.1.99) -- no entry on en1\n', b''),
                subprocess.CompletedProcess([], 0,
                b'? (192.168.1.99) at (incomplete) on en1 ifscope [ethernet]\n', b'')):
            self.arp = arp
            self.assertEqual(self.check(), {'ok': True, 'reason': None})

    def test_absent_neighbor_and_valid_loss_is_unavailable(self):
        self.arp = subprocess.CompletedProcess([], 1,
            b'192.168.1.99 (192.168.1.99) -- no entry\n', b'')
        self.ping = subprocess.CompletedProcess([], 2,
            b'1 packets transmitted, 0 packets received, 100.0% packet loss\n', b'')
        self.assertEqual(self.check(), {'ok': False, 'reason': 'read_failed'})

    def test_interface_address_malformed_duplicate_or_failed_neighbor_is_unknown(self):
        for output in (ARP.replace(b'en1', b'en2'), ARP.replace(b'1.99', b'1.98'),
                       ARP + ARP, b'private raw error', ARP.replace(b'2:0:0:0:0:9', b'2:0:9')):
            self.arp = subprocess.CompletedProcess([], 0, output, b'')
            self.assertIsNone(self.check()['ok'])
        self.arp = subprocess.CompletedProcess([], 1, b'private raw error', b'denied')
        self.assertIsNone(self.check()['ok'])

    def test_permissions_route_failures_and_invalid_ping_output_are_unknown(self):
        for code, out, err in ((0, SUMMARY, b'Operation not permitted'),
                              (2, b'private output', b'No route to host'),
                              (0, b'not a reply', b''), (0, SUMMARY + SUMMARY, b''),
                              (0, b'x' * 4097, b''), (1, SUMMARY, b'')):
            self.ping = subprocess.CompletedProcess([], code, out, err)
            self.assertEqual(self.check(), {'ok': None, 'reason': 'check_failed'})
        self.assertTrue(all(argv[0] == '/sbin/ping' for argv, _ in self.calls))

    def test_timeout_and_launch_error_never_retry(self):
        for error, reason in ((subprocess.TimeoutExpired('private command', 3), 'worker_timeout'),
                              (PermissionError('private path'), 'check_failed')):
            self.calls.clear()
            self.ping = error
            self.assertEqual(self.check(), {'ok': None, 'reason': reason})
            self.assertEqual(len(self.calls), 1)

    def test_neighbor_timeout_is_unknown_without_repeating_ping(self):
        self.arp = subprocess.TimeoutExpired('private command', 1)
        self.assertEqual(self.check(), {'ok': None, 'reason': 'worker_timeout'})
        self.assertEqual(len(self.calls), 2)

    def test_configuration_rejects_nonprivate_dns_ports_injection_and_unknown_fields(self):
        changes = ({'ipv4': 'example.com'}, {'ipv4': '8.8.8.8'}, {'ipv4': '127.0.0.1'},
            {'ipv4': '169.254.1.2'}, {'ipv4': '192.168.1.99:5555'}, {'ipv4': '::1'},
            {'ipv4': '192.168.001.099'}, {'interface': 'en1;touch /tmp/no'},
            {'interface': 'lo0'}, {'mac_address': '00:00:00:00:00:00'},
            {'mac_address': 'ff:ff:ff:ff:ff:ff'}, {'mac_address': '01:00:00:00:00:01'},
            {'mac_address': '02:00:00:00:00:0G'}, {'port': 5555}, {'schema_version': True},
            {'policy': 'adb'}, {'command': 'input'}, {'ipv4': None})
        for change in changes:
            self.value = {**CONFIG, **change}; self.save()
            with self.subTest(change=change):
                self.assertEqual(self.check(), {'ok': None, 'reason': 'configuration_unavailable'})
        self.assertEqual(self.calls, [])

    def test_invalid_large_or_missing_config_never_contacts_network(self):
        for value in ('invalid', '[]', '{}', 'x' * 4097):
            self.config.write_text(value)
            self.assertIsNone(self.check()['ok'])
        self.config.unlink()
        self.assertIsNone(self.check()['ok'])
        self.assertFalse(self.config.exists())
        self.assertEqual(self.calls, [])

    def test_missing_shared_symlink_or_fifo_state_is_not_created_or_repaired(self):
        self.lock.unlink()
        self.assertIsNone(self.check()['ok'])
        self.assertFalse(self.lock.exists())
        self.lock.touch(mode=0o600)
        for p in (self.lock, self.config):
            p.chmod(0o644)
            self.assertIsNone(self.check()['ok']); p.chmod(0o600)
            target = p.with_suffix('.old'); p.rename(target); p.symlink_to(target)
            self.assertIsNone(self.check()['ok']); p.unlink(); target.rename(p)
        self.config.unlink(); os.mkfifo(self.config, 0o600)
        self.assertIsNone(self.check()['ok'])
        self.assertEqual(self.calls, [])

    def test_shared_runtime_is_rejected(self):
        self.root.chmod(0o755)
        self.assertIsNone(self.check()['ok'])
        self.assertEqual(self.calls, [])

    def test_busy_is_unknown_without_probe_or_state_changes(self):
        with self.lock.open('r') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.check(), {'ok': None, 'reason': 'device_busy'})
        self.assertEqual(self.calls, [])

    def test_controller_keys_photos_and_pending_are_never_read_or_changed(self):
        for name in ('config.json', 'pending.json', 'adbkey', 'photo.jpg'):
            (self.root / name).write_text('synthetic forbidden read')
        original = os.open
        def guard(path, flags, *args, **kwargs):
            self.assertIn(Path(path).name, ('controller.lock', 'network-health.json'))
            return original(path, flags, *args, **kwargs)
        with patch('os.open', side_effect=guard), \
             patch('builtins.open', side_effect=AssertionError), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError):
            self.assertTrue(self.check()['ok'])
        for name in ('config.json', 'pending.json', 'adbkey', 'photo.jpg'):
            self.assertEqual((self.root / name).read_text(), 'synthetic forbidden read')

    def test_process_runner_has_no_shell_or_inherited_secrets(self):
        with patch('subprocess.run', return_value=self.ping) as run:
            health_worker._run(['/sbin/ping', '-n', CONFIG['ipv4']], 3)
        kwargs = run.call_args.kwargs
        self.assertNotIn('shell', kwargs)
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(set(kwargs['env']), {'PATH', 'LANG', 'LC_ALL'})
        self.assertEqual(kwargs['timeout'], 3)

    def test_cli_rejects_target_paths_shell_or_controls(self):
        for args in (['--config', '/private/config'], ['--apply'], ['--serial', 'private'],
                     ['--command', 'input tap 1 2'], ['--host', CONFIG['ipv4']]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): health_worker.main(args)


if __name__ == '__main__':
    unittest.main()
