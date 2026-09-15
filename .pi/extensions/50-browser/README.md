# JARVIS browser bridge

## Active local setup

The authenticated localhost daemon retains the original `browser_*` HTTP interface.
The extension backend uses Microsoft's Playwright extension in the user's normal
Chrome profile, inside the **JARVIS Browser — Automation Only** window. One persistent connection
tab doubles as its anchor; there is no separate anchor page. It does not
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

## Window and focus isolation

`launch-extension-in-automation-window.py` finds the existing window by its anchor
title or the connection URL's `#jarvis-automation-anchor-v2` marker, or creates a
dedicated window if absent. It reuses the marked connection tab across daemon
restarts rather than accumulating connection tabs. It never logs token-bearing
URLs and records native IDs. The daemon verifies the connection tab's native ID,
window ID, official extension URL, and anchor fragment before acting. After
connection, it titles the tab and removes only our old data-page anchor in that
same window. The connection page is never adopted as a work tab.

**Pinning limitation:** the official extension uses Chrome tab groups. Pinning its
connection tab removes it from the group and disconnects automation (verified in a
live test). Keep this single anchor/connection tab **unpinned**. One-tab operation
and reuse across daemon restart passed the complete live regression suite.

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

## Implementation and safety

- `extension-browser-backend.mjs` uses the supported Playwright MCP in-process
  connection API. Its code tool is private: only fixed internal handlers run;
  the HTTP interface does not expose arbitrary JavaScript.
- Actions are serialized. A failed mutation is never automatically replayed.
- MCP transcripts are not returned or logged; only the JSON result is parsed.
  Error text redacts the token and extension connection URLs.
- Uploads read only caller-specified files, transfer their bytes to the selected
  file input, and dispatch input/change events. The extension transport cannot
  reliably use native file-path uploads. Limit: 32 MiB per call.
- `browser_close(all:true)` releases the logical tool handle but retains the
  long-lived connection, matching the original daemon's behavior.
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
python3 .pi/extensions/50-browser/test-extension-focus.py
```

The live test uses a temporary localhost fixture and temporary upload file, not an
external account or personal tab. The focus test checks the foreground application,
Chrome window, and selected personal tab throughout the fixture test. Run with the
personal window foreground (not the automation window) for a meaningful comparison.

Verified: five unit tests, live navigation/typing/empty clear/click/wait/extraction/
links/PNG/scroll/upload/tab selection/cleanup, automatic reconnection after closing
only the automation connection tab, and foreground stability across 113 samples
in the final complete live run. Dependency audit reported zero vulnerabilities.

Official extension instructions:
https://github.com/microsoft/playwright/blob/main/packages/extension/README.md
