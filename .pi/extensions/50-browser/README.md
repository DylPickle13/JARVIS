# JARVIS browser bridge

## Active local setup

The authenticated localhost daemon retains the original `browser_*` HTTP interface.
The extension backend uses Microsoft's Playwright extension in the user's normal
Chrome profile, inside the **JARVIS Browser — Automation Only** window. One connection
tab doubles as its anchor for each transport generation; reconnects replace only
that internal anchor, never the work tabs. It does not
use Chrome's remote-debugging toggle or a second user-data directory.

Local configuration (outside the repository):

- `~/.jarvis/browser-backend.json`: `{"backend":"extension"}`
- `~/.jarvis/playwright-extension.token`: user-provided extension token, mode 0600
- `~/.jarvis/extension-window.json`: current native window/connection-tab IDs and
  prior foreground information; no authentication token
- Existing `com.jarvis.browser-bridge` LaunchAgent starts at login and retains the
  local bearer-authenticated endpoint configured in `.env`.

`PI_BROWSER_BACKEND=cdp` overrides the file for rollback. Alternatively change
`browser-backend.json` to `{"backend":"cdp"}` and restart the LaunchAgent. CDP
fallback still requires Chrome's remote-debugging setting and connection approval.

## Multiple Pi sessions (protocol v2)

All Pi sessions see the same automation-window tab inventory. Each live client has
an automatically generated identity and its own **selected Chrome tab ID**. A new
session's first `browser_open` creates its own tab; it never inherits Chrome's
physically selected tab. Subsequent actions target the selected stable ID. The
single daemon queue covers inventory/lease validation, tab activation, and the
complete action, so separate workflows can interleave without crossing targets.

- `browser_tabs(action:"list")` shows every work tab, its `tabId`, controller and
  lease expiry. `activeIndex` / `selectedTabId` describe only the requesting session.
- `browser_tabs(action:"switch", tabId:123)` selects and leases that tab. Prefer
  `tabId`; legacy `index` resolves against **that session's last returned inventory**,
  not whichever tab currently occupies the global position.
- Leased tabs remain visible to everyone, but another session cannot select,
  interact with, or close them. A busy response identifies the controlling client.
- `browser_tabs(action:"release", tabId:123)` explicitly hands off a tab without
  closing it; omit `tabId` to release the current selection. Switching does not
  release other tabs, allowing a multi-tab workflow to keep its reservations.
- `browser_close(all:true)` / `/browser close`, session changes, and shutdown
  release only that client's leases. Chrome and all shared tabs remain open.
- Leases expire after **15 minutes without an action on that tab**, recovering
  crashed clients. Merely listing tabs does not renew leases. An expired/released
  selection requires an explicit switch to reacquire control; actions never
  silently steal it back. There is no automatic forced takeover or mutation replay.
- Closed/moved selected tabs produce an error, never fallback to another tab.
  Use `browser_open(newTab:true)` or explicitly select an existing tab to continue.
- In-memory session state survives a Playwright transport reset. An uncertain
  transport outcome fences subsequent actions until explicit reselection; stale
  index snapshots are cleared. After a **daemon restart**, tabs remain open but
  session selections/leases are intentionally not restored: list and reselect.
  Chrome tab IDs are not durable across a Chrome restart.

This is coordination between trusted Pi clients, not account isolation: all tabs
still share the Chrome profile's cookies/storage, and manual browser interactions
are outside the lease system. Popups and user-created automation tabs are visible
but must be selected explicitly before control.

### Upgrade

Restart the local `com.jarvis.browser-bridge` LaunchAgent, then `/reload` in each
already-running Pi session (or start new sessions). The client verifies protocol
v2 before any control request. Old clients without `X-Jarvis-Browser-Session` can
still list/status, but their control requests are rejected rather than falling
back to unsafe global selection. Session-aware clients fail closed on the legacy
CDP backend; multi-session routing currently supports the extension backend only.
The protocol identity is transport metadata, never a model-supplied tool argument.

### Silent MCP reconnect recovery

Playwright MCP can discard/recreate its internal backend without closing the MCP
client. `connected:true` alone therefore cannot establish tab ownership. Every
fixed action now rediscovers the connection anchor and reconciles tab IDs through
the verified relay inventory, even on a completely fresh Playwright context.
Absent anchors and missing/duplicate inventory IDs fail before creating tabs or
pruning leases. Regression tests cover context loss between creation and navigation.

The original failure was `New tab identity missing; refusing navigation`, followed
by apparently healthy inventories containing blank tabs without `tabId`. The
previous tests incorrectly retained the anchor while simulating context loss.
Forced reconnects reproduced a second failure: the old extension connection's
asynchronous debugger/tab-group cleanup could detach a new connection that reused
its anchor's Chrome tab ID. Reloading an anchor could also leave its old connection
alive on the work tabs. Recovery now:

1. Creates a **fresh anchor ID** in the recorded automation window. The launcher
   atomically publishes metadata, and the relay waits for the launcher to exit
   successfully before completing initialization.
2. Detects changed connection generations even when the MCP client stays open.
3. Retires only stale `JARVIS Browser` extension connections wholly contained in
   that window, excluding the current connection. Other clients or groups spanning
   another window are never disconnected. Waits for old debugger/group cleanup,
   then removes obsolete internal anchors and reconciles the existing work tabs.
4. Allows at most two retries of **connection/read-only preflight only**, preserving
   valid selected IDs and leases. Explicit missing/moved-window failures are not
   automatically retried. Once an action is dispatched—including tab creation—an
   uncertain outcome is never replayed and requires explicit reselection.

`daemon.recoveryCount` reports preflight recovery attempts. Minimal relay diagnostics
in `.pi/runtime/browser-bridge.launchd.err.log` contain only fixed event names,
numeric tab IDs and allowlisted reasons—not CDP payloads, page URLs or tokens.
`User disconnected` can mean the bridge intentionally retired its own stale group;
it does not necessarily mean the user clicked anything.

## Window and focus isolation

`launch-extension-in-automation-window.py` reuses only the **recorded native
window ID**, or creates a new dedicated window if that ID no longer exists.
It never follows a moved marker or a matching page title into a personal window.
Every handshake creates a fresh connection tab, with obsolete internal anchors
removed after safe cleanup. It never logs token-bearing URLs. The daemon verifies
the connection tab's native ID, window ID, official extension URL, and anchor
fragment before acting. Connection pages are never adopted as work tabs.

**Pinning limitation:** the official extension uses Chrome tab groups. Pinning its
connection tab removes it from the group and disconnects automation (verified in a
live test). Keep the current anchor/connection tab **unpinned**. The bridge no
longer calls pin/unpin during preparation; new anchors are unpinned by default.

Playwright's default relay creates tabs in the current window before extension
grouping moves them. `patch-playwright-background.mjs` fixes that in the pinned
package: `chrome.tabs.create` receives the verified automation `windowId`. Tabs are
selected **inside that window** for reliable rendering/input, without focusing the
window. The relay also replaces `Page.bringToFront` with a window-checked
`chrome.tabs.update(active:true)` executed in the authenticated extension connection
page. No `chrome.windows.update(focused:true)` is used for normal actions.

The patch is applied by `postinstall`, is idempotent, checks the exact Playwright
version/anchors, and is required by the backend at startup. Review it before
upgrading Playwright. Do not use `npm install --ignore-scripts` for deployment.

**Connection caveat:** the official installed extension itself explicitly focuses
Chrome on a fresh handshake. JARVIS restores the previously foreground window/app
when possible, but a brief focus change during initial connection/reconnection is
still possible. Normal navigation and interaction do not require foregrounding.
No Chrome restart or macOS reboot was forced during testing; bridge restarts and
token-authenticated reconnection were tested. Reboot/login behavior still needs a
real-world check after the user's next restart.

## Automation-window tab recovery

The bridge reconciles the live Chrome inventory **before each browser action**,
including status/list, rather than keeping only tabs created in the current
connection. Tabs already open or moved into the verified automation window are
rediscovered after reconnects. Chrome tab IDs distinguish duplicate URLs; no
navigation, reload, or form replay is used. Tabs moved out disappear from the
next inventory. Personal windows and extension connection pages are excluded.
This is on-demand reconciliation, not a continuously running inventory timer.

The pinned relay uses the authenticated anchor to query `chrome.tabs.query` with
the verified window ID and attach existing work tabs. Fixed internal evaluation
markers return relay tab identity/inventory through Playwright's existing page
transport: the extension disallows `Target.attachToBrowserTarget`, so ordinary
`newCDPSession` cannot be used. No arbitrary-code endpoint is exposed.

Chrome tab IDs survive bridge reconnects, not Chrome restarts. Recovery cannot
restore unsaved forms if Chrome itself discards/reloads/closes the underlying tab.

## Implementation and safety

- `extension-browser-backend.mjs` uses the supported Playwright MCP in-process
  connection API. Its code tool is private: only fixed internal handlers run;
  the HTTP interface does not expose arbitrary JavaScript.
- Actions and session/lease routing are serialized. A failed mutation is never automatically replayed.
- MCP transcripts are not returned or logged; only the JSON result is parsed.
  Error text redacts the token and extension connection URLs.
- Uploads read only caller-specified files, transfer their bytes to the selected
  file input, and dispatch input/change events. The extension transport cannot
  reliably use native file-path uploads. Limit: 32 MiB per call.
- `browser_close(all:true)` releases the client's leases/selection but retains
  every tab and the long-lived connection.
- The old CDP implementation remains available; no personal Chrome profile files
  or application documents are modified by this setup.

## Setup / restart / checks

```sh
cd /Users/dylanrapanan/JARVIS
npm --prefix .pi/extensions/50-browser ci
python3 .pi/extensions/50-browser/setup-extension-token.py
launchctl kickstart -k gui/$(id -u)/com.jarvis.browser-bridge
npm --prefix .pi/extensions/50-browser test
JARVIS_TEST_BROWSER_URL=http://127.0.0.1:17323 \
  python3 .pi/extensions/50-browser/test-extension-live.py
python3 .pi/extensions/50-browser/test-extension-focus.py --fixture-window
JARVIS_TEST_BROWSER_URL=http://127.0.0.1:17323 \
  python3 .pi/extensions/50-browser/test-multi-session-live.py
# Opt-in chaos test: reloads the internal anchor five times; never reloads work tabs.
JARVIS_TEST_RECONNECTS=5 JARVIS_TEST_BROWSER_URL=http://127.0.0.1:17323 \
  python3 .pi/extensions/50-browser/test-multi-session-live.py
# Opt-in: restarts the live bridge; only opens/closes its own local fixture tab.
JARVIS_TEST_BROWSER_URL=http://127.0.0.1:17323 \
  python3 .pi/extensions/50-browser/test-window-tab-recovery.py
```

The live test uses a temporary localhost fixture and temporary upload file, not an
external account or personal tab. The focus test checks the foreground application,
Chrome window, and selected tab throughout the fixture test. `--fixture-window`
uses and removes a disposable blank non-automation window, avoiding personal tabs.
Without that option, the personal window must already be in front.

The protocol-v2 unit suite covers independent client identities/selections,
shared inventory, interleaved actions, queue serialization, lease conflicts and
handoff, expiry, stale indexes, closed tabs, keyboard shortcuts, navigation failure,
transport fencing, lifecycle cleanup, and older-bridge rejection. The opt-in
multi-session live test creates only two localhost fixture tabs and removes them.

Final verification on the local bridge: 32 Node browser/client/lifecycle tests,
4 Python launcher tests, and 7 lazy-loader regression tests passed. The live soak
completed two consecutive five-reconnect cycles (10 deliberate anchor reloads),
including a bridge restart between cycles, plus both full localhost fixture runs.
After adding the atomic launcher acknowledgement, a further three forced reconnects
and another complete fixture run passed on the final deployed code.
Selected tab IDs, independent values and page contents survived every reconnect.
The external-tab recovery test separately verified unsaved input across a daemon
restart. Focus stayed unchanged across 156 samples using a disposable blank
non-automation window. Earlier failed-test fixtures were cleaned up; application
and personal tabs were not filled, submitted, navigated or closed.

Reboot/Chrome-restart behavior is not covered by these tests. Actual Chrome tab
closure, manual interference, lease expiry, or an uncertain in-flight action still
fails closed rather than redirecting or automatically replaying user input.

Earlier tab-recovery update verified: seven unit tests, an externally created automation-window
fixture discovered without navigation, and the same Chrome tab ID plus unsaved input
preserved across a live bridge restart. Existing application tabs were left untouched.
The full live fixture regression also passed after the update.

Previously verified: five unit tests, live navigation/typing/empty clear/click/wait/extraction/
links/PNG/scroll/upload/tab selection/cleanup, automatic reconnection after closing
only the automation connection tab, and foreground stability across 113 samples
in the final complete live run. Dependency audit reported zero vulnerabilities.

Official extension instructions:
https://github.com/microsoft/playwright/blob/main/packages/extension/README.md
