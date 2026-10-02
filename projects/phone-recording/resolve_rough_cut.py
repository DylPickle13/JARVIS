"""Generate an explicit, guarded Resolve Lua proof-of-concept edit.
Source media stays unchanged. No existing timeline is overwritten or deleted.
"""
import json
from pathlib import Path
from resolve_import import lua_quote


def generate(report, output, version=1):
    if not isinstance(version,int) or version<1:raise ValueError("Invalid revision")
    if not report.get('ok') or report.get('fps') != 30:
        raise ValueError('Approved 30fps sync report required')
    clips=report['clips'];roles={c['role'] for c in clips}
    if roles != {'lg','samsung','iphone'}:
        raise ValueError('This technical demo requires the verified three-camera take')
    # Start inside the shared interval; 12 six-second shots demonstrate editable cuts.
    start=max(c['timeline_start_frame'] for c in clips)
    start=((start+29)//30)*30
    end=min(c['timeline_start_frame']+int(float(c['metadata']['format']['duration'])*30) for c in clips)
    count=min(12,(end-start)//180)
    if count<1:raise ValueError('Insufficient shared footage')
    cycle=('samsung','lg','samsung','iphone')
    plan=[{'role':cycle[i%4],'source_clock':start+i*180,'record_frame':i*180,'duration':180} for i in range(count)]
    entries=',\n'.join('{role='+lua_quote(c['role'])+',path='+lua_quote(c['path'])+',offset='+str(c['timeline_start_frame'])+',seconds='+str(float(c['metadata']['format']['duration']))+'}' for c in clips)
    edits=',\n'.join('{role='+lua_quote(s['role'])+',clock='+str(s['source_clock'])+',record='+str(s['record_frame'])+',duration=180}' for s in plan)
    script='''local app=resolve or bmd.scriptapp('Resolve')
assert(app,'Resolve unavailable')
local pm=app:GetProjectManager()
local project=pm:GetCurrentProject()
assert(project and project:GetName()=='Phone Recordings Auto Sync','Wrong project; no edits')
assert(tonumber(project:GetSetting('timelineFrameRate'))==30,'30fps project required')
local pool=project:GetMediaPool()
local sourceName=SOURCE_NAME
local roughName=ROUGH_NAME
for i=1,project:GetTimelineCount() do
 local name=project:GetTimelineByIndex(i):GetName()
 assert(name~=sourceName and name~=roughName,'Timeline exists; do not overwrite or replay')
end
local clips={CLIPS}
local byRole={}
local media={}
local function walk(folder)
 for _,item in ipairs(folder:GetClipList()) do media[item:GetClipProperty('File Path')]=item end
 for _,sub in ipairs(folder:GetSubFolderList()) do walk(sub) end
end
walk(pool:GetRootFolder())
for _,c in ipairs(clips) do
 c.media=assert(media[c.path],'Verified source not imported: '..c.role)
 assert(c.media:GetClipProperty('Online Status')=='Online','Source offline')
 c.fps=assert(tonumber(c.media:GetClipProperty('FPS')),'Unknown source FPS')
 c.frames=assert(tonumber(c.media:GetClipProperty('Frames')),'Unknown source frames')
 assert(math.abs(c.frames/c.fps-c.seconds)<0.15,'Source duration interpretation changed')
 byRole[c.role]=c
end
local function append(c, first, last, record, kind, track)
 assert(first>=0 and last<=c.frames and last>=first,'Source range invalid')
 local items=pool:AppendToTimeline({{mediaPoolItem=c.media,startFrame=first,endFrame=last,recordFrame=record,mediaType=kind,trackIndex=track}})
 assert(items and #items==1,'Append failed')
 return items[1]
end
local source=assert(pool:CreateEmptyTimeline(sourceName),'Cannot create source timeline')
assert(project:SetCurrentTimeline(source),'Cannot select source timeline')
assert(source:SetStartTimecode('00:00:00:00'),'Cannot set source origin')
for _,kind in ipairs({'video','audio'}) do
 while source:GetTrackCount(kind)<#clips do assert(source:AddTrack(kind),'Cannot add source track') end
end
for i,c in ipairs(clips) do
 local item=append(c,0,c.frames,c.offset,1,i)
 assert(item:GetStart()==c.offset,'Source placement mismatch')
 assert(math.abs(item:GetDuration()-c.seconds*30)<4,'Source duration mismatch; review VFR')
 append(c,0,c.frames,c.offset,2,i)
 source:SetTrackName('video',i,c.role)
 source:SetTrackName('audio',i,c.role)
 source:SetTrackEnable('audio',i,c.role=='samsung')
end
source:AddMarker(0,'Yellow','Synced sources — preserve','Original VFR files. Only Samsung audio enabled. Visual sync remains to be reviewed.',1)
assert(pm:SaveProject(),'Cannot save source timeline')
local rough=assert(pool:CreateEmptyTimeline(roughName),'Cannot create rough cut')
assert(project:SetCurrentTimeline(rough),'Cannot select rough cut')
assert(rough:SetStartTimecode('00:00:00:00'),'Cannot set rough origin')
local shots={SHOTS}
for i,s in ipairs(shots) do
 local c=byRole[s.role]
 local first=math.floor((s.clock-c.offset)*c.fps/30+0.5)
 local length=math.floor(s.duration*c.fps/30+0.5)
 local item=append(c,first,first+length,s.record,1,1)
 assert(item:GetStart()==s.record and item:GetDuration()==s.duration,'Cut timing mismatch; no further edits')
 rough:AddMarker(s.record,'Blue',s.role,'Technical demo: editable six-second camera cut; not an artistic selection.',1)
end
local master=byRole.samsung
local first=math.floor((COMMON_START-master.offset)*master.fps/30+0.5)
local length=math.floor(TOTAL_FRAMES*master.fps/30+0.5)
local audio=append(master,first,first+length,0,2,1)
assert(math.abs(audio:GetDuration()-TOTAL_FRAMES)<=1,'Master audio duration mismatch')
rough:SetTrackName('video',1,'Editable camera cuts')
rough:SetTrackName('audio',1,'Samsung continuous master')
rough:AddMarker(TOTAL_FRAMES-1,'Yellow','Human review','Check picture/audio sync, LG darkness and portrait iPhone. Fine-tune cuts and grading; preserve Synced Sources.',1)
assert(pm:SaveProject(),'Project save failed')
app:OpenPage('edit')
print('JARVIS: created '..sourceName..' and '..roughName)
'''
    for key,value in {'SOURCE_NAME':lua_quote('Synced Sources '+report['take_id']+f' v{version:03d}'),'ROUGH_NAME':lua_quote('Rough Cut '+report['take_id']+f' v{version:03d}'),'CLIPS':entries,'SHOTS':edits,'COMMON_START':str(start),'TOTAL_FRAMES':str(count*180)}.items():script=script.replace(key,value)
    Path(output).write_text(script)
    return {'take_id':report['take_id'],'common_start':start,'duration_frames':count*180,'shots':plan,'purpose':'technical editable handoff demo, not artistic edit'}
