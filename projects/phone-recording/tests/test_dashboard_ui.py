"""Offline real-Chrome UI checks. Isolated temporary profile; no real API/phones."""
import json
import os
import signal
import time
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CHROME=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

FIXTURE=r'''
let submissions=0;
const now=new Date().toISOString();
const roles=['lg','samsung','iphone','overhead'];
const base={config_id:'fixture',cameras:roles.map((role,i)=>({role,name:['Wide Angle','Dyl Cam','Bass Pedals','Overhead'][i],enabled:true,preview:true,model:'Fixture phone',video_label:'4K / 30'})),active:null,jobs:[],takes:[],preview:null,source_root:'fixture',local_storage:{ok:true,free_bytes:20*1024**3},remote:{config_id:'fixture',observed:now,states:Object.fromEntries(roles.map(r=>[r,'idle'])),pending_take:null,readiness:{config_id:'fixture',checked_at:now,ok:true,phones:Object.fromEntries(roles.map(r=>[r,{ok:true,metrics:{battery_percent:95,free_bytes:20*1024**3},warnings:['Temperature unavailable; manually check for excessive heat.']}]))}}};
const imageSrc=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');Object.defineProperty(HTMLImageElement.prototype,'src',{get:imageSrc.get,set(value){imageSrc.set.call(this,value.startsWith('/api/preview')?'data:image/svg+xml;base64,'+btoa('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="700"><rect width="400" height="700" fill="gray"/></svg>'):value);}});
window.fetch=async(path)=>{if(path==='/api/jobs'){submissions++;await new Promise(r=>setTimeout(r,30));}return {ok:true,json:async()=>path==='/api/state'?structuredClone(base):{csrf:'fixture'}};};
'''

CHECKS=r'''
setTimeout(async()=>{
 const failures=[];let count=0;
 const check=(value,name)=>{count++;if(!value)failures.push(name);};
 const q=id=>document.getElementById(id);
 try{
  render(structuredClone(base));
  check(q('main-action').textContent==='Start recording','fresh healthy idle can start');
  check(!q('framing').disabled,'fresh idle framing enabled');
  check(q('iphone-health').textContent.includes('Temperature unavailable'),'missing telemetry explicit');
  check(document.documentElement.scrollHeight<=innerHeight+1,'no page vertical scroll at '+innerWidth+'x'+innerHeight);
  check(document.documentElement.scrollWidth<=innerWidth+1,'no page horizontal scroll');
  check(document.querySelectorAll('.camera').length===4,'four dynamic camera cards');
  let preview=structuredClone(base);preview.preview={observed:now,expires_in:60};render(preview);
  check([...document.querySelectorAll('.camera img')].every(i=>!i.hidden&&i.getBoundingClientRect().bottom<=i.parentElement.getBoundingClientRect().bottom),'all four snapshots fit inside camera cards '+JSON.stringify([...document.querySelectorAll('.camera img')].map(i=>({image:i.getBoundingClientRect().toJSON(),card:i.parentElement.getBoundingClientRect().toJSON()}))));
  let d=structuredClone(base);d.remote.readiness.checked_at='2000-01-01T00:00:00Z';render(d);
  check(q('main-action').textContent==='Check cameras','stale health cannot start');
  d=structuredClone(base);d.remote.states.iphone='unknown';render(d);
  check(q('framing').disabled,'unknown camera blocks framing');
  d=structuredClone(base);d.remote.pending_take='take';d.remote.states=Object.fromEntries(roles.map(r=>[r,'recording']));d.jobs=[{id:'start',take_id:'take',action:'start',state:'done',phase:'recording',created:now,updated:now}];render(d);
  check(q('main-action').textContent==='Stop & review'&&!q('main-action').disabled,'confirmed recording has stop');
  check(q('refresh').disabled&&q('framing').disabled,'no idle probes while recording');
  check(q('elapsed').textContent!=='—:—','timer bound to matching confirmed take');
  d.remote.pending_take='different';render(d);check(q('elapsed').textContent==='—:—','no unrelated take timer');
  d=structuredClone(base);d.active='job';d.jobs=[{id:'job',action:'start',state:'running',phase:'starting_job',created:now,updated:now}];render(d);
  check(q('session-state').textContent==='Starting','command sent not recording confirmed');
  check(q('main-action').disabled,'no second command while active');
  d.jobs[0].state='uncertain';render(d);check(q('session-state').textContent==='Needs attention'&&q('main-action').disabled,'ambiguous request blocks replay');
  check(q('jobs').textContent.includes('Reconcile — no retry'),'observation-only recovery offered');
  d.jobs[0]={...d.jobs[0],action:'prepare',state:'running',phase:'audio_sync'};render(d);
  check(q('session-state').textContent==='Aligning audio','actual sync phase shown');
  d=structuredClone(base);d.takes=[{id:'fixture-take',local:true,cameras:roles,sync_ok:true,import_status:{ok:false}}];render(d);
  check(q('latest-status').textContent.includes('import needed'),'sync success is not import success');
  d.takes[0].import_status.ok=true;render(d);check(q('latest').textContent.includes('Open Resolve'),'verified import has honest app opener');
  check(q('latest').textContent.includes('Delete take…'),'delete available after local preparation');
  const pipeline=document.querySelector('.pipeline-details');pipeline.open=true;check(document.documentElement.scrollHeight<=innerHeight+1,'expanded pipeline fits');pipeline.open=false;
  check(getComputedStyle(document.documentElement).colorScheme==='dark','dark-only design');
  check(q('iphone-metrics').textContent.includes('95% battery'),'compact camera metrics retained');
  d=structuredClone(base);d.remote.pending_take='pending-test';d.remote.pending_review=true;render(d);
  check(q('main-action').textContent==='Transfer recording','pause before phone transfer');
  check(q('latest').textContent.includes('Delete take…')&&!q('latest').querySelector('.delete-take').disabled,'phone discard available before transfer');
  let promptText='';window.prompt=text=>{promptText=text;return null;};await deleteTake('pending-test');
  check(promptText.includes('NO saved Mac copy exists'),'phone discard warns no saved copy');
  d=structuredClone(base);d.remote.takes=[{id:'collected-test'}];render(d);
  check(q('latest').textContent.includes('Verify copy & prepare')&&q('latest').textContent.includes('Delete take…'),'pause with delete before verified copy');
  check(document.documentElement.scrollHeight<=innerHeight+1,'review actions fit without page scrolling');
  d.active='transfer';d.jobs=[{id:'transfer',action:'collect',state:'running',created:now,updated:now}];render(d);
  check(q('latest').querySelector('.delete-take').disabled,'no deletion during active transfer');
  q('open-library').click();check(q('library-dialog').open,'library opens in overlay');q('library-dialog').close();
  q('open-advanced').click();check(q('advanced').open,'recovery opens in overlay');q('advanced').close();
  render(structuredClone(base));const first=action('start');const second=action('start');await Promise.all([first,second]);check(submissions===1,'double-click creates one submission');
  window.fetch=async()=>{throw Error('offline fixture');};await refresh();
  check(q('main-action').disabled&&q('framing').disabled,'disconnect disables controls');
  check(q('status-note').textContent.includes('may still be running'),'disconnect never implies stopped');
  check(document.documentElement.scrollHeight<=innerHeight+1,'disconnect alert still fits screen');
 }catch(e){failures.push(e.stack);}
 const out=document.createElement('pre');out.id='ui-test-result';out.textContent=JSON.stringify({count,failures,width:innerWidth,height:innerHeight});document.body.append(out);
},100);
'''

@unittest.skipUnless(CHROME.exists(),'Chrome required for isolated layout checks')
class DashboardUITests(unittest.TestCase):
    def test_offline_states_and_single_screen_layout(self):
        for width,height in ((1440,900),(1280,720),(1024,650),(900,600)):
            with self.subTest(viewport=(width,height)),tempfile.TemporaryDirectory(prefix='phone-ui-test-') as tmp:
                folder=Path(tmp)
                (folder/'fixture.js').write_text(FIXTURE)
                (folder/'checks.js').write_text(CHECKS)
                html=(ROOT/'dashboard/index.html').read_text().replace('href="/style.css"','href="'+(ROOT/'dashboard/style.css').as_uri()+'"')
                html=html.replace('<script src="/app.js" defer></script>','<script src="fixture.js"></script><script src="'+(ROOT/'dashboard/app.js').as_uri()+'" defer></script><script src="checks.js" defer></script>')
                (folder/'index.html').write_text(html)
                # Some macOS Chrome builds retain helpers after dumping DOM.
                # Bound and close this test's private process group, never live Chrome.
                with (folder/'stdout').open('w+') as out,(folder/'stderr').open('w+') as err:
                    process=subprocess.Popen([str(CHROME),'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions','--disable-gpu','--no-proxy-server','--allow-file-access-from-files','--user-data-dir='+str(folder/'profile'),'--window-size='+str(width)+','+str(height+87),'--virtual-time-budget=2000','--dump-dom',(folder/'index.html').as_uri()],stdout=out,stderr=err,start_new_session=True)
                    match=None;output=''
                    try:
                        deadline=time.monotonic()+12
                        while time.monotonic()<deadline:
                            out.seek(0);output=out.read()
                            match=re.search(r'<pre id="ui-test-result">(.*?)</pre>',output,re.S)
                            if match:break
                            time.sleep(.1)
                    finally:
                        try:os.killpg(process.pid,signal.SIGTERM)
                        except ProcessLookupError:pass
                        try:process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid,signal.SIGKILL);process.wait()
                    self.assertIsNotNone(match,output[-1500:])
                report=json.loads(match[1]);self.assertEqual(report['failures'],[],report)
                self.assertGreaterEqual(report['count'],24)
