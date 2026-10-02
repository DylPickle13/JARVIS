"""Guarded deletion of capture and editing copies on this Mac."""
import json
import fcntl
from contextlib import ExitStack
import subprocess
import time
from delete_storage import checked_folder, verify_files, save


def confirmation(take, scope=None):
    if scope is None: _,m=eligible(take);scope=m['stage']
    return 'DELETE '+take+' '+scope.upper()


def eligible(take):
    import dashboard_jobs as j
    import re
    if not isinstance(take,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',take):raise ValueError('Invalid take ID')
    c=j.cache()
    if 'recording' in c.get('states',{}).values():raise RuntimeError('Finish recording before deletion')
    if c.get('pending_take'):
        if c['pending_take']!=take or not c.get('pending_review'):raise RuntimeError('Pending take is not ready for review/discard')
        return None,{'take_id':take,'stage':'phones','files':{}}
    if (j.MEDIA/take).exists():
        folder=checked_folder(j.MEDIA,take)
        m=json.loads((folder/'_verified-export.json').read_text())
        if m.get('take_id')!=take or not m.get('files'):raise ValueError('Unknown verified take')
        return folder,{**m,'stage':'both'}
    if any(t['id']==take for t in c.get('takes',[])):
        import resolve_native as n
        if any(json.loads(p.read_text()).get('take_id')==take for p in n.RUNTIME.glob('*/plan.json')):
            raise RuntimeError('Resolve history exists but local copy is missing; inspect before deleting')
        return None,{'take_id':take,'stage':'remote','files':{}}
    raise ValueError('Unknown take; nothing deleted')


def approval_plan(take, manifest):
    """Bind confirmation to scope, saved fingerprints and Resolve identity.

    No phone access or full-media hashing in an HTTP request. The worker checks
    this plan again under the preparation/import locks, then verifies the bytes.
    """
    import dashboard_jobs as j
    from runtime_paths import CAPTURE
    from delete_storage import inventory_hashes, source_inventory
    plan = {'schema': 1, 'take_id': take, 'stage': manifest['stage']}
    if manifest['stage'] == 'phones':
        pending = json.loads((j.ROOT / 'pending-take.json').read_text())
        if (pending.get('id') != take or not pending.get('review')
                or pending.get('files') or pending.get('iphone_files')
                or (CAPTURE / take).exists() or (j.MEDIA / take).exists()):
            raise RuntimeError('Phone-only review scope changed')
        from review_take import approval_binding
        plan['phone_binding'] = approval_binding(pending)
    else:
        capture = checked_folder(CAPTURE, take)
        plan['files'] = source_inventory(capture, take)
        if manifest['stage'] == 'both':
            if inventory_hashes(manifest['files']) != plan['files']:
                raise RuntimeError('Capture/editing inventories differ')
            report = j.MEDIA / take / 'Resolve Sync/sync-report.json'
            plan['resolve_import'] = json.loads(report.read_text()).get('resolve_import') if report.exists() else None
    return plan


def remote(take, job, mode, files):
    # Historical name; exact-take operation is now local, with the same journal/lock.
    from runtime_paths import CAPTURE, ROOT
    from delete_storage import remote_operation
    return remote_operation(CAPTURE, ROOT, take, job, mode, files)


def resolve_script(take, uid, directory, media):
    from resolve_native import quote as q, PROJECT
    text='''local intent=INTENT
local old=io.open(intent,'r');assert(not old,'Already attempted; inspect receipt, no replay')
local f=assert(io.open(intent,'w'));f:write('started');f:close()
local mutated=false
local ok,err=xpcall(function()
 local pm=resolve:GetProjectManager();local p=pm:GetCurrentProject()
 local names=pm:GetProjectListInCurrentFolder() or {};local found=false
 for _,name in pairs(names) do if name==PROJECT then found=true end end
 assert(found,'Dedicated project not found; inspect manually')
 if p and p:GetName()=='Untitled Project' then
  assert(p:GetTimelineCount()==0,'Nonempty unrelated project')
  local root=p:GetMediaPool():GetRootFolder()
  assert(#(root:GetClipList() or {})==0 and #(root:GetSubFolderList() or {})==0,'Nonempty unrelated project')
  for _,name in pairs(names) do assert(name~='Untitled Project','Saved unrelated project') end
  p=pm:LoadProject(PROJECT)
 end
 assert(p and p:GetName()==PROJECT,'Unrelated project open; no deletion')
 assert(p:GetTimelineCount()==1,'Project contains other timelines; manual cleanup required')
 local tl=p:GetTimelineByIndex(1)
 assert(tl:GetName()==TIMELINE and tl:GetUniqueId()==UID,'Timeline identity changed; no deletion')
 local prefix=MEDIA
 local function inspect(folder)
  for _,clip in ipairs(folder:GetClipList() or {}) do
   local path=clip:GetClipProperty('File Path')
   assert((path and string.sub(path,1,#prefix)==prefix) or
    (tl:GetMediaPoolItem() and clip:GetUniqueId()==tl:GetMediaPoolItem():GetUniqueId()),'Project contains unrelated media')
  end
  for _,child in ipairs(folder:GetSubFolderList() or {}) do inspect(child) end
 end
 inspect(p:GetMediaPool():GetRootFolder())
 mutated=true
 assert(pm:CloseProject(p),'Project close failed')
 assert(pm:DeleteProject(PROJECT),'Project deletion failed')
 for _,name in pairs(pm:GetProjectListInCurrentFolder() or {}) do assert(name~=PROJECT,'Project remains listed') end
end,debug.traceback)
f=assert(io.open(RESULT,'w'));f:write(ok and 'ok\\n' or (mutated and 'error\\n' or 'blocked\\n'),tostring(err),'\\n');f:close()
'''
    import re
    values={'INTENT':q(str(directory/'resolve-intent.txt')),'RESULT':q(str(directory/'resolve-result.txt')),'PROJECT':q(PROJECT),'TIMELINE':q('Phone Sync '+take),'UID':q(uid),'MEDIA':q(str(media/take)+'/')}
    return re.sub(r'\b(?:INTENT|RESULT|PROJECT|TIMELINE|UID|MEDIA)\b',lambda m:values[m.group()],text)


def resolve_delete(take, folder, directory):
    import resolve_native as n
    rpath = folder/'Resolve Sync/sync-report.json'
    report = json.loads(rpath.read_text()) if rpath.exists() else {}
    imported = report.get('resolve_import') or {}
    # A failed/ambiguous import cannot be silently treated as no project.
    for p in n.RUNTIME.glob('*/plan.json'):
        plan = json.loads(p.read_text())
        if plan.get('take_id') != take: continue
        result = n.read_result(p.parent/'result.txt')
        if (p.parent/'intent.txt').exists() and (not result or result['status'] != 'blocked'):
            if not imported.get('ok'): raise RuntimeError('Resolve import intent needs inspection before deletion')
    if not imported.get('ok'):
        if imported: raise RuntimeError('Resolve import was not confirmed; inspect project before deleting')
        return False
    if not imported.get('timeline_id') or imported.get('project') != n.PROJECT:
        raise RuntimeError('Missing Resolve identity; no deletion')
    script = directory/'delete.lua'
    script.write_text(resolve_script(take, imported['timeline_id'], directory, folder.parent))
    staging = n.RUNTIME/'dispatch.pending'
    staging.write_text('dofile('+n.quote(str(script))+')\n');staging.chmod(0o600);staging.replace(n.RUNTIME/'dispatch.lua')
    n.launch()  # One invocation. Any timeout remains uncertain.
    for _ in range(90):
        result = n.read_result(directory/'resolve-result.txt')
        if result: break
        time.sleep(1)
    else: raise RuntimeError('Resolve outcome unknown; no automatic retry')
    if result['status'] != 'ok': raise RuntimeError('Resolve deletion '+result['status']+': '+result['message'])
    save(n.RUNTIME/'generation.json', {'id':'after-delete-'+directory.name,'reason':'Explicit permanent test take/project deletion; no backups'})
    return True


def finish(take, directory, project_deleted):
    import dashboard_jobs as j
    # Keep historic receipts, but remove stale library entries and pointers.
    c = j.cache()
    if c.get('pending_take')==take:c.update(pending_take=None,pending_review=False,observed=None);c.pop('readiness',None)
    c['takes'] = [t for t in c.get('takes', []) if t['id'] != take]; j.cache(c)
    for name in ('latest-resolve-ready.json','latest-resolve-import.lua'):
        p=j.ROOT/name
        if p.is_file() and take in p.read_text(): p.unlink()
    result={'ok':True,'take_id':take,'both_macs_deleted':False,'local_copies_deleted':True,'resolve_project_deleted':project_deleted,'backups_created':False}
    save(directory/'complete.json',result)
    return result


def run(job, recovery=False):
    import dashboard_jobs as j
    import resolve_native as n
    take=job['take_id'];directory=n.RUNTIME/'deletions'/job['id']
    if recovery:
        # Observation only. Never repeat a Resolve mutation or rmtree.
        p=directory/'complete.json'
        if p.exists(): return json.loads(p.read_text())
        intent=directory/'intent.json'
        if intent.exists():
            plan=json.loads(intent.read_text())
            # Lost acknowledgements may be reconciled from an exact remote receipt,
            # but never resume an interrupted deletion of remaining media.
            receipt=remote(take,job['id'],'read',{})
            if receipt.get('status')=='deleted' and receipt.get('take_id')==take and not (j.MEDIA/take).exists():
                decision=directory/'resolve-decision.json'
                if plan.get('scope')=='phone originals only; no Mac copy':
                    result=finish(take,directory,False)
                    result.update(scope='phones',phone_originals_deleted=True,both_macs_deleted=False,local_copies_deleted=False)
                    save(p,result);return result
                if decision.exists():
                    return finish(take,directory,json.loads(decision.read_text())['project_deleted'])
        raise RuntimeError('Deletion incomplete or outcome unverified. Manual inspection required; nothing replayed.')
    if (directory/'intent.json').exists(): raise RuntimeError('Deletion already attempted; reconcile instead')
    approved = job.get('delete_plan')
    if not approved or approved.get('take_id') != take:
        raise RuntimeError('Missing durable deletion approval; confirm a new job')
    with ExitStack() as stack:
        n.RUNTIME.mkdir(mode=0o700,parents=True,exist_ok=True)
        for path in (j.ROOT/'.resolve-sync.lock',n.RUNTIME/'import.lock'):
            f=stack.enter_context(path.open('a'));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        folder, m = eligible(take)
        if approval_plan(take, m) != approved:
            raise RuntimeError('Deletion scope/inventory changed after confirmation; confirm again')
        if m['stage']=='phones':
            save(directory/'approval.json', approved['phone_binding'])
            save(directory/'intent.json',{'take_id':take,'scope':'phone originals only; no Mac copy','permanent':True})
            j.update(job['id'],phase='discarding_phone_originals')
            from runtime_paths import helper
            out=subprocess.run(helper('review_take.py',take,job['id'],str(directory/'approval.json')),capture_output=True,text=True,timeout=3700)
            if out.returncode:raise RuntimeError('Phone discard outcome needs inspection: '+out.stderr[-900:])
            receipt=json.loads(out.stdout)
            if receipt.get('status')!='deleted' or receipt.get('take_id')!=take:raise RuntimeError('Phone discard not confirmed')
            result=finish(take,directory,False);result.update(scope='phones',phone_originals_deleted=True,both_macs_deleted=False,local_copies_deleted=False)
            save(directory/'complete.json',result);return result
        m['files'] = approved['files']
        if folder:verify_files(folder,m['files'])
        checked=remote(take,job['id'],'check',m['files'])
        if checked.get('status') != 'checked' or checked.get('files') != approved['files']:
            raise RuntimeError('Remote deletion not verified safe')
        m['files']=checked['files']
        save(directory/'intent.json',{'take_id':take,'files':m['files'],'scope':'local capture and editing copies and sole dedicated Resolve project','permanent':True})
        j.update(job['id'],phase='deleting_resolve_project')
        project_deleted=resolve_delete(take,folder,directory) if folder else False
        save(directory/'resolve-decision.json',{'project_deleted':project_deleted})
        j.update(job['id'],phase='deleting_remote_take')
        if remote(take,job['id'],'delete',m['files']).get('status') != 'deleted':
            raise RuntimeError('Remote deletion unverified; no replay')
        save(directory/'remote-deleted.json',{'ok':True})
        j.update(job['id'],phase='deleting_local_take')
        # Recheck the exact folder/inventory immediately before removal.
        if folder:
            checked_folder(j.MEDIA,take);verify_files(folder,m['files'])
            import shutil
            shutil.rmtree(folder)
            if folder.exists(): raise RuntimeError('Local folder still exists')
        result=finish(take,directory,project_deleted)
        # Completed menu replay is guarded, but make routine dispatch harmless too.
        (n.RUNTIME/'dispatch.lua').write_text("print('No take queued. Use Phone Recording dashboard.')\n")
        return result
