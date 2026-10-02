import unittest
from inventory import PHONES, inspect, parse_battery, parse_devices


class InventoryTests(unittest.TestCase):
    def test_only_known_devices(self):
        self.assertEqual(parse_devices('List of devices attached\nunknown device\nR5CRC27FBMP unauthorized\n'), {'R5CRC27FBMP': 'unauthorized'})

    def test_battery_ignores_history(self):
        self.assertEqual(parse_battery('  level: 43\n  temperature: 322\n  USB powered: true\n09-07 Sending: level: 5\n'), {'percent': 43, 'temperature_c': 32.2, 'USB powered': True})

    def test_disconnected_does_not_query(self):
        calls = []
        def runner(adb, args):
            calls.append(args)
            return ''
        result = inspect('adb', runner)
        self.assertEqual(calls, [['devices', '-l']])
        self.assertTrue(all(p['usb_state'] == 'disconnected' for p in result['android']))

    def test_connected_read_only(self):
        calls = []
        def runner(adb, args):
            calls.append(args)
            if args == ['devices', '-l']:
                return '\n'.join(f'{serial} device' for serial in PHONES)
            if args[-1] == 'net.sourceforge.opencamera':
                return 'package:net.sourceforge.opencamera'
            return ''
        result = inspect('adb', runner)
        self.assertTrue(all(p['apps']['open_camera'] for p in result['android']))
        self.assertTrue(all(not p['apps']['blackmagic_camera'] for p in result['android']))
        self.assertFalse(any('input' in c or 'tcpip' in c or 'install' in c for c in calls))

    def test_partial_failure_is_explicit(self):
        def runner(adb, args):
            if args == ['devices', '-l']:
                return 'R5CRC27FBMP device'
            raise RuntimeError('failure')
        self.assertIn('error', inspect('adb', runner)['android'][0])


if __name__ == '__main__':
    unittest.main()
