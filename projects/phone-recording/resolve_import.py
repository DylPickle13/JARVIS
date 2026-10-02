"""Guarded Resolve import. Does not switch away from unrelated user projects."""
import json
import math
import os
from pathlib import Path
import sys

PROJECT = 'Phone Recordings Auto Sync'
APP = Path('/Applications/DaVinci Resolve.app/Contents')
ROOT = Path(__file__).resolve().parent


def connect():
    os.environ['RESOLVE_SCRIPT_LIB'] = str(APP/'Libraries/Fusion/fusionscript.so')
    modules = str(APP/'Resources/Developer/Scripting/Modules')
    if modules not in sys.path: sys.path.insert(0,modules)
    import DaVinciResolveScript as dvr
    return dvr.scriptapp('Resolve')


def import_timeline(report_path):
    """Default pipeline path: native per-camera stack, via finite in-app Lua."""
    try:
        from resolve_native import import_timeline as native_import
        return native_import(report_path)
    except Exception as error:
        return {'ok':False,'reason':type(error).__name__+': '+str(error)[:1000]}


def import_timeline_external(report_path):
    """Legacy external OTIO diagnostic; no longer the default pipeline path."""
    report = json.loads(Path(report_path).read_text())
    if not report.get('ok'):
        return {'ok':False,'reason':'Sync not approved; import refused'}
    try:
        resolve = connect()
        if not resolve:
            return {'ok':False,'reason':'External Resolve scripting unavailable. Use the generated Import into Resolve.lua from inside Resolve, or import Synced.otio manually.'}
        manager = resolve.GetProjectManager(); project = manager.GetCurrentProject()
        if project and project.GetName()!=PROJECT:
            return {'ok':False,'reason':'Unrelated project open; no project switch or edit performed. Open '+PROJECT+' and retry.'}
        if not project:
            project = manager.LoadProject(PROJECT) or manager.CreateProject(PROJECT)
        if not project: raise RuntimeError('Cannot open dedicated sync project')
        name = 'Phone Sync '+report['take_id']
        timeline = next((project.GetTimelineByIndex(i) for i in range(1,project.GetTimelineCount()+1) if project.GetTimelineByIndex(i).GetName()==name),None)
        if not timeline:
            # Only set defaults before the first timeline; never alter existing edits.
            if project.GetTimelineCount()==0:
                if not project.SetSetting('timelineFrameRate','30'): raise RuntimeError('Cannot set 30 FPS')
                project.SetSetting('timelineResolutionWidth','3840'); project.SetSetting('timelineResolutionHeight','2160')
            pool = project.GetMediaPool()
            imported = pool.ImportMedia([c['path'] for c in report['clips']])
            if not imported or len(imported)!=len(report['clips']): raise RuntimeError('Media import incomplete')
            timeline = pool.ImportTimelineFromFile(report['timeline'],{'timelineName':name,'importSourceClips':True})
        if not timeline: raise RuntimeError('Timeline import failed')
        if timeline.GetTrackCount('video')!=len(report['clips']): raise RuntimeError('Unexpected video track count; review imported timeline')
        origin = timeline.GetStartFrame()
        for i,clip in enumerate(report['clips'],1):
            items = timeline.GetItemListInTrack('video',i)
            if len(items)!=1 or abs(items[0].GetStart()-origin-clip['timeline_start_frame'])>.5:
                raise RuntimeError('Imported placement mismatch; review timeline')
            expected = math.floor(float(clip['metadata']['format']['duration'])*30)
            if abs(items[0].GetDuration()-expected)>1:
                raise RuntimeError('Imported duration mismatch; inspect variable-frame-rate source handling')
            media = items[0].GetMediaPoolItem()
            if not media or Path(media.GetClipProperty('File Path')).resolve()!=Path(clip['path']).resolve():
                raise RuntimeError('Imported source path mismatch')
            timeline.SetTrackEnable('audio',i,clip['role']==report['reference'])
        if not manager.SaveProject(): raise RuntimeError('Project save failed')
        return {'ok':True,'project':PROJECT,'timeline':name,'verified':'track placement, duration, source paths; visual lip-sync still unmeasured'}
    except Exception as error:
        return {'ok':False,'reason':str(error)[:1000]}


def lua_quote(text):
    delimiter = '='
    while ']'+delimiter+']' in str(text): delimiter += '='
    return '['+delimiter+'['+str(text)+']'+delimiter+']'


def write_lua_import(report,output):
    """Menu fallback works inside Resolve without changing external API permissions."""
    expected = ',\n'.join('{path='+lua_quote(c['path'])+',role='+lua_quote(c['role'])+',start='+str(c['timeline_start_frame'])+',duration='+str(math.floor(float(c['metadata']['format']['duration'])*30))+'}' for c in report['clips'])
    text = '''-- Generated only after successful audio-sync checks. No media deletion.
local app = resolve or bmd.scriptapp('Resolve')
assert(app, 'Resolve unavailable')
local pm = app:GetProjectManager()
local project = pm:GetCurrentProject()
local projectName = PROJECT_NAME
assert(not project or project:GetName()==projectName, 'Unrelated project open. Open Phone Recordings Auto Sync first; no edits made.')
project = project or pm:LoadProject(projectName) or pm:CreateProject(projectName)
assert(project, 'Cannot open dedicated project')
local name = TIMELINE_NAME
local clips = {EXPECTED_CLIPS}
local timeline = nil
for i=1,project:GetTimelineCount() do
  local candidate = project:GetTimelineByIndex(i)
  if candidate:GetName()==name then timeline=candidate end
end
if not timeline then
  if project:GetTimelineCount()==0 then
    assert(project:SetSetting('timelineFrameRate','30'), 'Cannot set 30 FPS')
    project:SetSetting('timelineResolutionWidth','3840')
    project:SetSetting('timelineResolutionHeight','2160')
  end
  local pool = project:GetMediaPool()
  local paths = {}
  for _,clip in ipairs(clips) do table.insert(paths,clip.path) end
  local imported = pool:ImportMedia(paths)
  assert(imported and #imported==#clips,'Media import incomplete')
  timeline=pool:ImportTimelineFromFile(TIMELINE_PATH,{timelineName=name,importSourceClips=true})
end
assert(timeline,'Timeline import failed')
assert(timeline:GetTrackCount('video')==#clips,'Track count mismatch; inspect imported timeline')
local origin=timeline:GetStartFrame()
for i,clip in ipairs(clips) do
  local items=timeline:GetItemListInTrack('video',i)
  assert(#items==1 and math.abs(items[1]:GetStart()-origin-clip.start)<0.5,'Placement mismatch; inspect timeline')
  assert(math.abs(items[1]:GetDuration()-clip.duration)<=1,'Duration mismatch; inspect VFR handling')
  local media=items[1]:GetMediaPoolItem()
  assert(media and media:GetClipProperty('File Path')==clip.path,'Source path mismatch')
  timeline:SetTrackEnable('audio',i,clip.role==REFERENCE_ROLE)
end
assert(pm:SaveProject(),'Project save failed')
print('Imported and checked: '..name..'. Audio aligned; visual sync still needs a spot check.')
'''
    for key,value in {'PROJECT_NAME':lua_quote(PROJECT),'TIMELINE_NAME':lua_quote('Phone Sync '+report['take_id']),'EXPECTED_CLIPS':expected,'TIMELINE_PATH':lua_quote(report['timeline']),'REFERENCE_ROLE':lua_quote(report['reference'])}.items():
        text = text.replace(key,value)
    path = Path(output)/'Import into Resolve.lua'; path.write_text(text)
    # This pointer is used by an explicitly installed Resolve Utility menu item.
    (ROOT/'latest-resolve-import.lua').write_text('dofile('+lua_quote(path)+')\n')
    return path
