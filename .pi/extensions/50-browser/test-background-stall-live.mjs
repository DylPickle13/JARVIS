// Private supervised experiment; no public fault knobs and no force-clear path.
if(process.env.JARVIS_TEST_BACKGROUND_STALL_MAINTENANCE!=='1') {
  console.error('Not authorized: requires supervised idle browser maintenance');process.exit(2);
}
const {createServer}=await import('node:http');
const {readFile,writeFile,mkdir}=await import('node:fs/promises');
const {homedir}=await import('node:os');
const {join,dirname}=await import('node:path');
const {fileURLToPath}=await import('node:url');
const {randomUUID}=await import('node:crypto');
const {execFile}=await import('node:child_process');
const {promisify}=await import('node:util');
const here=dirname(fileURLToPath(import.meta.url));
const output=process.env.JARVIS_TEST_BACKGROUND_STALL_REPORT;
if(!output) throw new Error('Explicit private report path required');
const assert=(x,m)=>{if(!x)throw new Error(m);},pause=ms=>new Promise(r=>setTimeout(r,ms));
const report={kind:'background-stall-passive-tab-switch-baseline',startedAt:new Date().toISOString(),phase:'initial',steps:[],fixtures:[],originalTabIds:[]};
let backend,ledger,server;
async function save(){await writeFile(output,JSON.stringify(report,null,2),{mode:0o600});}
async function step(name,fn){report.phase=name;await save();const start=Date.now();try{const result=await fn();report.steps.push({name,at:new Date().toISOString(),durationMs:Date.now()-start,ok:true,result});await save();return result;}catch(e){report.steps.push({name,at:new Date().toISOString(),durationMs:Date.now()-start,ok:false});throw e;}}
try {
  let loaded=false;try{await promisify(execFile)('/bin/launchctl',['print',`gui/${process.getuid()}/com.jarvis.browser-bridge`]);loaded=true;}catch{}
  assert(!loaded,'Production bridge must be unloaded before private fixture');
  const config=JSON.parse(await readFile(join(homedir(),'.jarvis/browser-backend.json'),'utf8'));
  const identity=JSON.parse(await readFile(join(homedir(),'.jarvis/extension-window.json'),'utf8'));
  assert(config.backend==='extension'&&identity.connectionMode==='jarvis-background-native-v1','Existing native automation window required');
  const {OperationLedger}=await import('./operation-ledger.mjs');
  ledger=new OperationLedger({path:join(homedir(),'.jarvis/browser-recovery/operations.json')});
  await ledger.load();assert(!ledger.unresolved().length,'Unresolved evidence blocks test');
  await ledger.acquireLock();assert(!ledger.unresolved().length,'Journal changed while locking');
  const {ExtensionBrowserBackend}=await import('./extension-browser-backend.mjs');
  backend=new ExtensionBrowserBackend({profileDir:join(homedir(),'Library/Application Support/Google/Chrome'),
    profileDirectory:config.extensionProfileDirectory,chromePath:join(here,'launch-extension-in-automation-window.py'),
    recoveryLedger:ledger,recoveryMode:'verified-only'});
  const session=randomUUID();report.session=session;
  const status=await backend.handle('/status',{},session);
  assert(!status.daemon.quarantined&&backend.window.windowId===identity.windowId,'Initial identity/health check failed');
  report.originalTabIds=status.pages.map(p=>p.tabId);report.windowId=identity.windowId;
  server=createServer((req,res)=>{
    res.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});
    res.end(`<!doctype html><title>JARVIS background stall baseline</title>
    <style>body{height:3500px}button{position:fixed;top:30px;left:30px}pre{position:fixed;left:200px;top:0}</style>
    <button id="target">Synthetic click</button><pre id="stats"></pre>
    <script>
    const s={clicks:0,wheels:0,scrollY:0,visibility:document.visibilityState};
    const show=()=>{s.visibility=document.visibilityState;document.querySelector('#stats').textContent=JSON.stringify(s)};
    // No animation-frame loop, periodic timer, animation, or DOM heartbeat:
    // instrumentation must not keep an otherwise idle renderer producing frames.
    document.querySelector('#target').onclick=()=>{s.clicks++;show()};
    addEventListener('wheel',()=>{s.wheels++;show()},{passive:true});
    addEventListener('scroll',()=>{s.scrollY=scrollY;show()});show();
    </script>`);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const url=`http://127.0.0.1:${server.address().port}`;
  const created=await step('create-fixture',()=>backend.handle('/open',{url,newTab:true},session));
  report.fixtures.push(created.tabId);await save();
  await step('initial-telemetry',async()=>JSON.parse((await backend.handle('/extract',{selector:'#stats'},session)).text));
  const peer=randomUUID();report.peerSession=peer;
  const peerTab=await step('create-peer-fixture',()=>backend.handle('/open',{url,newTab:true},peer));
  report.fixtures.push(peerTab.tabId);await save();
  await step('idle-before-click',async()=>{await pause(70000);return {idleMs:70000};});
  await step('single-click',()=>backend.handle('/click',{selector:'#target'},session));
  const click=await step('after-click',async()=>JSON.parse((await backend.handle('/extract',{selector:'#stats'},session)).text));
  assert(click.clicks===1,'Click was missing or repeated');
  await step('select-peer',()=>backend.handle('/tabs',{action:'switch',tabId:peerTab.tabId},peer).then(()=>({selected:true})));
  await step('idle-before-wheel',async()=>{await pause(70000);return {idleMs:70000};});
  await step('single-wheel',()=>backend.handle('/scroll',{direction:'down',amount:400,x:500,y:400},session));
  await pause(1000);
  const wheel=await step('after-wheel',async()=>JSON.parse((await backend.handle('/extract',{selector:'#stats'},session)).text));
  assert(wheel.wheels===1&&wheel.scrollY>0,'Wheel was missing or repeated');
  const final=await backend.handle('/status',{},session);
  assert(report.originalTabIds.every(id=>final.pages.some(p=>p.tabId===id)),'Original work tab disappeared');
  await backend.handle('/close',{all:false},session);
  report.fixtures=report.fixtures.filter(id=>id!==created.tabId);await save();
  await backend.handle('/close',{all:false},peer);
  report.fixtures=[];report.phase='baseline-did-not-reproduce';report.completedAt=new Date().toISOString();await save();
  await ledger.flush();await ledger.close();server.close();await backend.client?.close();
  process.exit(0);
} catch(error) {
  // No replay or cleanup while execution is unknown. Keep observer and server alive
  // so late receipts can be collected after an OWNER-performed visibility change.
  report.phase='stopped';report.reason=backend?.quarantine?'execution-fenced':'fixture-error';
  console.error('Fixture stopped; no retry, reset or evidence resolution performed.');
  for(;;) {
    const op=backend?.recoveryOperation;
    report.observedAt=new Date().toISOString();
    report.recoveryState=backend?.recoveryState;
    report.execution=op?{operationId:op.record.id,action:op.path,...op.observed.snapshot(),diagnostics:op.observed.diagnostics()}:null;
    await ledger?.flush().catch(()=>{});await save();await pause(1000);
  }
}
