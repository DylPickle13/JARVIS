// PRIVATE supervised SDK fixture. No HTTP fault parameter or force-clear API.
// Guard before backend imports, token access, Chrome access, or listener creation.
if (process.env.JARVIS_TEST_VERIFIED_RECOVERY_MAINTENANCE !== '1') {
  console.error('Not authorized: verified recovery live checks require a supervised idle maintenance window.');
  process.exit(2);
}

const {createServer}=await import('node:http');
const {readFile,writeFile,mkdir}=await import('node:fs/promises');
const {homedir}=await import('node:os');
const {join,dirname}=await import('node:path');
const {fileURLToPath}=await import('node:url');
const {randomUUID}=await import('node:crypto');
const {execFile}=await import('node:child_process');
const {promisify}=await import('node:util');
const assert=(condition,message)=>{if(!condition)throw new Error(message);};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const root=join(dirname(fileURLToPath(import.meta.url)),'../..');
const reportPath=join(root,'runtime/browser-extension-review/verified-recovery-live.json');
const report={kind:'private-sdk-fault-injection',synthetic:true,productionModeChanged:false,
  positive:null,negative:null,originalTabIds:[],fixtureTabIds:[],requiresSupervisedResolution:false};
let backend,ledger,server;

async function main() {
  // A competing bridge must never share this fixture's journal or debugger group.
  let present=false;
  try {await promisify(execFile)('/bin/launchctl',['print',`gui/${process.getuid()}/com.jarvis.browser-bridge`]);present=true;}catch{}
  assert(!present,'Bridge must be unloaded by the supervising operator before this private fixture.');
  const configuration=JSON.parse(await readFile(join(homedir(),'.jarvis/browser-backend.json'),'utf8'));
  const identity=JSON.parse(await readFile(join(homedir(),'.jarvis/extension-window.json'),'utf8'));
  assert(configuration.backend==='extension','Extension backend required; no fallback permitted.');
  assert(identity.connectionMode==='jarvis-background-native-v1'&&Number.isSafeInteger(identity.windowId),'Recorded native automation window required.');
  const {OperationLedger}=await import('./operation-ledger.mjs');
  ledger=new OperationLedger({path:join(homedir(),'.jarvis/browser-recovery/operations.json')});
  await ledger.load();assert(ledger.unresolved().length===0,'Unresolved production evidence: stop, never clear it in a fixture.');
  await ledger.acquireLock();assert(ledger.unresolved().length===0,'Evidence changed while obtaining exclusive journal ownership.');
  const {ExtensionBrowserBackend}=await import('./extension-browser-backend.mjs');
  backend=new ExtensionBrowserBackend({profileDir:join(homedir(),'Library/Application Support/Google/Chrome'),
    profileDirectory:configuration.extensionProfileDirectory,
    chromePath:join(dirname(fileURLToPath(import.meta.url)),'launch-extension-in-automation-window.py'),
    recoveryLedger:ledger,recoveryMode:'verified-only'});
  const A=randomUUID(),B=randomUUID();
  const before=await backend.handle('/status',{},A);
  assert(!before.daemon.quarantined,'Initial bridge state must be healthy.');
  assert(backend.window.windowId===identity.windowId,'Automation window identity changed.');
  report.windowId=identity.windowId;report.originalTabIds=before.pages.map(p=>p.tabId);
  server=createServer((request,response)=>{
    response.writeHead(200,{'Content-Type':'text/html'});
    response.end(`<!doctype html><title>JARVIS verified recovery fixture</title>
      <textarea id="draft"></textarea><button id="reset">Reset synthetic counter</button><p id="stats">0:0</p>
      <script>let writes=0;const field=document.querySelector('#draft'),stats=document.querySelector('#stats');
      const show=()=>stats.textContent=field.value.length+':'+writes;
      field.addEventListener('input',()=>{writes++;show()});document.querySelector('#reset').onclick=()=>{writes=0;show()};</script>`);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const url=`http://127.0.0.1:${server.address().port}`;
  for(const session of [A,B]) report.fixtureTabIds.push((await backend.handle('/open',{url,newTab:true},session)).tabId);
  await backend.handle('/type',{selector:'#draft',text:'seed',clear:true,delayMs:0},A);
  await backend.handle('/click',{selector:'#reset'},A);
  await backend.handle('/type',{selector:'#draft',text:'peer-draft',clear:true,delayMs:0},B);

  const realCall=backend.client.callTool.bind(backend.client);
  async function injectOnce(path,body,session) {
    let injected=0;
    backend.client.callTool=(args,extra,options)=>{
      // The fixed controller body is unchanged. Only this private SDK client's
      // reply deadline is shortened once; Chrome execution is still observed.
      if(injected===0&&args.arguments?.code?.includes(`)(page, ${JSON.stringify(path)}, `)) {
        injected++;return realCall(args,extra,{...options,timeout:5});
      }
      return realCall(args,extra,options);
    };
    try {
      await backend.handle(path,body,session);
      throw new Error('Injected deadline did not occur; do not repeat the mutation.');
    } catch(error) {
      assert(injected===1,'Private deadline injection was not bound to the requested fixed handler.');
      assert(/recovery pending|quarantined/i.test(error.message),'Expected the execution fence, not a silently successful reply.');
    } finally {backend.client.callTool=realCall;}
    return backend.recoveryOperation;
  }

  const positive=await injectOnce('/type',{selector:'#draft',text:'X'.repeat(5000),clear:true,delayMs:0},A);
  assert(positive&&positive.tabId===report.fixtureTabIds[0],'Positive outcome must bind to our own synthetic tab.');
  const cached=await backend.handle('/status',{},B);
  assert(cached.daemon.inventoryStale&&!cached.needsReselect,'Other client must retain selection while dispatch is fenced.');
  const limit=Date.now()+35000;
  while(backend.recoveryState!=='healthy'&&Date.now()<limit) {
    assert(backend.recoveryState!=='blocked-needs-supervision','Positive recovery unexpectedly requires supervision.');
    await pause(50);
  }
  assert(backend.recoveryState==='healthy'&&!backend.quarantine,'Late verified input failed to recover.');
  const stats=(await backend.handle('/extract',{selector:'#stats'},A)).text;
  assert(stats==='5000:1','Synthetic replacement was missing, partial, or replayed.');
  const peer=(await backend.handle('/status',{},B));
  assert(peer.selectedTabId===report.fixtureTabIds[1]&&!peer.needsReselect,'Peer lease or selection changed.');
  assert((await backend.handle('/extract',{selector:'#stats'},B)).text==='10:1','Peer draft changed.');
  assert(report.originalTabIds.every(id=>peer.pages.some(p=>p.tabId===id)),'An original work-tab identity disappeared.');
  report.positive={passed:true,operationId:positive.record.id,quiescent:positive.observed.snapshot().quiescent,
    valueVerified:positive.record.valueVerified,inputEvents:1,peerSelectionPreserved:true,originalIdsPresentBeforeNegative:true};

  // Deliberately exhaust a SHORT TEST-ONLY drain budget on a pure wait. No
  // submission, typing replay, unknown input, or extension mutation is involved.
  // This demonstrates that later positive proof cannot silently clear the fence.
  backend.drainGraceMs=200;
  const negative=await injectOnce('/wait',{ms:1200},A);
  assert(negative&&negative.path==='/wait'&&negative.tabId===report.fixtureTabIds[0],'Negative case must be a fixture-local read-only wait.');
  const negativeLimit=Date.now()+15000;
  while(!negative.observed.snapshot().quiescent&&Date.now()<negativeLimit) await pause(50);
  await ledger.flush();
  assert(negative.observed.snapshot().quiescent&&ledger.proven(negative.record),'The synthetic wait did not finish with positive controller proof.');
  assert(backend.quarantine&&backend.recoveryState==='blocked-needs-supervision','Grace exhaustion was bypassed by late proof.');
  let refused=false;
  try {await backend.handle('/tabs',{action:'switch',tabId:report.fixtureTabIds[0]},A);}catch{refused=true;}
  assert(refused,'Explicit reselection incorrectly bypassed quarantine.');
  report.negative={passed:true,operationId:negative.record.id,action:'/wait',outcome:negative.record.outcome,
    quiescent:true,pending:negative.record.pending,unknown:negative.record.unknown,quarantineRetained:true,reselectionRefused:true};
  report.requiresSupervisedResolution=true;report.passed=true;
  // NO reset, journal resolution, fixture-tab closure or service restart here.
  // The supervising owner must acknowledge this completed synthetic wait before
  // the operator resolves that exact record and restores the bridge.
}

try {await main();}
catch {report.passed=false;report.requiresSupervisedResolution=!!backend?.quarantine;console.error('STOP: live recovery fixture failed; evidence retained, no blind cleanup or retry.');}
finally {
  await mkdir(dirname(reportPath),{recursive:true});await writeFile(reportPath,JSON.stringify(report,null,2),{mode:0o600});
  await ledger?.flush().catch(()=>{});
  await ledger?.close().catch(()=>{});
  server?.close();
  console.log(JSON.stringify({passed:report.passed,positive:report.positive?.passed??false,negative:report.negative?.passed??false,
    requiresSupervisedResolution:report.requiresSupervisedResolution}));
  // Exiting this fixture is NOT cancellation proof. Only independently recorded
  // terminal/command acknowledgements above establish completion; unresolved
  // journal evidence survives, and the service is deliberately left unloaded.
  process.exit(report.passed?0:1);
}
