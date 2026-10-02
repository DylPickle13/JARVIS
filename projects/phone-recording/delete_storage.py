"""Exact-take local storage deletion with closed inventories.

No phone commands, broad glob deletion, backups or Trash. Remote intent is
single-shot: a lost acknowledgement is read, never blindly replayed.
"""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil


def save(path, value):
    import os
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix('.pending')
    with temp.open('w') as f:
        json.dump(value, f); f.flush(); os.fsync(f.fileno())
    temp.chmod(0o600); temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def checked_folder(root, take):
    if not isinstance(take, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', take):
        raise ValueError('Invalid exact take ID')
    p = root/take
    if root.is_symlink() or p.is_symlink() or not p.is_dir():
        raise ValueError('Missing take or symbolic link; deletion blocked')
    if p.resolve().parent != root.resolve(): raise ValueError('Take outside media root')
    if any(f.is_symlink() for f in p.rglob('*')): raise ValueError('Symlink inside take')
    return p


GENERATED_FILES = {
    'transfer-manifest.json', '_verified-export.json', 'iphone/iphone-transfer.json',
    'video-analysis.json', 'Resolve Sync/sync-report.json', 'Resolve Sync/Synced.otio',
    'Resolve Sync/Import into Resolve.lua',
}


def inventory_hashes(files):
    if not isinstance(files, dict) or not files:
        raise ValueError('Empty verified inventory')
    result = {}
    for rel, entry in files.items():
        path = Path(rel)
        if (path.is_absolute() or '..' in path.parts or len(path.parts) < 2
                or path.suffix.lower() not in ('.mp4', '.mov')
                or not re.fullmatch('[0-9a-f]{64}', entry.get('sha256', ''))):
            raise ValueError('Invalid source path/checksum')
        result[rel] = {'sha256': entry['sha256']}
    return result


def source_inventory(folder, take):
    """Read receipt identities only; byte verification happens under the delete lock."""
    m = json.loads((folder / 'transfer-manifest.json').read_text())
    if m.get('id') != take:
        raise ValueError('Capture take identity mismatch')
    files = dict(m.get('files', {}))
    iphone = folder / 'iphone/iphone-transfer.json'
    if 'iphone' in m.get('scope', []) and not iphone.exists():
        raise ValueError('Missing iPhone receipt')
    if iphone.exists():
        if m.get('iphone_complete') is not True:
            raise ValueError('iPhone collection incomplete')
        entries = json.loads(iphone.read_text())
        if not isinstance(entries, list) or not entries:
            raise ValueError('Invalid iPhone manifest')
        for entry in entries:
            rel = Path(entry['mac_path']).relative_to(folder).as_posix()
            if entry.get('verified') is not True or rel in files:
                raise ValueError('Unverified/duplicate iPhone source')
            files[rel] = entry
    if any(e.get('deleted') is not True for e in files.values()):
        raise ValueError('Phone-original deletion not verified')
    if m.get('scope') and {Path(n).parts[0] for n in files} != set(m['scope']):
        raise ValueError('Incomplete camera inventory')
    return inventory_hashes(files)


def verify_files(folder, files):
    files = inventory_hashes(files)
    allowed = set(files) | GENERATED_FILES
    directories = {parent.as_posix() for rel in allowed for parent in Path(rel).parents if parent != Path('.')}
    for p in folder.rglob('*'):
        rel = p.relative_to(folder).as_posix()
        if p.is_symlink():
            raise ValueError('Symlink inside take')
        if p.is_dir():
            if rel not in directories:
                raise ValueError('Unexpected directory inside take: ' + rel)
        elif not p.is_file() or (rel not in allowed and p.name != '.DS_Store'):
            raise ValueError('Unexpected file inside take: ' + rel)
    for rel, entry in files.items():
        path = Path(rel)
        if path.is_absolute() or '..' in path.parts or len(path.parts) < 2:
            raise ValueError('Invalid source path')
        p = folder/path
        if not p.is_file() or p.is_symlink(): raise ValueError('Missing source or symlink')
        h = hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
        if h.hexdigest() != entry['sha256']: raise ValueError('Source checksum changed; inspect before deleting')


def remote_operation(root, control, take, job, mode, expected):
    if not re.fullmatch(r'[0-9a-f]{32}', job): raise ValueError('Invalid deletion job')
    receipt = control/'.dashboard-deletions'/job/'result.json'
    intent = receipt.with_name('intent.json')
    if mode == 'read':
        return json.loads(receipt.read_text()) if receipt.exists() else {'status':'unknown'}
    if mode not in ('check', 'delete'): raise ValueError('Invalid deletion mode')
    with (control/'.pair-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        if intent.exists():
            return json.loads(receipt.read_text()) if receipt.exists() else {'status':'unknown'}
        if (control/'pending-take.json').exists(): raise RuntimeError('Phone collection pending; no deletion')
        for p in (control/'.dashboard-jobs').glob('*.json'):
            if json.loads(p.read_text()).get('state') in ('queued','running','uncertain'):
                raise RuntimeError('Remote job unresolved; no deletion')
        folder = checked_folder(root, take)
        files = source_inventory(folder, take)
        expected = inventory_hashes(expected) if expected else files
        if files != expected:
            raise ValueError('Mac inventories differ from approved deletion')
        verify_files(folder, expected)
        if mode == 'check': return {'status':'checked','files':expected}
        save(intent, {'take_id':take, 'files':expected})
        shutil.rmtree(folder)
        if folder.exists(): raise RuntimeError('Remote folder still exists')
        result = {'status':'deleted', 'take_id':take}
        save(receipt, result)
        return result


if __name__ == '__main__':
    import sys
    take, job, mode, expected = sys.argv[1:]
    from runtime_paths import CAPTURE, ROOT
    print(json.dumps(remote_operation(CAPTURE, ROOT, take, job, mode, json.loads(expected))))
