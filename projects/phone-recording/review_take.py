"""Stopped-take inventory and explicit discard BEFORE any saved Mac copy.

All callers hold .pair-control.lock. Read-only fingerprinting may stream iPhone
bytes into memory, but never writes footage. No camera toggles in this module.
"""
import asyncio
import json
from pathlib import Path
import re
import time
from collect import save, names, REMOTE, NAME
import iphone_collect as ic
from iphone_network import files


def idle(pair):
    if pair.status()!=pair.IDLE: raise RuntimeError('Every camera must be verified idle')


def android_hash(pair, role, name):
    if not NAME.fullmatch(name): raise ValueError('Unsafe media name')
    from android_media import fingerprint
    sha, _ = fingerprint(pair.android.adb, role, REMOTE + name)
    return sha


def android_new(pair,take):
    return {r:sorted(set(names(pair.android.adb,r))-set(take['before'][r])) for r in pair.android.PHONES}


async def iphone_plan(pair,take):
    async with files(pair.ROOT) as service:
        inventory=await ic.inventory(service)
        new=sorted(set(inventory)-set(take['iphone_before']))
        if len(new)!=1: raise RuntimeError('Expected exactly one new iPhone clip; inspect before discard')
        await asyncio.sleep(2)
        if await ic.inventory(service)!=inventory: raise RuntimeError('iPhone inventory changing')
        path=new[0];size=inventory[path]
        if size<=0: raise RuntimeError('Empty iPhone clip')
        sha=await ic.stream(service,path,size)
        if await ic.inventory(service)!=inventory: raise RuntimeError('iPhone clip changed')
        return {path:{'bytes':size,'sha256':sha}}


def freeze(pair,take):
    idle(pair)
    if take.get('review'): return take['review']
    if take.get('files') or take.get('iphone_files'): raise RuntimeError('Collection already started; cannot offer phone-only discard')
    new=android_new(pair,take)
    if any(len(v)!=1 for v in new.values()): raise RuntimeError('Expected one new clip per Android; inspect take')
    android={r:{name:android_hash(pair,r,name) for name in values} for r,values in new.items()}
    iphone=asyncio.run(pair.bounded(iphone_plan(pair,take),3600))
    idle(pair)
    if android_new(pair,take)!=new: raise RuntimeError('Android inventory changed')
    for r,values in android.items():
        for name,sha in values.items():
            if android_hash(pair,r,name)!=sha: raise RuntimeError('Android clip changed')
    take['review']={'android':android,'iphone':iphone,'stopped_at':time.time()}
    save(pair.ROOT/'pending-take.json',take)
    return take['review']


async def discard_iphone(pair,take,receipt):
    plan=take['review']['iphone']
    async with files(pair.ROOT) as service:
        current=await ic.inventory(service)
        if set(current)-set(take['iphone_before'])!=set(plan): raise RuntimeError('iPhone inventory changed; no deletion')
        for path,record in plan.items():
            if current.get(path)!=record['bytes'] or await ic.stream(service,path,record['bytes'])!=record['sha256']:
                raise RuntimeError('iPhone fingerprint changed; no deletion')
        idle(pair)
        # Each exact path is journalled before its single mutation. No replay.
        for path in plan:
            save(receipt/'iphone-delete-intent.json',{'take_id':take['id'],'path':path})
            await service.rm(path)
            if path in await ic.inventory(service): raise RuntimeError('iPhone deletion not confirmed')


def approval_binding(take):
    return {key: take.get(key) for key in
            ('id', 'config_id', 'review', 'before', 'iphone_before')}


def discard(pair,take_id,job,approved=None):
    if not re.fullmatch('[0-9a-f]{32}',job): raise ValueError('Invalid job ID')
    receipt=pair.ROOT/'.dashboard-deletions'/job
    if (receipt/'intent.json').exists(): raise RuntimeError('Discard already attempted; manual reconciliation only')
    pending=pair.ROOT/'pending-take.json';take=json.loads(pending.read_text())
    if take['id']!=take_id or take.get('config_id')!=pair.CONFIG_ID: raise RuntimeError('Pending take identity/configuration changed')
    if approved is not None and approval_binding(take) != approved:
        raise RuntimeError('Phone discard inventory changed after confirmation')
    if not take.get('review') or take.get('files') or take.get('iphone_files'): raise RuntimeError('Not a stopped, untransferred review take')
    from runtime_paths import CAPTURE, EDITING
    if any((root/take_id).exists() for root in (CAPTURE, EDITING)): raise RuntimeError('Mac take folder exists; inspect partial collection')
    idle(pair)
    new=android_new(pair,take);plan=take['review']['android']
    if new!={r:sorted(v) for r,v in plan.items()}: raise RuntimeError('Android inventory changed')
    for r,values in plan.items():
        for name,sha in values.items():
            if android_hash(pair,r,name)!=sha: raise RuntimeError('Android fingerprint changed')
    receipt.mkdir(mode=0o700,parents=True,exist_ok=True)
    save(receipt/'intent.json',{'take_id':take_id,'scope':'phone originals; explicit discard without backup','review':take['review']})
    asyncio.run(pair.bounded(discard_iphone(pair,take,receipt),3600))
    idle(pair)
    for r,values in plan.items():
        for name,sha in values.items():
            idle(pair)
            if android_hash(pair,r,name)!=sha: raise RuntimeError('Android fingerprint changed before deletion')
            save(receipt/(r+'-delete-intent.json'),{'take_id':take_id,'name':name,'sha256':sha})
            pair.android.adb(r,'shell','rm',REMOTE+name)
            if name in names(pair.android.adb,r): raise RuntimeError('Android deletion not confirmed')
    result={'status':'deleted','take_id':take_id,'phone_originals_deleted':True,'backups_created':False}
    save(receipt/'phones-deleted.json',result)
    pending.unlink()
    save(receipt/'result.json',result)
    return result


if __name__=='__main__':
    import sys,fcntl
    import managed_control as pair
    take,job,approval_path=sys.argv[1:]
    approved=json.loads(Path(approval_path).read_text())
    with (pair.ROOT/'.pair-control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for p in (pair.ROOT/'.dashboard-jobs').glob('*.json'):
            if json.loads(p.read_text()).get('state') in ('queued','running','uncertain'):
                raise RuntimeError('Remote job unresolved')
        print(json.dumps(discard(pair,take,job,approved)))
