"""Registry-selected managed camera engine. Android ADB + pinned iPhone Wi-Fi control.
All callers must hold .pair-control.lock. Never keep Apple file sessions during capture.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import uuid
import pair_control as android
from collect import names,save,transfer as android_transfer
import iphone_collect
import iphone_wifi

ROOT=android.ROOT
from camera_config import ROLES,IDLE,CONFIG_ID
import readiness
PHONES=android.PHONES
DEFAULT_ADB=android.DEFAULT_ADB


def observe(role):
    try:
        if role!='iphone':return android.state(role)
        value=iphone_wifi.read_json('transports/0/record').get('recording')
        return 'recording' if value is True else 'idle' if value is False else 'unknown'
    except Exception:return 'unknown'


def parallel(fn,roles):
    with ThreadPoolExecutor(max_workers=max(1,len(roles))) as pool:return dict(zip(roles,pool.map(fn,roles)))


def status():return parallel(observe,ROLES)


def connection_info():
    result=android.transport.describe(android.TRANSPORTS,android.PHONES)
    result['iphone']={'mode':'wifi','endpoint':f'{iphone_wifi.HOST}:{iphone_wifi.PORT}',
                      'security':'pinned HTTPS + existing-pairing Apple Network file access'}
    return result


def command(role,start):
    try:
        if role!='iphone':return android.toggle(role)
        code,_=iphone_wifi.request('/control/api/v1/transports/0/'+('record' if start else 'stop'),'POST')
        return {'http':code,'accepted':code==204}
    except Exception as e:return {'uncertain':type(e).__name__+': '+str(e)[:200]}


def after_commands(stopping=False):
    result=status()
    if stopping:
        # Blackmagic stop completion is asynchronous. Observation only, never another stop.
        for _ in range(4):
            if result['iphone']=='idle':break
            time.sleep(1);result['iphone']=observe('iphone')
    return result


def change(action):
    before=status()
    if action=='start' and before!=IDLE:
        return {'ok':False,'error':'Every enabled camera must be verified idle','after':before}
    targets=list(ROLES) if action=='start' else [r for r,s in before.items() if s=='recording']
    commands=parallel(lambda r:command(r,action=='start'),targets)
    after=after_commands(action=='stop')
    expected='recording' if action=='start' else 'idle'
    result={'ok':after=={r:expected for r in ROLES},'before':before,'commands':commands,'after':after}
    if action=='start' and not result['ok']:
        rollback=[r for r,v in after.items() if v=='recording']
        result['rollback_commands']=parallel(lambda r:command(r,False),rollback)
        result['after_rollback']=after_commands(True)
        result['error']='Partial/uncertain start; confirmed recordings stopped once. Inspect unknown states; no restart.'
    return result


async def bounded(awaitable,timeout):return await asyncio.wait_for(awaitable,timeout)


def begin():
    pending=ROOT/'pending-take.json'
    if pending.exists():raise RuntimeError('A take awaits collection')
    fmt=iphone_wifi.read_json('system/format')
    if fmt.get('recordResolution')!={'width':3840,'height':2160} or str(fmt.get('frameRate')) not in ('30','30.00') or fmt.get('offSpeedEnabled') is not False:
        raise RuntimeError('iPhone must remain native 4K/30 with off-speed disabled')
    if iphone_wifi.read_json('transports/0/proxyRecording').get('enabled') is not False:
        raise RuntimeError('iPhone proxies must be off; no settings changed')
    # Context exits here BEFORE durable intent and any recording command.
    before_iphone=asyncio.run(bounded(iphone_collect.baseline(ROOT),60))
    take={'id':time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8],
          'scope':list(ROLES),'config_id':CONFIG_ID,'before':{r:names(android.adb,r) for r in android.PHONES},
          'files':{},'iphone_before':before_iphone,'iphone_files':{},'iphone_complete':False}
    save(pending,take)
    return take


def managed(action):
    existing=ROOT/'pending-take.json'
    if existing.exists():
        pending_config=json.loads(existing.read_text())
        if pending_config.get('config_id')!=CONFIG_ID:
            return {'ok':False,'error':'Pending take camera configuration differs; inspect and recover without sending commands','after':status()}
    if action=='start':
        ready=status()
        if ready!=IDLE:return {'ok':False,'error':'Every enabled camera must be idle; nothing started','after':ready}
        health=readiness.check(ready)
        if not readiness.approved(health):
            return {'ok':False,'error':'Camera health/storage check blocks Start; review readiness details', 'after':ready,'readiness':health}
        begin()
        result=change('start');result['readiness']=health
        return result
    result=change('stop') if action in ('stop','stop_review') else {'after':status()}
    result['ok']=result['after']==IDLE
    if not result['ok']:
        result['collection']={'ok':False,'error':'Every enabled camera must be verified idle; collection deferred'}
        return result
    pending=ROOT/'pending-take.json'
    if not pending.exists():
        result.update(ok=False,collection={'ok':False,'error':'No managed take; no media swept'})
        return result
    take=json.loads(pending.read_text())
    if take.get('scope')!=list(ROLES) or 'iphone_before' not in take:
        result.update(ok=False,collection={'ok':False,'error':'Legacy/incompatible pending take; deliberate recovery required'})
        return result
    if action=='stop_review':
        from review_take import freeze
        freeze(__import__(__name__),take)
        result['review_ready']=True
        return result
    try:
        from runtime_paths import CAPTURE
        dest=CAPTURE
        # Retry validates even completed iPhone records; never sweeps beyond the fixed inventory.
        result['iphone_collection']=asyncio.run(bounded(iphone_collect.transfer(ROOT,dest),10800))
        if status()!=IDLE:raise RuntimeError('Camera state changed; Android collection deferred')
        result['collection']=android_transfer(ROOT,android.PHONES,android.adb,android.DEFAULT_ADB,dest)
        result['ok']=result['collection']['ok']
    except Exception as e:
        result.update(ok=False,collection={'ok':False,'error':type(e).__name__+': '+str(e)[:500]})
    return result
