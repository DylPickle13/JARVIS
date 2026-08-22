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
UI. Signed `0.3.0 (24)` is archived and ready for Dylan's iPhone connection;
the physical iPhone and Apple Watch remain on `0.2.0 (23)` until deployment.
Build 24 adds a real Pi terminal as the middle iPhone tab using SwiftTerm,
SwiftNIO SSH, and a persistent isolated tmux session on this Mac. It preserves
build 18's Events cleanup, build 19's foreground refresh, and build 23's exact
“Hey JARVIS” plug phrases. Owner physical SSH/Pi validation remains pending. The
three-slot Smart Stack launcher artwork now passes physical review. Physical consoles
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
retry on Watch. Build 20 added only Turn On JARVIS Plug and Turn Off JARVIS Plug
to Siri/Shortcuts. Build 23 makes their sole spoken form “Hey JARVIS, turn
on/off [the] [plug]” and keeps upgrade-time parameter publication reliable.
Build 24 changes iPhone navigation to Home, Pi, and Settings. The Pi tab opens
an authentic 24-bit terminal, connects directly to macOS SSH, and creates or
reattaches the `jarvis-ios` tmux session running Pi in this repository. Their
plug parameter is populated from current `jarvisd` state rather than a compiled
list; the generic widget action is not discoverable.

Build-24 artifacts: `/tmp/JARVIS-build24-pi-terminal.xcarchive` and
`/tmp/JARVIS-build24-pi-terminal-export/JARVIS.ipa` (SHA-256
`a91d698ca710d985f2c82ea3469b14489e33ab251bc21083b12a1c95c58e47cf`).

**v5 note:** the app is the native Apple client for Operation JARVIS. Its
backend is the small `jarvisd` daemon in this folder, which remains the only
hardware/status/service API control plane. The iPhone Pi tab adds a separate,
explicit SSH terminal data plane. APNs push + Live Activities are out (free Apple ID can't do
APNs); oMLX is out of app scope entirely. The widget catalogue is Open JARVIS,
JARVIS Plug, JARVIS Plug Grid, and read-only Air Purifier.

**Everything lives in this folder** — the Swift app targets, the shared
`JARVISKit` package, *and* the `jarvisd` backend daemon are all under
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
  Siri/Shortcuts via App Intents, and the iPhone-only SSH-backed Pi terminal,
  with LAN and Tailscale remote access.
- **Out:** Cast (all TV/speaker control), Spotify, camera, in-app voice/wake
  word, Raspberry Pi room endpoint, Discord bot/scheduler process mutation and
  scheduled-job mutation in the read-only first release, **APNs push
  + Live Activities** (paid-account only), **oMLX** (nothing), room-display
  HUD, phone-voice PWA.

## Devices & distribution

- iPhone 11 (iOS 26) + Apple Watch Series 11 46 mm (watchOS 26).
- Free Apple ID (no $99 yet): 7-day provisioning expiry, refreshed with
  `scripts/redeploy-jarvis-app.sh` (added in M0).
- Simulator-first development; real-device gates at end of M0, M3, M4.

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
- **iOS app — navigation** — 3-tab shell (Home / Pi / Settings). Home shows:
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
  fallback. Polling also stops while Pi is selected. `jarvisd` state reads are
  cached, so warm snapshots return in milliseconds.
- **iOS app — Pi terminal** — SwiftTerm renders the real Pi TUI while SwiftNIO
  SSH carries a password-authenticated PTY to this Mac. First use confirms and
  remembers the SSH host key; the password is kept in target-local Keychain.
  An isolated `jarvis-mobile` tmux server creates or attaches `jarvis-ios`, so
  Pi survives tab changes, app backgrounding, termination, and reconnection.
  The compact horizontal key deck exposes Escape, Ctrl, Tab, Ctrl-C, arrows,
  Shift/Option-Return, common Pi shortcuts, paste, and keyboard dismissal.
  Pinch adjusts the terminal font and landscape is enabled.
- **watchOS app** — builds for Apple Watch Series 11 (46mm), uses real
  `WCSessionDelegate` reachability callbacks, refreshes immediately on
  activation and every 15 seconds while visible, cancels work when inactive,
  and supports direct/relay/cache plug controls. The normal refresh control is
  gone; Retry appears only after failure. The app is embedded in the iPhone
  bundle under `Watch/`. The corrected
  parent registration plus developer Watch install produces
  `isWatchAppInstalled=true` and `isCompanionAppInstalled=true` under free
  provisioning; the final physical reachability/relay matrix remains open.
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
├── jarvisd/                    # Python backend daemon (port 8790)
│   ├── jarvisd.py              #   HTTP server + cached state coordinator
│   ├── tests/                  #   auth, input, cache, event, service tests
│   ├── services.json           #   launchctl service registry
│   ├── resurrector.sh          #   watchdog (keeps jarvisd alive)
│   └── launchd/                #   LaunchAgent plists (jarvisd + resurrector)
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
