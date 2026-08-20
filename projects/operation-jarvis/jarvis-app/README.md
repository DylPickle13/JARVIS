# jarvis-app

Native iOS + watchOS app for Operation JARVIS — phone and Apple Watch control
surface for the JARVIS stack on `mac-mini-64` (plugs, air purifier,
status/telemetry, events, service control), over LAN or Tailscale.

**Status:** **M2.1 implementation complete; dashboard removal complete; physical M3 regression gate pending** —
M0–M2 were verified on the iPhone 11; `jarvisd` now has explicit
trusted-network/token auth modes, bounded HTTP input, background single-flight
state caching, reversible LaunchAgent controls, bounded event persistence, and
daemon regression tests. The iOS app owns one scene-aware connection/polling
coordinator with idempotent desired-state writes and honest stale/unavailable
UI. JARVIS `0.2.0 (9)` is installed on both physical devices from the verified
archive, with the final icon and both WatchConnectivity installed flags true.
Physical consoles reached `reachable=true` and acknowledged repeated
iPhone-to-Watch state delivery. Cellular/Tailscale cold launch and relaunch
also pass. Build 9 removes weather, places plugs before the air purifier, moves
services to the bottom of Home, and removes the System tab. The Watch-originated
relay-command, widget, offline, live path-change, and accessibility rows remain
outstanding.

**v5 note:** the app is the native Apple client for Operation JARVIS. Its
backend is the small `jarvisd` daemon in this folder, which is the app's only
control plane. APNs push + Live Activities are out (free Apple ID can't do
APNs); oMLX is out of app scope entirely; widgets = plug grid only for now.

**Everything lives in this folder** — the Swift app targets, the shared
`JARVISKit` package, *and* the `jarvisd` backend daemon are all under
`jarvis-app/` so the whole project is self-contained.

## Read first

- [`docs/watch-companion-packaging-deployment-and-recovery-2026-08-20.md`](docs/watch-companion-packaging-deployment-and-recovery-2026-08-20.md)
  — operational Watch companion packaging, non-skipping installation,
  diagnostics, and non-destructive recovery runbook. Read this before any
  physical Watch deployment or WatchConnectivity investigation.
- [`docs/ios-watchos-app-research-2026-07-09.md`](docs/ios-watchos-app-research-2026-07-09.md)
  — historical research and architecture record (not an operational runbook).
- [`docs/post-deployment-next-steps-2026-08-20.md`](docs/post-deployment-next-steps-2026-08-20.md)
  — prioritized physical gates, verification, commit strategy, and path to M4.

## Scope (v5, approved)

- **In:** smart plugs, air purifier, status and telemetry (Pi session count,
  network, uptime), events feed, service start/stop/restart (room-audio server),
  plug-grid widgets (iOS home + lock-screen),
  watch interactive plug complication), Siri/Shortcuts via App Intents,
  Tailscale remote access.
- **Out:** Cast (all TV/speaker control), Spotify, camera, in-app voice/wake
  word, Raspberry Pi room endpoint, Discord bot process control, **APNs push
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
  `/api/v1/events`, `/api/v1/services` (status/start/stop/restart).
- **iOS app — Home screen** — 3-tab shell (Home / Events / Settings). Home
  shows: connection header (LAN vs Tailscale + IP), Pi session
  count, a **2-column plug grid**, then the **air purifier** (power switch +
  Auto/Manual/Sleep/Pet segmented control + fan 1–4 slider). Weather and its
  external data collection are removed. At the bottom, Home lists registered
  services and `jarvisd` information with **Stop** (confirmation), **Restart**,
  and **Start** controls. Plug controls send desired-state `plug-on`/`plug-off`
  commands, serialize per resource, and show busy/error/unavailable states.
- **iOS app — Events (M2)** — live activity feed from `/api/v1/events`: one row
  per event (✓/✗/○ status glyph, action, summary, relative time), newest-first,
  auto-polls every 5 s + pull-to-refresh. The event bridge in `jarvis.py` posts
  to jarvisd directly through the single event-ingest sink.
- **iOS app — M2.1 lifecycle** — health-first discovery is owned by the scene
  lifecycle, retries with backoff after transport failures, observes network
  path changes, cancels background polling, and polls only the selected tab.
  `jarvisd` state reads are cached, so warm snapshots return in milliseconds.
- **watchOS app** — builds for Apple Watch Series 11 (46mm), uses real
  `WCSessionDelegate` reachability callbacks, supports direct/relay/cache plug
  controls, and is embedded in the iPhone bundle under `Watch/`. The corrected
  parent registration plus developer Watch install produces
  `isWatchAppInstalled=true` and `isCompanionAppInstalled=true` under free
  provisioning; the final physical reachability/relay matrix remains open.
- **M3 widget foundations** — iOS plug-grid and watch selected-plug WidgetKit
  extensions are embedded, use typed desired-state App Intents, stale rendering,
  and `SnapshotStore` caching. The Personal Team profile cannot provide App
  Groups or shared widget credentials, so widgets use a bounded direct-daemon
  trusted-network fallback; they do not claim shared cache/token or phone relay
  support. The consolidated physical widget/Watch matrix remains outstanding.
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
├── docs/                       # research & plan (v5)
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
│   ├── JARVISApp.swift         #   @main + 3-tab shell
│   ├── AppState.swift          #   connection + state + command model
│   ├── AppStateWatchBridge.swift
│   ├── Info.plist              #   scoped local/Tailscale ATS policy
│   ├── PrivacyInfo.xcprivacy
│   ├── Assets.xcassets/        #   icon + accent color
│   └── Views/
│       ├── HomeView.swift      #   Pi, plugs, purifier, services + daemon info
│       ├── EventsView.swift    #   M2 live event feed (5 s poll + pull-to-refresh)
│       ├── SettingsView.swift  #   connection management + about
│       └── Components.swift    #   badge, card, formatting helpers
├── JARVISWatch/                # watchOS app target
│   ├── JARVISWatchApp.swift
│   ├── Info.plist              #   ATS exception
│   └── Views/WatchConnectView.swift
├── JARVISWidget/               # iOS WidgetKit plug grid + App Intent
│   └── JARVISWidget.entitlements
└── JARVISWatchWidget/          # watchOS WidgetKit plug complication
```

## Backend dependency

`jarvisd` — Python daemon in `jarvis-app/jarvisd/` (port 8790, LaunchAgent +
resurrector): auth, cached `/api/v1/state`, `/api/v1/command` (allowlisted →
`jarvis-cli`), `/api/v1/events`, `/api/jarvis/events` ingest (existing
jarvis-cli contract), `/api/v1/services` (start/stop/restart). Full spec:
research doc §6. Tailscale on the Mac is transport-only.

### Security configuration

The default `JARVISD_AUTH_MODE=trusted-network` accepts only the configured
LAN/Tailscale CIDRs and preserves zero-tap app access. For strict token mode,
set `JARVISD_AUTH_MODE=token` and provide `JARVIS_API_TOKEN`; missing/wrong
app tokens are rejected. `JARVISD_EVENT_TOKEN` is scoped to
`POST /api/jarvis/events` and cannot control
commands or services. Configure `JARVISD_TRUSTED_CIDRS` when the home subnet
changes. Do not put tokens in the repository.
