import sys
import time
import unittest
from unittest import mock

from test_jarvisd import jarvisd
from jarvisd_core import host_memory


def sample(page=16384):
    return f'''17179869184
Mach Virtual Memory Statistics: (page size of {page} bytes)
Pages free: 1000.
Anonymous pages: 400000.
Pages purgeable: 10000.
Pages wired down: 100000.
Pages occupied by compressor: 40000.
Pages stored in compressor: 999999.
File-backed pages: 300000.
'''


class HostMemoryTests(unittest.TestCase):
    def test_used_is_nonpurgeable_app_wired_and_physical_compressor_not_cache_or_swap(self):
        for page in [4096, 16384]:
            result = host_memory.parse_memory(sample(page))
            self.assertEqual(result['usedBytes'], 530000 * page)
            self.assertEqual(result['totalBytes'], 17179869184)
            changed_cache = sample(page).replace('300000.', '500000.').replace('999999.', '900000.')
            self.assertEqual(host_memory.parse_memory(changed_cache), result)

    def test_bad_missing_duplicate_and_inconsistent_counters_fail_closed(self):
        for text in ['', sample(8192), sample().replace('17179869184', '0'),
                     sample().replace('Anonymous pages:', 'Unknown:'),
                     sample().replace('400000.', '-1.'),
                     sample().replace('400000.', 'true.'),
                     sample().replace('10000.', '500000.'),
                     sample().replace('400000.', '99999999999.'),
                     sample() + 'Pages wired down: 100000.\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                host_memory.parse_memory(text)

    def test_fixed_local_and_trusted_remote_commands(self):
        with mock.patch.object(host_memory, '_read', return_value=sample()) as read:
            self.assertTrue(host_memory.collect_host_memory('mac-mini-64')['ok'])
            self.assertEqual(read.call_args.args[0], ['/bin/sh', '-c', host_memory.COMMAND])
            self.assertTrue(host_memory.collect_host_memory('mac-mini-16')['ok'])
            argv = read.call_args.args[0]
            self.assertEqual(argv[0], '/usr/bin/ssh')
            self.assertEqual(argv[-2:], ['mac-mini-16', host_memory.COMMAND])
            for option in ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'ConnectionAttempts=1',
                           'ClearAllForwardings=yes', 'ForwardAgent=no', 'PermitLocalCommand=no']:
                self.assertIn(option, argv)
            read.reset_mock()
            self.assertFalse(host_memory.collect_host_memory('untrusted')['ok'])
            read.assert_not_called()

    def test_errors_are_sanitized(self):
        for error in [TimeoutError('PRIVATE'), OSError('PRIVATE'), ValueError('PRIVATE')]:
            with mock.patch.object(host_memory, '_read', side_effect=error):
                self.assertEqual(host_memory.collect_host_memory('mac-mini-16'),
                                 {'ok': False, 'error': 'Mac memory unavailable.'})

    def test_reader_deadline_and_output_bound_and_nonzero_exit(self):
        with mock.patch.object(host_memory, 'TIMEOUT', 0.2):
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                host_memory._read([sys.executable, '-c', 'import time; time.sleep(5)'])
            self.assertLess(time.monotonic() - start, 1.5)
        with self.assertRaises(ValueError):
            host_memory._read([sys.executable, '-c', 'print("x" * 20000)'])
        with self.assertRaises(ValueError):
            host_memory._read([sys.executable, '-c', 'raise SystemExit(1)'])
        self.assertEqual(host_memory._read([sys.executable, '-c', 'print("ok")']), 'ok\n')
