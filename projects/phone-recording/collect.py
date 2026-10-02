"""Transfer only managed Android clips, with durable verification/deletion receipts.

Callers hold the controller lock and verify that every enabled camera is idle.
A retry observes state and revalidates retained bytes; it never infers success
from an absent phone file without a durable, verified deletion intent.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import uuid

from android_media import fingerprint
from media_validation import verify_video

REMOTE = '/sdcard/DCIM/OpenCamera/'
NAME = re.compile(r'VID_[A-Za-z0-9_.-]+\.mp4\Z')


def sync_directory(path):
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def save(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    sync_directory(path.parent)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def names(adb, phone):
    return sorted(n for n in adb(phone, 'shell', 'ls', '-1', REMOTE).splitlines() if NAME.fullmatch(n))


def begin(root, phones, adb):
    pending = root / 'pending-take.json'
    if pending.exists():
        raise RuntimeError('A take awaits collection; run stop/collect before starting another')
    take = {'id': time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8],
            'before': {p: names(adb, p) for p in phones}, 'files': {}}
    save(pending, take)
    return take


def verified_copy(target, record):
    if (record.get('path') != str(target) or not target.is_file() or target.is_symlink()
            or ('bytes' in record and target.stat().st_size != record['bytes'])
            or digest(target) != record['sha256']):
        raise RuntimeError('Verified Mac copy missing/changed; no phone deletion')
    # Older receipts had hashes but no full media validation. Upgrade safely.
    if not record.get('verified'):
        record['metadata'] = verify_video(target)
        record['verified'] = True
    record['bytes'] = target.stat().st_size


def collect_phone(take, phone, phones, adb, adb_path, destination, pending):
    current = set(names(adb, phone)) - set(take['before'][phone])
    recorded = {key.split('/', 1)[1] for key in take['files'] if key.startswith(phone + '/')}
    frozen = take.get('review', {}).get('android', {}).get(phone)
    plans = take.setdefault('android_plan', {})
    if phone not in plans:
        planned = current | recorded
        if frozen is not None and planned != set(frozen):
            raise RuntimeError('Android inventory differs from stopped review')
        if not planned:
            raise RuntimeError('No managed clip found for camera; collection incomplete')
        plans[phone] = sorted(planned)
        save(pending, take)
    planned = set(plans[phone])
    if not planned or current - planned or recorded - planned:
        raise RuntimeError('Unexpected additional Android clip; inspect fixed transfer plan')
    if frozen is not None and planned != set(frozen):
        raise RuntimeError('Android transfer plan differs from stopped review')

    target_dir = destination / take['id'] / phone
    if (any(p.is_symlink() for p in (destination, target_dir.parent, target_dir))
            or destination.resolve() not in target_dir.resolve().parents):
        raise RuntimeError('Unsafe collection directory')
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted(planned):
        if not NAME.fullmatch(name) or name in take['before'][phone]:
            raise RuntimeError('Unexpected media filename')
        key = phone + '/' + name
        target = target_dir / name
        if target.is_symlink():
            raise RuntimeError('Unsafe local target')
        remote = REMOTE + name
        record = take['files'].get(key)
        if record:
            verified_copy(target, record)
            if frozen is not None and record['sha256'] != frozen.get(name):
                raise RuntimeError('Stopped review clip changed')
            if record.get('deleted'):
                if name in current:
                    raise RuntimeError('Previously deleted phone path reappeared; inspect')
                save(pending, take)
                continue
            if name not in current:
                if not record.get('delete_intent'):
                    raise RuntimeError('Phone file disappeared without durable delete intent')
                record['deleted'] = True
                save(pending, take)
                continue
        elif name not in current:
            raise RuntimeError('Planned phone file disappeared without verified copy')

        sha, size = fingerprint(adb, phone, remote)
        if frozen is not None and sha != frozen.get(name):
            raise RuntimeError('Stopped review clip changed')
        if record and (record['sha256'] != sha or record['bytes'] != size):
            raise RuntimeError('Phone file changed after verification')
        if not record:
            if target.exists():
                if target.stat().st_size != size or digest(target) != sha:
                    raise RuntimeError('Destination conflict; existing file left intact')
                metadata = verify_video(target)
            else:
                partial = target.with_name(target.name + '.partial.' + uuid.uuid4().hex)
                try:
                    subprocess.run(
                        [adb_path, '-s', phones[phone], 'pull', remote, str(partial)],
                        check=True, capture_output=True, timeout=1800,
                    )
                    if partial.stat().st_size != size or digest(partial) != sha:
                        raise RuntimeError('Hash mismatch/file changed; original retained')
                    metadata = verify_video(partial)
                    with partial.open('rb') as f:
                        os.fsync(f.fileno())
                    if target.exists():
                        raise RuntimeError('Destination appeared during transfer')
                    partial.replace(target)
                finally:
                    partial.unlink(missing_ok=True)
            # Publish the media AND its newly created ancestor directories before
            # any deletion intent. The controller journal is a different directory.
            with target.open('rb') as f:
                os.fsync(f.fileno())
            for directory in (target_dir, target_dir.parent, destination, destination.parent):
                sync_directory(directory)
            record = {'path': str(target), 'bytes': size, 'sha256': sha,
                      'metadata': metadata, 'verified': True, 'deleted': False}
            take['files'][key] = record
            save(pending, take)

        # Decode may take minutes. Recheck both copies immediately before intent.
        verified_copy(target, record)
        if fingerprint(adb, phone, remote) != (sha, size):
            raise RuntimeError('Phone file changed; original retained')
        record['delete_intent'] = True
        save(pending, take)
        adb(phone, 'shell', 'rm', remote)
        if name in names(adb, phone):
            raise RuntimeError('Phone deletion not confirmed')
        record['deleted'] = True
        save(pending, take)


def transfer(root, phones, adb, adb_path, destination):
    pending = root / 'pending-take.json'
    if not pending.exists():
        return {'ok': False, 'error': 'No managed take: refusing to sweep unrelated phone media'}
    take = json.loads(pending.read_text())
    if 'iphone_before' in take and not take.get('iphone_complete'):
        return {'ok': False, 'error': 'Managed iPhone collection incomplete; take cannot finalize'}
    if (not re.fullmatch(r'[A-Za-z0-9_-]+', take['id']) or not phones
            or set(take['before']) != set(phones)):
        return {'ok': False, 'error': 'Invalid managed take identity/camera scope'}
    results = {}
    for phone in take['before']:
        try:
            if not re.fullmatch(r'[a-z][a-z0-9_]*', phone):
                raise RuntimeError('Invalid camera role')
            collect_phone(take, phone, phones, adb, adb_path, destination, pending)
            results[phone] = {'ok': True}
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError, IndexError) as e:
            results[phone] = {'ok': False, 'error': str(e)[:400]}
    ok = bool(results) and all(r['ok'] for r in results.values())
    if ok:
        archive = destination / take['id']
        save(archive / 'transfer-manifest.json', take)
        pending.unlink()
        sync_directory(pending.parent)
    return {'ok': ok, 'destination': str(destination / take['id']), 'phones': results}
