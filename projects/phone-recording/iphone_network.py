"""Existing-pairing Apple Network file access. Never selects USB or creates trust.

Caller must hold the controller lock and verify idle before opening file services.
The service must be closed before any recording starts.
"""
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re

from runtime_paths import ROOT
BUNDLE='com.blackmagic-design.DaVinciCamera'


def identity(root=ROOT):
    value=json.loads((root/'.iphone-network.json').read_text())
    identifier=value.get('identifier','')
    if not re.fullmatch(r'[A-Fa-f0-9-]{24,41}',identifier):
        raise ValueError('Expected USB-verified iPhone identity configuration')
    return identifier


@asynccontextmanager
async def files(root=ROOT):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.house_arrest import HouseArrestService
    expected=identity(root)
    async with await create_using_usbmux(serial=expected,autopair=False,connection_type='Network') as client:
        if client.udid!=expected or client.product_type!='iPhone12,1':
            raise RuntimeError('iPhone identity mismatch; no app files accessed')
        if client.service.mux_device.connection_type!='Network':
            raise RuntimeError('Network transport required; no USB fallback')
        async with await HouseArrestService.create(client,BUNDLE,documents_only=True) as service:
            yield service
