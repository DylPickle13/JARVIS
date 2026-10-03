import { readFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execFileAsync=promisify(execFile);
import { join, basename, extname } from 'node:path';
import { homedir } from 'node:os';
import { createConnection } from '@playwright/mcp';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { BrowserSessions, validateTabInventory } from './browser-sessions.mjs';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { verifiedType } from './verified-input.mjs';
import { actionDeadlineMs, isRequestDeadline, isLocalActionFailure, failureKind } from './action-policy.mjs';

// Fixed implementation only: callers cannot submit code to the MCP server.
// Never adopt the seed page (which may be the extension's connection tab).
export async function extensionAction(seed, action, b, typeAction = verifiedType) {
  const context = seed.context();
  let state = context.__jarvisOwnedTabs;
  if (!state) {
    state = { pages: [], active: null };
    context.__jarvisOwnedTabs = state;
  }
  state.pages = state.pages.filter(p => !p.isClosed());
  // MCP may silently replace its backend/context after a disconnect without
  // closing the daemon's client. Rediscover the anchor on EVERY action, rather
  // than trusting either connected=true or a property on the previous context.
  // The relay's inventory operation verifies the exact window/connection IDs.
  if (action !== '/connect' && action !== '/prepare-anchor') {
    state.anchor = context.pages().find(p => !p.isClosed() && p.url().startsWith('chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html') && p.url().endsWith('#jarvis-automation-anchor-v2'));
    if (!state.anchor) throw new Error('Automation connection anchor unavailable; refusing unverified tab discovery or creation');
    const inventory = JSON.parse(await state.anchor.evaluate('"JARVIS_INTERNAL_SYNC_WINDOW_TABS_V1"').catch(e => { throw new Error('Anchor inventory: ' + e.message); }));
    const allowed = new Map(inventory.tabs.map(t => [t.tabId, t]));
    const pages = [];
    state.tabIds = new Map();
    let selected = null;
    const seen = new Set();
    const deadline = Date.now() + 10000;
    // Target attachment emits before Playwright finishes initializing the Page.
    do {
      for (const page of context.pages()) {
        if (page === state.anchor || page.isClosed() || seen.has(page)) continue;
        const identity = JSON.parse(await page.evaluate('"JARVIS_INTERNAL_TAB_IDENTITY_V1"').catch(e => { throw new Error('Work-tab identity: ' + e.message); }));
        seen.add(page);
        const tab = allowed.get(identity.tabId);
        if (!tab) continue;
        pages.push(page);
        state.tabIds.set(page, tab.tabId);
        if (tab.active) selected = page;
      }
      if (pages.length === allowed.size) break;
      if (Date.now() >= deadline) throw new Error('Automation tab initialization incomplete; retry listing tabs');
      await seed.waitForTimeout(50);
    } while (true);
    state.pages = pages;
    if (!pages.includes(state.active)) state.active = selected || pages[0] || null;
  }
  const create = async () => {
    if (!state.anchor || !state.tabIds) throw new Error('Automation connection anchor unavailable; refusing tab creation');
    const p = await context.newPage();
    state.pages.push(p);
    state.active = p;
    if (state.anchor) {
      const identity = JSON.parse(await p.evaluate('"JARVIS_INTERNAL_TAB_IDENTITY_V1"'));
      if (!Number.isSafeInteger(identity.tabId)) throw new Error('New tab identity missing');
      state.tabIds.set(p, identity.tabId);
    }
    return p;
  };
  const current = async () => {
    if (b.targetTabId !== undefined) {
      const target = state.pages.find(p => state.tabIds?.get(p) === b.targetTabId);
      if (!target) throw new Error(`Tab ${b.targetTabId} was closed or moved; refusing to target a different tab`);
      return target;
    }
    if (!state.pages.includes(state.active)) state.active = state.pages[0] || null;
    return state.active || await create();
  };
  const info = async p => ({url:p.url(), title:await p.title(), ...(state.tabIds?.has(p) ? {tabId:state.tabIds.get(p)} : {})});
  const status = async () => ({
    activeIndex:state.pages.indexOf(state.active),
    pages:await Promise.all(state.pages.map(async (p,index) => ({index,...await info(p)}))),
  });
  const locator = (p, fallback) => b.selector ? p.locator(b.selector) : b.text !== undefined ? p.getByText(b.text, {exact:!!b.exact}) : p.locator(fallback);
  const timeout = Math.max(250, Math.min(Number(b.timeoutMs ?? 10000), 60000));
  if (action === '/prepare-anchor') {
    const anchor=context.pages().find(p=>!p.isClosed() && p.url().startsWith('chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html') && p.url().endsWith('#jarvis-automation-anchor-v2'));
    if (!anchor) throw new Error('Automation connection anchor unavailable');
    await anchor.evaluate(async ({windowId,connectionTabId}) => {
      const t=await chrome.tabs.getCurrent();
      if (t?.id!==connectionTabId || t.windowId!==windowId || location.hash!=='#jarvis-automation-anchor-v2') throw new Error('Connection anchor identity mismatch');
      document.title='JARVIS Browser — Automation Only';
      // A fresh anchor avoids late detach/ungroup callbacks from the previous
      // connection targeting the new one. Do not update `pinned`: it can ungroup.
      // Wait for old debugger/group cleanup before adopting any work tabs.
      const deadline=Date.now()+15000;
      let tabs;
      for (;;) {
        tabs=await chrome.tabs.query({windowId});
        const windowTabIds=new Set(tabs.map(tab=>tab.id));
        const status=await chrome.runtime.sendMessage({type:'getConnectionStatus'});
        // Closing/reloading an anchor can leave its old connection controlling
        // work tabs. Retire only this bridge's stale groups, wholly contained
        // in our verified window; never another client or a personal tab.
        for (const connection of status?.connections || []) {
          const ids=connection.connectedTabIds || [];
          if (connection.clientName==='JARVIS Browser' && Number.isSafeInteger(connection.id) && ids.length && !ids.includes(connectionTabId) && ids.every(id=>windowTabIds.has(id))) {
            await chrome.runtime.sendMessage({type:'disconnect',connectionId:connection.id});
          }
        }
        const current=tabs.find(tab=>tab.id===connectionTabId);
        const targets=await chrome.debugger.getTargets();
        const attached=new Set(targets.filter(target=>target.attached).map(target=>target.tabId));
        const stale=tabs.some(tab=>{
          if (tab.id===connectionTabId) return false;
          const inCurrentGroup=current?.groupId>=0 && tab.groupId===current.groupId;
          const oldAnchor=tab.url?.startsWith('chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html') && tab.url.endsWith('#jarvis-automation-anchor-v2');
          return !inCurrentGroup && (attached.has(tab.id) || (oldAnchor && tab.groupId>=0));
        });
        if (!stale) break;
        if (Date.now()>=deadline) throw new Error('Previous automation connection cleanup incomplete; refusing competing debugger ownership');
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      for (const old of tabs) {
        if (old.id===t.id) continue;
        const obsoleteAnchor=old.url?.startsWith('chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html') && old.url.endsWith('#jarvis-automation-anchor-v2');
        const legacy=old.title==='JARVIS Browser — Automation Only' && old.url?.startsWith('data:text/html');
        if (obsoleteAnchor || legacy) await chrome.tabs.remove(old.id);
      }
    },b);
    state.anchor = anchor;
    return status();
  }
  // Bootstrap MCP's current context without reading stale work-page objects.
  if (action === '/connect') return {activeIndex:-1,pages:[]};
  if (action === '/status') return status();
  if (action === '/tabs') {
    if (b.action !== 'list') {
      const target = b.targetTabId !== undefined
        ? state.pages.find(p => state.tabIds?.get(p) === b.targetTabId)
        : state.pages[b.index];
      if (!target) throw new Error('Invalid or missing automation tab; refusing to target another tab');
      if (b.action === 'switch') { await target.bringToFront(); state.active = target; }
      else if (b.action === 'close') {
        await target.close();
        state.pages = state.pages.filter(p => p !== target);
        if (state.active === target) state.active = state.pages[0] || null;
      } else throw new Error('Invalid tab action');
    }
    return status();
  }
  if (action === '/close') {
    if (b.all === false && state.pages.includes(state.active)) {
      await state.active.close();
      state.pages = state.pages.filter(p => !p.isClosed());
      state.active = state.pages[0] || null;
    }
    return {closedAll:b.all !== false, daemonKeptAlive:true};
  }
  if (action === '/new-tab') {
    const p = await create();
    return { ...await info(p), index: state.pages.indexOf(p) };
  }
  if (action === '/open') {
    let url = String(b.url || '').trim();
    if (!url) throw new Error('URL required');
    if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) url = `https://${url}`;
    if (!/^https?:\/\//i.test(url) && url !== 'about:blank') throw new Error('Only HTTP(S) and about:blank navigation supported');
    const p = b.newTab ? await create() : await current();
    await p.bringToFront();
    await p.goto(url, {waitUntil:'domcontentloaded', timeout:60000});
    return {...await info(p), index:state.pages.indexOf(p)};
  }
  const p = await current();
  // Patched relay selects within the background automation window only.
  await p.bringToFront();
  if (action === '/extract') {
    const max = Math.max(500,Math.min(Number(b.maxText ?? 12000),50000));
    const text = await (b.selector ? p.locator(b.selector) : p.locator('body')).innerText({timeout});
    const links = b.includeLinks ? await p.locator(b.selector || 'body').locator('a[href]').evaluateAll(as => as.slice(0,120).map(a => ({text:a.innerText,href:a.href}))) : undefined;
    return {...await info(p), text:text.slice(0,max), ...(links ? {links} : {})};
  }
  if (action === '/screenshot') {
    const buffer = b.selector ? await p.locator(b.selector).screenshot({type:'png',timeout}) : await p.screenshot({type:'png',fullPage:!!b.fullPage,timeout});
    return {...await info(p), data:buffer.toString('base64'), mimeType:'image/png', width:buffer.readUInt32BE(16),height:buffer.readUInt32BE(20)};
  }
  if (action === '/click') {
    const options = {button:b.button || 'left',clickCount:Math.max(1,Math.min(Number(b.clicks || 1),3)),timeout};
    let x=b.x,y=b.y;
    if (b.selector || b.text !== undefined) {
      const l=locator(p); const box=await l.boundingBox();
      if (box) {x=box.x+box.width/2;y=box.y+box.height/2;}
      await l.click(options);
    } else {
      if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('Click target required');
      await p.mouse.click(x,y,options);
    }
    return {...await info(p),x:x ?? 0,y:y ?? 0};
  }
  if (action === '/type') {
    const result = await typeAction(p, b, timeout);
    return {...await info(p), ...result};
  }
  if (action === '/upload') {
    const files=b.paths || (b.path ? [b.path] : []);
    if (!files.length) throw new Error('Upload file required');
    const l=locator(p,'input[type=file]');
    let method='input';
    let input=l;
    if (!await l.evaluate(e => e.tagName === 'INPUT' && e.type === 'file')) {
      const [chooser]=await Promise.all([p.waitForEvent('filechooser',{timeout}),l.click({timeout})]);
      input=chooser.element(); method='filechooser';
    }
    // Chrome's extension debugger transport cannot reliably set local file paths.
    // Transfer only the caller-approved file bytes to the selected upload input.
    await input.evaluate((element, entries) => {
      if (element.tagName !== 'INPUT' || element.type !== 'file') throw new Error('Not a file input');
      if (!element.multiple && entries.length > 1) throw new Error('Input does not support multiple files');
      const transfer=new DataTransfer();
      for (const f of entries) {
        const bytes=Uint8Array.from(atob(f.data),c=>c.charCodeAt(0));
        transfer.items.add(new File([bytes],f.name,{type:f.mimeType}));
      }
      element.files=transfer.files;
      element.dispatchEvent(new Event('input',{bubbles:true}));
      element.dispatchEvent(new Event('change',{bubbles:true}));
    },b.uploadFiles);
    return {...await info(p),files,method};
  }
  if (action === '/key') {
    const k=String(b.key || '');
    if (['meta+t','control+t'].includes(k.toLowerCase())) return info(await create());
    if (['meta+w','control+w'].includes(k.toLowerCase())) {
      await p.close(); state.pages=state.pages.filter(q => q!==p); state.active=state.pages[0] || null;
      return state.active ? info(state.active) : {url:'',title:''};
    }
    await p.keyboard.press(k); return info(p);
  }
  if (action === '/scroll') {
    const amount=Math.max(50,Math.min(Number(b.amount ?? 700),3000)),direction=b.direction || 'down';
    if (b.x !== undefined && b.y !== undefined) await p.mouse.move(b.x,b.y);
    await p.mouse.wheel(direction==='left' ? -amount : direction==='right' ? amount : 0,direction==='up' ? -amount : direction==='down' ? amount : 0);
    return {...await info(p),amount,direction};
  }
  if (action === '/wait') {
    if (b.ms) await p.waitForTimeout(Math.max(0,Math.min(Number(b.ms),60000)));
    if (b.selector) await p.locator(b.selector).waitFor({state:'visible',timeout});
    if (b.text) await p.getByText(b.text,{exact:false}).first().waitFor({state:'visible',timeout});
    if (b.loadState) await p.waitForLoadState(b.loadState,{timeout});
    return info(p);
  }
  throw new Error('Unsupported browser action');
}

export function parseToolResult(result) {
  const text=(result.content || []).filter(c => c.type==='text').map(c => c.text).join('\n');
  if (result.isError) throw new Error(text.split('### Ran')[0]);
  const match=text.match(/### Result\n([\s\S]*?)(?=\n### |$)/);
  if (!match) throw new Error('Missing extension result');
  return JSON.parse(match[1]);
}

export class ExtensionBrowserBackend {
  constructor({profileDir,profileDirectory,chromePath,tokenPath=join(homedir(),'.jarvis','playwright-extension.token'),windowPath=join(homedir(),'.jarvis','extension-window.json')}) {
    Object.assign(this,{profileDir,profileDirectory,chromePath,tokenPath,windowPath});
    this.queue=Promise.resolve(); this.connected=false; this.lastError='';
    this.sessions = new BrowserSessions();
    this.resetCount=0; this.connectionGeneration=0; this.operationSequence=0;
    this.lastFailure=null; this.lastReset=null; this.quarantine=null;
    this.lastInventory={activeIndex:-1,pages:[]};
  }
  async init() {
    if (this.client) return;
    const relaySource=readFileSync(require.resolve('playwright-core/lib/coreBundle'),'utf8');
    if (!['JARVIS_BACKGROUND_TABS_V2','JARVIS_BACKGROUND_SELECTION_V2','JARVIS_WINDOW_TAB_SYNC_V1','JARVIS_LAUNCHER_ACK_V1'].every(marker=>relaySource.includes(marker))) throw new Error('Background-tab patch missing; run npm install in .pi/extensions/50-browser before using extension mode');
    const token=(await readFile(this.tokenPath,'utf8')).trim();
    if (!token) throw new Error('Playwright extension token is empty');
    this.secret=token;
    process.env.PLAYWRIGHT_MCP_EXTENSION_TOKEN=token;
    process.env.JARVIS_EXTENSION_WINDOW_FILE=this.windowPath;
    process.env.PLAYWRIGHT_MCP_EXECUTABLE_PATH=this.chromePath;
    if (this.profileDirectory) process.env.PLAYWRIGHT_MCP_PROFILE_DIR_NAME=this.profileDirectory;
    else delete process.env.PLAYWRIGHT_MCP_PROFILE_DIR_NAME;
    this.server=await createConnection({extension:true,snapshot:{mode:'none'},timeouts:{action:10000,navigation:60000},outputDir:join(homedir(),'.jarvis','browser-output')});
    this.client=new Client({name:'JARVIS Browser',version:'1.0.0'});
    const [ct,st]=InMemoryTransport.createLinkedPair();
    await this.server.connect(st); await this.client.connect(ct);
    const {tools}=await this.client.listTools();
    this.runTool=tools.find(t => t.name==='browser_run_code_unsafe' || t.name==='browser_run_code')?.name;
    if (!this.runTool) throw new Error('Pinned Playwright version lacks code tool');
  }
  status(inventory = {activeIndex:-1,pages:[]}) {
    return {protocolVersion:2,launchMode:'extension',running:this.connected,connected:this.connected,profileDir:this.profileDir,profileDirectory:this.profileDirectory || '(automation-window profile; token authenticated)',automationWindow:{dedicated:true,windowId:this.window?.windowId,title:'JARVIS Browser — Automation Only',anchorOpen:!!this.window,avoidsForegroundActivation:true,sessionOwnedTabsOnly:false,automationWindowTabsOnly:true},daemon:{connectedAt:this.connectedAt || null,lastError:this.lastError,connecting:!!this.connecting,recoveryCount:this.recoveryCount || 0,resetCount:this.resetCount,connectionGeneration:this.connectionGeneration,lastFailure:this.lastFailure,lastReset:this.lastReset,quarantined:!!this.quarantine,quarantine:this.quarantine,inventoryStale:!!this.quarantine},...inventory};
  }
  diagnostic(event, fields = {}) {
    // Call sites pass fixed event/reason names and numeric IDs/timings only.
    // Never include bodies, field values, selectors, URLs or exception messages.
    console.error('JARVIS_BRIDGE ' + JSON.stringify({event,at:new Date().toISOString(),...fields}));
  }
  sanitize(message) {
    let text=String(message);
    if (this.secret) text=text.split(this.secret).join('[REDACTED]');
    return text.replace(/chrome-extension:\/\/\S+/g,'[extension connection URL]');
  }
  async assertWindow() {
    const {windowId,connectionTabId}=this.window || {};
    if (![windowId,connectionTabId].every(Number.isSafeInteger)) throw new Error('Automation window identity missing');
    // Native-mode preparation and the immediately following relay inventory
    // both verify these IDs through the authenticated extension. Do not send
    // AppleEvents: macOS may launch Chrome if it exits during a read-only check.
    if (this.window.connectionMode === 'jarvis-background-native-v1') return;
    const script=`tell application "Google Chrome"
      set w to first window whose id is ${windowId}
      set foundAnchor to false
      set foundConnection to false
      repeat with t in tabs of w
        if (id of t as text) is "${connectionTabId}" then
          if (URL of t starts with "chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html") and (URL of t ends with "#jarvis-automation-anchor-v2") then
            set foundAnchor to true
            set foundConnection to true
          end if
        end if
      end repeat
      if not foundAnchor or not foundConnection then error "Automation window or connection moved/closed"
      return "verified"
    end tell`;
    try { await execFileAsync('/usr/bin/osascript',['-e',script],{timeout:10000}); }
    catch (error) {
      // This script contains only window/tab IDs and fixed markers, never page
      // content or connection tokens. Distinguish AppleEvent failure from a
      // genuinely missing anchor without exposing the connection URL.
      console.error('JARVIS_WINDOW_VERIFY', JSON.stringify({time:new Date().toISOString(),code:error.code,signal:error.signal,killed:error.killed,stderr:this.sanitize(error.stderr || '').slice(0,1500)}));
      throw new Error('Automation window or connection moved/closed; refusing to control another window');
    }
  }
  async restoreConnectionFocus() {
    const w=this.window;
    if (w?.connectionMode === 'jarvis-background-native-v1' || !w?.previousFrontWindowId) return;
    const script=`on run argv
      tell application "System Events" to set currentApp to bundle identifier of first application process whose frontmost is true
      if currentApp is not "com.google.Chrome" then return
      tell application "Google Chrome"
        if (id of front window as text) is not item 1 of argv then return
        if item 1 of argv is not item 2 of argv then
          try
            set index of (first window whose id is (item 2 of argv as integer)) to 1
          end try
        end if
      end tell
      if item 3 of argv is not "" and item 3 of argv is not "com.google.Chrome" then
        tell application id (item 3 of argv) to activate
      end if
    end run`;
    await execFileAsync('/usr/bin/osascript',['-e',script,'--',String(w.windowId),String(w.previousFrontWindowId),w.previousFrontApp || ''],{timeout:10000}).catch(()=>{});
  }
  async reset(reason = 'explicit-reset') {
    if (this.quarantine) throw new Error('Browser bridge quarantined: unacknowledged action may still be running. Supervised recovery required.');
    this.resetCount++;
    this.lastReset={at:new Date().toISOString(),reason};
    this.diagnostic('reset',{reason,resetCount:this.resetCount});
    this.connectedAt=null;
    const client=this.client,server=this.server;
    this.client=null;this.server=null;this.connected=false;this.window=null;this.preparedConnectionTabId=null;
    await client?.close().catch(()=>{});await server?.close().catch(()=>{});
  }
  async callAction(path, body = {}) {
    const timed=['/type','/click','/key','/scroll','/upload','/open','/new-tab','/tabs'].includes(path);
    const started=Date.now(), operationId=++this.operationSequence;
    const fields={operationId,action:timed ? path : 'preflight',tabId:Number.isSafeInteger(body.targetTabId) ? body.targetTabId : null};
    if (timed) this.diagnostic('action-start',{...fields,deadlineMs:actionDeadlineMs(path,body)});
    try {
      const result=parseToolResult(await this.client.callTool({name:this.runTool,arguments:{code:`async (page) => await (${extensionAction.toString()})(page, ${JSON.stringify(path)}, ${JSON.stringify(body)}, (${verifiedType.toString()}))`}},undefined,{timeout:actionDeadlineMs(path, body)}));
      if (timed) this.diagnostic('action-end',{...fields,durationMs:Date.now()-started,outcome:'completed'});
      return result;
    } catch (error) {
      this.diagnostic('action-end',{...fields,durationMs:Date.now()-started,outcome:failureKind(error)});
      throw error;
    }
  }
  isTransportFailure(message) {
    return /target (?:page|closed)|context or browser has been closed|disconnected|extension did not connect|connection.*(?:lost|closed)|connection anchor unavailable|Anchor inventory:|Work-tab identity:|execution context was destroyed|tab identity missing|inventory identity missing|request timed out|transport/i.test(message);
  }
  async prepare() {
    await this.init();
    // MCP can reconnect without notifying its client. Bootstrap it, then read
    // the launcher's fresh connection ID before trusting cached daemon state.
    await this.callAction('/connect');
    this.window=JSON.parse(await readFile(this.windowPath,'utf8'));
    if (this.preparedConnectionTabId!==this.window.connectionTabId) {
      await this.callAction('/prepare-anchor', {windowId:this.window.windowId,connectionTabId:this.window.connectionTabId});
      this.preparedConnectionTabId=this.window.connectionTabId;
      this.connectionGeneration++;
      this.connectedAt=new Date().toISOString();
      this.diagnostic('connection-generation',{generation:this.connectionGeneration,connectionTabId:this.preparedConnectionTabId});
      await this.restoreConnectionFocus();
    }
    await this.assertWindow();
    const inventory=validateTabInventory(await this.callAction('/status'));
    this.lastInventory=inventory;
    this.connected=true;
    this.connectedAt ||= new Date().toISOString();
    return inventory;
  }
  async prepareWithRecovery() {
    // Only connection establishment and read-only discovery may retry. Once
    // session routing dispatches ANY action (including new-tab), never replay.
    if (this.quarantine) throw new Error('Browser bridge quarantined; supervised recovery required.');
    for (let attempt=0; ; attempt++) {
      try { return await this.prepare(); }
      catch (error) {
        const message=this.sanitize(error.message || error);
        // A request timeout is NOT a cancellation acknowledgement. Even an
        // inventory call can have pending relay work; do not start a new context.
        if (isRequestDeadline(error) || attempt >= 2 || !this.isTransportFailure(message) || message.startsWith('Automation window or connection moved/closed')) throw error;
        this.lastFailure={at:new Date().toISOString(),kind:'preflight-transport-error',action:'preflight',sessionId:null,tabId:null};
        await this.reset('preflight-transport-error');
        this.recoveryCount=(this.recoveryCount || 0)+1;
        this.connecting=true;
        await new Promise(resolve=>setTimeout(resolve,100*(attempt+1)));
      }
    }
  }
  handle(path,body={},sessionId='__bridge__') {
    // Serialize tab selection + actions; never replay a failed mutating action.
    const run=async () => {
      if (path === '/close' && body.all !== false) {
        return this.sessions.handle(path, body, sessionId, () => { throw new Error('Release must not access Chrome'); });
      }
      if (this.quarantine) {
        // Cached status/release only. NEVER activate, inspect through Playwright,
        // reconnect, or allow explicit reselection to override this fence.
        if (path === '/status' || (path === '/tabs' && ['list','release'].includes(body.action))) {
          const result=await this.sessions.handle(path,body,sessionId,()=>{throw new Error('Quarantine must not access Chrome');},this.lastInventory,{reconcile:false});
          return this.status(result);
        }
        throw new Error('Browser bridge quarantined: an earlier action has no cancellation acknowledgement. Supervised recovery required; no action performed.');
      }
      this.connecting=!this.connected;
      let dispatched=false;
      try {
        const inventory=await this.prepareWithRecovery();
        if (path==='/upload') {
          const paths=body.paths || (body.path ? [body.path] : []);
          const mime={'.pdf':'application/pdf','.txt':'text/plain','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'};
          let total=0;
          const uploadFiles=[];
          for (const file of paths) {
            const data=await readFile(file); total+=data.length;
            if (total>32*1024*1024) throw new Error('Extension uploads limited to 32 MiB per call');
            uploadFiles.push({name:basename(file),mimeType:mime[extname(file).toLowerCase()] || 'application/octet-stream',data:data.toString('base64')});
          }
          body={...body,uploadFiles};
        }
        // Session routing, lease validation, activation and action all share the
        // same queue. Never expose internal targetTabId or /new-tab to callers.
        this.lastInventory=inventory;
        const result = await this.sessions.handle(path === '/connect' ? '/status' : path, body, sessionId, (action, args) => {
          dispatched=true;
          return this.callAction(action, args);
        }, inventory);
        this.connected=true;this.connectedAt ||= new Date().toISOString();this.lastError='';
        if (['/status','/tabs','/connect'].includes(path)) return this.status(result);
        return result;
      } catch(error) {
        this.lastError=this.sanitize(error.message || error);
        this.lastFailure={at:new Date().toISOString(),kind:failureKind(error),action:path,sessionId,tabId:this.sessions.session(sessionId).tabId};
        if (isRequestDeadline(error)) {
          // Promise rejection does not stop CDP input. Retain the old transport
          // and prohibit ALL further browser dispatch until supervised recovery.
          this.quarantine={...this.lastFailure,reason:'execution-not-acknowledged'};
          this.diagnostic('quarantine',{reason:'execution-not-acknowledged',tabId:this.lastFailure.tabId});
          this.sessions.invalidate();
          this.connected=false;
        } else if (!this.connected || this.isTransportFailure(this.lastError)) {
          this.sessions.invalidate();
          await this.reset(dispatched ? 'action-transport-error' : 'preflight-transport-error');
        } else if (dispatched && isLocalActionFailure(path,this.lastError)) {
          // The action returned an error (unlike MCP's outer timeout). Its
          // outcome may be partial, but other sessions keep their selections.
          this.sessions.invalidate(sessionId);
          this.diagnostic('session-fenced',{reason:this.lastFailure.kind,tabId:this.lastFailure.tabId});
        }
        throw new Error(this.lastError + (this.quarantine ? ' Browser bridge quarantined; supervised recovery required.' : ''));
      } finally {this.connecting=false;}
    };
    const result=this.queue.then(run,run);this.queue=result.catch(()=>{});return result;
  }
}
