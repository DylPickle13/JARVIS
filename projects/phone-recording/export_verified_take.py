#!/usr/bin/env python3
"""Stream locally captured manifest-verified media under the controller lock."""
import fcntl
import io
import json
from pathlib import Path
import re
import sys
import tarfile
from camera_config import CAMERAS


def catalog(root, take_id):
    if take_id == 'latest':
        candidates = list(root.glob('*/transfer-manifest.json'))
        if not candidates:
            raise RuntimeError('No completed managed takes')
        take_id = max(candidates, key=lambda p: p.stat().st_mtime).parent.name
    if not re.fullmatch(r'[A-Za-z0-9_-]+', take_id):
        raise ValueError('Invalid take ID')
    folder = root / take_id
    manifest = json.loads((folder/'transfer-manifest.json').read_text())
    if manifest['id'] != take_id:
        raise RuntimeError('Manifest take mismatch')
    files = {}
    for key, record in manifest['files'].items():
        if not record.get('deleted'):
            raise RuntimeError('Phone collection incomplete')
        files[key] = {'sha256':record['sha256']}
    iphone = folder/'iphone/iphone-transfer.json'
    if 'iphone' in manifest.get('scope',[]) and (not manifest.get('iphone_complete') or not iphone.exists()):
        raise RuntimeError('Managed three-camera take lacks completed iPhone verification')
    if iphone.exists():
        for record in json.loads(iphone.read_text()):
            if not record.get('deleted'):
                raise RuntimeError('iPhone collection incomplete')
            relative = Path(record['mac_path']).relative_to(folder).as_posix()
            files[relative] = {'sha256':record['sha256']}
    present = {p.relative_to(folder).as_posix() for role in CAMERAS for p in (folder/role).rglob('*') if p.suffix.lower() in ('.mp4','.mov')}
    if manifest.get('scope') and {Path(n).parts[0] for n in files} != set(manifest['scope']):
        raise RuntimeError('Managed camera set incomplete')
    if present != set(files) or not files:
        raise RuntimeError('Media/verification manifest mismatch; refusing unverified footage')
    for name, info in files.items():
        path = folder/name
        if Path(name).is_absolute() or '..' in Path(name).parts or not path.is_file() or path.is_symlink() or folder.resolve() not in path.resolve().parents:
            raise RuntimeError('Unsafe media path')
        if not re.fullmatch(r'[0-9a-f]{64}', info['sha256']):
            raise RuntimeError('Invalid checksum')
        info['bytes'] = path.stat().st_size
    return folder, {'take_id':take_id,'files':files}


def main():
    from runtime_paths import ROOT, CAPTURE
    controller = ROOT
    with (controller/'.pair-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if (controller/'pending-take.json').exists():
            raise RuntimeError('Recording/collection pending; copy deferred')
        folder, info = catalog(CAPTURE, sys.argv[1])
        if '--catalog' in sys.argv:
            print(json.dumps(info)); return
        with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
            data = json.dumps(info).encode()
            member = tarfile.TarInfo('_verified-export.json'); member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
            for name in info['files']:
                archive.add(folder/name, arcname=name, recursive=False)


if __name__ == '__main__':
    main()
