import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import razer_bridge

ROOT = Path(__file__).resolve().parents[1]


class RazerBridgeTests(unittest.TestCase):
    def test_valid_settings(self):
        for op, value, y in [('effect', 0, 0), ('brightness', 100, 0), ('dpi', 800, 1600),
                             ('poll', 1000, 0), ('get-dpi', 0, 0), ('get-poll', 0, 0),
                             ('get-brightness', 0, 0)]:
            razer_bridge.validate_settings(dict(operation=op, value=value, y=y))

    def test_invalid_settings(self):
        for op, value, y in [('effect', 3, 0), ('brightness', True, 0), ('dpi', 6401, 800),
                             ('poll', 250, 0), ('get-dpi', 1, 0), ('raw', 0, 0)]:
            with self.assertRaises(ValueError):
                razer_bridge.validate_settings(dict(operation=op, value=value, y=y))

    def test_one_shot_no_raw_reports(self):
        result = subprocess.CompletedProcess([], 0, '{"status":"success","data":{}}', '')
        with patch('razer_bridge.subprocess.run', return_value=result) as run:
            razer_bridge.request('apply', dict(operation='effect', value=1, y=0))
            run.assert_called_once()
            args = run.call_args.args[0]
            self.assertEqual(args[1], '--jarvis-razer')
            body = json.loads(args[2])
            self.assertEqual(body['operation_type'], 'jarvis_razer_v1')
            self.assertEqual(set(body), {'operation_type', 'id', 'sent_at', 'action', 'settings'})

    def test_uncertain_never_retries(self):
        with patch('razer_bridge.subprocess.run', side_effect=subprocess.TimeoutExpired('cli', 6)) as run:
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                razer_bridge.request('apply', dict(operation='effect', value=0, y=0))
            run.assert_called_once()

    def test_native_protocol_lifecycle_journal_sanitizers(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / 'test_razer'
            result = subprocess.run(['clang++', '-std=c++20', '-fblocks', '-Wall', '-Wextra', '-Werror',
                                     '-fsanitize=address,undefined', '-g', '-I',
                                     str(ROOT / 'karabiner/upstream/vendor/vendor/include'),
                                     str(ROOT / 'karabiner/prototype/test_razer.cpp'),
                                     '-framework', 'IOKit', '-framework', 'CoreFoundation', '-o', str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
