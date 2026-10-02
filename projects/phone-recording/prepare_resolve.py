#!/usr/bin/env python3
"""Verify a local capture, create an editing copy, align audio and prepare Resolve."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from collect import save

ROOT = Path(__file__).resolve().parent
DEST = Path.home()/'Movies/Phone Recordings'
# Legacy function name remote_command is retained for compatibility; execution is local.


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()


def remote_command(take, catalog=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',take):
        raise ValueError('Invalid take ID')
    from runtime_paths import helper
    return helper('export_verified_take.py',take,*(['--catalog'] if catalog else []))


def verify(folder, manifest):
    for name, info in manifest['files'].items():
        p = folder/name
        if Path(name).is_absolute() or '..' in Path(name).parts or not p.is_file() or p.is_symlink() or folder.resolve() not in p.resolve().parents:
            raise RuntimeError('Missing/unsafe local file: '+name)
        if p.stat().st_size!=info['bytes'] or digest(p)!=info['sha256']:
            raise RuntimeError('Local copy checksum conflict: '+name)


def receive(take):
    manifest = json.loads(subprocess.check_output(remote_command(take,True),text=True,timeout=30))
    # Pin latest to this exact ID for streaming, never resolve latest twice.
    take = manifest['take_id']; target = DEST/take
    if target.exists():
        verify(target,manifest)
        save(target/'_verified-export.json',manifest)
        return target
    DEST.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(DEST).free < sum(f['bytes'] for f in manifest['files'].values())+1024**3:
        raise RuntimeError('Insufficient local disk headroom')
    with tempfile.TemporaryDirectory(prefix='.incoming-',dir=DEST) as temp:
        stage = Path(temp)
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen(remote_command(take),stdout=subprocess.PIPE,stderr=errors)
            seen = set()
            try:
                with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
                    for member in archive:
                        name = member.name
                        if not member.isfile() or name in seen or Path(name).is_absolute() or '..' in Path(name).parts:
                            raise RuntimeError('Unsafe/duplicate archive entry')
                        if name == '_verified-export.json':
                            if member.size>1024*1024: raise RuntimeError('Oversize manifest')
                            if json.load(archive.extractfile(member)) != manifest:
                                raise RuntimeError('Source manifest changed')
                        elif name in manifest['files']:
                            if member.size != manifest['files'][name]['bytes']:
                                raise RuntimeError('Source file size changed')
                            p = stage/name; p.parent.mkdir(parents=True,exist_ok=True)
                            with archive.extractfile(member) as source, p.open('xb') as out:
                                shutil.copyfileobj(source,out,1024*1024); out.flush(); os.fsync(out.fileno())
                        else:
                            raise RuntimeError('Unexpected archive member: '+name)
                        seen.add(name)
                if proc.wait(timeout=30)!=0:
                    errors.seek(0); raise RuntimeError(errors.read().decode(errors='replace')[-1000:])
                if seen != set(manifest['files']) | {'_verified-export.json'}:
                    raise RuntimeError('Incomplete source archive')
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
                proc.stdout.close()
        verify(stage,manifest)
        save(stage/'_verified-export.json',manifest)
        # TemporaryDirectory removes only its staging path, which no longer exists.
        stage.rename(target)
    return target


def report_phase(job_id, take_id, phase):
    """Only the owning live dashboard job may publish preparation progress."""
    if not job_id:
        return
    import dashboard_jobs as jobs
    job = jobs.get(job_id)
    if job['state'] != 'running' or job['take_id'] != take_id or job['action'] not in ('stop', 'collect', 'prepare'):
        raise RuntimeError('Preparation progress job identity/state mismatch')
    if phase not in ('verifying_local_copy', 'audio_sync', 'resolve_import'):
        raise ValueError('Invalid preparation phase')
    jobs.update(job_id, phase=phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--take',default='latest')
    parser.add_argument('--local',type=Path,help='Analyze an already received take without contacting phones/remote host')
    parser.add_argument('--reference',default='samsung')
    parser.add_argument('--max-offset',type=float,default=20)
    parser.add_argument('--import-resolve',action='store_true',help='Attempt import into a dedicated project; never alter existing user projects')
    parser.add_argument('--dashboard-job',help=argparse.SUPPRESS)
    args = parser.parse_args()
    with (ROOT/'.resolve-sync.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        report_phase(args.dashboard_job,args.take,'verifying_local_copy')
        if args.local:
            folder = args.local.resolve()
            verify(folder,json.loads((folder/'_verified-export.json').read_text()))
        else:
            print('Verifying local capture and creating the editing copy...',flush=True)
            folder = receive(args.take)
        print('Media verified locally; analyzing reference audio...',flush=True)
        report_phase(args.dashboard_job,folder.name,'audio_sync')
        from audio_sync import synchronize
        report = synchronize(folder,args.reference,args.max_offset)
        if report['ok']:
            save(ROOT/'latest-resolve-ready.json',{'folder':str(folder),'report':str(folder/'Resolve Sync/sync-report.json')})
            if args.import_resolve:
                report_phase(args.dashboard_job,folder.name,'resolve_import')
                from resolve_import import import_timeline
                report['resolve_import'] = import_timeline(folder/'Resolve Sync/sync-report.json')
                save(folder/'Resolve Sync/sync-report.json',report)
        print(json.dumps({k:v for k,v in report.items() if k!='clips'},indent=2),flush=True)
        print('Report: '+str(folder/'Resolve Sync/sync-report.json'),flush=True)
        if not report['ok']: raise SystemExit(2)


if __name__ == '__main__':
    main()
