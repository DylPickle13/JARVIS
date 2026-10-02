#!/usr/bin/env python3
"""Idle-only diagnostic roundtrip through Apple Network transport, not camera media."""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import asyncio
import fcntl
import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path
from collect import save
from iphone_network import files,ROOT
from iphone_wifi import request
from iphone_usb import connect,mux


def idle():
    code,body=request('/control/api/v1/transports/0/record')
    if code!=200 or json.loads(body).get('recording') is not False:
        raise RuntimeError('iPhone must be verified idle')


async def validate():
    run=uuid.uuid4().hex
    folder=ROOT/'.wifi-validation'/run
    folder.mkdir(parents=True,mode=0o700)
    source=folder/'iphone-source.bin';source.write_bytes(secrets.token_bytes(8*1024*1024))
    payload=source.read_bytes();sha=hashlib.sha256(payload).hexdigest()
    name='phone-recording-wifi-'+run+'.bin';remote='/Documents/'+name
    with connect() as sock:
        devices=mux(sock,{'MessageType':'ListDevices'}).get('DeviceList',[])
    usb_count=sum(d.get('Properties',{}).get('ConnectionType')=='USB' for d in devices)
    start=time.monotonic()
    async with files() as service:
        if name in await service.listdir('/Documents'):raise RuntimeError('Diagnostic filename conflict')
        await service.set_file_contents(remote,payload)
        for n in (1,2):
            data=await service.get_file_contents(remote)
            if hashlib.sha256(data).hexdigest()!=sha:raise RuntimeError('Diagnostic hash mismatch; phone fixture retained')
            target=folder/f'iphone-read-{n}.bin';target.write_bytes(data)
            if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise RuntimeError('Mac reread hash mismatch')
        idle()
        # Exactly the new verified fixture; no directory sweeps or media removal.
        await service.rm(remote)
        if name in await service.listdir('/Documents'):raise RuntimeError('Diagnostic cleanup unconfirmed')
    idle()
    result={'ok':True,'id':run,'transport':'Network','usb_devices_present':usb_count,
            'bytes':len(payload),'sha256':sha,'independent_network_reads':2,
            'roundtrip_seconds':round(time.monotonic()-start,3),'diagnostic_phone_file_removed':True,
            'recording_commands_sent':False,'camera_media_touched':False,'after':'idle'}
    save(folder/'result.json',result)
    print(json.dumps(result,indent=2))


def main():
    with (ROOT/'.pair-control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (ROOT/'pending-take.json').exists():raise RuntimeError('Pending take; diagnostic deferred')
        idle()
        asyncio.run(asyncio.wait_for(validate(),timeout=120))


if __name__=='__main__':main()
