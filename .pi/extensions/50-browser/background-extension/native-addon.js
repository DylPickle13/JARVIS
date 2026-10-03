// JARVIS local adaptation; appended to the pinned official service worker.
// No focus restoration: neither the launcher nor this path may activate a window.
(() => {
  const mode = 'jarvis-background-native-v1';
  let port;
  const seen = new Set();
  async function handle(message) {
    const id = message?.id;
    if (typeof id !== 'string' || !id || seen.has(id)) return;
    seen.add(id); // Never replay an uncertain tab-creation request.
    try {
      if (message.command !== 'connect' || message.mode !== mode || !Number.isSafeInteger(message.windowId) || message.windowId <= 0)
        throw new Error('Invalid request');
      const url = new URL(message.url);
      const expected = new URL(chrome.runtime.getURL('connect.html'));
      if (url.protocol !== expected.protocol || url.host !== expected.host || url.pathname !== expected.pathname || url.hash !== '#jarvis-automation-anchor-v2')
        throw new Error('Invalid connection URL');
      const relay = new URL(url.searchParams.get('mcpRelayUrl'));
      if (relay.protocol !== 'ws:' || !['127.0.0.1', '[::1]'].includes(relay.hostname) || !relay.port || relay.username || relay.password || !url.searchParams.get('token') || url.searchParams.get('protocolVersion') !== '2')
        throw new Error('Invalid relay');
      const window = await chrome.windows.get(message.windowId);
      if (window.id !== message.windowId || window.type !== 'normal' || window.incognito)
        throw new Error('Automation window unavailable');
      const tab = await chrome.tabs.create({windowId: message.windowId, url: url.href, active: false});
      if (!Number.isSafeInteger(tab.id) || tab.windowId !== message.windowId)
        throw new Error('Unexpected tab identity');
      port.postMessage({id, ok: true, mode, windowId: tab.windowId, connectionTabId: tab.id});
    } catch {
      // A rejected/lost response may follow a created tab. No automatic retry,
      // fallback, URL logging, personal-window adoption, or tab cleanup guess.
      try { port.postMessage({id, ok: false, mode}); } catch {}
    }
  }
  function connect() {
    try {
      port = chrome.runtime.connectNative('com.jarvis.browser_background');
      port.onMessage.addListener(handle);
      port.onDisconnect.addListener(() => {
        void chrome.runtime.lastError;
        setTimeout(connect, 3000); // Reopen only the local pipe, never Chrome.
      });
      port.postMessage({type: 'hello', mode});
    } catch {
      setTimeout(connect, 3000);
    }
  }
  connect();
})();
