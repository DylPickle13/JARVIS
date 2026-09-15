// Version-pinned local adaptation of Microsoft's extension relay.
// All tab creation/selection uses Chrome extension APIs, NOT foreground APIs.
import { createRequire } from 'node:module';
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
writeFileSync(file,source);
console.log('Pinned background creation/selection patches verified.');
