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
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';

// Fixed implementation only: callers cannot submit code to the MCP server.
// Never adopt the seed page (which may be the extension's connection tab).
export async function extensionAction(seed, action, b) {
  const context = seed.context();
  let state = context.__jarvisOwnedTabs;
  if (!state) {
    state = { pages: [], active: null };
    context.__jarvisOwnedTabs = state;
  }
  state.pages = state.pages.filter(p => !p.isClosed());
  const create = async () => {
    const p = await context.newPage();
    state.pages.push(p);
    state.active = p;
    return p;
  };
  const current = async () => {
    if (!state.pages.includes(state.active)) state.active = state.pages[0] || null;
    return state.active || await create();
  };
  const info = async p => ({url:p.url(), title:await p.title()});
  const status = async () => ({
    activeIndex:state.pages.indexOf(state.active),
    pages:await Promise.all(state.pages.map(async (p,index) => ({index,...await info(p)}))),
  });
  const locator = (p, fallback) => b.selector ? p.locator(b.selector) : b.text !== undefined ? p.getByText(b.text, {exact:!!b.exact}) : p.locator(fallback);
  const timeout = Math.max(250, Math.min(Number(b.timeoutMs ?? 10000), 60000));
  if (action === '/prepare-anchor') {
    await seed.evaluate(async ({windowId,connectionTabId}) => {
      const t=await chrome.tabs.getCurrent();
      if (t?.id!==connectionTabId || t.windowId!==windowId || location.hash!=='#jarvis-automation-anchor-v2') throw new Error('Connection anchor identity mismatch');
      document.title='JARVIS Browser — Automation Only';
      // Playwright uses a tab group; Chrome ungrouping on pin disconnects it.
      await chrome.tabs.update(t.id,{pinned:false});
      // Migrate only our exact legacy data-page marker in this same window.
      const tabs=await chrome.tabs.query({windowId});
      for (const old of tabs) if (old.id!==t.id && old.title==='JARVIS Browser — Automation Only' && old.url?.startsWith('data:text/html')) await chrome.tabs.remove(old.id);
    },b);
    return status();
  }
  if (action === '/connect' || action === '/status') return status();
  if (action === '/tabs') {
    if (b.action !== 'list') {
      if (!Number.isInteger(b.index) || !state.pages[b.index]) throw new Error('Invalid automation tab index');
      const target = state.pages[b.index];
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
  if (action === '/open') {
    let url = String(b.url || '').trim();
    if (!url) throw new Error('URL required');
    if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) url = `https://${url}`;
    if (!/^https?:\/\//i.test(url) && url !== 'about:blank') throw new Error('Only HTTP(S) and about:blank navigation supported');
    const p = b.newTab ? await create() : await current();
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
    if (b.selector) await p.locator(b.selector).focus({timeout});
    const editable = await p.evaluate(() => {
      const e=document.activeElement;
      return !!e && (e.isContentEditable || (e.tagName==='TEXTAREA' && !e.disabled && !e.readOnly) || (e.tagName==='INPUT' && !e.disabled && !e.readOnly && !['button','submit','checkbox','radio','file','hidden'].includes(e.type)));
    });
    if (!editable) throw new Error('No editable element focused');
    if (b.clear) {
      if (b.selector) await p.locator(b.selector).fill('', {timeout});
      else await p.evaluate(() => {
        const e=document.activeElement;
        if (e.isContentEditable) e.textContent='';
        else {
          const proto=e.tagName==='TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(e,'');
        }
        e.dispatchEvent(new Event('input',{bubbles:true}));
      });
    }
    await p.keyboard.type(String(b.text), {delay:Math.max(0,Math.min(Number(b.delayMs ?? 20),1000))});
    return {...await info(p),typedCharacters:String(b.text).length};
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
  constructor({profileDir,profileDirectory,chromePath,tokenPath=join(homedir(),'.jarvis','playwright-extension.token')}) {
    Object.assign(this,{profileDir,profileDirectory,chromePath,tokenPath});
    this.queue=Promise.resolve(); this.connected=false; this.lastError=''; this.cached={activeIndex:-1,pages:[]};
  }
  async init() {
    if (this.client) return;
    const relaySource=readFileSync(require.resolve('playwright-core/lib/coreBundle'),'utf8');
    if (!['JARVIS_BACKGROUND_TABS_V2','JARVIS_BACKGROUND_SELECTION_V2'].every(marker=>relaySource.includes(marker))) throw new Error('Background-tab patch missing; run npm install in .pi/extensions/50-browser before using extension mode');
    const token=(await readFile(this.tokenPath,'utf8')).trim();
    if (!token) throw new Error('Playwright extension token is empty');
    this.secret=token;
    process.env.PLAYWRIGHT_MCP_EXTENSION_TOKEN=token;
    process.env.JARVIS_EXTENSION_WINDOW_FILE=join(homedir(),'.jarvis','extension-window.json');
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
  status() {
    return {launchMode:'extension',running:this.connected,connected:this.connected,profileDir:this.profileDir,profileDirectory:this.profileDirectory || '(automation-window profile; token authenticated)',automationWindow:{dedicated:true,windowId:this.window?.windowId,title:'JARVIS Browser — Automation Only',anchorOpen:!!this.window,avoidsForegroundActivation:true,sessionOwnedTabsOnly:true},daemon:{connectedAt:this.connectedAt || null,lastError:this.lastError,connecting:!!this.connecting},...this.cached};
  }
  sanitize(message) {
    let text=String(message);
    if (this.secret) text=text.split(this.secret).join('[REDACTED]');
    return text.replace(/chrome-extension:\/\/\S+/g,'[extension connection URL]');
  }
  async assertWindow() {
    const {windowId,connectionTabId}=this.window || {};
    if (![windowId,connectionTabId].every(Number.isSafeInteger)) throw new Error('Automation window identity missing');
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
    catch { throw new Error('Automation window or connection moved/closed; refusing to control another window'); }
  }
  async restoreConnectionFocus() {
    const w=this.window;
    if (!w?.previousFrontWindowId) return;
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
  async reset() {
    const client=this.client,server=this.server;
    this.client=null;this.server=null;this.connected=false;this.window=null;this.cached={activeIndex:-1,pages:[]};
    await client?.close().catch(()=>{});await server?.close().catch(()=>{});
  }
  handle(path,body={}) {
    // Serialize tab selection + actions; never replay a failed mutating action.
    const run=async () => {
      if (path==='/status' && !this.client) return this.status();
      this.connecting=!this.connected;
      try {
        await this.init();
        if (!this.connected) {
          parseToolResult(await this.client.callTool({name:this.runTool,arguments:{code:`async (page) => await (${extensionAction.toString()})(page, '/connect', {})`}},undefined,{timeout:60000}));
          this.window=JSON.parse(await readFile(join(homedir(),'.jarvis','extension-window.json'),'utf8'));
          parseToolResult(await this.client.callTool({name:this.runTool,arguments:{code:`async (page) => await (${extensionAction.toString()})(page, '/prepare-anchor', ${JSON.stringify({windowId:this.window.windowId,connectionTabId:this.window.connectionTabId})})`}},undefined,{timeout:60000}));
          await this.restoreConnectionFocus();
        }
        await this.assertWindow();
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
        const result=parseToolResult(await this.client.callTool({name:this.runTool,arguments:{code:`async (page) => await (${extensionAction.toString()})(page, ${JSON.stringify(path)}, ${JSON.stringify(body)})`}},undefined,{timeout:150000}));
        this.connected=true;this.connectedAt ||= new Date().toISOString();this.lastError='';
        if (['/status','/tabs','/connect'].includes(path)) {this.cached=result;return this.status();}
        return result;
      } catch(error) {
        this.lastError=this.sanitize(error.message || error);
        // Only rebuild a lost transport; selector/validation errors must not orphan tabs.
        if (!this.connected || /closed|disconnected|extension did not connect|connection.*lost/i.test(this.lastError)) await this.reset();
        throw new Error(this.lastError);
      } finally {this.connecting=false;}
    };
    const result=this.queue.then(run,run);this.queue=result.catch(()=>{});return result;
  }
}
