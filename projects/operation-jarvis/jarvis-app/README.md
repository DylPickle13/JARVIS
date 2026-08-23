# jarvis-app

Native iOS + watchOS app for Operation JARVIS — phone and Apple Watch control
surface for the JARVIS stack on `mac-mini-64` (plugs, air purifier,
status/telemetry, service control), over LAN or Tailscale.

**Status:** **M2.1 implementation complete; dashboard removal complete; physical M3 regression gate pending** —
M0–M2 were verified on the iPhone 11; `jarvisd` now has explicit
trusted-network/token auth modes, bounded HTTP input, background single-flight
state caching, reversible LaunchAgent controls, bounded event persistence, and
daemon regression tests. The iOS app owns one scene-aware connection/polling
coordinator with idempotent desired-state writes and honest stale/unavailable
UI. Build `0.3.0 (39)` is installed and running on the allowlisted iPhone 11
and Apple Watch Series 11 from the exact audited artifacts. Build 37 retains
build 36's fixed-editor fullscreen
Pi renderer, one-line wheel behavior, cursor correction, full-screen Watch
shell, 11-point readable transcript, 9-point pannable Raw grid, pinned input
rail, and on-demand six-key palette. Its dock is now **Keys / Input / Send**:
Input opens watchOS system keyboard/dictation and inserts reviewed text at Pi's
cursor without Return; only Send emits Return. Build 38 replaces the legacy
WatchKit input controller—which could default directly to dictation—with public
watchOS `TextFieldLink`, opening the keyboard surface first while retaining its
microphone option and the same no-Return staging semantics. Build 39 mirrors
tmux's exact ANSI-styled grid—including Pi thinking, tool-call backgrounds,
assistant output, dividers, cursor inversion, and token/footer colors—rather
than inferring Pi features. Codex quota accents now use a consistent electric-
blue theme on iPhone and Watch. Its focused Digital Crown moves a local read-only
viewport through 160 captured tmux-history rows, never sends terminal input,
and passed simulator scroll interaction in both directions. Build 39 also adds
the host-only bare **“Hey JARVIS”** conversational App Intent: Siri requests one
prompt, target-local Keychain configuration preflights the shared authenticated
and certificate-pinned terminal client, then one normalized prompt is attempted
with `appendReturn=true` and no POST retry. Build 37 also adds sanitized,
read-only Codex weekly quota, reset, plan, five-hour status, and credit telemetry
from `projects/quotas` to iPhone Home and the Watch System page. Build 34 adds Watch terminal failover from the saved LAN endpoint to
stable Tailscale MagicDNS and the current Tailscale address, fits every tmux row
onto one clipped Watch display row, and restores held-Backspace repeat for the
iPhone SwiftTerm keyboard. Build 33 makes the Watch terminal the first of
exactly three vertical pages, followed by Plugs and System, with no launcher
button. Build 32 introduced the native Watch JARVIS terminal backed by a
separate certificate-pinned HTTPS bridge on TCP `8792`. It renders and controls
the same persistent `jarvis-ios` tmux pane, accepts Watch keyboard/Scribble/
dictation input, and remains separate from `jarvisd`. Build 39 makes Digital
Crown and touch scrolling local/read-only instead of injecting remote mouse
bytes. Build 31 retains build 30's scroll speed while pacing
wheel input on 60 Hz display frames for burst-free movement, and renames the Pi
tab to JARVIS. Build 30 ends the compact key deck at the Down arrow and slows
touch scrolling by 60%. Build 29 maps vertical touch drags to Pi's fullscreen
wheel scrolling instead of text selection and replaces the dedicated Control-C
key with a slash key. Build 28 performs a one-time migration to an 18-point
starting zoom, then preserves later pinch changes. Build 27 removed the explicit
Pi session display name while retaining SwiftTerm, SwiftNIO SSH, and the
persistent isolated tmux session on this Mac. It preserves build 18's Events
cleanup, build 19's foreground refresh, and build 23's exact “Hey JARVIS” plug
phrases. Physical Watch validation confirms authenticated pinned-HTTPS frames,
one shared Pi pane during simultaneous iPhone attachment, and automatic bridge-
restart recovery without recreating tmux. Owner typing, dictation, key-deck,
Crown, touch, and build-34 off-LAN acceptance remain open. Build-37 staged-input/
explicit-Send behavior and physical Codex quota rendering remain owner
acceptance gates. Build-39 physical Crown/ANSI rendering and bare-phrase Siri
routing remain acceptance gates. The three-slot Smart
Stack launcher artwork now passes physical review. Physical consoles
reached `reachable=true` and acknowledged repeated iPhone-to-Watch state
delivery. Cellular/Tailscale cold launch and relaunch also pass. Build 9 removed
weather, reordered Home, and removed the System tab. Build 10 adds read-only
Discord bot and scheduler status plus a sanitized dynamic scheduled-job
inventory. Build 11 replaced the widget catalogue; all four widgets appeared in
the signed physical iPhone gallery and the launcher deep link passed. That gate
exposed a completed-result cache bug after a plug interaction. Build 12 removes
that stale replay, applies confirmed command state immediately, renders pending
feedback, and suppresses repeated same-state taps. Its signed iPhone round trip
passed with exactly one event pair in each direction and the initial state
restored. The Watch gallery then exposed four selected-plug presets and a
two-item grid. Build 13 is the local correction: one editable selected-plug
entry and an all-four 2×2 Watch grid. The physical Watch gallery, editing,
launcher, grid, read-only purifier, and plug-control feedback now pass. Four
intentional alternating Watch widget writes each produced one POST/event pair
and left the lamp restored off. Watch-originated app relay, offline, remaining
accessory-family, live path-change, and accessibility rows remain open. Build 14
is installed on the Watch and adds the branded full-colour launcher widget.
Build 15 is the installed aesthetic candidate: the Watch app now uses a
three-page holographic overview, 2×2 plug control deck, and system/air-quality
page; the iPhone app adds the matching system-pulse header, device-specific plug
cards, air-quality gauge, collapsed runtime sections, event cards, and branded
Settings presentation. Physical review found a blank Open JARVIS Watch launcher
image. Build 16 gives the circular image an explicit proposed frame, forces the
asset to original/full-colour rendering, resolves it from the extension bundle,
and reloads its static timeline whenever the Watch host launches. Physical
review showed that the three-slot Combination widget can use a non-full-colour
rendering mode. Build 17 now branches on `widgetRenderingMode`, uses exact
100×100 Watch-scale full-colour and high-contrast accented assets, explicitly
sizes the circular slot with `GeometryReader`, and advances the launcher kind to
clear the old cached rendition. The re-added physical widget displays the
JARVIS logo successfully. Build 18 deletes `EventsView`, removes its tab and
deep-link route, and strips its AppState UI/polling state. The backend event
audit contract remains intact. Build 19 refreshes both hosts immediately on
activation and every 15 seconds while visible, cancels polling when inactive,
and replaces normal refresh buttons with automatic status plus failure-only
retry on Watch. Build 20 added Turn On JARVIS Plug and Turn Off JARVIS Plug
to Siri/Shortcuts; build 39 adds the separate conversational prompt intent. Build 23 makes their sole spoken form “Hey JARVIS, turn
on/off [the] [plug]” and keeps upgrade-time parameter publication reliable.
Build 24 changes iPhone navigation to Home, Pi, and Settings. The terminal tab opens
an authentic 24-bit terminal and connects directly to macOS SSH. Build 25 moves
first-create/reconnect into `scripts/jarvis-mobile-terminal.sh`, which creates
`jarvis-ios` detached before attaching and supplies Homebrew's path to Pi's Node
launcher under macOS's minimal remote-command environment. Build 26 starts with
the keyboard closed, pins an always-visible keyboard toggle beside the
scrolling key deck, supports tap-to-open and down-swipe dismissal, and prevents
shortcut keys from reopening a deliberately hidden keyboard. Build 27 launches
plain `pi` without a `--name` display-label override. Build 28 recognizes the
legacy saved zoom that masked build 27's fresh default, migrates it once to 18
points, and preserves later pinch zoom within the 9–20-point range. Build 29
disables touch-selection gestures, converts vertical drags to SGR wheel events
for Pi's application-owned viewport, and changes the dedicated Control-C key to
`/`; Ctrl-C remains available through latched Ctrl or a hardware keyboard.
Build 30 removes Left, Right, Shift-Return, Option-Return, Pi-menu, and Paste
buttons so the key deck ends at Down, while retaining the fixed keyboard toggle.
It raises the wheel threshold from 18 to 45 points at default zoom for a 60%
scroll-speed reduction. Build 31 preserves that distance mapping, caps pending
steps, and emits at most one wheel step per 60 Hz display frame instead of
bursting multiple terminal redraws together. The terminal tab is now labeled
JARVIS. Siri's plug parameter is populated from current `jarvisd` state rather
than a compiled list; the generic widget action is not discoverable.

Installed, signed, and audited build-39 artifacts:
`/tmp/JARVIS-build39-ansi-mirror-crown-siri.xcarchive` and
`/tmp/JARVIS-build39-ansi-mirror-crown-siri-export/JARVIS.ipa` (SHA-256
`a6fad3b0836e21b4dd352b9562832c218b24b3708a1f23339bfde1fdb2be1c8e`).

Superseded build-38 artifacts: `/tmp/JARVIS-build38-keyboard-first-watch-input.xcarchive`
and `/tmp/JARVIS-build38-keyboard-first-watch-input-export/JARVIS.ipa`
(SHA-256 `c38d6e7bbc53a2708230a4107e0d25c946b76fb51d70e7e2740d9468c05d4350`).

Superseded installed build-37 artifacts: `/tmp/JARVIS-build37-staged-input-codex-quota.xcarchive`
and `/tmp/JARVIS-build37-staged-input-codex-quota-export/JARVIS.ipa`
(SHA-256 `769d78d519303e6e11c312596f2fb8d26f4a66bb91713059e5aec3af79a19fa6`).

Superseded installed build-36 artifacts: `/tmp/JARVIS-build36-readable-watch-dictation.xcarchive`
and `/tmp/JARVIS-build36-readable-watch-dictation-export/JARVIS.ipa`
(SHA-256 `3430df1569a1befa3acc58f430a344235490e1c7ad4fbc49a4303889ff66b9d6`).

Superseded build-35 artifacts: `/tmp/JARVIS-build35-terminal-scroll-watch-fullscreen.xcarchive`
and `/tmp/JARVIS-build35-terminal-scroll-watch-fullscreen-export/JARVIS.ipa`
(SHA-256 `6c8d733ae1e9dfa3049e19f72fd1c34809be65aadf326e3eef68d7160763711a`).
Build 35 was not physically deployed; build 36 supersedes it.

Build-32 artifacts: `/tmp/JARVIS-build32-watch-terminal.xcarchive` and
`/tmp/JARVIS-build32-watch-terminal-export/JARVIS.ipa` (SHA-256
`26037a06fdb67f751cbbcb7c10e0d3389dbe5e32e901cffc86d53ae4c521f477`).

**v5 note:** the app is the native Apple client for Operation JARVIS. Its
backend is the small `jarvisd` daemon in this folder, which remains the only
hardware/status/service API control plane. The iPhone JARVIS tab uses a separate
SSH terminal data plane; the Watch reaches that same tmux pane through the
independent token- and certificate-protected `jarvis-terminald` HTTPS bridge.
APNs push + Live Activities are out (free Apple ID can't do
APNs); oMLX is out of app scope entirely. The widget catalogue is Open JARVIS,
JARVIS Plug, JARVIS Plug Grid, and read-only Air Purifier.

**Everything lives in this folder** — the Swift app targets, shared
`JARVISKit` package, `jarvisd`, and `jarvis-terminald` are all under
`jarvis-app/` so the whole project is self-contained.

## Read first

- [`docs/README.md`](docs/README.md) — the single architecture, security,
  packaging, deployment, widget, physical-validation, recovery, and release
  reference for the app.

## Scope (v5, approved)

- **In:** smart plugs, air purifier, status and telemetry (Pi session count,
  network, uptime, Discord bot, room audio, scheduler, and scheduled jobs),
  service start/stop/restart (room-audio server), launcher,
  configurable plug, plug-grid, and purifier-status widgets on iPhone and Watch,
  Siri/Shortcuts via App Intents, the iPhone SSH-backed Pi terminal, and the
  foreground-only Watch view of that same persistent terminal over the private
  HTTPS bridge, with LAN and Tailscale remote access.
- **Out:** Cast (all TV/speaker control), Spotify, camera, in-app voice/wake
  word, Raspberry Pi room endpoint, Discord bot/scheduler process mutation and
  scheduled-job mutation in the read-only first release, **APNs push
  + Live Activities** (paid-account only), **oMLX** (nothing), room-display
  HUD, phone-voice PWA.

## Devices & distribution

- iPhone 11 (iOS 26) + Apple Watch Series 11 46 mm (watchOS 26).
- Free Apple ID (no $99 yet): 7-day provisioning expiry, refreshed with
  `scripts/redeploy-jarvis-app.sh` (added in M0).
- Simulator validation is restricted to exactly one iPhone 11 and one Apple
  Watch Series 11 (46mm) device; physical devices remain the release gate.

## Branding

- App name: **JARVIS**
- Accent: **light blue / holographic blue** (exact value set in M0)
- Icon: generated from `../jarvis-icon.png` for both opaque iOS and watchOS
  app-icon catalogs

## What's working now (M2/M2.1 + M3 foundations)

- **`jarvisd` daemon** — running under launchd (`com.operation-jarvis.jarvisd`)
  with a resurrector watchdog. Explicit `JARVISD_AUTH_MODE=trusted-network`
  (default, configured LAN/Tailscale CIDRs) or `token` mode protects the API;
  `JARVISD_EVENT_TOKEN` is scoped to event ingestion. Verified: `/health`,
  `/api/v1/state` (plugs, purifier, Pi count, network, uptime),
  `/api/v1/command` (allowlisted, rejects cast), `/api/jarvis/events` ingest,
  `/api/v1/events`, `/api/v1/services` (server-allowlisted lifecycle actions),
  and `/api/v1/scheduled-jobs` (sanitized read-only inventory).
- **iOS app — navigation** — 3-tab shell (Home / JARVIS / Settings). Home shows:
  connection header (LAN vs Tailscale + IP), Pi session
  count, a **2-column plug grid**, then the **air purifier** (power switch +
  Auto/Manual/Sleep/Pet segmented control + fan 1–4 slider). Weather and its
  external data collection are removed. At the bottom, Home lists the Discord
  bot, room-audio server, scheduler, dynamic scheduled jobs, and protected
  `jarvisd` information. Only server-allowlisted service actions are rendered;
  the new Discord and scheduler cards are read-only. Plug controls send
  desired-state `plug-on`/`plug-off`
  commands, serialize per resource, and show busy/error/unavailable states.
- **Event audit backend** — the bounded `/api/v1/events` API and single
  `/api/jarvis/events` ingest sink remain available to operational tooling, but
  the native iPhone client no longer displays or polls an Events feed.
- **iOS app — lifecycle** — health-first discovery is owned by the scene
  lifecycle, retries with backoff after transport failures, observes network
  path changes, refreshes Home immediately and every 15 seconds, and cancels
  polling in Settings or the background. Pull-to-refresh remains an optional
  fallback. Polling also stops while JARVIS is selected. `jarvisd` state reads are
  cached, so warm snapshots return in milliseconds.
- **iOS app — Pi terminal** — SwiftTerm renders the real Pi TUI while SwiftNIO
  SSH carries a password-authenticated PTY to this Mac. First use confirms and
  remembers the SSH host key; the password is kept in target-local Keychain.
  An isolated `jarvis-mobile` tmux server creates or attaches `jarvis-ios`, so
  Pi survives tab changes, app backgrounding, termination, and reconnection.
  Build 37 retains build 36's Pi fullscreen TUI presentation,
  fixes wheel routing to the input cursor, limits tmux's fallback to one line,
  and hides the remote hardware cursor while retaining Pi's software cursor in
  the fixed editor. The compact key deck exposes Escape, Ctrl, Tab, slash, Up, and Down. A fixed trailing button
  always shows or hides the keyboard; the terminal also supports tap-to-open
  and downward-swipe dismissal without letting shortcut keys reopen it. A fresh
  install starts at 18 points, pinch persists intentional zoom, and landscape
  is enabled.
- **watchOS app** — builds for Apple Watch Series 11 (46mm), uses real
  `WCSessionDelegate` reachability callbacks, refreshes immediately on
  activation and every 15 seconds while visible, cancels work when inactive,
  and supports direct/relay/cache plug controls. The normal refresh control is
  gone; Retry appears only after failure. The app is embedded in the iPhone
  bundle under `Watch/`. The corrected
  parent registration plus developer Watch install produces
  `isWatchAppInstalled=true` and `isCompanionAppInstalled=true` under free
  provisioning; the final physical reachability/relay matrix remains open.
  Build 33 places the foreground terminal directly on page one, followed by
  Plugs and System for exactly three vertical pages. It uses pinned HTTPS
  snapshots instead of direct SSH, stores its token in Watch-local Keychain,
  supports system text entry plus Esc/Ctrl/Tab/slash/Up/Down, and cancels
  polling when inactive. Build 34 adds LAN-to-Tailscale route failover and a
  fitted one-tmux-row-per-display-row renderer. Build 36 adds build 35's
  status-bar-free custom pager, reclaims the bottom inset, wraps output in an
  11-point Read mode, preserves a pannable 9-point Raw grid, and pins the cursor
  row. Build 37 replaces duplicate Type/Speak actions with a compact
  Keys/Input/Send dock. Input uses WatchKit's public system text controller for
  keyboard or dictation and inserts bytes with `appendReturn=false`; the
  separate Send action emits exactly `0x0d`. Build 38 uses keyboard-first
  `TextFieldLink` instead of the legacy controller that could open directly in
  dictation; microphone entry remains available in the system keyboard. The
  prompt rail is the final review surface, disconnected input remains disabled
  and unqueued, and no text-input completion can execute a command. Build 37 also replaces the System page's
  connection-source panel with a Codex quota ring and adds the same tracker to
  iPhone Home. `jarvisd` runs the quotas project's fixed read-only
  `codex --json` command every five minutes, publishes only sanitized quota fields,
  retains the last good value on provider failure, and excludes quota failure
  from global hardware-state staleness. The Watch still uses an underscored
  status-bar modifier that requires physical regression after OS/Xcode updates.
- **Siri plug control** — the iPhone and Watch hosts advertise exactly two
  dynamic App Shortcuts. Their only phrases are “Hey JARVIS, turn on/off [the]
  [plug]” plus parameterless “a plug” forms that ask which plug. Invoke the
  complete phrase as “Hey Siri, hey JARVIS, turn on/off the [plug].” No “with
  JARVIS”, “Use JARVIS”, or contact-directed “Tell JARVIS” fallback is
  advertised. A target-local schema/catalogue signature republishes parameter
  phrases after an upgrade even when cached plug IDs are unchanged. Runtime
  entities are derived from the current daemon plug map. Writes require fresh
  exact state, skip an already-satisfied request, use only `plug-on`/`plug-off`,
  and confirm the result. Watch uses direct access first and an immediate
  correlated iPhone relay second; it never queues a Siri write after timeout.
- **M3 widget foundations** — each embedded WidgetKit extension publishes four
  focused widgets: Open JARVIS, configurable JARVIS Plug, JARVIS Plug Grid, and
  read-only Air Purifier. Plug controls use typed desired-state App Intents;
  stale/unknown state blocks writes. Fifteen-minute timelines share a short
  single-flight direct-daemon refresh. The Personal Team profile cannot provide
  App Groups or shared widget credentials, so widgets do not claim shared
  cache/token or phone-relay support. Signed physical gallery and representative
  command validation pass; stale/offline and remaining accessory-family rows are
  tracked in the unified documentation.
- **`JARVISKit`** — shared package with `JarvisClient` (incl. `discover`),
  `StateSnapshot` models, `EndpointStore` (Keychain), `WatchBridge`; mocked
  networking tests pass, while live integration tests are explicit opt-in.
- **`scripts/redeploy-jarvis-app.sh`** — deterministic one-command build +
  CoreDevice install for iPhone-only development (free Apple ID, 7-day
  auto-provisioning), with current-build output and embedded-watch
  verification. CoreDevice sets a skip-Watch-install flag; use the companion
  runbook's IPA/`ideviceinstaller` flow when registration or transfer is under
  test.
- **`scripts/redeploy-jarvis-watch.sh`** — deterministic watchOS device build +
  install for an available paired physical Watch, with a clear CoreDevice
  availability check.
- **`scripts/verify-jarvis-app.sh`** — daemon tests, package tests, plist/shell
  checks, and iOS/watchOS simulator builds; live tests are opt-in.

## Layout (current)

```text
jarvis-app/
├── README.md                   # this file
├── project.yml                 # xcodegen spec (regenerates JARVIS.xcodeproj)
├── JARVIS.xcodeproj            # generated (do not hand-edit)
├── docs/README.md              # unified architecture and operations guide
├── scripts/
│   └── redeploy-jarvis-app.sh  # one-command device build + install
├── jarvisd/                    # Python hardware/status/service daemon (port 8790)
│   ├── jarvisd.py              #   HTTP server + cached state coordinator
│   ├── tests/                  #   auth, input, cache, event, service tests
│   ├── services.json           #   launchctl service registry
│   ├── resurrector.sh          #   watchdog (keeps jarvisd alive)
│   └── launchd/                #   LaunchAgent plists (jarvisd + resurrector)
├── terminald/                  # authenticated Watch terminal bridge (port 8792)
│   ├── jarvis_terminald.py     #   tmux snapshots + bounded byte input
│   ├── tests/                  #   auth/frame/input/provisioning unit tests
│   └── launchd/                #   separate LaunchAgent
├── JARVISKit/                  # shared Swift package (client, models, watch bridge)
│   ├── Package.swift
│   ├── Sources/JARVISKit/      #   Models, JarvisClient, EndpointStore, WatchBridge
│   └── Tests/JARVISKitTests/   #   unit + live integration tests
├── JARVIS/                     # iOS app target (SwiftUI)
│   ├── JARVISApp.swift         #   @main + Home/Pi/Settings tab shell
│   ├── AppState.swift          #   connection + state + command model
│   ├── AppStateWatchBridge.swift
│   ├── Info.plist              #   scoped local/Tailscale ATS policy
│   ├── PrivacyInfo.xcprivacy
│   ├── Assets.xcassets/        #   icon + accent color
│   ├── Terminal/               #   SwiftTerm + SwiftNIO SSH + Pi key deck
│   └── Views/
│       ├── HomeView.swift      #   Pi telemetry, plugs, purifier, services + daemon info
│       ├── SettingsView.swift  #   connection management + about
│       └── Components.swift    #   badge, card, formatting helpers
├── JARVISWatch/                # watchOS app target
│   ├── JARVISWatchApp.swift
│   ├── Info.plist              #   ATS exception
│   └── Views/WatchConnectView.swift
├── SharedAppIntents/           # compiled into all four host/extension targets
├── JARVISWidget/               # four iOS WidgetKit widgets
└── JARVISWatchWidget/          # four watchOS widgets/complications
```

## Backend dependency

`jarvisd` — Python daemon in `jarvis-app/jarvisd/` (port 8790, LaunchAgent +
resurrector): auth, cached `/api/v1/state`, `/api/v1/command` (allowlisted →
`jarvis-cli`), `/api/v1/events`, `/api/jarvis/events` ingest (existing
jarvis-cli contract), `/api/v1/services` (start/stop/restart), and sanitized
`/api/v1/scheduled-jobs`. Full contract and operating procedure:
[`docs/README.md`](docs/README.md). Tailscale on the Mac is transport-only.

### Security configuration

The default `JARVISD_AUTH_MODE=trusted-network` accepts only the configured
LAN/Tailscale CIDRs and preserves zero-tap app access. For strict token mode,
set `JARVISD_AUTH_MODE=token` and provide `JARVIS_API_TOKEN`; missing/wrong
app tokens are rejected. `JARVISD_EVENT_TOKEN` is scoped to
`POST /api/jarvis/events` and cannot control
commands or services. Configure `JARVISD_TRUSTED_CIDRS` when the home subnet
changes. Do not put tokens in the repository.
