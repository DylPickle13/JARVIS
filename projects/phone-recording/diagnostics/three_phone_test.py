#!/usr/bin/env python3
"""Bounded USB three-phone test; independent of the two-phone GUI.
Run using .iphone-venv/bin/python. Single toggles; unknown states defer collection.
Mac recordings retained. Existing phone media excluded by pre-start inventory.
"""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import pair_control as pair
from collect import begin, transfer, save
from iphone_api import read_json, request
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.house_arrest import HouseArrestService

ROOT = Path.home() / 'phone-recording'
BUNDLE = 'com.blackmagic-design.DaVinciCamera'
MEDIA = '/Documents/Media'
DEST = Path.home() / 'Movies/Phone Recordings'
REPORT = ROOT / 'three-phone-test-result.json'


def observe(phone):
    try:
        if phone == 'iphone':
            recording = read_json('transports/0/record').get('recording')
            return 'recording' if recording is True else 'idle' if recording is False else 'unknown'
        return pair.state(phone)
    except Exception:
        return 'unknown'


def states():
    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(zip(('lg', 'samsung', 'iphone'), pool.map(observe, ('lg', 'samsung', 'iphone'))))


def command(phone, start):
    try:
        if phone == 'iphone':
            code, body = request('/control/api/v1/transports/0/' + ('record' if start else 'stop'), 'POST')
            return {'http': code, 'accepted': code == 204}
        return pair.toggle(phone)
    except Exception as e:
        return {'uncertain': str(e)[:300]}


async def iphone_files(svc):
    files = {}
    async for root, dirs, entries in svc.walk(MEDIA):
        for name in entries:
            if Path(name).suffix.lower() in ('.mov', '.mp4'):
                path = root + '/' + name
                info = await svc.stat(path)
                if info.get('st_ifmt') != 'S_IFREG':
                    raise RuntimeError('Unexpected nonregular video file')
                files[path] = int(info['st_size'])
    return files


async def stream(svc, remote, size, output=None):
    handle = await svc.fopen(remote, 'r')
    digest = hashlib.sha256()
    count = 0
    try:
        while count < size:
            data = await svc.fread(handle, min(1024 * 1024, size-count))
            if not data:
                raise RuntimeError('Premature end of iPhone file')
            if output is not None:
                output.write(data)
            digest.update(data)
            count += len(data)
    finally:
        await svc.fclose(handle)
    return digest.hexdigest()


async def collect_iphone(svc, before, dest):
    current = await iphone_files(svc)
    new = sorted(set(current) - set(before))
    if not new:
        raise RuntimeError('No new iPhone video found; no cleanup performed')
    await asyncio.sleep(2)
    stable = await iphone_files(svc)
    results = []
    for remote in new:
        size = current[remote]
        if size <= 0 or stable.get(remote) != size:
            raise RuntimeError('iPhone file still changing; original retained')
        relative = Path(remote).relative_to(MEDIA)
        if '..' in relative.parts:
            raise RuntimeError('Unsafe relative media path')
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError('Destination already exists; refusing overwrite')
        partial = target.with_suffix(target.suffix + '.partial')
        with partial.open('xb') as f:
            copied_hash = await stream(svc, remote, size, f)
            f.flush()
            os.fsync(f.fileno())
        # Independent second USB read verifies original, plus local disk reread.
        phone_hash = await stream(svc, remote, size)
        with partial.open('rb') as f:
            local_hash = hashlib.file_digest(f, 'sha256').hexdigest()
        if local_hash != phone_hash or local_hash != copied_hash or int((await svc.stat(remote))['st_size']) != size:
            raise RuntimeError('iPhone checksum/size changed; original retained')
        probe = subprocess.run(['/opt/homebrew/bin/ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height,avg_frame_rate','-of','json',str(partial)],capture_output=True,text=True,check=True,timeout=60)
        metadata = json.loads(probe.stdout)
        if float(metadata['format']['duration']) <= 0:
            raise RuntimeError('Invalid video duration')
        subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-xerror','-i',str(partial),'-map','0:v:0','-fps_mode','passthrough','-enc_time_base','1:1000000','-f','null','-'],capture_output=True,check=True,timeout=300)
        partial.replace(target)
        record = {'phone_path': remote, 'mac_path': str(target), 'bytes': size, 'sha256': local_hash, 'metadata': metadata, 'deleted': False}
        results.append(record)
        save(dest / 'iphone-transfer.json', results)
        await svc.rm(remote)
        if remote in await iphone_files(svc):
            raise RuntimeError('iPhone deletion not confirmed')
        record['deleted'] = True
        save(dest / 'iphone-transfer.json', results)
    return results


async def main():
    ROOT.mkdir(exist_ok=True)
    with (ROOT / '.pair-control.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = {'started_at': datetime.datetime.now().astimezone().isoformat(), 'preflight': states()}
        if any(s != 'idle' for s in report['preflight'].values()):
            raise RuntimeError('All three phones must be verified idle')
        fmt = read_json('system/format')
        if fmt.get('frameRate') != '30' or fmt.get('recordResolution') != {'width':3840,'height':2160} or fmt.get('offSpeedEnabled') is not False:
            raise RuntimeError('iPhone not at verified 4K/30')
        async with await create_using_usbmux(autopair=False, connection_type='USB') as lockdown:
            async with await HouseArrestService.create(lockdown, BUNDLE, documents_only=True) as svc:
                before = await iphone_files(svc)
                report['iphone_before'] = before
                take = begin(ROOT, pair.PHONES, pair.adb)
                report['take_id'] = take['id']
                save(REPORT, report)
                phones = ['lg', 'samsung', 'iphone']
                try:
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        report['start_commands'] = dict(zip(phones,pool.map(lambda p: command(p, True),phones)))
                    time.sleep(2)
                    report['recording_states'] = states()
                    save(REPORT, report)
                    if any(s != 'recording' for s in report['recording_states'].values()):
                        raise RuntimeError('Partial/uncertain start; inspect result')
                    print('All three recording; waiting 60 seconds',flush=True)
                    time.sleep(60)
                finally:
                    report['before_stop'] = states()
                    # Only stop confirmed recordings from this all-idle baseline.
                    stop = [p for p,s in report['before_stop'].items() if s == 'recording']
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        report['stop_commands'] = dict(zip(stop,pool.map(lambda p: command(p, False),stop)))
                    time.sleep(2)
                    report['after_stop'] = states()
                    save(REPORT, report)
                if any(s != 'idle' for s in report['after_stop'].values()):
                    raise RuntimeError('Stop uncertain; all transfers deferred')
                print('All idle; collecting iPhone over USB',flush=True)
                try:
                    report['iphone_transfer'] = await collect_iphone(svc, before, DEST / take['id'] / 'iphone')
                except Exception as e:
                    report['iphone_error'] = str(e)
                save(REPORT, report)
        print('Collecting Android clips over USB',flush=True)
        report['android_transfer'] = transfer(ROOT,pair.PHONES,pair.adb,pair.DEFAULT_ADB,DEST)
        report['ok'] = bool(report.get('iphone_transfer')) and report['android_transfer']['ok'] and 'iphone_error' not in report
        report['ended_at'] = datetime.datetime.now().astimezone().isoformat()
        save(REPORT,report)
        print(json.dumps(report,indent=2),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
