"""Callback lifecycle tests; never start a real Bluetooth manager or scan."""
import asyncio
from contextlib import contextmanager
import sys
import unittest
from unittest.mock import patch

from listener import pooled_corebluetooth_backend


class PoolTests(unittest.TestCase):
    def test_pool_covers_dispatch_and_unwinds_errors(self):
        events = []

        @contextmanager
        def pool():
            events.append('enter')
            try:
                yield
            finally:
                events.append('exit')

        class Manager:
            def did_discover_peripheral(self, value, *, fail=False):
                events.append(value)
                if fail:
                    raise ValueError('test')
                return value

        class Backend:
            def __init__(self, marker):
                self.marker = marker
                self._manager = Manager()

        scanner = pooled_corebluetooth_backend(Backend, pool)('marker')
        self.assertEqual(scanner.marker, 'marker')
        callback = scanner._manager.did_discover_peripheral
        self.assertEqual(callback('conversion and observer'), 'conversion and observer')
        with self.assertRaises(ValueError):
            callback('failure', fail=True)
        self.assertEqual(events, ['enter', 'conversion and observer', 'exit',
                                  'enter', 'failure', 'exit'])

    def test_async_dispatch_rejected(self):
        class Manager:
            async def did_discover_peripheral(self):
                pass

        class Backend:
            def __init__(self):
                self._manager = Manager()

        with self.assertRaises(RuntimeError):
            pooled_corebluetooth_backend(Backend, None)()

    def test_installed_bleak_dispatch_and_retained_values(self):
        if sys.platform != 'darwin':
            self.skipTest('CoreBluetooth dependency test requires macOS')
        try:
            import objc
            from Foundation import NSData, NSDictionary, NSNumber, NSUUID
            import bleak.backends.corebluetooth.scanner as module
            from bleak.backends.corebluetooth.CentralManagerDelegate import CentralManagerDelegate
        except ImportError:
            self.skipTest('Run with presence/.venv/bin/python for installed dependency test')

        class FakeManager:
            # Exercise the actual installed Bleak dispatch, but never construct
            # its real CBCentralManager (which would access Bluetooth).
            did_discover_peripheral = CentralManagerDelegate.did_discover_peripheral

            def __init__(self):
                self.callbacks = {}
                self.started = False

            async def wait_until_ready(self):
                pass

            async def start_scan(self, uuids):
                self.started = True

            async def stop_scan(self):
                self.started = False

        class Peripheral:
            def identifier(self):
                return NSUUID.alloc().initWithUUIDString_('00000000-0000-0000-0000-000000000001')

            def name(self):
                return 'Synthetic test'

        async def check():
            depth = 0
            observed = []

            @contextmanager
            def pool():
                nonlocal depth
                with objc.autorelease_pool():
                    depth += 1
                    try:
                        yield
                    finally:
                        depth -= 1

            def observer(device, adv):
                self.assertEqual(depth, 1)
                observed.append((device, adv))

            with patch.object(module, 'CentralManagerDelegate', FakeManager):
                backend = pooled_corebluetooth_backend(module.BleakScannerCoreBluetooth, pool)
                scanner = backend(observer, None, 'active', cb={})
            self.assertTrue(hasattr(scanner._manager.did_discover_peripheral, '__wrapped__'))
            await scanner.start()
            data = NSDictionary.dictionaryWithDictionary_({
                'kCBAdvDataManufacturerData': NSData.dataWithBytes_length_(b'\x4c\x00test', 6),
            })
            for _ in range(100):
                scanner._manager.did_discover_peripheral(
                    None, Peripheral(), data, NSNumber.numberWithInt_(-60))
            self.assertEqual(depth, 0)
            self.assertEqual(len(scanner.seen_devices), 1)
            # The cache intentionally retains the latest native objects; those
            # and observer-owned objects must remain usable after pool drainage.
            device, adv = observed[-1]
            self.assertEqual(adv.rssi, -60)
            self.assertEqual(adv.manufacturer_data[76], b'test')
            self.assertEqual(str(adv.platform_data[0].identifier().UUIDString()), device.address)
            self.assertEqual(len(adv.platform_data[1]['kCBAdvDataManufacturerData']), 6)
            await scanner.stop()
            self.assertFalse(scanner._manager.callbacks)

        asyncio.run(check())


if __name__ == '__main__':
    unittest.main()
