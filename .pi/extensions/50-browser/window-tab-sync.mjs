// Embedded into the pinned relay; no caller-controlled code or window selection.
export async function syncWindowTabs() {
  const { windowId, connectionTabId } = JSON.parse(require('fs').readFileSync(process.env.JARVIS_EXTENSION_WINDOW_FILE, 'utf8'));
  if (![windowId, connectionTabId].every(Number.isSafeInteger)) throw new Error('Automation window identity missing');
  const connection = this._tabSessions.get(connectionTabId);
  if (!connection) throw new Error('Authenticated connection unavailable');
  const expression = `(${async function(windowId, connectionTabId) {
    const anchor = await chrome.tabs.getCurrent();
    if (anchor?.id !== connectionTabId || anchor.windowId !== windowId || location.hash !== '#jarvis-automation-anchor-v2' || !location.href.startsWith('chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html')) throw new Error('Connection anchor identity mismatch');
    return (await chrome.tabs.query({windowId})).filter(t => t.id !== connectionTabId && !t.url?.startsWith('chrome-extension://')).map(t => ({tabId:t.id, active:t.active}));
  }.toString()})(${JSON.stringify(windowId)},${JSON.stringify(connectionTabId)})`;
  const result = await this._sendToExtension('chrome.debugger.sendCommand', [{tabId:connectionTabId}, 'Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true}]);
  if (result?.exceptionDetails || !Array.isArray(result?.result?.value)) throw new Error('Automation tab discovery failed');
  const tabs = result.result.value;
  const inventory = [];
  for (const tab of tabs) {
    // A close/move racing discovery fails the request, never navigates/replays it.
    const session = await this._attachTab(tab.tabId);
    inventory.push({...tab, targetId:session.targetInfo.targetId});
  }
  return {tabs:inventory};
}
