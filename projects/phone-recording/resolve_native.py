"""Reusable native Resolve timeline drop through an explicit finite Lua menu job.

No UI timeline editing, listener, recording commands, or automatic project switch.
The App Store build supplies `resolve` to menu scripts. Persist submission BEFORE
launch; ambiguous attempts are never replayed. Completed imports never overwrite edits.
"""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from collect import save
from camera_config import CAMERAS

PROJECT='Phone Recordings Auto Sync'
FUSION=Path.home()/'Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data/Library/Application Support/Fusion'
# Shared ordinary media-folder workspace avoids repeated protected app-container
# access by VS Code/Pi workers. Only the fixed menu launcher lives in the sandbox.
RUNTIME=Path.home()/'Movies/Phone Recordings/.resolve-automation'
MENU=FUSION/'Scripts/Utility/JARVIS Approved Edit.lua'


def quote(value):
    eq='='
    while ']'+eq+']' in str(value):eq+='='
    return '['+eq+'['+str(value)+']'+eq+']'


def plan(report_path):
    from prepare_resolve import verify
    report_path=Path(report_path)
    r=json.loads(report_path.read_text())
    if not r.get('ok') or r.get('fps')!=30:raise ValueError('Approved 30fps audio sync required')
    take=r.get('take_id','')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',take):raise ValueError('Invalid take ID')
    folder=report_path.parent.parent
    manifest=json.loads((folder/'_verified-export.json').read_text())
    if folder.name!=take or manifest.get('take_id')!=take:raise ValueError('Take mismatch')
    verify(folder,manifest)
    clips=[];roles=set();paths=set()
    for c in r['clips']:
        role=c['role'];p=Path(c['path']).resolve()
        if role not in CAMERAS or role in roles:raise ValueError('Unknown/duplicate camera role')
        relative=p.relative_to(folder.resolve()).as_posix()
        if relative not in manifest['files'] or Path(relative).parts[0]!=role:raise ValueError('Unverified source')
        offset=c['timeline_start_frame'];seconds=float(c['metadata']['format']['duration'])
        if type(offset) is not int or offset<0 or not 0<seconds<86400:raise ValueError('Invalid source timing')
        roles.add(role);paths.add(relative)
        clips.append({'role':role,'label':CAMERAS[role]['name'],'path':str(p),'offset':offset,'seconds':seconds,'sha256':manifest['files'][relative]['sha256']})
    if paths!=set(manifest['files']) or r['reference'] not in roles:raise ValueError('Incomplete camera/reference set')
    return {'schema':1,'take_id':take,'project':PROJECT,'timeline':'Phone Sync '+take,'reference':r['reference'],'clips':clips}


def script(p, result, intent):
    entries=',\n'.join('{role='+quote(c['role'])+',label='+quote(c['label'])+',path='+quote(c['path'])+',offset='+str(c['offset'])+',seconds='+str(c['seconds'])+'}' for c in p['clips'])
    text=r'''-- Generated source-linked stack only: no cuts, deletes, listener or loop.
local resultPath=RESULT_PATH
local intentPath=INTENT_PATH
local function report(status,message)
 local f=assert(io.open(resultPath,'w'))
 f:write(status,'\n',tostring(message):gsub('[\r\n]',' '),'\n');f:close()
end
local previous=io.open(intentPath,'r')
if previous then
 previous:close()
 local done=io.open(resultPath,'r')
 if done then done:close() else report('error','Intent already exists; no replay') end
 return
end
local app=resolve or bmd.scriptapp('Resolve')
if not app then report('blocked','Resolve unavailable');return end
local pm=app:GetProjectManager()
local project=pm:GetCurrentProject()
-- Resolve exposes a transient empty placeholder after closing/deleting a project.
-- Never treat a saved or populated project as disposable based on its name alone.
if project and project:GetName()=='Untitled Project' and project:GetTimelineCount()==0 then
 local names=pm:GetProjectListInCurrentFolder()
 local root=project:GetMediaPool():GetRootFolder()
 local saved=false
 if names then for _,n in pairs(names) do if n=='Untitled Project' then saved=true end end end
 if names and not saved and #root:GetClipList()==0 and #root:GetSubFolderList()==0 then project=nil end
end
if project and project:GetName()~=PROJECT_NAME then report('blocked','Unrelated project open; no switch or edit performed');return end
local clips={CLIPS}
local name=TIMELINE_NAME
if project then
 for i=1,project:GetTimelineCount() do
  if project:GetTimelineByIndex(i):GetName()==name then report('blocked','Timeline already exists without this completion receipt; preserve edits and inspect');return end
 end
 if project:GetTimelineCount()>0 and tonumber(project:GetSetting('timelineFrameRate'))~=30 then report('blocked','Existing project is not 30fps; no settings changed');return end
end
local f=assert(io.open(intentPath,'w'));f:write('started\n');f:close()
local ok,err=xpcall(function()
 project=project or pm:LoadProject(PROJECT_NAME) or pm:CreateProject(PROJECT_NAME)
 assert(project and project:GetName()==PROJECT_NAME,'Cannot open dedicated project')
 -- Loading an existing dedicated project must not evade duplicate/settings guards.
 for i=1,project:GetTimelineCount() do assert(project:GetTimelineByIndex(i):GetName()~=name,'Timeline exists; no overwrite') end
 if project:GetTimelineCount()==0 then
  assert(project:SetSetting('timelineFrameRate','30'),'Cannot set 30fps')
  assert(project:SetSetting('timelineResolutionWidth','3840'),'Cannot set width')
  assert(project:SetSetting('timelineResolutionHeight','2160'),'Cannot set height')
 end
 assert(tonumber(project:GetSetting('timelineFrameRate'))==30,'30fps required')
 local pool=project:GetMediaPool();local media={}
 local function walk(folder)
  for _,m in ipairs(folder:GetClipList()) do media[m:GetClipProperty('File Path')]=m end
  for _,sub in ipairs(folder:GetSubFolderList()) do walk(sub) end
 end
 walk(pool:GetRootFolder())
 for _,c in ipairs(clips) do
  c.media=media[c.path]
  if not c.media then
   local imported=pool:ImportMedia({c.path});assert(imported and #imported==1,'Media import incomplete')
   c.media=imported[1]
  end
  assert(c.media:GetClipProperty('File Path')==c.path,'Source path mismatch')
  assert(c.media:GetClipProperty('Online Status')=='Online','Source offline')
  c.frames=assert(tonumber(c.media:GetClipProperty('Frames')),'Unknown source frames')
  c.fps=assert(tonumber(c.media:GetClipProperty('FPS')),'Unknown source fps')
  assert(math.abs(c.frames/c.fps-c.seconds)<0.15,'Source duration interpretation changed; inspect VFR')
 end
 local timeline=assert(pool:CreateEmptyTimeline(name),'Timeline creation failed')
 assert(project:SetCurrentTimeline(timeline),'Cannot select timeline')
 assert(timeline:SetStartTimecode('00:00:00:00'),'Cannot set timeline origin')
 for _,kind in ipairs({'video','audio'}) do
  while timeline:GetTrackCount(kind)<#clips do assert(timeline:AddTrack(kind),'Cannot add track') end
 end
 for i,c in ipairs(clips) do
  for _,kind in ipairs({'video','audio'}) do
   local items=pool:AppendToTimeline({{mediaPoolItem=c.media,startFrame=0,endFrame=c.frames,recordFrame=c.offset,mediaType=kind=='video' and 1 or 2,trackIndex=i}})
   assert(items and #items==1,'Append failed')
   assert(items[1]:GetStart()==c.offset,'Placement mismatch')
   assert(math.abs(items[1]:GetDuration()-c.seconds*30)<4,'Duration mismatch; inspect VFR')
   assert(items[1]:GetMediaPoolItem():GetClipProperty('File Path')==c.path,'Appended source mismatch')
   assert(timeline:SetTrackName(kind,i,c.label),'Track naming failed')
   if kind=='audio' then assert(timeline:SetTrackEnable(kind,i,c.role==REFERENCE),'Audio enable failed') end
  end
 end
 for _,kind in ipairs({'video','audio'}) do
  assert(timeline:GetTrackCount(kind)==#clips,'Track count mismatch')
  for i=1,#clips do assert(#timeline:GetItemListInTrack(kind,i)==1,'Clip count mismatch') end
 end
 timeline:AddMarker(0,'Yellow','Aligned camera tracks','One full source per video track. Only reference audio enabled. Top enabled video track is visible; disable upper tracks to inspect lower angles. Review picture/audio sync before editing.',1)
 assert(pm:SaveProject(),'Save failed')
 timeline:SetCurrentTimecode('00:00:00:00')
 app:OpenPage('edit')
 report('ok',timeline:GetUniqueId())
end,debug.traceback)
if not ok then report('error',err) end
'''
    # Single regex substitution prevents replacement tokens inside paths being re-expanded.
    values={'RESULT_PATH':quote(result),'INTENT_PATH':quote(intent),'PROJECT_NAME':quote(PROJECT),'TIMELINE_NAME':quote(p['timeline']),'REFERENCE':quote(p['reference']),'CLIPS':entries}
    return re.sub(r'\b(?:RESULT_PATH|INTENT_PATH|PROJECT_NAME|TIMELINE_NAME|REFERENCE|CLIPS)\b',lambda m:values[m.group()],text)


def launch():
    # One menu invocation, not keyboard typing or GUI timeline editing.
    subprocess.run(['open','-a','DaVinci Resolve'],check=True,timeout=15)
    check='''tell application "System Events" to tell process "Resolve"
get exists menu item "JARVIS Approved Edit" of menu 1 of menu item "Scripts" of menu "Workspace" of menu bar item "Workspace" of menu bar 1
end tell'''
    for _ in range(20):
        r=subprocess.run(['osascript','-e',check],capture_output=True,text=True,timeout=5)
        if r.returncode==0 and r.stdout.strip()=='true':break
        time.sleep(1)
    else:raise RuntimeError('Resolve menu script unavailable; restart Resolve when safe, then inspect this request before retrying')
    subprocess.run(['osascript','-e','''tell application "System Events" to tell process "Resolve"
click menu item "JARVIS Approved Edit" of menu 1 of menu item "Scripts" of menu "Workspace" of menu bar item "Workspace" of menu bar 1
end tell'''],check=True,capture_output=True,text=True,timeout=15)


def read_result(path):
    if not path.exists():return None
    lines=path.read_text().splitlines()
    # A partially written result is not completion.
    if len(lines)<2 or lines[0] not in ('ok','blocked','error'):return None
    return {'ok':lines[0]=='ok','status':lines[0],'message':lines[1]}


def import_timeline(report_path, timeout=90):
    p=plan(report_path)
    # Explicit project rebuilds rotate this generation AFTER backed-up deletion.
    # Ordinary retries never change it and therefore preserve completed edits.
    generation=RUNTIME/'generation.json'
    if generation.exists():p['project_generation']=json.loads(generation.read_text())['id']
    key=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()
    RUNTIME.mkdir(parents=True,mode=0o700,exist_ok=True)
    with (RUNTIME/'import.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        folder=RUNTIME/key;folder.mkdir(mode=0o700,exist_ok=True)
        result=folder/'result.txt';intent=folder/'intent.txt';state=folder/'request.json'
        def outcome(r,cached=False):
            return {'ok':r['ok'],'project':PROJECT,'timeline':p['timeline'],'tracks':len(p['clips']),
                    'request_id':key,'already_imported':cached and r['ok'],
                    'reason':r['message'] if not r['ok'] else 'Previously imported; no Resolve edits repeated' if cached else 'Native per-camera tracks saved; visual sync needs review',
                    'timeline_id':r['message'] if r['ok'] else None}
        for other in RUNTIME.glob('*/request.json'):
            if other.parent!=folder and not read_result(other.parent/'result.txt'):
                return {'ok':False,'reason':'Another native import is unresolved; no new job launched: '+other.parent.name}
        prior=read_result(result)
        if prior and prior['ok']:return outcome(prior,True)
        if intent.exists() or (state.exists() and not prior):
            return {'ok':False,'reason':'Previous import outcome uncertain; no replay. Inspect native request '+key,'request_id':key}
        if prior and prior['status']!='blocked':return outcome(prior)
        # A blocked result explicitly means no edit occurred, so a later deliberate
        # import can try again after the user opens the correct project.
        if result.exists():result.unlink()
        save(folder/'plan.json',p)
        job=folder/'job.lua';job.write_text(script(p,result,intent));job.chmod(0o600)
        # The installed menu launcher is fixed. Never inspect/write the protected
        # Resolve container during normal pipeline operation.
        staging=RUNTIME/'dispatch.pending'
        staging.write_text('-- JARVIS finite approved import; no persistent process.\ndofile('+quote(job)+')\n')
        staging.chmod(0o600);staging.replace(RUNTIME/'dispatch.lua')
        save(state,{'state':'submitted','request_id':key,'plan':p})
        launch_error=None
        try:launch()
        except Exception as e:launch_error=type(e).__name__+': '+str(e)[:300]
        deadline=time.monotonic()+timeout
        while True:
            r=read_result(result)
            if r:return outcome(r)
            if launch_error or time.monotonic()>=deadline:
                return {'ok':False,'request_id':key,'reason':'Native import outcome unverified; no replay. '+(launch_error or 'Timed out waiting for result')}
            time.sleep(.5)
