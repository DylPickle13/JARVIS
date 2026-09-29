// Version-pinned local adaptation of Microsoft's extension relay.
// All tab creation/selection uses Chrome extension APIs, NOT foreground APIs.
import { createRequire } from 'node:module';
import { syncWindowTabs } from './window-tab-sync.mjs';
import { readFileSync, writeFileSync } from 'node:fs';
const require=createRequire(import.meta.url);
const file=require.resolve('playwright-core/lib/coreBundle');
if (require('playwright-core/package.json').version !== '1.64.0-alpha-2026-09-14') throw new Error('Review background patch before changing Playwright version');
let source=readFileSync(file,'utf8');
const oldCreate='const tab2 = await this._sendToExtension("chrome.tabs.create", [{ url: url3 }]);';
const create=`// JARVIS_BACKGROUND_TABS_V2
        const windowId = JSON.parse(require("fs").readFileSync(process.env.JARVIS_EXTENSION_WINDOW_FILE, "utf8")).windowId;
        if (!Number.isInteger(windowId)) throw new Error("JARVIS: automation window identity missing");
        const tab2 = await this._sendToExtension("chrome.tabs.create", [{ url: url3, active: true, windowId }]);`;
const priorCreate=/\/\/ JARVIS_BACKGROUND_TABS_V1\n[\s\S]*?const tab2 = await this\._sendToExtension\("chrome\.tabs\.create", \[\{ url: url3, active: (?:true|false), windowId \}\]\);/;
if (!source.includes(create)) {
  if (priorCreate.test(source)) source=source.replace(priorCreate,create);
  else {
    if(source.split(oldCreate).length!==2)throw new Error('Tab creation patch anchor changed');
    source=source.replace(oldCreate,create);
  }
}
const oldFocus='return await this._sendToExtension("chrome.debugger.sendCommand", [\n          { tabId: tabSession.tabId, sessionId: cdpSessionId },';
const focus=`// JARVIS_BACKGROUND_SELECTION_V2
        if (method === "Page.bringToFront") {
          const windowId = JSON.parse(require("fs").readFileSync(process.env.JARVIS_EXTENSION_WINDOW_FILE, "utf8")).windowId;
          const connection = [...this._tabSessions.values()].find(s => s.targetInfo?.url?.startsWith("chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html"));
          if (!connection || !Number.isInteger(windowId)) throw new Error("JARVIS: authenticated connection page unavailable");
          const expression = "(async () => { const t = await chrome.tabs.get(" + JSON.stringify(tabSession.tabId) + "); if (t.windowId !== " + JSON.stringify(windowId) + ") throw new Error('Refusing non-automation tab'); await chrome.tabs.update(t.id, {active:true}); return true; })()";
          const result = await this._sendToExtension("chrome.debugger.sendCommand", [{tabId:connection.tabId}, "Runtime.evaluate", {expression,awaitPromise:true,returnByValue:true}]);
          if (result?.exceptionDetails || result?.result?.value !== true) throw new Error("JARVIS: background tab selection failed");
          return {};
        }
        ${oldFocus}`;
if (!source.includes(focus)) {
  const previous=/\/\/ JARVIS_BACKGROUND_SELECTION_V1\n[\s\S]*?\n        return await this\._sendToExtension\("chrome\.debugger\.sendCommand", \[\n          \{ tabId: tabSession\.tabId, sessionId: cdpSessionId \},/;
  if (previous.test(source)) source=source.replace(previous,focus);
  else {
    if(source.split(oldFocus).length!==2)throw new Error('Tab selection patch anchor changed');
    source=source.replace(oldFocus,focus);
  }
}
const syncAnchor='async sendCommand(sessionId, method, params2) {';
const syncPatch=`${syncAnchor}\n        // JARVIS_WINDOW_TAB_SYNC_V1`;
// Migrate the development-only CDP command; the extension disallows newCDPSession.
source=source.replace(/\/\/ JARVIS_WINDOW_TAB_SYNC_V1\n        if \(method === "Jarvis.syncWindowTabs"\)[\s\S]*?\n        let tabSession/, '// JARVIS_WINDOW_TAB_SYNC_V1\n        let tabSession');
if (!source.includes(syncPatch)) {
  if (source.split(syncAnchor).length!==2) throw new Error('Tab sync patch anchor changed');
  source=source.replace(syncAnchor,syncPatch);
}
const identityAnchor='// JARVIS_BACKGROUND_SELECTION_V2';
const identityPatch=`// JARVIS_INTERNAL_EVALUATION_V1
        if (method === "Runtime.callFunctionOn" && params2?.returnByValue) {
          const expression = params2.arguments?.[3]?.value;
          if (expression === '\"JARVIS_INTERNAL_SYNC_WINDOW_TABS_V1\"') {
            const identity = JSON.parse(require("fs").readFileSync(process.env.JARVIS_EXTENSION_WINDOW_FILE, "utf8"));
            if (tabSession.tabId !== identity.connectionTabId) throw new Error("Tab discovery requires authenticated anchor");
            const inventory = await (${syncWindowTabs.toString()}).call(this);
            return {result:{type:"string",value:JSON.stringify(inventory)}};
          }
          if (expression === '\"JARVIS_INTERNAL_TAB_IDENTITY_V1\"') return {result:{type:"string",value:JSON.stringify({tabId:tabSession.tabId})}};
        }
        ` + identityAnchor;
source=source.replace('if (method === "Jarvis.tabIdentity") return {tabId:tabSession.tabId};\n        ', '');
if (!source.includes(identityPatch)) {
  if (source.includes('// JARVIS_INTERNAL_EVALUATION_V1')) source=source.replace(/\/\/ JARVIS_INTERNAL_EVALUATION_V1[\s\S]*?\/\/ JARVIS_BACKGROUND_SELECTION_V2/,identityPatch);
  else source=source.replace(identityAnchor,identityPatch);
}
const attachAnchor='async _attachTab(tabId) {';
const attachPatch=`// JARVIS_SERIAL_TAB_ATTACH_V1
      async _attachTab(tabId) {
        this._jarvisPendingAttach ||= new Map();
        if (this._jarvisPendingAttach.has(tabId)) return await this._jarvisPendingAttach.get(tabId);
        const pending = this._jarvisAttachTab(tabId);
        this._jarvisPendingAttach.set(tabId, pending);
        try { return await pending; } finally { this._jarvisPendingAttach.delete(tabId); }
      }
      async _jarvisAttachTab(tabId) {`;
if (!source.includes('JARVIS_SERIAL_TAB_ATTACH_V1')) {
  if (source.split(attachAnchor).length !== 2) throw new Error('Tab attachment patch anchor changed');
  source=source.replace(attachAnchor,attachPatch);
}
writeFileSync(file,source);
console.log('Pinned background creation/selection patches verified.');
