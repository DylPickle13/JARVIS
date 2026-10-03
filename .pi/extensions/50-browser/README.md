# JARVIS browser bridge

## Reliability update (deployed; supervised live checks passed)

The backend reliability update was deployed with sir's approval on 2026-10-03
at approximately 18:20 EDT, after sir confirmed sessions 7/8 were finished.
78 offline tests passed; only the bridge was restarted. Automatic native
reconnection succeeded and all seven work-tab IDs remained present in the same
automation window. Chrome and its installed v2 extension/helper were not replaced
or restarted. No application form was filled, navigated or submitted by deployment.

See [RELIABILITY-CANDIDATE.md](RELIABILITY-CANDIDATE.md) for verified long-text
replacement, session-local failure handling, unresolved-deadline quarantine,
recovery diagnostics and rollback. Supervised live long-text, nested/page scrolling,
local-failure isolation, full interactions and two-session reconnect checks passed.
Foreground/personal-tab/Space telemetry stayed unchanged across 297 reliability,
172 interaction and 270 final reconnect samples. An earlier reconnect monitor was
invalidated by sir's reported accidental sleep; the approved awake rerun used
command-scoped sleep prevention and passed. All seven original tabs remained;
fixture tabs were cleaned up. Sir confirmed the final run stayed invisible;
acceptance is complete. These passes
are not an absolute focus guarantee or proof of the original wheel-stall cause.

## Active local setup

The authenticated localhost daemon retains the original `browser_*` HTTP interface.
The extension backend uses the reviewed local JARVIS adaptation of Microsoft's
Playwright extension in the user's normal Chrome profile, inside the
**JARVIS Browser — Automation Only** window. One connection
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
window ID**. It now refuses to create a replacement window if that ID is missing:
a replacement could open on the user's working Space. It never follows a moved
marker or a matching page title into a personal window.
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

**Background-only connection policy:** the official extension explicitly calls
`chrome.windows.update(..., {focused:true})` on a fresh handshake. Restoring focus
afterward is not isolation. The installed local build instead uses the reviewed
native path below for automatic fresh handshakes, with no focus API or AppleEvent.
If that endpoint is absent, the launcher blocks **stock handshakes by default,
before any AppleEvent**, including implicit MCP reconnects and Chrome cold starts.
Existing connections are not terminated by this guard. A denied stock launch
exits with code 3; older running relay code may show
the generic `Automation launcher failed before publishing window identity` error.
Do not retry by using stock Chrome, CDP, or a new profile to bypass this guard.

This guard is read from disk on each launch and needs no daemon/Chrome restart.
It prevents the known stock handshake focus operation; it is **not proof that
every normal action is focus-free**. The local build passed the supervised live
checks below, but polling cannot prove an absolute no-switch guarantee.
No disruptive live testing should run while sir is working.

**Spaces are manual, not enforced:** keep the existing automation window on
Desktop 2 and personal windows on Desktop 1, using the same signed-in profile.
The bridge tracks a Chrome window ID, not a macOS Space. It cannot verify or repair
Space placement, and closing/restarting Chrome invalidates that identity. Do not
assign the whole Chrome application to a Space. Never claim permanent Space
isolation or automatic silent reconnection with the stock extension.

### Stock fallback: explicit supervised reconnection only

This allowance is not needed for the installed reviewed native path. If stock
fallback is deliberately required, ask sir for a maintenance window; it **may
switch Spaces**. Verify the recorded automation window still exists and sir has
placed it on Desktop 2. Only then, using that verified numeric window ID:

```sh
python3 .pi/extensions/50-browser/launch-extension-in-automation-window.py \
  --allow-once --window-id VERIFIED_ID --acknowledge-focus-change
# Within 60 seconds, make one browser request to establish the connection.
```

The owner-only 0600 allowance in `~/.jarvis/browser-reconnect-once.json` is consumed
atomically before attempting the handshake, even if the attempt fails. It expires
after 60 seconds, is tied to the recorded window ID, and is never automatically
renewed. Remove the allowance file to cancel it before use. Missing/invalid window
identity or a closed window still fails; the launcher never creates a new one.
This is a shared bridge allowance, not a client-specific permission: pause other
browser clients during supervised setup. Rebuilding a missing window/identity is
manual maintenance, not automatic recovery.

### Silent automatic reconnect: installed local build

Installed with sir's approval on **2026-10-03**:
[`background-extension/README.md`](background-extension/README.md) documents the
reviewed `0.4.0-jarvis-background-2` build at
`~/.jarvis/browser-background-extension-v2`, and its registered native helper.
It removes the stock focus call and pins new tab groups to the automation window
(the stock grouping API otherwise defaults to the foreground window). A native
pipe creates **inactive connection tabs in the existing recorded window**, with
no AppleScript, window creation, focus restoration, or foreground fallback after
uncertain outcomes. Same profile, extension ID and existing token; the only added
permission is `nativeMessaging`. Chrome itself was not restarted.

**Supervised verification:** 62 offline checks passed (43 Node, 19 Python).
Seven automatic forced reconnects (five with personal Chrome foreground, two with
VS Code foreground), two bridge-restart recovery tests and full interaction runs
passed. Foreground app, personal window/tab and both displays' active Spaces were
unchanged in sampled telemetry. Unsaved input and Chrome tab IDs survived recovery.
Sir confirmed the final tests stayed invisible on 2026-10-03. Acceptance is
complete; no universal no-switch guarantee or automatic Space placement is claimed.

The first live build exposed and failed closed on tab-group window drift; v2 fixes
it and adds attachment-callback regression tests. An initial stress test also
switched Spaces because its AppleScript **URL setter explicitly shows Chrome**.
The corrected test uses the actual `reload` command; production reconnects do not
use either AppleScript operation. Installation's `chrome://extensions` tab was
removed before inventory tests because privileged Chrome pages are not debuggable.

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

The unit suite is non-disruptive. The live examples below are **maintenance-only**:
reconnect/restart stress tests require a supervised maintenance window and must
not be used while sir is working. Normal native reconnects are automatic; do not
grant stock allowances in test scripts. Historical results below are distinct
from the current local-build acceptance results above.

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
# Focus + per-display Space telemetry, with a personal Chrome window first:
JARVIS_TEST_RECONNECTS=5 python3 .pi/extensions/50-browser/test-extension-focus.py \
  --spaces --script test-multi-session-live.py
# Opt-in bridge restart; background-created fixture avoids foregrounding setup:
JARVIS_TEST_BACKGROUND_RECOVERY=1 python3 .pi/extensions/50-browser/test-extension-focus.py \
  --spaces --script test-window-tab-recovery.py
```

The live test uses a temporary localhost fixture and temporary upload file, not an
external account or personal tab. The focus test checks the foreground application,
Chrome window, and selected tab throughout the fixture test. `--fixture-window`
uses and removes a disposable blank non-automation window, avoiding personal tabs.
Without that option, the personal window must already be in front. A changing
sample is not by itself proof of automation theft: user-initiated app/tab changes
also fail this test. `--spaces` compiles `test-space-snapshot.swift` temporarily
and reads every display's active Space via a private macOS API (read-only,
maintenance test only, not production enforcement). Failure to read it fails the
test. `--script` selects a fixed fixture; the most recent sample report is saved
under `.pi/runtime/browser-extension-review/focus-last-report.json` with only
bundle/window/tab/Space IDs, not page content or connection tokens.
Conversely, polling can miss brief switches; neither a pass
nor restoring the final foreground state establishes an absolute no-switch guarantee.

The protocol-v2 unit suite covers independent client identities/selections,
shared inventory, interleaved actions, queue serialization, lease conflicts and
handoff, expiry, stale indexes, closed tabs, keyboard shortcuts, navigation failure,
transport fencing, lifecycle cleanup, and older-bridge rejection. The opt-in
multi-session live test creates only two localhost fixture tabs and removes them.

Historical verification before the local background extension: 32 Node browser/client/lifecycle tests,
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
