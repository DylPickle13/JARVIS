# Background-only automatic reconnect extension

**Status: v2 installed with sir's approval on 2026-10-03; supervised live checks passed.**
Build: `~/.jarvis/browser-background-extension-v2` (`0.4.0-jarvis-background-2`).
Native host registered in Chrome's user-level `NativeMessagingHosts` directory;
private socket live at `~/.jarvis/browser-native/control.sock`. Same profile,
extension ID and existing token preserved; only the bridge was restarted.
Seven forced reconnects, two bridge-restart recoveries and full interaction tests
passed with unchanged sampled foreground and both displays' active Spaces.
62 offline checks passed (43 Node, 19 Python). Sir confirmed the final tests
stayed invisible on 2026-10-03, completing acceptance. This is not an absolute
no-switch guarantee.

Stock fallback remains guarded; native reconnects are automatic. The original
v1 directory is retained but is not loaded; do not reload that failed candidate.

## Design

The official Playwright 0.4.0 worker calls both `tabs.update(active:true)` and
`windows.update(focused:true)` during every connection. The local relay cannot
undo that without a visible switch. The local build removes that exact operation.
It also avoids AppleScript tab creation and focus restoration entirely:

1. The patched worker keeps a `chrome.runtime.connectNative` pipe to a small local
   Python host. Reopening this pipe never launches or activates Chrome.
2. The host exposes a **0700 directory / 0600 Unix socket**, not a TCP port. It
   accepts only a fixed connection request, bound to the recorded window ID,
   existing extension token, protocol 2, JARVIS client, and a loopback WS relay.
   A per-host lock prevents another profile from replacing a live socket.
3. The launcher sends the fresh URL over that pipe. The worker creates one
   **inactive tab in that exact existing window**. It never creates windows,
   calls a focus API, changes Spaces, or falls back to the current window.
4. The official connection UI still validates its existing authentication token.
   The worker establishes the same Playwright protocol, without focusing Chrome.
   New groups explicitly use the selected tab's original window ID. Membership
   checks reject tabs that moved out; default `tabs.group` creation otherwise
   moves the connection tab into the foreground window. This was caught by the
   first live test; the v2 worker and attachment-callback regressions fix it.
5. The launcher atomically publishes the new tab identity with
   `connectionMode: jarvis-background-native-v1` and no prior-focus restoration.
   Native-mode backend verification uses authenticated relay inventory rather
   than AppleEvents. Tab inventory, leases, old-anchor cleanup and page state
   retention continue through the existing bridge.

Missing socket/extension/window fails closed. A sent native request with an
uncertain outcome is not replayed or downgraded to AppleScript. Closing Chrome or
its automation window still requires manually restoring a separate-Space window;
**this does not implement automatic macOS Space placement or Chrome cold start**.
Ordinary same-window transport reconnects are the target of this candidate.

## Provenance and permissions

`build.py` verifies the **exact SHA256** of the reviewed Google Chrome Web Store
CRX3 (Playwright Extension 0.4.0) and original worker. It is an artifact pin, not an
independent CRX signature verifier. The public download used for review:

https://clients2.google.com/service/update2/crx?response=redirect&prodversion=146.0.0.0&acceptformat=crx3&x=id%3Dmmlmfjhmonkocbjadbfplnigmagldckm%26uc

- CRX SHA256: `e012b45f6170f627d275588ca1a37dffe5919c2635bbac512f11b74930e63835`
- Upstream worker SHA256: `e77f9014417f5107332b80b8f5d4cfce2d83a7e269a85b0aa771576e045737ac`
- `upstream-background-0.4.0.mjs` is the exact Apache-2.0 worker used as an offline
  test fixture. Copyright notices and license are retained. Focus and grouping
  transformations both require exact reviewed source anchors.
- The manifest explicitly labels this a **local JARVIS adaptation, not an official
  Microsoft release**. Same public key/extension ID retained for bridge and origin
  compatibility. It replaced the official extension through Chrome's Load unpacked UI; it is not
  a second profile. No manual profile-file edits or extension-storage reset occurred.
- Additional permission: **`nativeMessaging`** (talk to this local helper).
  No additional website host permissions; no policy, no Chrome launch flags,
  no OS security settings, and no website-cookie/profile migration.
- This is an unpacked developer build. Automatic upstream updates are intentionally
  absent; new versions require a new reviewed artifact pin and tests.

## Build and offline verification (no browser access)

```sh
# Downloaded/reviewed CRX is currently cached under .pi/runtime (not committed).
python3 .pi/extensions/50-browser/background-extension/build.py \
  --crx .pi/runtime/browser-extension-review/official.crx \
  --output .pi/runtime/browser-extension-review/background-only
npm --prefix .pi/extensions/50-browser test
```

Build refuses an existing output directory, rather than overwriting a potentially
installed extension. It only produces files: **no installation, native-host
registration, daemon restart, Chrome invocation, or authorization grant**.
`native-host-manifest.json` inside the build is a staged manifest, not registered.
Its absolute paths are specific to the output location; do not move an installed
build without rebuilding/reviewing the manifest.

Tests execute the actual transformed worker with mocked Chrome APIs: twenty
fresh handshakes, inactive creation, no focus/window-creation calls, missing/wrong
windows, invalid URLs/relay hosts, duplicate/uncertain requests, and native pipe
loss. Python tests exercise real OS native framing and Unix sockets against a
simulated extension, token/window checks, a competing-host lock, EOF cleanup,
atomic launcher identity publication and no foreground fallback. These are **not
live macOS/Chrome focus or Space tests**.

## Installation requires sir's approval and a maintenance window

Do not install while sir works. Replacing/reloading the extension disrupts its
current debugger connection; other Pi browser clients must be paused first.

1. Build to a permanent directory (e.g. `~/.jarvis/browser-background-extension`)
   using the reviewed CRX and inspect its build receipt and manifest.
2. With approval, register that build's `native-host-manifest.json` as
   `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.jarvis.browser_background.json`.
   Back up any existing entry; never silently replace another registration.
3. In the **same signed-in Chrome profile**, load the unpacked build through
   `chrome://extensions` developer mode. Because it retains the official ID,
   Chrome may require explicitly replacing/removing the Web Store extension.
   Confirm that step with sir rather than manipulating Chrome's profile files.
   Website cookies/logins remain in the same profile. Extension-local token
   storage may reset; if so, configure the new extension token using the existing
   secure setup process, never logs/chat.
4. Confirm the dedicated automation window still exists on Desktop 2 and its
   recorded ID is correct. Do not adopt a personal window or make a replacement
   on Desktop 1. Restart **only the bridge**, with approval, to load native-mode
   verification; Chrome itself should not need a restart.
5. Verify the native socket is present. Run one supervised connect, the full
   fixture/focus test, repeated forced reconnects and daemon-restart recovery.
   Require unchanged foreground app/window/tab and user confirmation of no Space
   switching. If anything changes, stop; do not call this production-proven.
6. Only after verification update the operational docs/memory from staged to live.

Installation receipt/token backup is under
`~/.jarvis/browser-background-install/20261003T142126/`; do not print its token.

**Test stimulus caveat:** AppleScript `set URL of t to URL of t` performs a
browser-initiated navigation with a user gesture and shows the window. The old
stress fixture therefore caused a Space switch independently of native creation.
Use the actual `reload t` command for forced reconnects, and
`JARVIS_TEST_BACKGROUND_RECOVERY=1` for focus-monitored bridge restarts. Keep
`chrome://extensions` setup tabs out of automation-window inventory; those
privileged Chrome pages cannot be debugger-controlled.

Rollback (also supervised): disable the local build, restore the official Web Store
extension in the same profile and its token configuration, then unregister only
this native host. The launcher will again block fresh stock handshakes by default.
No website profiles or browsing data should be removed.
