#!/usr/bin/env python3
"""Bounded iPhone-only capture with proxies off, no AFC session during capture.
Launch detached with stdout/stderr logged, using .iphone-venv/bin/python.
Retain uncertain/damaged footage. No restart after a failed recording command.
"""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import asyncio
import datetime
import fcntl
import json
import time
import uuid

from collect import save
from iphone_api import read_json, request
from three_phone_test import ROOT, DEST, BUNDLE, states, observe, iphone_files, collect_iphone
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.house_arrest import HouseArrestService

REPORT = ROOT / 'iphone-isolated-test-result.json'


async def inventory():
    async with await create_using_usbmux(autopair=False, connection_type='USB') as lock:
        async with await HouseArrestService.create(lock, BUNDLE, documents_only=True) as svc:
            return await iphone_files(svc)


async def main():
    with (ROOT / '.pair-control.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = {'ok': False, 'started_at': datetime.datetime.now().astimezone().isoformat(),
                  'id': 'iphone-isolated-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]}
        started_attempt = False
        capture_passed = False
        try:
            initial = states()
            if any(s != 'idle' for s in initial.values()):
                raise RuntimeError('All phones must be verified idle')
            if (ROOT / 'pending-take.json').exists():
                raise RuntimeError('Resolve pending Android take first')
            result['before'] = await asyncio.wait_for(inventory(), 60)
            result['proxy_before'] = read_json('transports/0/proxyRecording')
            save(REPORT, result)
            if result['proxy_before'].get('enabled') is True:
                if observe('iphone') != 'idle':
                    raise RuntimeError('iPhone no longer idle')
                code, body = request('/control/api/v1/transports/0/proxyRecording', 'PUT', {'enabled': False})
                result['proxy_put_status'] = code
                if code != 204:
                    raise RuntimeError('Proxy update unverified; not retrying')
            result['proxy_after'] = read_json('transports/0/proxyRecording')
            if result['proxy_after'].get('enabled') is not False:
                raise RuntimeError('Proxies not verified off')
            fmt = read_json('system/format')
            result['format'] = fmt
            if fmt.get('frameRate') != '30' or fmt.get('recordResolution') != {'width':3840,'height':2160} or fmt.get('offSpeedEnabled') is not False:
                raise RuntimeError('Not native 4K/30 normal speed')
            if observe('iphone') != 'idle':
                raise RuntimeError('iPhone not verified idle')
            save(REPORT, result)
            # AFC/lockdown contexts have closed before sending record.
            started_attempt = True
            code, body = request('/control/api/v1/transports/0/record', 'POST')
            result['start_http'] = code
            save(REPORT, result)
            if code != 204:
                raise RuntimeError('Start command not accepted; no retry')
            time.sleep(2)
            result['after_start'] = observe('iphone')
            save(REPORT, result)
            if result['after_start'] != 'recording':
                raise RuntimeError('Recording not confirmed; no blind start retry')
            print('iPhone confirmed recording 4K/30 with proxies off; 30-second hold', flush=True)
            for _ in range(6):
                time.sleep(5)
                if observe('iphone') != 'recording':
                    raise RuntimeError('Recording lost during hold')
            capture_passed = True
        except Exception as e:
            result['error'] = str(e)[:600]
        finally:
            if started_attempt:
                result['before_stop'] = observe('iphone')
                if result['before_stop'] == 'recording':
                    try:
                        result['stop_http'] = request('/control/api/v1/transports/0/stop', 'POST')[0]
                    except Exception as e:
                        result['stop_error'] = str(e)[:300]
                for _ in range(6):
                    result['after_stop'] = observe('iphone')
                    if result['after_stop'] == 'idle':
                        break
                    time.sleep(1)
            save(REPORT, result)
        if started_attempt and result.get('after_stop') == 'idle' and all(s == 'idle' for s in states().values()):
            try:
                async with await create_using_usbmux(autopair=False, connection_type='USB') as lockdown:
                    async with await HouseArrestService.create(lockdown, BUNDLE, documents_only=True) as svc:
                        result['transfer'] = await asyncio.wait_for(collect_iphone(svc, result['before'], DEST / result['id'] / 'iphone'), 600)
                result['ok'] = capture_passed and bool(result['transfer']) and 'error' not in result
            except Exception as e:
                result['transfer_error'] = str(e)[:600]
        result['ended_at'] = datetime.datetime.now().astimezone().isoformat()
        save(REPORT, result)
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
