"""Retryable managed iPhone collection over Network-only House Arrest.
No file service is opened during capture. Pending-take journal precedes deletion.
"""
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path,PurePosixPath
import shutil
import uuid
from collect import save
from iphone_network import files

MEDIA='/Documents/Media'


def relative(remote):
    p=PurePosixPath(remote)
    if '..' in p.parts or not remote.startswith(MEDIA+'/') or any(ord(c)<32 for c in remote):
        raise RuntimeError('Unsafe iPhone media path')
    r=p.relative_to(MEDIA)
    if r.suffix.lower() not in ('.mov','.mp4'):raise RuntimeError('Unexpected iPhone media extension')
    return Path(*r.parts)


async def inventory(service):
    found={};count=0
    async def walk(folder,depth=0):
        nonlocal count
        if depth>20:raise RuntimeError('Unexpected media directory depth')
        for name in await service.listdir(folder):
            if name in ('.','..'):continue
            if '/' in name or any(ord(c)<32 for c in name):raise RuntimeError('Unsafe media entry')
            count+=1
            if count>10000:raise RuntimeError('Media inventory exceeds safety limit')
            path=folder+'/'+name;info=await service.stat(path)
            if info.get('st_ifmt')=='S_IFDIR':await walk(path,depth+1)
            elif Path(name).suffix.lower() in ('.mov','.mp4'):
                relative(path)
                if info.get('st_ifmt')!='S_IFREG':raise RuntimeError('Nonregular media entry')
                found[path]=int(info['st_size'])
    await walk(MEDIA)
    return found


async def baseline(root):
    async with files(root) as service:return await inventory(service)


async def stream(service,remote,size,output=None):
    handle=await service.fopen(remote,'r');sha=hashlib.sha256();count=0
    try:
        while count<size:
            data=await service.fread(handle,min(1024*1024,size-count))
            if not data or len(data)>size-count:raise RuntimeError('Invalid/truncated iPhone file read')
            if output is not None:output.write(data)
            sha.update(data);count+=len(data)
    finally:await service.fclose(handle)
    return sha.hexdigest()


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def verify_media(path):
    from media_validation import verify_video
    return verify_video(path, dimensions=(3840, 2160))


async def transfer(root,destination):
    pending=root/'pending-take.json';take=json.loads(pending.read_text())
    if 'iphone_before' not in take:raise RuntimeError('No managed iPhone inventory; refusing sweep')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',take['id']):raise RuntimeError('Invalid managed take ID')
    dest=destination/take['id']/'iphone'
    if dest.is_symlink() or destination.resolve() not in dest.resolve().parents:raise RuntimeError('Unsafe collection directory')
    dest.mkdir(parents=True,exist_ok=True)
    records=take.setdefault('iphone_files',{})
    async with files(root) as service:
        current=await inventory(service)
        if not take.get('iphone_discovery_complete'):
            new=sorted(set(current)-set(take['iphone_before']))
            if not new:raise RuntimeError('No new iPhone clip; collection deferred')
            frozen=take.get('review',{}).get('iphone')
            if frozen is not None and set(new)!=set(frozen):raise RuntimeError('iPhone inventory differs from stopped review')
            await asyncio.sleep(2);stable=await inventory(service)
            if set(stable)-set(take['iphone_before'])!=set(new):raise RuntimeError('iPhone file set still changing')
            for remote in new:
                if current[remote]<=0 or stable.get(remote)!=current[remote]:raise RuntimeError('iPhone file still changing/empty')
                records[remote]={'phone_path':remote,'mac_path':str(dest/relative(remote)),
                                 'bytes':current[remote],'deleted':False,'verified':False}
            take['iphone_discovery_complete']=True;save(pending,take)
        if not records:raise RuntimeError('Empty iPhone transfer plan')
        if set(current)-set(take['iphone_before'])-set(records):raise RuntimeError('Unexpected additional iPhone clip; inspect')
        for remote,record in records.items():
            target=dest/relative(remote)
            if remote in take['iphone_before'] or str(target)!=record['mac_path']:raise RuntimeError('Invalid managed file binding')
            if target.is_symlink() or dest.resolve() not in target.resolve().parents:raise RuntimeError('Unsafe local target')
            if record.get('verified'):
                if not target.is_file() or target.stat().st_size!=record['bytes'] or digest(target)!=record['sha256']:
                    raise RuntimeError('Verified Mac copy missing/changed; no phone deletion')
                if record.get('deleted'):
                    if remote in current:raise RuntimeError('Previously deleted path reappeared; inspect')
                    continue
                if remote not in current:
                    if not record.get('delete_intent'):raise RuntimeError('Phone file disappeared without durable delete intent')
                    record['deleted']=True;save(pending,take);continue
                if current[remote]!=record['bytes'] or await stream(service,remote,record['bytes'])!=record['sha256']:
                    raise RuntimeError('Phone file changed after verification')
            else:
                size=record['bytes']
                if current.get(remote)!=size or size<=0:raise RuntimeError('Planned phone file missing/changed')
                if shutil.disk_usage(dest).free<size+512*1024*1024:raise RuntimeError('Insufficient collection disk headroom')
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    # Crash after atomic finalize but before journal: reread and decode, never overwrite.
                    if target.stat().st_size!=size:raise RuntimeError('Existing destination conflict')
                    sha=await stream(service,remote,size)
                    if digest(target)!=sha:raise RuntimeError('Existing destination conflict')
                    if await stream(service,remote,size)!=sha:raise RuntimeError('Phone changed on independent reread')
                    metadata=verify_media(target)
                else:
                    partial=target.with_name(target.name+'.partial.'+uuid.uuid4().hex)
                    with partial.open('xb') as out:
                        sha=await stream(service,remote,size,out);out.flush();os.fsync(out.fileno())
                    if await stream(service,remote,size)!=sha or digest(partial)!=sha:
                        raise RuntimeError('iPhone checksum mismatch; original retained')
                    metadata=verify_media(partial)
                    if target.exists():raise RuntimeError('Destination appeared during transfer')
                    partial.replace(target)
                    directory=os.open(target.parent,os.O_RDONLY)
                    try:os.fsync(directory)
                    finally:os.close(directory)
                if int((await service.stat(remote))['st_size'])!=size:raise RuntimeError('Phone size changed')
                record.update(sha256=sha,metadata=metadata,verified=True);save(pending,take)
            frozen=take.get('review',{}).get('iphone')
            if frozen is not None and record['sha256']!=frozen.get(remote,{}).get('sha256'):
                raise RuntimeError('Stopped iPhone review fingerprint changed; original retained')
            from iphone_wifi import read_json
            if read_json('transports/0/record').get('recording') is not False:
                raise RuntimeError('iPhone state changed; original retained')
            record['delete_intent']=True;save(pending,take)
            await service.rm(remote)  # One mutation; ambiguous outcomes reconciled from this journal.
            if remote in await inventory(service):raise RuntimeError('Phone deletion not confirmed')
            record['deleted']=True;save(pending,take)
    # All sessions closed before publishing completion. Android collection finalizes the take.
    save(dest/'iphone-transfer.json',list(records.values()))
    take['iphone_complete']=True;save(pending,take)
    return {'ok':True,'files':len(records)}
