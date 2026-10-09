export function validateTabInventory(inventory) {
  const pages = inventory?.pages;
  if (!Array.isArray(pages) || pages.some(p => !Number.isSafeInteger(p.tabId)) || new Set(pages.map(p => p.tabId)).size !== pages.length) {
    throw new Error('Automation inventory identity missing or duplicated; refusing tab control');
  }
  return inventory;
}

// Daemon-owned state, independent of Playwright's connection/context lifetime.
// All calls MUST run inside ExtensionBrowserBackend's single action queue.
export class BrowserSessions {
  constructor({ leaseMs = 15 * 60 * 1000, now = Date.now } = {}) {
    this.sessions = new Map();
    this.leases = new Map();
    this.leaseMs = leaseMs;
    this.now = now;
  }

  session(id) {
    if (!this.sessions.has(id)) this.sessions.set(id, { tabId: null, listed: [], uncertain: false });
    return this.sessions.get(id);
  }

  lease(tabId) {
    const lease = this.leases.get(tabId);
    if (lease && lease.expiresAt <= this.now()) {
      this.leases.delete(tabId);
      return undefined;
    }
    return lease;
  }

  claim(id, tabId) {
    const lease = this.lease(tabId);
    if (lease && lease.owner !== id) {
      throw new Error(`Tab ${tabId} is controlled by another Pi session (${lease.owner}). Ask that session to browser_tabs(action:"release", tabId:${tabId}), or wait for its idle lease to expire. No action performed.`);
    }
    this.leases.set(tabId, { owner: id, expiresAt: this.now() + this.leaseMs });
  }

  release(id, tabId) {
    if (this.leases.get(tabId)?.owner === id) this.leases.delete(tabId);
  }

  // An indeterminate transport outcome must not silently resume a stale workflow.
  invalidate(id) {
    const affected = id === undefined ? this.sessions.values() : [this.session(id)];
    for (const session of affected) {
      session.uncertain = true;
      session.listed = [];
    }
  }

  async handle(path, body, id, run, inventory, { reconcile = true, allowInspection = false } = {}) {
    const session = this.session(id);
    // Releasing a session never needs a functioning browser connection.
    if (path === '/close' && body.all !== false) {
      for (const [tabId, lease] of this.leases) if (lease.owner === id) this.leases.delete(tabId);
      this.sessions.delete(id);
      return { closedAll: true, daemonKeptAlive: true, released: true };
    }

    if (!reconcile && path !== '/status' && !(path === '/tabs' && ['list','release'].includes(body.action))) {
      throw new Error('Stale inventory cannot authorize browser actions');
    }
    inventory = validateTabInventory(inventory ?? await run('/status', {}));
    const pages = inventory.pages;
    const exists = tabId => pages.some(p => p.tabId === tabId);
    // Cached quarantine inventory may predate an uncertain creation. It must
    // never erase leases or assert that a now-unlisted selected tab is gone.
    if (reconcile) for (const tabId of this.leases.keys()) if (!exists(tabId)) this.leases.delete(tabId);
    const status = () => {
      session.listed = pages.map(p => p.tabId);
      return {
        activeIndex: pages.findIndex(p => p.tabId === session.tabId),
        selectedTabId: session.tabId,
        selectionMissing: reconcile && session.tabId !== null && !exists(session.tabId),
        needsReselect: session.uncertain || (session.tabId !== null && this.lease(session.tabId)?.owner !== id),
        sessionId: id,
        leaseIdleTimeoutMs: this.leaseMs,
        pages: pages.map((p, index) => {
          const lease = this.lease(p.tabId);
          return { ...p, index, controlledBy: lease?.owner ?? null, controlledByThisSession: lease?.owner === id, leaseExpiresAt: lease?.expiresAt ?? null };
        }),
      };
    };
    const target = () => {
      // Indexes resolve against THIS session's last returned inventory, not a
      // newly reordered global array. Explicit stable IDs need no prior listing.
      const tabId = body.tabId ?? (Number.isInteger(body.index) ? session.listed[body.index] : undefined);
      if (!Number.isSafeInteger(tabId)) throw new Error('Specify tabId, or list tabs before using an index.');
      if (reconcile && !exists(tabId)) throw new Error(`Tab ${tabId} was closed or moved out of the automation window. List tabs and explicitly select another tab.`);
      return tabId;
    };
    const current = () => {
      const tabId = session.tabId;
      if (tabId === null) throw new Error('No tab selected for this Pi session. Open a URL or explicitly switch to a listed tab.');
      if (!exists(tabId)) throw new Error(`Selected tab ${tabId} was closed or moved out of the automation window. No action performed; explicitly select another tab.`);
      if (session.uncertain && !(allowInspection && ['/screenshot','/extract'].includes(path))) throw new Error('Previous browser action had an uncertain outcome. Inspect/list tabs and explicitly switch before continuing; do not replay a mutation blindly.');
      if (this.lease(tabId)?.owner !== id) throw new Error(`Control of tab ${tabId} was released or expired. Explicitly switch to reacquire it before continuing.`);
      this.claim(id, tabId);
      return tabId;
    };
    const create = async () => {
      // Separate creation from navigation so even a failed navigation retains
      // the new tab's stable identity and lease; no other session adopts it.
      const page = await run('/new-tab', {});
      if (!Number.isSafeInteger(page.tabId)) throw new Error('New tab identity missing; refusing navigation');
      session.tabId = page.tabId;
      session.uncertain = false;
      this.claim(id, page.tabId);
      // Preserve indexes returned by open until this session lists tabs again.
      session.listed[page.index] = page.tabId;
      return page;
    };

    if (path === '/status' || (path === '/tabs' && body.action === 'list')) return status();
    if (path === '/tabs') {
      if (body.action === 'release') {
        const tabId = body.tabId !== undefined || body.index !== undefined ? target() : session.tabId;
        if (tabId === null) throw new Error('No selected tab to release');
        this.release(id, tabId);
        return status();
      }
      if (!['switch', 'close'].includes(body.action)) throw new Error('Invalid tab action');
      const tabId = target();
      this.claim(id, tabId);
      await run('/tabs', { action: body.action, targetTabId: tabId });
      if (body.action === 'switch') {
        session.tabId = tabId;
        session.uncertain = false;
      } else {
        this.release(id, tabId);
        pages.splice(pages.findIndex(p => p.tabId === tabId), 1);
        // Keep the selected ID as a tombstone: never fall back to another tab.
      }
      return status();
    }
    if (path === '/open') {
      let url = String(body.url || '').trim();
      if (!url) throw new Error('URL required');
      if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) url = `https://${url}`;
      if (!/^https?:\/\//i.test(url) && url !== 'about:blank') throw new Error('Only HTTP(S) and about:blank navigation supported');
      const page = body.newTab || session.tabId === null ? await create() : { tabId: current() };
      return run('/open', { ...body, url, newTab: false, targetTabId: page.tabId });
    }
    if (path === '/key' && ['meta+t', 'control+t'].includes(String(body.key).toLowerCase())) return create();
    const tabId = current();
    const closes = (path === '/close' && body.all === false) || (path === '/key' && ['meta+w', 'control+w'].includes(String(body.key).toLowerCase()));
    if (closes) {
      await run('/tabs', { action: 'close', targetTabId: tabId });
      this.release(id, tabId);
      return { url: '', title: '', tabId, closedAll: false, daemonKeptAlive: true };
    }
    return run(path, { ...body, targetTabId: tabId });
  }
}
