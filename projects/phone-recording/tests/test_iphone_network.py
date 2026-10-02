import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock,patch,sentinel
import iphone_network as network


class IdentityTests(unittest.TestCase):
    def test_requires_bound_identity(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):network.identity(Path(root))
            p=Path(root)/'.iphone-network.json'
            p.write_text(json.dumps({'identifier':'not-a-device'}))
            with self.assertRaises(ValueError):network.identity(Path(root))
            p.write_text(json.dumps({'identifier':'a'*40}))
            self.assertEqual(network.identity(Path(root)),'a'*40)


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client=types.SimpleNamespace(udid='a'*40,product_type='iPhone12,1',
                     service=types.SimpleNamespace(mux_device=types.SimpleNamespace(connection_type='Network')))
        self.context=AsyncMock();self.context.__aenter__.return_value=self.client
        self.service=AsyncMock();self.service.__aenter__.return_value=sentinel.afc
        self.connect=AsyncMock(return_value=self.context);self.open_app=AsyncMock(return_value=self.service)
        lockdown=types.ModuleType('pymobiledevice3.lockdown');lockdown.create_using_usbmux=self.connect
        house=types.ModuleType('pymobiledevice3.services.house_arrest')
        house.HouseArrestService=types.SimpleNamespace(create=self.open_app)
        for p in [patch.dict(sys.modules,{'pymobiledevice3.lockdown':lockdown,'pymobiledevice3.services.house_arrest':house}),
                  patch.object(network,'identity',return_value='a'*40)]:
            p.start();self.addCleanup(p.stop)

    async def test_exact_network_selection_no_autopair_and_closes(self):
        async with network.files() as service:self.assertIs(service,sentinel.afc)
        self.connect.assert_awaited_once_with(serial='a'*40,autopair=False,connection_type='Network')
        self.open_app.assert_awaited_once_with(self.client,network.BUNDLE,documents_only=True)
        self.service.__aexit__.assert_awaited_once();self.context.__aexit__.assert_awaited_once()

    async def test_identity_mismatch_blocks_app_access(self):
        self.client.udid='b'*40
        with self.assertRaises(RuntimeError):
            async with network.files():pass
        self.open_app.assert_not_awaited()

    async def test_usb_returned_by_library_is_rejected(self):
        self.client.service.mux_device.connection_type='USB'
        with self.assertRaises(RuntimeError):
            async with network.files():pass
        self.open_app.assert_not_awaited()

    async def test_unavailable_network_never_retries_usb(self):
        self.connect.side_effect=ConnectionError('offline')
        with self.assertRaises(ConnectionError):
            async with network.files():pass
        self.connect.assert_awaited_once();self.open_app.assert_not_awaited()

    async def test_file_read_error_closes_both_sessions(self):
        with self.assertRaises(OSError):
            async with network.files():raise OSError('read failed')
        self.service.__aexit__.assert_awaited_once();self.context.__aexit__.assert_awaited_once()


if __name__=='__main__':unittest.main()
