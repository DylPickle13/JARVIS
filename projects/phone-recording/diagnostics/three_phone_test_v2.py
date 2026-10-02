#!/usr/bin/env python3
"""Bounded three-phone test; detach at launch, no AFC connection during capture."""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
import fcntl
import json
import time
from collect import begin, transfer, save
from iphone_api import read_json
import pair_control as pair
from three_phone_test import ROOT, DEST, BUNDLE, states, command, collect_iphone
from iphone_isolated_test import inventory
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.house_arrest import HouseArrestService

REPORT = ROOT / 'three-phone-v2-result.json'


async def main():
    with (ROOT / '.pair-control.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = {'ok': False, 'started_at': datetime.datetime.now().astimezone().isoformat()}
        attempted = False
        capture_passed = False
        try:
            result['preflight'] = states()
            if any(s != 'idle' for s in result['preflight'].values()):
                raise RuntimeError('All three phones must be verified idle')
            fmt = read_json('system/format')
            if fmt.get('frameRate') != '30' or fmt.get('recordResolution') != {'width':3840,'height':2160} or fmt.get('offSpeedEnabled') is not False:
                raise RuntimeError('iPhone not at 4K/30')
            if read_json('transports/0/proxyRecording').get('enabled') is not False:
                raise RuntimeError('iPhone proxies must be off')
            result['iphone_before'] = await asyncio.wait_for(inventory(), 60)
            take = begin(ROOT, pair.PHONES, pair.adb)
            result['take_id'] = take['id']
            save(REPORT, result)
            if any(s != 'idle' for s in states().values()):
                raise RuntimeError('State changed during inventory; no start sent')
            # All file-sharing services are closed before capture.
            phones = ['lg', 'samsung', 'iphone']
            attempted = True
            with ThreadPoolExecutor(max_workers=3) as pool:
                result['start_commands'] = dict(zip(phones, pool.map(lambda p: command(p, True), phones)))
            time.sleep(2)
            result['recording_states'] = states()
            save(REPORT, result)
            if any(s != 'recording' for s in result['recording_states'].values()):
                raise RuntimeError('Partial/uncertain start; no blind retry')
            print('All three confirmed recording; holding 60 seconds', flush=True)
            time.sleep(60)
            result['end_recording_states'] = states()
            capture_passed = all(s == 'recording' for s in result['end_recording_states'].values())
            if not capture_passed:
                raise RuntimeError('One or more recordings ended unexpectedly')
        except Exception as e:
            result['error'] = str(e)[:600]
        finally:
            if attempted:
                result['before_stop'] = states()
                stop = [p for p,s in result['before_stop'].items() if s == 'recording']
                with ThreadPoolExecutor(max_workers=3) as pool:
                    result['stop_commands'] = dict(zip(stop, pool.map(lambda p: command(p, False), stop)))
                time.sleep(2)
                for _ in range(6):
                    result['after_stop'] = states()
                    if all(s == 'idle' for s in result['after_stop'].values()):
                        break
                    time.sleep(1)
            save(REPORT, result)
        if attempted and all(s == 'idle' for s in result.get('after_stop', {'missing':'unknown'}).values()):
            print('All stopped; USB collection beginning', flush=True)
            try:
                async with await create_using_usbmux(autopair=False, connection_type='USB') as lockdown:
                    async with await HouseArrestService.create(lockdown, BUNDLE, documents_only=True) as svc:
                        result['iphone_transfer'] = await asyncio.wait_for(collect_iphone(svc, result['iphone_before'], DEST / result['take_id'] / 'iphone'), 600)
            except Exception as e:
                result['iphone_error'] = str(e)[:600]
            save(REPORT, result)
            try:
                result['android_transfer'] = transfer(ROOT, pair.PHONES, pair.adb, pair.DEFAULT_ADB, DEST)
            except Exception as e:
                result['android_error'] = str(e)[:600]
            result['ok'] = capture_passed and bool(result.get('iphone_transfer')) and result.get('android_transfer',{}).get('ok',False) and not any(k in result for k in ('error','iphone_error','android_error'))
        result['ended_at'] = datetime.datetime.now().astimezone().isoformat()
        save(REPORT, result)
        print(json.dumps(result,indent=2),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
