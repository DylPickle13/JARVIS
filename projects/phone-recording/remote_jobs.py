#!/usr/bin/env python3
"""Local durable single-shot Wi-Fi recording helper; no SSH or USB fallback."""
import argparse
import datetime
import fcntl
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback
from collect import save
import managed_control as pair
from camera_config import CONFIG_ID
import readiness

from runtime_paths import ROOT, CAPTURE
JOBS = ROOT/'.dashboard-jobs'
ACTIONS = ('start','stop','stop_review','collect','status')


def now():
    return datetime.datetime.now().astimezone().isoformat()


def valid_id(value):
    if not re.fullmatch(r'[0-9a-f]{32}',value): raise ValueError('Invalid job ID')
    return value


def read_job(job_id):
    path=JOBS/(valid_id(job_id)+'.json')
    job=json.loads(path.read_text())
    age=(datetime.datetime.now().astimezone()-datetime.datetime.fromisoformat(job.get('started',job['created']))).total_seconds()
    if job['state'] in ('queued','running') and age>45:
        with (JOBS/(job_id+'.lock')).open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return job
            job=json.loads(path.read_text())
            if job['state'] in ('queued','running'):
                job.update(state='error',error='Remote worker disappeared; outcome unverified. Inspect phone states and pending take. No command replayed.',ended=now())
                save(path,job)
    return job


def submit(job_id,action):
    valid_id(job_id)
    if action not in ACTIONS: raise ValueError('Unknown action')
    JOBS.mkdir(mode=0o700,exist_ok=True)
    with (JOBS/'.submit.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path = JOBS/(job_id+'.json')
        if path.exists():
            job = read_job(job_id)
            if job['action']!=action: raise RuntimeError('Idempotency key/action conflict')
            return job  # Never re-execute an ambiguous recording mutation.
        job = {'id':job_id,'action':action,'state':'queued','created':now()}
        save(path,job)
        with (JOBS/(job_id+'.log')).open('ab') as log:
            p = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker',job_id],cwd=ROOT,
                                 stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        # Worker owns subsequent updates. Never overwrite its result after spawn.
        return {**job,'pid':p.pid}


def snapshot():
    ready = pair.status()
    pending = ROOT/'pending-take.json'
    takes = []
    for p in sorted(CAPTURE.glob('*/transfer-manifest.json'),reverse=True):
        try:
            m=json.loads(p.read_text())
            takes.append({'id':m['id'],'path':str(p.parent),'cameras':sorted(m.get('scope',m.get('before',{}))),
                          'has_iphone':(p.parent/'iphone/iphone-transfer.json').exists()})
        except (ValueError,KeyError,OSError): continue
    health=readiness.check(ready) if not pending.exists() else None
    return {'config_id':CONFIG_ID,'readiness':health,'states':ready,'observed':now(),'pending_take':json.loads(pending.read_text())['id'] if pending.exists() else None,
            'pending_review':bool(json.loads(pending.read_text()).get('review')) if pending.exists() else False,
            'takes':takes[:100],'host':'mac-mini-64','scope':list(pair.ROLES),
            'transports':pair.connection_info()}


def worker(job_id):
    job = read_job(job_id); path=JOBS/(job_id+'.json')
    with (JOBS/(job_id+'.lock')).open('a') as own:
        fcntl.flock(own,fcntl.LOCK_EX | fcntl.LOCK_NB)
        if job['state']!='queued': return
        job.update(state='running',started=now()); save(path,job)
        try:
            with (ROOT/'.pair-control.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
                pending=ROOT/'pending-take.json'
                if job['action'] in ('stop','stop_review','collect') and pending.exists():
                    job['take_id']=json.loads(pending.read_text())['id']
                # Persist intent before entering code that can send a toggle.
                job['phase']='executing_'+job['action']; save(path,job)
                if job['action']=='status':
                    result=snapshot()
                else:
                    result=pair.managed(job['action'])
                    if job['action']=='start' and pending.exists():
                        job['take_id']=json.loads(pending.read_text())['id']
                job.update(state='done',result=result,ended=now())
        except Exception as error:
            # Errors are not permission to retry a toggle. Preserve uncertain intent.
            job.update(state='error',error=str(error)[:1000],ended=now())
            traceback.print_exc()
        save(path,job)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['submit','read','worker','preview']);p.add_argument('id');p.add_argument('action',nargs='?',choices=ACTIONS)
    a=p.parse_args();valid_id(a.id)
    if a.command=='preview':
        from framing_preview import capture
        print(json.dumps(capture()))
    elif a.command=='worker': worker(a.id)
    else: print(json.dumps(submit(a.id,a.action) if a.command=='submit' else read_job(a.id)))


if __name__=='__main__':main()
