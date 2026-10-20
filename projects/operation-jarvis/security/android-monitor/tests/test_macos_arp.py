"""Offline macOS helper tests. Never open BPF or invoke the generated installer."""
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('build_macos_arp', ROOT / 'build_macos_arp.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
CONFIG = {'INTERFACE': 'en1', 'PHONE_IP': '192.168.40.11', 'PHONE_MAC': '02:11:22:33:44:11',
          'DOORBELL_IP': '192.168.40.12', 'DOORBELL_MAC': '02:11:22:33:44:12'}


class InstallerTests(unittest.TestCase):
    def test_exact_configuration(self):
        self.assertEqual(build.arguments(CONFIG), ['en1', '192.168.40.11', '02:11:22:33:44:11',
                                                  '192.168.40.12', '02:11:22:33:44:12'])
        for c in (CONFIG | {'PASSWORD': 'never'}, {k: v for k, v in CONFIG.items() if k != 'INTERFACE'},
                  CONFIG | {'INTERFACE': None}):
            with self.assertRaises(ValueError): build.arguments(c)

    def test_rejects_shell_and_public_addresses(self):
        for key, value in [('INTERFACE', 'en1;id'), ('INTERFACE', ''), ('INTERFACE', 'x' * 16),
                           ('PHONE_IP', '8.8.8.8'), ('PHONE_MAC', 'ff:ff:ff:ff:ff:ff'),
                           ('PHONE_IP', CONFIG['DOORBELL_IP']), ('PHONE_MAC', CONFIG['DOORBELL_MAC']),
                           ('PHONE_MAC', '02:00:00:00:00:00')]:
            with self.assertRaises(ValueError): build.arguments(CONFIG | {key: value})

    def test_plist_is_fixed_command_no_shell_or_credentials(self):
        p = plistlib.loads(plistlib.dumps(build.service(build.arguments(CONFIG))))
        self.assertEqual(p['ProgramArguments'][:2], ['/Library/PrivilegedHelperTools/com.jarvis.monitor-arp', '--run'])
        self.assertEqual(len(p['ProgramArguments']), 7)
        self.assertTrue(p['KeepAlive'])
        self.assertEqual(p['ThrottleInterval'], 60)
        self.assertNotIn('EnvironmentVariables', p)
        self.assertNotIn('password', json.dumps(p).lower())

    def test_installer_quotes_stage_and_validates_hashes(self):
        script = build.installer(Path("/tmp/stage's $(touch SHOULD_NOT_RUN)"), 'a' * 64, 'b' * 64, 'c' * 64)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'installer.sh'; path.write_text(script)
            subprocess.run(['/bin/sh', '-n', str(path)], check=True)
        self.assertEqual(script.count('/bin/launchctl bootstrap '), 1)
        self.assertNotIn('kickstart', script)
        self.assertNotIn('systemctl', script)
        self.assertNotIn('ssh ', script)
        self.assertNotIn('osascript', script)
        self.assertIn('bootstrap.attempted', script)
        self.assertLess(script.index('bootstrap.attempted'), script.index('/bin/launchctl bootstrap'))
        self.assertIn('verify /Library/PrivilegedHelperTools/com.jarvis.monitor-arp', script)
        self.assertIn('Existing installation or attempt', script)
        self.assertIn('set -C', script)

    def test_replacement_is_hash_guarded_and_preserves_plist_and_pi(self):
        script = build.replacement_installer(Path("/tmp/stage's replacement"), 'a' * 64, 'b' * 64, 'c' * 64, 'd' * 64)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'replace.sh'; path.write_text(script)
            subprocess.run(['/bin/sh', '-n', str(path)], check=True)
        self.assertEqual(script.count('/bin/launchctl bootout '), 1)
        self.assertEqual(script.count('/bin/launchctl bootstrap '), 1)
        self.assertIn('binary.before', script)
        self.assertIn('bootout.attempted', script)
        self.assertIn('bootstrap.attempted', script)
        self.assertIn('pgrep', script)
        self.assertIn('verify /Library/PrivilegedHelperTools/com.jarvis.monitor-arp ' + 'd' * 64, script)
        self.assertNotIn('systemctl', script)
        self.assertNotIn('rm ', script)
        self.assertNotIn('install -o root -g wheel -m 644', script)
        self.assertLess(script.index('bootout.attempted'), script.index('/bin/launchctl bootout'))
        self.assertLess(script.index('bootstrap.attempted'), script.index('/bin/launchctl bootstrap'))

    def test_local_privacy_handling_keeps_capture_binding_and_peer_proof(self):
        text = (ROOT / 'arp_repair_macos.c').read_text()
        self.assertIn('privacy_redacted_mac(local.mac)', text)
        self.assertIn('bind_local_identity(&current, &local, if_nametoindex(interface), bound_index)', text)
        self.assertIn('status = repair(&io, &current, &phone, &doorbell)', text)
        self.assertIn('memcmp(opened.mac, local.mac, 6)', text)
        self.assertLess(text.index('privileged-interface-identity-unavailable'), text.index('pcap_t *capture = open_capture'))

    def test_privilege_boundary_is_explicit(self):
        text = (ROOT / 'arp_repair_macos.c').read_text()
        self.assertIn('setgroups(0, NULL)', text)
        self.assertIn('setuid(0) == -1', text)
        self.assertLess(text.index('if (!drop_privileges())'), text.index('Transport io ='))
        self.assertIn('pcap_set_promisc(p, 0)', text)
        self.assertIn('arp and arp[6:2] = 2', text)
        self.assertIn('DLT_EN10MB', text)
        self.assertIn('O_NOFOLLOW', text)
        self.assertNotIn('system(', text)
        self.assertNotIn('popen(', text)


@unittest.skipUnless(sys.platform == 'darwin', 'macOS compiler/pcap required')
class NativeTests(unittest.TestCase):
    def test_protocol_with_address_and_undefined_behavior_sanitizers(self):
        with tempfile.TemporaryDirectory() as d:
            binary = Path(d) / 'protocol-test'
            subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-g', '-fsanitize=address,undefined', str(ROOT / 'tests/arp_protocol_test.c'),
                            '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertIn('ARP protocol tests passed', result.stdout)

    def test_production_build_and_invalid_cli_never_access_network(self):
        with tempfile.TemporaryDirectory() as d:
            binary = Path(d) / 'arp-repair-macos'
            subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                            str(ROOT / 'arp_repair_macos.c'), '-lpcap', '-o', str(binary)], check=True)
            for args in ([], ['--run'], ['--run', 'en1;id', *build.arguments(CONFIG)[1:]],
                         ['--check', 'en1', '8.8.8.8', CONFIG['PHONE_MAC'], CONFIG['DOORBELL_IP'], CONFIG['DOORBELL_MAC']]):
                r = subprocess.run([str(binary), *args], capture_output=True)
                self.assertEqual(r.returncode, 64)


if __name__ == '__main__':
    unittest.main()
