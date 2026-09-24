import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch, call
import ajazz

ROOT = Path(ajazz.__file__).parent


class SafetyAndProtocolTests(unittest.TestCase):
    def test_golden_report(self):
        expected = bytes.fromhex('04 2a 3d 06 1d 00 00 00 00 05 01 03 00 00 00 aa cc') + bytes(48)
        self.assertEqual(ajazz.report({}), expected)

    def test_rainbow(self):
        b = ajazz.report(dict(effect='wave', color='rainbow', direction='right_to_left'))
        self.assertEqual(b[9], 13)
        self.assertEqual(b[12:17], bytes([1, 1, 0, 0, 0]))

    def test_invalid(self):
        for config in [[], {'per_key': {}}, {'effect': 'static'}, {'effect': 'firmware'},
                       {'brightness': 'off'}, {'speed': -1}, {'color': '#12345'},
                       {'color': '#zzzzzz'}, {'direction': 'up'}, {'color': None}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                ajazz.report(config)

    def test_reserved_bytes_and_all_effects(self):
        for effect in ajazz.EFFECTS:
            b = ajazz.report({'effect': effect})
            self.assertEqual(len(b), 65)
            self.assertEqual(b[5:9], bytes(4))
            self.assertEqual(b[17:], bytes(48))

    def test_presets(self):
        for path in (ROOT / 'presets').glob('*.json'):
            self.assertEqual(len(ajazz.report(json.loads(path.read_text()))), 65)

    def test_discovery_only_enumerates(self):
        hid = Mock()
        ajazz.discover(hid)
        self.assertEqual(hid.mock_calls, [unittest.mock.call.enumerate()])

    def test_no_feature_or_input_report_methods(self):
        tree = ast.parse((ROOT / 'ajazz.py').read_text())
        banned = {'read', 'send_feature_report', 'get_feature_report',
                  'get_input_report', 'send_output_report'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, banned)

    def test_apply_requires_preset(self):
        p = subprocess.run([sys.executable, str(ROOT / 'ajazz.py'), 'apply'], capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn(b'required', p.stderr)

    def test_dry_run_and_overrides(self):
        p = subprocess.run([sys.executable, str(ROOT / 'ajazz.py'), 'apply', 'teal-breath',
                            '--effect', 'wave', '--color', 'rainbow', '--dry-run'],
                           capture_output=True, check=True)
        result = json.loads(p.stdout)
        self.assertFalse(result['hardware_write'])
        self.assertEqual(result['settings']['effect'], 'wave')
        self.assertEqual(result['settings']['color'], 'rainbow')

    def test_offline_commands_never_load_hid(self):
        for args in [['preview'], ['options'], ['effects'], ['presets'],
                     ['set', '--effect', 'rain', '--dry-run'],
                     ['apply', 'rainbow-wave', '--dry-run']]:
            with self.subTest(args=args), patch.object(sys, 'argv', ['ajazz'] + args), \
                 patch.object(ajazz, 'hid_module', side_effect=AssertionError('HID loaded')), \
                 patch('builtins.print'):
                ajazz.main()

    def test_empty_set_rejected(self):
        with patch.object(sys, 'argv', ['ajazz', 'set']), \
             patch.object(ajazz, 'hid_module') as loader, patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                ajazz.main()
            loader.assert_not_called()

    def test_all_discrete_values(self):
        for field, values, offset in [('brightness', ajazz.BRIGHTNESS, 10),
                                     ('speed', ajazz.SPEED, 11),
                                     ('direction', ajazz.DIRECTION, 12)]:
            for index, value in enumerate(values):
                self.assertEqual(ajazz.report({field: value})[offset], index)

    def fake_hid(self):
        hid = Mock()
        hid.enumerate.return_value = [dict(vendor_id=ajazz.VID, product_id=ajazz.PID,
            usage_page=ajazz.USAGE_PAGE, usage=146, interface_number=1,
            product_string='AK820', path=b'test')]
        hid.device.return_value.write.return_value = 65
        return hid

    def test_status_is_metadata_only_and_never_claims_live_settings(self):
        hid = self.fake_hid()
        result = ajazz.keyboard_status(hid)
        self.assertTrue(result['connected'])
        self.assertEqual(result['matching_interfaces'], 1)
        self.assertIsNone(result['lighting_state'])
        self.assertFalse(result['hardware_write'])
        self.assertEqual(hid.mock_calls, [call.enumerate()])

    def test_disconnected_status(self):
        hid = self.fake_hid()
        hid.enumerate.return_value = []
        result = ajazz.keyboard_status(hid)
        self.assertFalse(result['connected'])
        self.assertIsNone(result['lighting_state'])
        hid.device.assert_not_called()

    def test_status_does_not_guess_between_devices(self):
        hid = self.fake_hid()
        hid.enumerate.return_value *= 2
        result = ajazz.keyboard_status(hid)
        self.assertEqual(result['matching_interfaces'], 2)
        self.assertIsNone(result['lighting_state'])
        hid.device.assert_not_called()

    def test_single_shared_write_and_close(self):
        hid = self.fake_hid()
        shared = Mock()
        self.assertEqual(ajazz.send_once({}, hid, shared=shared), 65)
        shared.assert_called_once_with(hid)
        self.assertEqual(hid.device.return_value.mock_calls,
                         [call.open_path(b'test'), call.write(ajazz.report({})), call.close()])

    def test_identity_refusal(self):
        for key in ['vendor_id', 'product_id', 'usage_page', 'usage', 'interface_number', 'product_string']:
            hid = self.fake_hid()
            hid.enumerate.return_value[0][key] = 'wrong'
            with self.subTest(key=key), self.assertRaises(ValueError):
                ajazz.send_once({}, hid, shared=Mock())
            hid.device.assert_not_called()

    def test_multiple_devices_and_explicit_path(self):
        hid = self.fake_hid()
        hid.enumerate.return_value.append(hid.enumerate.return_value[0] | {'path': b'other'})
        with self.assertRaises(ValueError):
            ajazz.send_once({}, hid, shared=Mock())
        hid.device.assert_not_called()
        self.assertEqual(ajazz.send_once({}, hid, path_hex=b'other'.hex(), shared=Mock()), 65)
        hid.device.return_value.open_path.assert_called_once_with(b'other')

    def test_invalid_config_no_enumeration(self):
        hid = self.fake_hid()
        with self.assertRaises(ValueError):
            ajazz.send_once({'effect': 'static'}, hid, shared=Mock())
        hid.enumerate.assert_not_called()

    def test_no_write_on_open_failure(self):
        hid = self.fake_hid()
        hid.device.return_value.open_path.side_effect = OSError('open failed')
        with self.assertRaises(OSError):
            ajazz.send_once({}, hid, shared=Mock())
        hid.device.return_value.write.assert_not_called()
        hid.device.return_value.close.assert_called_once()

    def test_short_write_or_error_not_retried(self):
        for failure in [0, 64, OSError('failed')]:
            hid = self.fake_hid()
            if isinstance(failure, Exception):
                hid.device.return_value.write.side_effect = failure
            else:
                hid.device.return_value.write.return_value = failure
            with self.assertRaises((RuntimeError, OSError)):
                ajazz.send_once({}, hid, shared=Mock())
            hid.device.return_value.write.assert_called_once()
            hid.device.return_value.close.assert_called_once()

    def test_shared_failure_does_not_open(self):
        hid = self.fake_hid()
        with self.assertRaises(RuntimeError):
            ajazz.send_once({}, hid, shared=Mock(side_effect=RuntimeError('unavailable')))
        hid.device.assert_not_called()

    def test_shared_api_configuration(self):
        lib = Mock()
        lib.hid_darwin_get_open_exclusive.return_value = 0
        with patch.object(sys, 'platform', 'darwin'), patch.object(ajazz.ctypes, 'CDLL', return_value=lib):
            ajazz.configure_shared(Mock(__file__='test.so'))
        lib.hid_darwin_set_open_exclusive.assert_called_once_with(0)

    def test_shared_api_refuses_exclusive(self):
        lib = Mock()
        lib.hid_darwin_get_open_exclusive.return_value = 1
        with patch.object(sys, 'platform', 'darwin'), patch.object(ajazz.ctypes, 'CDLL', return_value=lib):
            with self.assertRaises(RuntimeError):
                ajazz.configure_shared(Mock(__file__='test.so'))

    def test_preview_offline(self):
        p = subprocess.run([sys.executable, str(ROOT / 'ajazz.py'), 'preview',
                            str(ROOT / 'presets/teal-breath.json')], capture_output=True, check=True)
        self.assertFalse(json.loads(p.stdout)['hardware_write'])

    def test_identity(self):
        d = dict(vendor_id=ajazz.VID, product_id=ajazz.PID, usage_page=ajazz.USAGE_PAGE)
        self.assertTrue(ajazz.matches(d))
        for key in d:
            self.assertFalse(ajazz.matches(d | {key: 0}))


if __name__ == '__main__':
    unittest.main()
