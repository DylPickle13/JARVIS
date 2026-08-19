# jarvis-app

Native iOS + watchOS app for Operation JARVIS — phone and Apple Watch control
surface for the JARVIS stack on `mac-mini-64` (plugs, air purifier,
status/telemetry, events, service control), over LAN or Tailscale.

**Status:** **M2 complete** — `jarvisd` daemon running under launchd (with
resurrector); iOS app has the full **Home control screen** (plugs, air purifier,
Pi count, weather) plus the **Events live feed** and **System service control**
(Stop/Restart the registered services), all verified live in the simulator;
event pipeline is dashboard-independent. watchOS app builds + runs.
Next: install the M2 build on the physical iPhone, then M3 (widgets + watch).

**v5 note:** the app is **dashboard-independent**. Its backend is a new small
daemon, `jarvisd` (in `jarvisd/`, this folder), which becomes the app's only
control plane. The existing dashboard runs in parallel during transition and is
retired in M5. APNs push + Live Activities are out (free Apple ID can't do
APNs); oMLX is out of app scope entirely; widgets = plug grid only for now.

**Everything lives in this folder** — the Swift app targets, the shared
`JARVISKit` package, *and* the `jarvisd` backend daemon are all under
`jarvis-app/` so the whole project is self-contained.

## Read first

- [`docs/ios-watchos-app-research-2026-07-09.md`](docs/ios-watchos-app-research-2026-07-09.md)
  — full research, architecture, scope decisions, UI mockups, and phased
  build plan (v5).

## Scope (v5, approved)

- **In:** smart plugs, air purifier, status & telemetry (weather, Pi session
  count, uptime), events feed, service start/stop/restart (room-audio server,
  dashboard during transition), plug-grid widgets (iOS home + lock-screen,
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
- Icon: **blue square placeholder** for now

## What's working now (M2)

- **`jarvisd` daemon** — running under launchd (`com.operation-jarvis.jarvisd`)
  with a resurrector watchdog. **No-token by default** (trusted home LAN /
  Tailscale); a token still works if `JARVIS_API_TOKEN` is set, so strict auth
  can be re-enabled without a client change. Verified: `/health`,
  `/api/v1/state` (plugs, purifier, Pi count, weather, network, uptime),
  `/api/v1/command` (allowlisted, rejects cast), `/api/jarvis/events` ingest,
  `/api/v1/events`, `/api/v1/services` (status/start/stop/restart).
- **iOS app — Home screen (M1)** — 4-tab shell (Home / Events / System /
  Settings). Home shows: connection header (LAN vs Tailscale + IP), weather
  card (Open-Meteo), Pi session count, **air purifier** (power switch +
  Auto/Manual/Sleep/Pet segmented control + fan 1–4 slider), and a **2-column
  plug grid** (tap a card to toggle). Polls the snapshot every 10 s; commands
  go through the `jarvisd` allowlist. Verified live in the iPhone 11 simulator.
- **iOS app — Events (M2)** — live activity feed from `/api/v1/events`: one row
  per event (✓/✗/○ status glyph, action, summary, relative time), newest-first,
  auto-polls every 5 s + pull-to-refresh. The event bridge in `jarvis.py` posts
  to jarvisd directly (dashboard-independent).
- **iOS app — System (M2)** — service control from `services.json`: a card per
  registered service (status dot, name, description, PID) with **Stop**
  (confirmation) / **Restart** (or **Start**) controls, plus a `jarvisd` daemon
  card (version + uptime). Verified the write path end-to-end (restart → new PID).
- **iOS app — auto-connect (M2 perf)** — connects as soon as `/health` answers
  (the slow state snapshot loads in the background); `discover()` returns the
  best reachable endpoint early instead of waiting on every candidate.
- **watchOS app** — builds for Apple Watch Series 11 (46mm) and runs in the
  simulator (connect screen; full watch UI + relay is M3).
- **`JARVISKit`** — shared package with `JarvisClient` (incl. `discover`),
  `StateSnapshot` models, `EndpointStore` (Keychain), `WatchBridge`; unit tests
  + live integration tests (hit the real daemon, skip gracefully when it's down)
  all pass.
- **`scripts/redeploy-jarvis-app.sh`** — one-command build + install for the
  physical iPhone (free Apple ID, 7-day auto-provisioning).

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
│   ├── jarvisd.py              #   ThreadingHTTPServer: state/command/events/services
│   ├── services.json           #   launchctl service registry
│   ├── resurrector.sh          #   watchdog (keeps jarvisd alive)
│   └── launchd/                #   LaunchAgent plists (jarvisd + resurrector)
├── JARVISKit/                  # shared Swift package (client, models, watch bridge)
│   ├── Package.swift
│   ├── Sources/JARVISKit/      #   Models, JarvisClient, EndpointStore, WatchBridge
│   └── Tests/JARVISKitTests/   #   unit + live integration tests
├── JARVIS/                     # iOS app target (SwiftUI)
│   ├── JARVISApp.swift         #   @main + 4-tab shell
│   ├── AppState.swift          #   connection + state + command model
│   ├── Info.plist              #   ATS exception for local/Tailscale HTTP
│   └── Views/
│       ├── HomeView.swift      #   M1 Home: weather, Pi, purifier, plug grid
│       ├── EventsView.swift    #   M2 live event feed (5 s poll + pull-to-refresh)
│       ├── SystemView.swift    #   M2 service control (Stop/Restart) + daemon info
│       ├── SettingsView.swift  #   connection management + about
│       └── Components.swift    #   badge, card, formatting helpers
├── JARVISWatch/                # watchOS app target
│   ├── JARVISWatchApp.swift
│   ├── Info.plist              #   ATS exception
│   └── Views/WatchConnectView.swift
├── JARVISToday/                # WidgetKit extension (iOS plug-grid widget)   [M3]
└── JARVISComplications/        # WidgetKit extension (watch plug complication) [M3]
```

## Backend dependency

`jarvisd` — Python daemon in `jarvis-app/jarvisd/` (port 8790, LaunchAgent +
resurrector): auth, `/api/v1/state`, `/api/v1/command` (allowlisted →
`jarvis-cli`), `/api/v1/events`, `/api/jarvis/events` ingest (existing
jarvis-cli contract), `/api/v1/services` (start/stop/restart). Full spec:
research doc §6. Tailscale on the Mac is transport-only.
