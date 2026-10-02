import asyncio
from contextlib import asynccontextmanager
import sys
from types import SimpleNamespace as N
import unittest
from unittest.mock import AsyncMock,patch
import iphone_preview as p


class PreviewLifecycleTests(unittest.TestCase):
    def setup_fakes(self, *, transport='Network', rsd_id='expected', failure=False):
        self.events=[]
        def closer(name):
            async def close():self.events.append(name)
            return close
        @asynccontextmanager
        async def context(name,value):
            try:yield value
            finally:self.events.append(name)
        client=N(udid='expected',product_type='iPhone12,1',service=N(mux_device=N(connection_type=transport)),close=closer('lockdown'))
        self.connect=AsyncMock(return_value=client)
        tun=N(set_peer=lambda address:None)
        result=N(client=N(tun=tun),address='::1',port=1,auxiliary_metadata=None)
        provider=N(close=closer('provider'),start_tcp_tunnel=lambda:context('tunnel',result))
        self.create=AsyncMock(return_value=provider)
        ts=N(USE_USERSPACE_TUNNEL=False,CoreDeviceTunnelProxy=N(create=self.create));self.ts=ts
        rsd=N(udid=rsd_id,connect=AsyncMock(),close=closer('rsd'))
        self.shot=AsyncMock(side_effect=RuntimeError('capture failed') if failure else None,return_value=b'\x89PNG\r\n\x1a\nimage')
        modules={
            'pymobiledevice3.lockdown':N(create_using_usbmux=self.connect),
            'pymobiledevice3.remote':N(tunnel_service=ts),
            'pymobiledevice3.remote.userspace_tunnel':N(UserspaceDialPlane=lambda *a:context('plane',N(dial=None))),
            'pymobiledevice3.remote.remote_service_discovery':N(RemoteServiceDiscoveryService=lambda *a,**k:rsd),
            'pymobiledevice3.services.dvt.instruments.dvt_provider':N(DvtProvider=lambda *a:context('dvt',N())),
            'pymobiledevice3.services.dvt.instruments.screenshot':N(Screenshot=lambda *a:context('shot',N(get_screenshot=self.shot))),
        }
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,modules).start()
        patch('iphone_network.identity',return_value='expected').start()

    def test_network_selection_and_cleanup_before_return(self):
        self.setup_fakes();self.assertTrue(p.capture().startswith(b'\x89PNG'))
        self.connect.assert_awaited_once_with(serial='expected',autopair=False,connection_type='Network')
        self.assertEqual(self.events,['shot','dvt','rsd','plane','tunnel','provider','lockdown'])
        self.assertFalse(self.ts.USE_USERSPACE_TUNNEL)

    def test_capture_failure_closes_every_resource(self):
        self.setup_fakes(failure=True)
        with self.assertRaisesRegex(RuntimeError,'capture failed'):p.capture()
        self.assertEqual(self.events,['shot','dvt','rsd','plane','tunnel','provider','lockdown'])
        self.assertFalse(self.ts.USE_USERSPACE_TUNNEL)

    def test_usb_is_rejected_without_tunnel(self):
        self.setup_fakes(transport='USB')
        with self.assertRaisesRegex(RuntimeError,'transport mismatch'):p.capture()
        self.create.assert_not_awaited();self.assertEqual(self.events,['lockdown'])

    def test_wrong_rsd_identity_closes_tunnel_without_screenshot(self):
        self.setup_fakes(rsd_id='wrong')
        with self.assertRaisesRegex(RuntimeError,'RSD identity'):p.capture()
        self.shot.assert_not_awaited()
        self.assertEqual(self.events,['rsd','plane','tunnel','provider','lockdown'])
        self.assertFalse(self.ts.USE_USERSPACE_TUNNEL)

    def test_timeout_unwinds_tunnel(self):
        self.setup_fakes()
        async def hang():await asyncio.sleep(10)
        self.shot.side_effect=hang
        with self.assertRaises(TimeoutError):p.capture(timeout=.02)
        self.assertEqual(self.events,['shot','dvt','rsd','plane','tunnel','provider','lockdown'])
        self.assertFalse(self.ts.USE_USERSPACE_TUNNEL)
