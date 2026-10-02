"""One-shot Network-only iPhone screenshot. Caller must hold the shared idle-camera lock.
No media files, pairing, mounting or persistent tunnels. Run in a dedicated worker process.
"""
import asyncio
from contextlib import AsyncExitStack


async def screenshot():
    from iphone_network import identity
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.remote import tunnel_service as ts
    from pymobiledevice3.remote.userspace_tunnel import UserspaceDialPlane
    from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot

    expected = identity()
    previous = ts.USE_USERSPACE_TUNNEL
    try:
        async with AsyncExitStack() as stack:
            client = await create_using_usbmux(serial=expected, autopair=False, connection_type='Network')
            stack.push_async_callback(client.close)
            if (client.udid != expected or client.product_type != 'iPhone12,1'
                    or client.service.mux_device.connection_type != 'Network'):
                raise RuntimeError('iPhone identity/Network transport mismatch')
            provider = await ts.CoreDeviceTunnelProxy.create(client)
            stack.push_async_callback(provider.close)
            ts.USE_USERSPACE_TUNNEL = True
            result = await stack.enter_async_context(provider.start_tcp_tunnel())
            tun = result.client.tun
            tun.set_peer(result.address)
            plane = await stack.enter_async_context(UserspaceDialPlane(tun, result.address))
            rsd = RemoteServiceDiscoveryService(
                (result.address, result.port), open_connection=plane.dial,
                auxiliary_metadata=result.auxiliary_metadata)
            stack.push_async_callback(rsd.close)
            await rsd.connect()
            if rsd.udid != expected:
                raise RuntimeError('RSD identity mismatch')
            async with DvtProvider(rsd) as dvt, Screenshot(dvt) as shot:
                data = await shot.get_screenshot()
                if not 0 < len(data) <= 30_000_000:
                    raise RuntimeError('Screenshot size invalid')
                return data
    finally:
        ts.USE_USERSPACE_TUNNEL = previous


def capture(timeout=45):
    return asyncio.run(asyncio.wait_for(screenshot(), timeout))
