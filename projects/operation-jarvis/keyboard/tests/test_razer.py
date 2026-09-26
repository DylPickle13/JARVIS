import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import razer


class RazerTests(unittest.TestCase):
    def test_effect_vectors(self):
        for effect, payload in [('off', '010400000000'),
                                ('steady', '010401000001ffffff'),
                                ('breathing', '010402010001ffffff')]:
            report = razer.build_report(effect=effect)
            data = bytes.fromhex(payload)
            self.assertEqual(len(report), 90)
            self.assertEqual(report[:8], bytes([0, 63, 0, 0, 0, len(data), 15, 2]))
            self.assertEqual(report[8:8 + len(data)], data)
            self.assertEqual(report[88], razer.checksum(report))
            self.assertEqual(report[89], 0)

    def test_brightness_bounds(self):
        for pct, raw in [(0, 0), (50, 128), (100, 255)]:
            r = razer.build_report(brightness=pct)
            self.assertEqual(r[5:11], bytes([3, 15, 4, 1, 4, raw]))
        for value in [-1, 101, 1.5, True]:
            with self.assertRaises(ValueError):
                razer.build_report(brightness=value)
        for kwargs in [{}, {'effect': 'rainbow'}, {'effect': 'off', 'brightness': 10}]:
            with self.assertRaises(ValueError):
                razer.build_report(**kwargs)

    def test_response_validation(self):
        req = razer.build_report(effect='steady')
        response = bytearray(req)
        response[0] = 2
        razer.validate_response(req, response)
        for index, value in [(0, 1), (1, 255), (6, 0), (88, 0), (89, 1)]:
            bad = bytearray(response)
            bad[index] = value
            with self.assertRaises(RuntimeError):
                razer.validate_response(req, bad)
        with self.assertRaises(RuntimeError):
            razer.validate_response(req, response[:-1])

    def test_exact_device_selection(self):
        good = dict(vendor_id=razer.VID, product_id=razer.PID, interface_number=0,
                    usage_page=1, usage=2, path=b'mouse')
        hid = Mock()
        hid.enumerate.return_value = [good, good, dict(good, interface_number=2),
                                      dict(good, product_id=0x71)]
        self.assertEqual(razer.candidates(hid), [good])

    def test_single_exchange(self):
        req = razer.build_report(effect='off')
        response = bytearray(req)
        response[0] = 2
        dev = Mock()
        dev.send_feature_report.return_value = 91
        dev.get_feature_report.return_value = response
        with patch('razer.time.sleep'):
            razer.exchange(dev, req)
        dev.send_feature_report.assert_called_once_with(b'\x00' + req)
        dev.get_feature_report.assert_called_once_with(0, 90)

    def test_short_write_never_retries(self):
        dev = Mock()
        dev.send_feature_report.return_value = 20
        with self.assertRaises(RuntimeError):
            razer.exchange(dev, razer.build_report(effect='off'))
        dev.send_feature_report.assert_called_once()
        dev.get_feature_report.assert_not_called()

    def test_uncertain_write_blocks_future_apply(self):
        with tempfile.TemporaryDirectory() as tmp, patch('razer.STATE', Path(tmp)):
            dev = Mock()
            with patch('razer.open_shared', return_value=dev) as opened, \
                    patch('razer.exchange', side_effect=OSError('unknown')) as exchange:
                with self.assertRaises(OSError):
                    razer.apply(None, [], razer.build_report(effect='off'))
                self.assertTrue((Path(tmp) / 'uncertain.json').exists())
                with self.assertRaises(RuntimeError):
                    razer.apply(None, [], razer.build_report(effect='off'))
                opened.assert_called_once()
                exchange.assert_called_once()
                dev.close.assert_called_once()

    def test_open_failure_creates_no_uncertain_write(self):
        with tempfile.TemporaryDirectory() as tmp, patch('razer.STATE', Path(tmp)), \
                patch('razer.open_shared', side_effect=OSError('open failed')):
            with self.assertRaises(OSError):
                razer.apply(None, [], razer.build_report(effect='off'))
            self.assertFalse((Path(tmp) / 'uncertain.json').exists())


if __name__ == '__main__':
    unittest.main()
