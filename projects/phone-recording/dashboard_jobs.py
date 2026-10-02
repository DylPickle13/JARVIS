"""Shared local job engine for dashboard and CLI. Recording work survives clients."""
from camera_config import CAMERAS,ROLES,PREVIEW_ROLES,IDLE,UNKNOWN,CONFIG_ID,public as camera_public
import readiness
import datetime
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'.dashboard'
MEDIA=Path.home()/'Movies/Phone Recordings'
ACTIONS=('status','start','stop','collect','prepare','import','preview','delete','stop_review')
BUSY=('queued','running','uncertain')


def now():return datetime.datetime.now().astimezone().isoformat()


@contextmanager
def db():
    STATE.mkdir(mode=0o700,exist_ok=True)
    c=sqlite3.connect(STATE/'jobs.sqlite',timeout=10)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, action TEXT NOT NULL, take_id TEXT, state TEXT NOT NULL, phase TEXT, created TEXT, updated TEXT, result TEXT, error TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)')
    # Separate table upgrades existing databases without rewriting jobs/history.
    c.execute('CREATE TABLE IF NOT EXISTS delete_approvals (job_id TEXT PRIMARY KEY, plan TEXT NOT NULL)')
    c.commit()
    try:
        with c:yield c
    finally:c.close()


def unpack(row):
    r=dict(row)
    if r.get('result'):r['result']=json.loads(r['result'])
    if r.get('delete_plan'):r['delete_plan']=json.loads(r['delete_plan'])
    return r


def get(job_id):
    with db() as c:
        row=c.execute('SELECT jobs.*, a.plan AS delete_plan FROM jobs LEFT JOIN delete_approvals a ON a.job_id=jobs.id WHERE jobs.id=?',(job_id,)).fetchone()
    if not row:raise ValueError('Job not found')
    return unpack(row)


def update(job_id,**fields):
    fields['updated']=now()
    if 'result' in fields:fields['result']=json.dumps(fields['result'])
    if not set(fields)<={'state','phase','updated','result','error','take_id'}:raise ValueError('Bad field')
    with db() as c:c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',list(fields.values())+[job_id])


def cache(value=None):
    with db() as c:
        if value is not None:c.execute('INSERT OR REPLACE INTO cache VALUES (?,?)',('remote',json.dumps(value)))
        r=c.execute('SELECT value FROM cache WHERE key=?',('remote',)).fetchone()
    return json.loads(r[0]) if r else {'states':dict(UNKNOWN),'takes':[],'observed':None}


def spawn(job_id,recover=False):
    with (STATE/(job_id+'.log')).open('ab') as log:
        subprocess.Popen([sys.executable,str(ROOT/'dashboard_jobs.py'),'worker',job_id]+(['--recover'] if recover else []),
                         cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)


def submit(action,take_id=None,request_id=None,confirmation=None):
    if action not in ACTIONS:raise ValueError('Unknown action')
    if action in ('prepare','import','delete'):
        if not take_id or not re.fullmatch(r'[A-Za-z0-9_-]+',take_id):raise ValueError('An explicit take ID is required')
    elif take_id is not None:raise ValueError('Take ID not accepted for this action')
    if action=='delete':
        if confirmation not in {'DELETE '+take_id+' '+scope for scope in ('PHONES','REMOTE','BOTH')}:raise ValueError('Exact permanent deletion confirmation required')
    job_id=request_id or uuid.uuid4().hex
    if not re.fullmatch(r'[0-9a-f]{32}',job_id):raise ValueError('Invalid idempotency key')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if old:
            if old['action']!=action or (action in ('prepare','import','delete') and old['take_id']!=take_id):raise ValueError('Idempotency conflict')
            if action == 'delete':
                approval = c.execute('SELECT plan FROM delete_approvals WHERE job_id=?', (job_id,)).fetchone()
                if not approval or confirmation != 'DELETE ' + take_id + ' ' + json.loads(approval[0])['stage'].upper():
                    raise ValueError('Deletion idempotency scope conflict')
            return unpack(old)
        if c.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','uncertain')").fetchone():
            raise RuntimeError('Another job is active or uncertain. Wait or reconcile it first.')
        if action=='delete':
            from delete_take import eligible, approval_plan, confirmation as required
            _,manifest=eligible(take_id)
            if confirmation!=required(take_id,manifest['stage']):raise ValueError('Take location changed; review deletion scope again')
            approved = approval_plan(take_id, manifest)
        if action in ('prepare','import'):
            status=cache()
            if status.get('pending_take') or 'recording' in status.get('states',{}).values():raise RuntimeError('Finish recording/collection before preparing another take')
        if action=='start':
            cached=c.execute('SELECT value FROM cache WHERE key=?',('remote',)).fetchone()
            status=json.loads(cached[0]) if cached else {}
            age=(datetime.datetime.now().astimezone()-datetime.datetime.fromisoformat(status['observed'])).total_seconds() if status.get('observed') else 1e9
            if not -5<=age<=120 or set(status.get('states',{}))!=set(ROLES) or set(status.get('states',{}).values())!={'idle'} or status.get('pending_take'):
                raise RuntimeError('Refresh cameras first: every enabled camera must be recently verified idle with no pending take.')
            if status.get('config_id')!=CONFIG_ID or not readiness.approved(status.get('readiness')):
                raise RuntimeError('Refresh camera health first: missing/stale/blocked readiness or configuration mismatch.')
            if not readiness.local_storage()['ok']:
                raise RuntimeError('Insufficient free space on this Mac (minimum 5 GiB).')
        c.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',(job_id,action,take_id,'queued','queued',now(),now(),None,None))
        if action == 'delete':
            c.execute('INSERT INTO delete_approvals VALUES (?,?)', (job_id, json.dumps(approved)))
    if action in ('start','preview'):clear_previews()
    try:spawn(job_id)
    except Exception as e:update(job_id,state='uncertain',error='Local worker launch uncertain: '+str(e))
    return get(job_id)


def recover(job_id):
    job=get(job_id)
    if job['state']!='uncertain':raise ValueError('Only uncertain jobs can be reconciled')
    with db() as c:
        if c.execute("UPDATE jobs SET state='queued',phase='reconciling',updated=? WHERE id=? AND state='uncertain'",(now(),job_id)).rowcount!=1:
            raise RuntimeError('Already reconciling')
    spawn(job_id,True);return get(job_id)


def remote(command,job_id,action=None):
    from runtime_paths import helper
    args=helper('remote_jobs.py',command,job_id,*([action] if action else []))
    out=subprocess.check_output(args,cwd=ROOT,text=True,stderr=subprocess.PIPE,timeout=180 if command=='preview' else 40)
    return json.loads(out)


def lost_workers():
    # Read-only reconciliation of local worker death; never reissue recording commands.
    with db() as c:rows=c.execute("SELECT * FROM jobs WHERE state IN ('queued','running')").fetchall()
    for row in rows:
        age=(datetime.datetime.now().astimezone()-datetime.datetime.fromisoformat(row['updated'])).total_seconds()
        if age<45:continue
        with (STATE/(row['id']+'.lock')).open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:continue
            latest=get(row['id'])
            if latest['state'] in ('queued','running'):
                update(row['id'],state='uncertain',error='Worker is no longer running. Reconcile; no camera command was retried.')


def local_takes():
    result=[]
    for p in sorted(MEDIA.glob('*/_verified-export.json'),reverse=True):
        try:
            m=json.loads(p.read_text());report=p.parent/'Resolve Sync/sync-report.json'
            sync=json.loads(report.read_text()) if report.exists() else None
            result.append({'id':m['take_id'],'path':str(p.parent),'cameras':sorted({Path(n).parts[0] for n in m['files']}),
                           'sync_ok':sync.get('ok') if sync else None,'sync_error':sync.get('error') if sync else None,
                           'timeline':sync.get('timeline') if sync and sync.get('ok') else None,
                           'import_status':sync.get('resolve_import') if sync else None})
        except (OSError,ValueError,KeyError):continue
    return result


def clear_previews():
    for name in [r+'.jpg' for r,c in CAMERAS.items() if c['preview']]+['preview.json']:
        (STATE/name).unlink(missing_ok=True)


def preview_info():
    try:
        value=json.loads((STATE/'preview.json').read_text())
        age=time.time()-value['created']
        if not 0<=age<=60:
            clear_previews();return None
        r=cache()
        if r.get('states')!=dict(IDLE) or r.get('pending_take'):return None
        with db() as c:
            if c.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','uncertain')").fetchone():return None
        return {'observed':value['observed'],'expires_in':int(60-age)}
    except (OSError,ValueError,KeyError):return None


def state():
    lost_workers()
    with db() as c:jobs=[unpack(r) for r in c.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 50')]
    return {'host':'mac-mini-64','recording_host':'mac-mini-64','scope':list(ROLES),'config_id':CONFIG_ID,'cameras':camera_public(),'local_storage':readiness.local_storage(),'remote':cache(),
            'jobs':jobs,'takes':local_takes(),'media_root':str(MEDIA),'source_root':str(ROOT),
            'active':next((j['id'] for j in jobs if j['state'] in BUSY),None),'preview':preview_info()}


def preparation(job_id,take_id):
    update(job_id,phase='copy_verify_and_audio_sync',take_id=take_id)
    # Existing CLI owns the cross-tool sync lock, verifies copies and makes OTIO.
    p=subprocess.run([sys.executable,str(ROOT/'prepare_resolve.py'),'--take',take_id,'--import-resolve','--dashboard-job',job_id],cwd=ROOT,timeout=7200)
    report=MEDIA/take_id/'Resolve Sync/sync-report.json'
    result=json.loads(report.read_text()) if report.exists() else {'ok':False,'error':'No local sync report'}
    if p.returncode!=0:result={**result,'ok':False,'error':result.get('error','Preparation failed; inspect job log')}
    return {k:result.get(k) for k in ('ok','error','timeline','offsets_seconds','resolve_import') if k in result}


def preparation_status(prepared):
    if not prepared.get('ok'):return {'state':'needs_review','phase':'sync_needs_review'}
    if prepared.get('resolve_import',{}).get('ok') is False:
        return {'state':'needs_review','phase':'resolve_import_needs_review'}
    return {'state':'done','phase':'timeline_ready'}


def worker(job_id,is_recovery=False):
    job=get(job_id)
    with (STATE/(job_id+'.lock')).open('a') as own:
        fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if get(job_id)['state'] not in ('queued','running'):return
        update(job_id,state='running',phase='reconciling_remote' if is_recovery else 'starting_job',error=None)
        action=job['action']
        try:
            if action in ('start','stop','stop_review','collect','status'):
                if not is_recovery:
                    update(job_id,phase='sending_single_remote_request')
                    # Exactly one submit. A timeout is an uncertain outcome, not retry permission.
                    remote('submit',job_id,action)
                deadline=time.monotonic()+3900
                while True:
                    r=remote('read',job_id)
                    if r['state'] in ('done','error'):break
                    if time.monotonic()>deadline:raise TimeoutError('Remote job still running; reconcile later')
                    update(job_id,phase=r.get('phase',r['state']))
                    time.sleep(2)
                update(job_id,result={'remote':r},take_id=r.get('take_id',job['take_id']))
                if r['state']=='error':
                    stale=cache();stale.pop('readiness',None);stale.update(states=dict(UNKNOWN),observed=None);cache(stale)
                    update(job_id,state='needs_review',phase='remote_error',error=r.get('error'));return
                result=r['result']
                if action=='status':
                    cache(result);update(job_id,state='done',phase='status_updated');return
                snapshot=cache();snapshot.pop('readiness',None);snapshot.update(states=result.get('after_rollback',result.get('after',dict(UNKNOWN))),observed=now())
                if not result.get('ok') and result.get('readiness'):
                    snapshot['readiness']=result['readiness']
                snapshot['pending_take']=r.get('take_id') if action in ('start','stop_review') or not result.get('ok') else None
                snapshot['pending_review']=bool(result.get('review_ready'))
                cache(snapshot)
                if not result.get('ok'):
                    update(job_id,state='needs_review',phase='control_or_collection_needs_review',error=result.get('error','Inspect remote result; no blind retry'));return
                if action=='start':update(job_id,state='done',phase='recording');return
                if action=='stop_review':update(job_id,state='done',phase='awaiting_transfer');return
                take_id=r.get('take_id')
                if not take_id:raise RuntimeError('Completed take identity missing; refusing latest-take guess')
                if action=='collect':
                    snapshot=cache();snapshot['takes']=[t for t in snapshot.get('takes',[]) if t['id']!=take_id]+[{'id':take_id,'cameras':list(ROLES),'has_iphone':True}]
                    cache(snapshot);update(job_id,state='done',phase='awaiting_verified_copy');return
                prepared=preparation(job_id,take_id)
                update(job_id,**preparation_status(prepared),result={'remote':r,'preparation':prepared})
            elif action=='preview':
                import base64
                from collect import save
                update(job_id,phase='checking_idle_and_capturing_snapshots')
                value=remote('preview',job_id)
                if set(value['images'])!=set(PREVIEW_ROLES):raise RuntimeError('Incomplete framing snapshots')
                if value.get('config_id')!=CONFIG_ID:raise RuntimeError('Remote framing configuration mismatch')
                if value.get('states')!=dict(IDLE):raise RuntimeError('Every enabled camera idle observation required for framing')
                for role,encoded in value['images'].items():
                    data=base64.b64decode(encoded,validate=True)
                    if len(data)>1_000_000 or not data.startswith(b'\xff\xd8'):raise RuntimeError('Invalid preview JPEG')
                    path=STATE/(role+'.jpg');path.write_bytes(data);path.chmod(0o600)
                save(STATE/'preview.json',{'created':time.time(),'observed':value['observed']})
                snapshot=cache();snapshot.update(states=dict(IDLE),observed=value['observed'],pending_take=None);cache(snapshot)
                update(job_id,state='done',phase='framing_snapshots_ready',result={'observed':value['observed'],'expires_in':60})
            elif action=='delete':
                from delete_take import run
                result=run(job,is_recovery)
                update(job_id,state='done',phase='take_deleted',result=result)
            elif action=='prepare':
                prepared=preparation(job_id,job['take_id'])
                update(job_id,**preparation_status(prepared),result={'preparation':prepared})
            elif action=='import':
                from resolve_import import import_timeline
                from collect import save
                with (ROOT/'.resolve-sync.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    path=MEDIA/job['take_id']/'Resolve Sync/sync-report.json'
                    report=json.loads(path.read_text());result=import_timeline(path)
                    report['resolve_import']=result;save(path,report)
                update(job_id,state='done' if result.get('ok') else 'needs_review',phase='resolve_import',result=result)
        except Exception as error:
            if action=='preview':clear_previews()
            # Mutations may have happened remotely. Keep the operation gate closed
            # until the same remote job ID is read, never resubmit on recovery.
            ambiguous=action in ('start','stop','stop_review','collect')
            if action=='delete':
                from resolve_native import read_result,RUNTIME
                directory=RUNTIME/'deletions'/job_id
                receipt=read_result(directory/'resolve-result.txt')
                ambiguous=(directory/'intent.json').exists() and not (receipt and receipt['status']=='blocked')
            update(job_id,state='uncertain' if ambiguous else 'needs_review',phase='connection_or_worker_error',error=str(error)[:1500])
            print(type(error).__name__+': '+str(error),flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['worker','status','start','stop','collect','refresh','prepare','import','recover','preview'])
    p.add_argument('value',nargs='?');p.add_argument('--recover',action='store_true');a=p.parse_args()
    if a.command=='worker':worker(a.value,a.recover)
    else:
        r=state() if a.command=='status' else recover(a.value) if a.command=='recover' else submit('status' if a.command=='refresh' else a.command,a.value)
        print(json.dumps(r,indent=2))
