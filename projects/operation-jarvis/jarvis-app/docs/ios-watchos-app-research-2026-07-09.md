# iOS + watchOS App for Operation JARVIS — Historical Research & Plan (v5)

> **Historical document — not an operational runbook.** This research records the
> transitional architecture considered on 2026-07-09. The deprecated Node/PWA
> dashboard and its `:8787` service were fully removed on 2026-08-20. Do not
> follow transitional commands, environment names, LaunchAgent paths, or source
> paths below that refer to it. The current architecture is documented in
> [`../README.md`](../README.md) and the post-deployment plan. For physical
> Watch packaging/deployment, use
> [`watch-companion-packaging-deployment-and-recovery-2026-08-20.md`](watch-companion-packaging-deployment-and-recovery-2026-08-20.md); it records the Xcode 26 `.watchkitapp`, `PlugIns/`, installer skip-flag, trust, and tunnel findings that supersede this research.

Date: 2026-07-09 (v5 revision: APNs push + Live Activities removed — a free
Apple ID cannot do APNs, verified; oMLX removed from app scope entirely;
name/accent/icon decided; widgets reduced to plug grid)
Status: approved scope — ready to build
Location: this doc lives in `projects/operation-jarvis/jarvis-app/docs/`; all app
code **and** the backend daemon live in `projects/operation-jarvis/jarvis-app/`
(the `jarvisd/` daemon is a subfolder of the app, so the whole project is
self-contained in `jarvis-app/`).

## 0. Scope decisions (v5)

| Decision | Value |
|---|---|
| iPhone | iPhone 11 (A13) — iOS 17/18/26, widgets + App Intents, all SwiftUI features we need |
| Apple Watch | Series 11, 46 mm — watchOS 26: interactive complications, wrist gestures, always-on |
| Distribution | **Free Apple ID** (no $99 yet) — 7-day provisioning expiry, no TestFlight; one-command redeploy script |
| Remote access | **Tailscale** (free personal plan, account ready) — the app's stable primary endpoint |
| Write access | **Not read-only** — app controls registered services via the new daemon |
| **Dashboard** | **Being retired.** The app must not depend on it. A new small daemon (**`jarvisd`**, §6) becomes the app's backend; the dashboard is run in parallel during transition, then removed (M5) |
| **Room-display HUD** | **Retired with the dashboard — no replacement** (decision 2026-07-09) |
| **Phone-voice PWA** | **Retired with the dashboard — no in-app voice, ever** (decision 2026-07-09) |
| **jarvisd auth** | **Brand-new `JARVIS_API_TOKEN`**, distinct from the dashboard's (decision 2026-07-09) |
| **Cast** | **Removed from scope entirely** — no TV/speaker control, no `speak` (decision 2026-07-09) |
| **APNs push + Live Activities** | **Removed** — APNs requires a paid Apple Developer Program (verified 2026-07-09); polling + in-app banners instead |
| **oMLX** | **Removed from app scope entirely** — no status, no control (decision 2026-07-09) |
| **App name** | **JARVIS** (decision 2026-07-09) |
| **Accent color** | **Light blue / holographic blue** (exact value set in M0; decision 2026-07-09) |
| **App icon** | **Blue square placeholder for now** (final icon later; decision 2026-07-09) |
| **Widgets** | **Plug grid only for now** (iOS home + lock-screen; watch interactive plug complication); other widget types deferred (decision 2026-07-09) |
| Dropped from v1 | Spotify, camera, in-app voice/wake word, Raspberry Pi room endpoint, **Cast** |
| Kept/added | Plugs, air purifier, status & telemetry, events, **plug-grid widgets (iOS + watch interactive complication)**, Siri/Shortcuts via App Intents |

### In scope (final feature list)

| Group | Functions |
|---|---|
| Status | JARVIS status, telemetry (weather, Pi session count, uptime) |
| Smart plugs | `plug-list`, `plug-status`, `plug-on/off/toggle` (discover stays CLI-only) |
| Air purifier | `purifier-status`, `purifier-set` (power, mode, speed, display, child-lock, light-detection, auto-preference, timer) |
| Events | live event feed (ingested from `jarvis-cli` + subsystems) |
| System (write) | start/stop/restart of registered services (room-audio server, dashboard during transition) |
| Watch | quick controls + interactive plug complication |
| Widgets | iOS plug-grid widget (home + lock-screen); watch interactive plug complication |
| Siri/Shortcuts | App Intents exposing the action surface |

### Out of scope (v5)

- **Cast** (TV/speakers: speak, status, volume, mute, stop, YouTube, play-url) —
  removed 2026-07-09. `speak` goes with it (it is cast-based).
- **APNs push notifications + Live Activities** — require a paid Apple
  Developer Program membership (verified 2026-07-09); removed with the
  free-account decision. Polling + in-app banners cover the needs; revisit if
  the $99 happens later.
- **oMLX** — no status, no control, nothing oMLX-related in the app (decision
  2026-07-09).
- Spotify, camera, in-app voice/wake word, Raspberry Pi room endpoint, Discord bot
  process control.
- **Retiring the dashboard's own UI features** (room-display HUD, phone-voice
  PWA, Pi/phone tiles, artifact browser) — **decided: all retired, no
  replacements** (§7 transition plan).

---

## 1. Architecture principle: the app owns the control plane

The dashboard (Node, :8787) was the de-facto API gateway, but it is being
retired. Instead of depending on it, we build **`jarvisd`** — a small,
dedicated, always-on Python daemon on mac-mini-64 that is the *only* backend
the app needs:

- It wraps `jarvis-cli --json …` for all control actions (exactly what the
  dashboard's `/api/jarvis/actions` did, minus the dying UI).
- It aggregates telemetry (plugs, purifier, Pi sessions, weather, uptime)
  into one state snapshot.
- It ingests events using the **existing** `jarvis-cli` event contract
  (`POST /api/jarvis/events` — `jarvis.py::emit_dashboard_event` already
  POSTs there; repointing `JARVIS_DASHBOARD_URL` at jarvisd is a one-line
  env change, zero code change).
- It handles service control (start/stop/restart of registered services).

`jarvis.py`, the voice pipeline, the Pi, and the room-audio server are
untouched. When the dashboard is removed (M5), nothing in the JARVIS stack
breaks — only the dashboard's own UI features go away (§7).

---

## 2. Devices & platform facts (verified)

- **iPhone 11**: floor for iOS 26; widgets, App Intents, interactive
  complications all fine.
- **Watch Series 11 (watchOS 26)**: interactive complications (watchOS 10+),
  wrist gestures + always-on (watchOS 11+), watch-speaker audio.
- **watchOS networking**: low-level networking (Bonjour/`NWBrowser`) only in
  audio-streaming context (TN3135) → **watch cannot do Bonjour discovery**;
  endpoints come from the iPhone app (WatchConnectivity) or relay-through-
  iPhone when it can't reach the Mac directly (§3.3).
  - https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos
- **Complications/widgets**: one WidgetKit + App Intents codebase → iOS home
  widgets, lock-screen accessory widgets, watch complications (interactive
  buttons included).
  - https://developer.apple.com/videos/play/wwdc2022/10050/ · https://developer.apple.com/videos/play/wwdc2022/10051/
- **iOS local network / ATS**: `NSLocalNetworkUsageDescription` in plist.
  Cleartext HTTP to LAN/Tailscale: try `NSAllowsLocalNetworking` first; if ATS
  blocks the `100.x` Tailscale IP, set `NSAllowsArbitraryLoads` (acceptable —
  personal app, no App Store review).
  - https://developer.apple.com/forums/thread/663858 · https://developer.apple.com/documentation/security/preventing-insecure-network-connections
- **Free Apple ID**: installs expire in **7 days** (reinstall to refresh); max
  3 apps (we use 2: iOS + independent watch app; extensions don't count);
  **APNs push does NOT work with a free account** (push requires a Developer
  Program membership — verified 2026-07-09); no TestFlight.
  - https://developer.apple.com/support/compare-memberships/
- **Tailscale**: free personal plan is plenty; `tailscaled` on the Mac +
  Tailscale app on the iPhone; no watchOS client → watch strategy in §3.3.

---

## 3. Networking design (Tailscale-first)

```text
iPhone app ──(Tailscale, home AND away)──▶ http://<mac-tailscale-ip>:8790  (jarvisd)
Watch app  ──(home Wi-Fi, direct)────────▶ http://<mac-lan-ip>:8790
Watch app  ──(away, WCSession relay via iPhone app)──▶ Tailscale ──▶ jarvisd
```

### 3.1 Tailscale setup (one-time, on mac-mini-64)

```bash
brew install tailscale
sudo brew services start tailscale          # tailscaled as a daemon
sudo tailscale up --hostname=mac-mini-64    # join tailnet (account ready)
tailscale ip -4                             # the app's stable endpoint
```

jarvisd binds `0.0.0.0:8790` → reachable on the Tailscale interface with zero
extra config. Token auth still applies.

### 3.2 iPhone app

- Primary endpoint: `http://<mac-tailscale-ip>:8790` — one URL for home and
  away (cellular included). Fallback: manual LAN IP in Settings.
- Keep `NSLocalNetworkUsageDescription` (prompt appears for LAN fallback).

### 3.3 Watch app endpoint strategy

- **At home**: watch on home Wi-Fi → direct to the Mac's **LAN IP** (the
  `100.x` Tailscale IP is only reachable from tailnet members; the watch
  can't join). jarvisd's `/api/v1/state` returns the Mac's LAN IP + Tailscale
  IP so the iPhone app can sync them to the watch.
- **Away**: **WCSession relay** — the watch sends API requests to the paired
  iPhone app over Bluetooth; the iPhone app (on the tailnet) executes and
  returns the response. Makes the watch functional anywhere the iPhone is.
- iPhone app syncs `{tailscaleUrl, lanUrl, token}` to the watch via
  WatchConnectivity + shared App Group on every successful connect.

---

## 4. App architecture

```text
┌────────────────────────────── iPhone (iOS app) ──────────────────────────────┐
│ SwiftUI "JARVIS"                                                              │
│  • Endpoint: Tailscale IP (default) / manual LAN IP; Keychain token          │
│  • Screens: Home, Events, System, Settings                                    │
│  • App Intents (Siri/Shortcuts)                                              │
│  • WatchConnectivity: sync endpoint/token/state ↔ watch; relay proxy         │
└──────────────┬────────────────────────────────────────────────────────────────┘
               │  HTTP (Tailscale or LAN)
┌──────────────▼────────────────────────────────────────────────────────────────┐
│ mac-mini-64                                                                   │
│  jarvisd (NEW Python daemon, :8790, LaunchAgent)                              │
│    auth · /api/v1/state · /api/v1/command → jarvis-cli · /api/v1/events       │
│    /api/jarvis/events (ingest, existing contract) · /api/v1/services          │
│  resurrector (separate LaunchAgent, keeps jarvisd alive)                      │
│  Tailscale (tailscaled) — transport only                                      │
│  (dashboard :8787 — legacy, parallel during transition, removed in M5)        │
└────────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────── Apple Watch (watch app) ────────────────────────┐
│  • Glance: PM2.5, plugs, Pi session count                                     │
│  • Controls: plugs, purifier quick-set (off/sleep/auto, fan 1–4)              │
│  • Complication: INTERACTIVE plug (tap = toggle)                              │
│  • Endpoint: WC-synced (LAN at home) or relay-through-iPhone (away)           │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Xcode project layout (single workspace, in `jarvis-app/`)

```text
jarvis-app/
├── README.md / .gitignore / docs/ / scripts/
├── jarvisd/                    # Python backend daemon (port 8790) + LaunchAgents
├── JARVISKit/                  # shared Swift package
│   ├── JarvisClient.swift      # URLSession client for jarvisd API
│   ├── EndpointStore.swift     # Tailscale/LAN URLs + Keychain token
│   ├── Models.swift            # Codable DTOs mirroring jarvisd JSON
│   └── WatchBridge.swift       # WCSession sync + relay proxy
├── JARVIS/                     # iOS app target (SwiftUI)
│   ├── Views/ Home, Events, System, Settings
│   └── Intents/                # App Intents (Siri/Shortcuts)
├── JARVISToday/                # WidgetKit extension (iOS plug-grid widget)
├── JARVISWatch/                # watchOS app target (independent-capable)
└── JARVISComplications/        # WidgetKit extension (watch interactive plug complication)
```

### 4.2 iOS app screens

1. **Home** — connection status (Tailscale/LAN, token ok), JARVIS status,
   Pi session count, weather, **purifier card** (PM2.5, power, mode, speed +
   quick-set: sleep/auto/off, fan speed), **plug grid** (tap = toggle,
   long-press = status).
2. **Events** — live feed (poll `/api/v1/events?since=…` every ~5 s while
   open), color-coded by ok/error.
3. **System** (write access) — registered services: status / start / stop /
   restart (room-audio server, dashboard during transition — per
   `jarvisd/services.json`).
4. **Settings** — endpoint (Tailscale default, manual override), token
   (Keychain), watch sync status.

### 4.3 Watch app

- **Glance view**: PM2.5 + purifier power, plug on/off summary, Pi session
  count, connection dot (direct vs relay).
- **Controls**: plug toggles; purifier quick-set (off/sleep/auto + fan 1–4).
- **Complication** (WidgetKit, watchOS 26) — plug grid only for now
  (decision 2026-07-09):
  - **interactive**: accessory-circular plug icon, tap = toggle plug.
- **Wrist gestures** (watchOS 26): double-tap = quick controls (configurable).

### 4.4 Widgets

- **Plug grid only for now** (decision 2026-07-09); other widget types
  (PM2.5, Pi count, weather) deferred.
- **iOS home, 4×4**: plug grid — all 4 plugs, tap = toggle (interactive
  buttons via App Intents, straight from the home screen).
- **Lock-screen accessory**: plug summary (rectangular, on/off dots).
- **Watch**: interactive plug complication (accessory-circular, tap = toggle).
- Refresh: WidgetKit timelines (15 min budget) + `reloadTimelines` on app
  foreground (no silent push — free account).

### 4.5 Siri / Shortcuts (App Intents)

Same `JarvisClient` code path: "Hey Siri, ask JARVIS to turn off the lamp",
"JARVIS status", "set purifier to sleep".

### 4.6 Notification strategy (no APNs on free account)

- **APNs push requires a paid Apple Developer Program membership**
  (verified 2026-07-09) → push notifications and Live Activities are **out of
  scope** for the free-account build.
- While the app is open: poll `/api/v1/state` (~30 s) and `/api/v1/events`
  (~5 s in the Events tab); in-app banners for command results and errors.
- Widgets refresh on WidgetKit timelines; complications on their schedules.
- If the $99 membership happens later: add an APNs sender to jarvisd +
  device registration + Live Activities (no app architecture change needed).

### 4.7 UI mockups (wireframes, HIG-aligned)

ASCII wireframes — layout intent, not final design. The design language
follows Apple's Human Interface Guidelines: SF Pro type scale, 16 pt
margins, inset-grouped cards with 12 pt continuous corners, system colors
with semantic labels, SF Symbols, native components (UISwitch,
UISegmentedControl, UISlider), full dark-mode adaptation, Dynamic Type,
VoiceOver labels, and Reduce Motion support.

**Design tokens (both platforms)**

| Token | iOS | Watch |
|---|---|---|
| App title | Large Title 34 pt bold | — (face supplies context) |
| Section header | Headline 17 pt semibold | footnote, secondary |
| Primary value | Title 2, rounded numerals | 40–44 pt rounded, centered |
| Meta text | Footnote 13 pt, secondary label | caption, secondary |
| Cards | insetGrouped, 12 pt continuous radius | full-width capsules, 20 pt radius |
| Accent | light blue (holographic blue) — custom accent, exact value set in M0 | same accent |
| State colors | green = on/ok · red = error · gray = off | same |
| Icons | SF Symbols, weight matched to text | SF Symbols 18–22 pt |
| Motion | subtle, respects Reduce Motion | radial gauge sweep on load |

SF Symbols used: `house`, `list.bullet.rectangle`, `gearshape.2`,
`gearshape`, `sun.max.fill`, `terminal`, `cpu`, `drop`, `power`,
`wifi`, `lock`, `bell`, `watch`.

Branding: app name **JARVIS** (display name on home screen, watch,
notifications). Icon: **blue square placeholder** for now (final icon later).
Accent: **light blue / holographic blue**.

**iOS — Home** (main tab)

```text
┌────────────────────────────────────────────────┐
│ 9:41                             ▂▄▆█  📶  🔋  │
│                                                │
│  JARVIS                                       │
│  ● Connected · Tailscale        100.96.55.86   │
│                                                │
│  ╭──────────────────────────────────────────╮  │
│  │ ☀  Pickering, ON              24°  18/26 │  │
│  │     Feels 25° · 41% humidity · 14 km/h   │  │
│  ╰──────────────────────────────────────────╯  │
│                                                │
│  ╭──────────────────────────────────────────╮  │
│  │ ⌨  Pi sessions                           │  │
│  │ 2 active                                 │  │
│  ╰──────────────────────────────────────────╯  │
│                                                │
│  Air purifier                          ( ON )  │
│  ╭──────────────────────────────────────────╮  │
│  │ 💧 12 µg/m³           Auto · fan 2       │  │
│  │ ┌─────┬───────┬─────┬────────┐           │  │
│  │ │ Off │ Sleep │Auto│ Manual │           │  │
│  │ fan   ──────●────────  1  2  3  4        │  │
│  ╰──────────────────────────────────────────╯  │
│                                                │
│  Plugs                                          │
│  ╭─────────────────────╮ ╭───────────────────╮ │
│  │ ⏻ family-room-light │ │ ⏻ lamp            │ │
│  │            ON        │ │           OFF     │ │
│  ╰─────────────────────╯ ╰───────────────────╯ │
│  ╭─────────────────────╮ ╭───────────────────╮ │
│  │ ⏻ pedalboard        │ │ ⏻ tv              │ │
│  │            ON        │ │           OFF     │ │
│  ╰─────────────────────╯ ╰───────────────────╯ │
│                                                │
│ ┌────────────────────────────────────────────┐ │
│ │   ⌂          ☰           ⚙          ⚙︎     │ │
│ │  Home      Events      System     Settings │ │
│ └────────────────────────────────────────────┘ │
└────────────────────────────────────────────────┘
```

HIG notes: Large Title; connection shown as a capsule with status dot;
weather/stat cards are insetGrouped; purifier mode is a
UISegmentedControl (selected segment = current mode, tap = set); fan is a
UISlider with tick labels; power is a UISwitch in the section header;
plug tiles are tappable cards (tap = toggle, state dot + label); tab bar
with SF Symbols, max 4 tabs.

**iOS — Events** (live feed, polls every ~5 s while open)

```text
┌────────────────────────────────────────────────┐
│ 9:41                             ▂▄▆█  📶  🔋  │
│                                                │
│  Events                                       │
│  ● live · refreshes every 5 s                 │
│                                                │
│  ╭──────────────────────────────────────────╮  │
│  │ 17:42  ✓  plug-toggle                    │  │
│  │         family-room-light → on           │  │
│  ├──────────────────────────────────────────┤  │
│  │ 17:39  ✓  purifier-set                   │  │
│  │         mode = sleep                     │  │
│  ├──────────────────────────────────────────┤  │
│  │ 17:31  ✗  room-audio-start               │  │
│  │         timed out after 12 s             │  │
│  ├──────────────────────────────────────────┤  │
│  │ 17:20  ✓  status                         │  │
│  │         JARVIS online                    │  │
│  ╰──────────────────────────────────────────╯  │
└────────────────────────────────────────────────┘
```

HIG notes: insetGrouped list, one row per event; time = caption
secondary, action = body primary, detail = footnote secondary; ✓/✗ in
green/red; pull-to-refresh + auto-poll.

**iOS — System** (write access)

```text
┌────────────────────────────────────────────────┐
│ 9:41                             ▂▄▆█  📶  🔋  │
│                                                │
│  System                                       │
│  Service control · write access               │
│                                                │
│  ╭──────────────────────────────────────────╮  │
│  │ ⚙ room-audio-server            ● running │  │
│  │   Pi room audio · :8791                   │  │
│  │             [ Stop ]   [ Restart ]        │  │
│  ╰──────────────────────────────────────────╯  │
│  ╭──────────────────────────────────────────╮  │
│  │ ⚙ dashboard (legacy)           ● running │  │
│  │   :8787 · retired in M5                   │  │
│  │             [ Stop ]   [ Restart ]        │  │
│  ╰──────────────────────────────────────────╯  │
│  ╭──────────────────────────────────────────╮  │
│  │ ⚙ jarvisd                      ● running │  │
│  │   app backend · :8790                     │  │
│  │   stopping takes the app offline          │  │
│  │             [ Stop ]   [ Restart ]        │  │
│  ╰──────────────────────────────────────────╯  │
└────────────────────────────────────────────────┘
```

HIG notes: one card per service; status dot + label; Stop = bordered
button (destructive tint on confirm sheet), Restart = bordered;
confirmation sheet before any stop (HIG: confirm destructive actions).

**iOS — Settings**

```text
┌────────────────────────────────────────────────┐
│ 9:41                             ▂▄▆█  📶  🔋  │
│                                                │
│  Settings                                     │
│                                                │
│  Endpoint                                     │
│  ╭──────────────────────────────────────────╮  │
│  │ ● Tailscale   100.96.55.86:8790          │  │
│  │ ○ LAN         192.168.21.63:8790         │  │
│  │ ○ Custom      [ address field ]          │  │
│  ╰──────────────────────────────────────────╯  │
│  ╭──────────────────────────────────────────╮  │
│  │ 🔒 Token          ••••••••  (Keychain)   │  │
│  │ 🔔 Push banners            ( ON )        │  │
│  │ ⌚ Watch sync   17:42 · LAN   [ Sync ]    │  │
│  ╰──────────────────────────────────────────╯  │
│  jarvisd 1.0 · up 3 d 04 h                     │
└────────────────────────────────────────────────┘
```

HIG notes: standard insetGrouped settings form; endpoint is a
radio list (selected = filled dot); token stored in Keychain, shown
masked; footer = footnote secondary.

**Watch — Glance** (watchOS 10+ language: circular, radial gauge,
large rounded numerals, minimal chrome)

```text
          ╭─────────────────────────────╮
          │     JARVIS            ● LAN │
          │                             │
          │         ╭─────────╮         │
          │        ╱   12      ╲        │
          │       │  µg/m³     │        │
          │        ╲           ╱        │
          │         ╰─────────╯         │
          │      Auto · fan 2 · on      │
          │                             │
          │   ⌨ 2 Pi    ⏻ 3/4 plugs    │
          │   ☀ 24°C    · via LAN      │
          ╰─────────────────────────────╯
```

HIG notes: PM2.5 as the hero value inside a radial gauge (sweeps on
load, always-on friendly); one line of context under the gauge; two
columns of icon + value stats at the bottom; connection dot top-right
(LAN / Tailscale / relay).

**Watch — Controls** (full-width capsule buttons: icon + label + state)

```text
          ╭─────────────────────────────╮
          │     Controls          ● LAN │
          │  ╭───────────────────────╮  │
          │  │ ⏻ family-room-light   │  │
          │  │                  ON   │  │
          │  ╰───────────────────────╯  │
          │  ╭───────────────────────╮  │
          │  │ ⏻ lamp                │  │
          │  │                  OFF  │  │
          │  ╰───────────────────────╯  │
          │  ╭───────────────────────╮  │
          │  │ 💧 purifier  [ sleep ] │  │
          │  ╰───────────────────────╯  │
          ╰─────────────────────────────╯
```

HIG notes: crown-scroll between Glance and Controls; each plug is a
full-width capsule (tap = toggle, state right-aligned); purifier quick-
set as a chip row (Off / Sleep / Auto / fan 1–4) that expands on tap;
wrist double-tap opens Controls.

**Watch — Complications** (watchOS 26, on any face)

| Complication | Shape | Content | Behavior |
|---|---|---|---|
| Plug (interactive) | accessory-circular | `⏻ lamp` | tap = toggle plug |

**Accessibility & theming (both platforms)**

- Full dark-mode adaptation (system colors only, no hard-coded RGB).
- Dynamic Type up to accessibility sizes (cards reflow, not truncate).
- VoiceOver: every control labeled ("Lamp, plug, on, double tap to
  toggle"); state changes announced.
- Reduce Motion: gauge sweep and row animations disabled.
- Contrast: state colors meet 4.5:1 on both backgrounds.
---

## 5. Free-account (no $99) workflow

- Xcode → Signing & Capabilities → **Automatically manage signing**, team =
  personal (free) Apple ID (iOS + watch targets).
- **7-day expiry**: after 7 days the app disappears; refresh =
  `jarvis-app/scripts/redeploy-jarvis-app.sh` (added in M0):

  ```bash
  xcodebuild -project JARVIS.xcodeproj -scheme JARVIS \
    -destination 'platform=iOS,id=<UDID>' -allowProvisioningUpdates build
  xcrun devicectl device install app --device <UDID> \
    ~/Library/Developer/Xcode/DerivedData/.../Build/Products/Debug-iphoneos/JARVIS.app
  ```

  (Running the iOS scheme in Xcode also deploys the watch app.)
- Mental model: "re-run the script weekly" (2 min). $99 later = 10-minute
  migration if it ever gets annoying.
- Caveats: max 3 apps per free account (we use 2); no TestFlight; **no APNs
  push** (paid-only capability).

---

## 6. New backend: `jarvisd` (lives in `jarvis-app/jarvisd/`)

Small Python daemon (stdlib `ThreadingHTTPServer`, same style as the
room-audio server; upgrade to FastAPI only if it gets painful). Own venv or
the main Operation JARVIS venv. Runs as LaunchAgent
`com.operation-jarvis.jarvisd`, installed like the dashboard's.

**Config** (env / `.env`): `JARVIS_API_TOKEN` (new token, distinct from the
dashboard's), `JARVISD_PORT=8790`,
`JARVISD_SERVICES_FILE=jarvisd/services.json`.

**Endpoints** (all require `x-jarvis-token` except `/health`):

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness (resurrector probes this) |
| `GET /api/v1/state` | aggregated snapshot: plugs, purifier, Pi session count, weather (Open-Meteo, 10-min cache), uptime, service states, **macLanIp + tailscaleIp**. Subsystems run in parallel threads with a ~10 s cap; partial results carry per-subsystem `ok/error` so one slow subsystem never blocks the snapshot |
| `POST /api/v1/command` | `{action, params}` → `jarvis-cli --json <action> …`; allowlist = in-scope actions only (status, plug-*, purifier-*). Same subprocess isolation as today (jarvis.py picks the right venv per subsystem) |
| `GET /api/v1/events?since=&limit=` | ring buffer of recent events (in-memory + optional jsonl persistence) |
| `POST /api/jarvis/events` | **ingest** (`jarvis.py::emit_event` payload); `JARVISD_EVENT_TOKEN` is ingest-only when token mode is enabled |
| `GET/POST /api/v1/services/<name>` | status / start / stop / restart for entries in `services.json` (name → launchctl label or command), currently the room-audio server |

**Resurrector**: separate LaunchAgent `com.operation-jarvis.jarvisd-resurrector`
(~30-line loop): every 10 s `curl /health`; if down → `launchctl kickstart
gui/<uid>/com.operation-jarvis.jarvisd`, with basic backoff (max 1 restart /
30 s). Keeps the app's backend alive; "stop" of other services from the app
can never strand the control plane.

**Why not keep using the dashboard as the API?** It's a 4,600-line Node UI
server carrying a room-display PWA, camera pipeline, and phone-voice proxy
that we're retiring. jarvisd is ~500 lines doing exactly what the app needs,
with no UI baggage to maintain or secure.

---

## 7. Simulator-first development strategy

Build M0–M4 primarily in the **iOS + watch simulators**; real devices at gates.

**Why it fits especially well:** the simulators run on mac-mini-64, the same
machine as jarvisd. The simulator inherits the host network stack, so it
reaches `http://127.0.0.1:8790` and the Tailscale `100.x` IP directly — full
API client + UI developed against the **real running daemon** with no device
and no permission prompts.

| Capability | Simulator | Real device needed |
|---|---|---|
| All SwiftUI screens, widgets, complications | ✅ | — |
| API client vs live jarvisd (localhost / Tailscale IP) | ✅ | — |
| Keychain token storage | ✅ | — |
| Watch app UI + complications | ✅ (watch simulator) | — |
| WatchConnectivity sync/relay | ❌ (needs paired hardware) | iPhone + Watch (M3 gate) |
| Siri | ❌ | iPhone (M4 gate) |
| Local-network prompt, real latency, battery | — | iPhone (M0 gate) |

**Device gates** (7-day clock starts at each):
1. **End of M0** — first iPhone install: Tailscale path, local-network
   prompt, Keychain, real latency.
2. **End of M3** — iPhone + Watch Series 11: WCSession sync, real
   complications, wrist gestures.
3. **M4** — Siri/Shortcuts.

**Tips:** default dev endpoint `http://127.0.0.1:8790`; switch to the
Tailscale IP in Settings to rehearse the device path. Run the iOS scheme with
"Show iOS & Watch" to deploy both. Stub WatchBridge behind a protocol so the
simulator build runs without a paired watch.

---

## 8. Phased build plan (v5)

| Phase | Scope | Est. |
|---|---|---|
| **M0 — connect** | Tailscale daemon on Mac; **jarvisd skeleton** (health, auth, `/api/v1/state` minimal, `/api/v1/command`, `/api/jarvis/events` ingest) + LaunchAgent + resurrector; Xcode workspace (iOS + watch + JARVISKit); app connect/status screen **in simulator** against live jarvisd (localhost + Tailscale IP); `redeploy-jarvis-app.sh`; ATS plist verified; first iPhone install gate | 2–3 days |
| **M1 — core control** | jarvisd full `/state` (plugs, purifier, Pi count, weather, IPs); app Home screen: plugs (list/toggle), purifier (status + quick-set), Pi count, weather | 2–3 days |
| **M2 — events + system** | Events live feed; System page (service control from `services.json`) | 1 day |
| **M3 — widgets + watch** | iOS plug-grid widget (home + lock); watch app (glance + controls); interactive plug complication; WatchConnectivity endpoint/token sync | 3–4 days |
| **M4 — polish + reach** | App Intents/Siri/Shortcuts, watch relay-through-iPhone (away) | 1–2 days |


Total: ~8–12 focused days. After M1 the app already covers plugs + purifier
+ status from the phone, fully independent of the dashboard.

---

## 9. Risks & mitigations (v5)

| Risk | Mitigation |
|---|---|
| 7-day free-account expiry | `redeploy-jarvis-app.sh` (2-min weekly refresh); $99 later if annoying |
| ATS blocks cleartext to Tailscale `100.x` | `NSAllowsLocalNetworking` first; fallback `NSAllowsArbitraryLoads` (no App Store) |
| Watch can't reach Mac away from home | WCSession relay through iPhone (M4); "via iPhone" indicator |
| jarvisd `/state` latency (parallel subprocesses: plugs/purifier) | Parallel threads + ~10 s cap + per-subsystem partial results; app shows stale/failed tiles instead of blocking |
| jarvisd dies → app stranded | Resurrector LaunchAgent + `/health`; resurrector is separate from everything it protects |

| No background push (free account) | App notifies only while open; widgets on timelines; acceptable per 2026-07-09 decision — revisit if the $99 happens |
| Token leak | New long random `JARVIS_API_TOKEN`; Tailscale E2E; Keychain only |
| VeSync write lag | Show `verification_pending`; no auto-retry (matches CLI semantics) |

---

## 10. Open questions (v5 — all resolved 2026-07-09)

1. ~~Room-display HUD~~ — **retired, no replacement** ✓
2. ~~Phone-voice PWA~~ — **retired; no in-app voice in iOS/watch app** ✓
3. ~~Token~~ — **brand-new `JARVIS_API_TOKEN` for jarvisd** ✓
4. ~~Resurrector~~ — yes, for jarvisd (in M0) ✓
5. ~~Tailscale~~ — account ready; existing user-space tailscaled already authenticated (node IP 100.96.55.86) ✓
6. ~~Simulator-first~~ — yes, with device gates ✓
7. ~~Cast~~ — **removed from scope** ✓
8. ~~APNs push / Live Activities~~ — **removed** (free account can't do APNs, verified 2026-07-09); polling + in-app banners instead ✓
9. ~~oMLX~~ — **removed from app scope entirely** (no status, no control) ✓
10. ~~App name~~ — **JARVIS** ✓
11. ~~Accent color~~ — **light blue / holographic blue** ✓
12. ~~App icon~~ — **blue square placeholder for now** ✓
13. ~~Widgets~~ — **plug grid only for now**; other widget types deferred ✓

## 12. Implementation log

### M0 — connect (in progress → functionally complete 2026-08-18)

Done and verified:
- **`jarvisd`** built (`jarvisd/jarvisd.py`, stdlib `ThreadingHTTPServer`, port
  8790) with strict `x-jarvis-token` auth on `/api/v1/*`, lenient ingest on
  `/api/jarvis/events` (no-token OK, matching the dashboard's current behavior
  so `jarvis.py` can repoint with a one-line env change), `/api/v1/state`
  aggregation (plugs, purifier, Pi count, Open-Meteo weather w/ 10-min cache,
  network, uptime, services) with partial results + per-subsystem ok/error,
  `/api/v1/command` allowlist (no cast), event ring buffer + JSONL persistence,
  `/api/v1/services` start/stop/restart via `launchctl`. `services.json` lists
  room-audio-server + dashboard.
- **LaunchAgents installed**: `com.operation-jarvis.jarvisd` +
  `com.operation-jarvis.jarvisd-resurrector` (10s health probe, kickstart with
  30s backoff). Verified the resurrector restarts jarvisd after a kill.
- **`JARVIS_API_TOKEN`** (64-hex) added to `~/.env`; `JARVISD_TAILSCALE_IP`
  fallback added. Path detection in `jarvisd.py` is location-independent
  (walks up to find `jarvis-cli` / `.env`; env overrides available).
- **Xcode workspace** generated via xcodegen (`project.yml` → `JARVIS.xcodeproj`):
  `JARVISKit` local package + `JARVIS` (iOS 17+) + `JARVISWatch` (watchOS 10+).
- **`JARVISKit`**: `JarvisClient` (health/state/command/events/services),
  `StateSnapshot` + related models, `EndpointStore` (Keychain token +
  UserDefaults URL), `WatchBridge` (WCSession, platform-gated). Unit tests +
  live integration tests (real daemon, skip when down) — **all pass**.
- **iOS app**: connect/status screen (HIG: large title, inset-grouped form,
  SF Symbols, semantic colors). Runs in iPhone 11 simulator and shows **live
  state** from the real jarvisd (status, uptime, LAN 192.168.21.215, Tailscale
  100.96.55.86, plugs 1/4, purifier on, PM2.5 1 µg/m³). ATS exception for
  local/Tailscale HTTP in `Info.plist`.
- **watchOS app**: connect screen runs in Apple Watch Series 11 (46mm) simulator.
- **`scripts/redeploy-jarvis-app.sh`**: one-command device build + install
  (free Apple ID, `-allowProvisioningUpdates`); fails gracefully with clear
  instructions when no signing identity / no device.

Remaining M0 gate:
- **First physical iPhone install** — needs a free Apple ID signed into Xcode
  (Settings → Accounts) and the iPhone 11 connected. Then run
  `scripts/redeploy-jarvis-app.sh`. Verifies the Tailscale path, local-network
  prompt, and real-device signing.

M0 gate — **CLEARED 2026-08-18**: first physical iPhone install done. The
iPhone 11 auto-discovered the home LAN endpoint and connected with no token;
`jarvisd` logs confirmed the iPhone's `GET /api/v1/state 200`. Real-device
signing with the configured free Personal Team, trust-the-developer, and the
local-network path all verified.

### M0 follow-up (2026-08-18): no-token + auto-discovery

Per request, the app now connects with **no token** and **auto-discovers** the
endpoint:
- `jarvisd` is no-token by default on every endpoint (trusted home LAN /
  Tailscale). If a token is sent and `JARVIS_API_TOKEN` is configured it must
  match — so strict auth can be re-enabled later without a client change.
- `JARVISKit` gained `JarvisClient.discover(_:)` (probes candidate base URLs in
  parallel, short timeout, returns the first that answers `/health` by priority)
  and `JarvisEndpoints.defaults` (home LAN IP `192.168.21.215`, then Tailscale
  `100.96.55.86`). iOS `AppState` + watch `WatchConnectModel` auto-discover on
  launch and on Connect; the token field is gone from the UI (an optional
  endpoint override remains for advanced use).
- Verified in the iPhone 11 simulator: clean install, no seed, auto-detected the
  LAN endpoint and rendered live state with no token.
- `scripts/redeploy-jarvis-app.sh` fixed to use `DEVELOPMENT_TEAM` and detect the
  configured free Personal Team from Xcode's provisioning defaults.

### M1 — core control (complete 2026-08-19)

Built the iOS **Home** control screen (the main M1 deliverable) on a 4-tab shell
(Home / Events / System / Settings):
- `AppState` gained command support: `send(action:params:)`, `fetchState()`
  (state-only, no re-discovery), and convenience `togglePlug` / `setPurifierPower`
  / `setPurifierMode` / `setPurifierFan` (each sends through the `jarvisd`
  allowlist, then re-fetches state).
- `HomeView` (new): connection header (LAN vs Tailscale + active IP), weather
  card (Open-Meteo, WMO code → SF Symbol + tint), Pi sessions card, air purifier
  section (power `UISwitch` + Auto/Manual/Sleep/Pet `UISegmentedControl` + fan
  1–4 `Slider` that commits on release), and a 2-column **plug grid** (tap a card
  to toggle). Polls the snapshot every 10 s while connected; toolbar refresh.
- `SettingsView` (new): the former M0 connect screen — endpoint override,
  Connect/Reset, live status (uptime, LAN/Tailscale/active IP), About.
- `EventsView` + `SystemView`: designed M2 placeholders so the 4-tab shell is
  complete. `Components.swift`: shared `ConnectionBadge`, inset-grouped `Card`,
  and formatting helpers (uptime, display name, weather symbol/tint).
- Design notes: purifier on/off is a **switch** (not an "Off" segment) and the
  mode segments match the daemon's real modes (`auto/manual/sleep/pet`); the fan
  slider mirrors the live `fanLevel`/`fanSetLevel` and is enabled in Manual mode.
- Verified: iOS simulator (iPhone 11) renders live Home with real data (weather,
  Pi count, purifier, 4 plugs); fan slider consistent with header; live polling
  confirmed (Pi count updated 2→1 between refreshes). watchOS build unaffected.
  `JARVISKit` 6/6 tests pass. The configured iOS Personal Team build signs clean.
- Remaining: install the M1 build on the physical iPhone (needs reconnect).

### M2 — events + system (complete 2026-08-19)

Replaced the M1 `EventsView`/`SystemView` placeholders with live implementations,
and made the event pipeline dashboard-independent.

**Backend (event bridge):**
- `jarvis.py` `emit_dashboard_event` now posts to **both** jarvisd (primary,
  `JARVISD_URL` default `http://127.0.0.1:8790`, no token — the ingest is
  lenient) and the dashboard (during transition, with its token). Verified the
  dashboard does **not** relay to jarvisd, so this direct post is required for
  the app's feed. Confirmed live: a `plug-status` command bumped the jarvisd
  event seq and the newest event matched.

**App — Events tab:**
- `EventsView` (rewritten): inset-grouped `List`, one row per event (status
  glyph ✓ green / ✗ red / ○ neutral, action, one-line summary, compact relative
  timestamp). Newest-first, "N recent · auto-refreshes every 5 s" header, pulls
  the last 100. Auto-polls every 5 s while the tab is open (`.task` loop) plus
  pull-to-refresh. Distinct connecting / not-connected / empty states.
- `AppState`: `lastEvents` + `fetchEvents(limit:)`; `JarvisFormat.relativeTime`
  + `parseISO8601` helpers added to `Components.swift`.

**App — System tab:**
- `SystemView` (rewritten): one inset-grouped card per registered service from
  `services.json` (Dashboard, Room Audio Server) — status dot (green/gray),
  friendly name, description, PID, and **Stop** (destructive, confirmation
  dialog) / **Restart** (or **Start** when stopped) controls. A `jarvisd` daemon
  card shows version + uptime. Fetches on appear, pull, and every 15 s.
- `AppState`: `lastServices` + `fetchServices()`, `fetchHealth()`, and
  `runServiceAction(name:action:)` (sends through the allowlist, re-fetches,
  surfaces errors). `ServiceActionResult` gained `description`.

**Connection performance (fixes found while verifying M2):**
- `AppState.refresh()` now marks **connected as soon as `/health` answers** and
  fetches the (slow) state snapshot in the background — the state endpoint is
  ~5 s (N+1 `plug-status` + purifier + weather) and was gating the connection.
- `JarvisClient.discover()` now returns the highest-priority success **as soon
  as it's known** (early-exit) instead of waiting on every candidate, so a
  slow/unreachable candidate (e.g. Tailscale IP on the home LAN) no longer
  delays connect.

**Verified (iPhone 11 simulator, live jarvisd):**
- Events tab renders the live feed (real plug/purifier events, ✓/✗/○ glyphs,
  relative times, newest-first).
- System tab renders both service cards (Running, PIDs, descriptions) + daemon
  card (version 0.1.0, uptime).
- Service **write path** confirmed end-to-end: `restart` on the legacy dashboard
  returned ok and produced a new PID (1577 → 60972).
- Home tab connects fast and shows live data. `JARVISKit` 6/6 tests pass.
- Remaining: install the M2 build on the physical iPhone (needs reconnect);
  the ~5 s state endpoint is a follow-up perf item (not connection-blocking).

**Physical iPhone deploy (2026-08-19):** M2 build installed + launched on
Dylan's iPhone 11 using the configured free Personal Team; confirmed live
polling (`state` + `health` every ~15 s). Two `redeploy-jarvis-app.sh`
bugs fixed along the way: `ID_COUNT` was never set (always failed the identity
gate) and the device parser broke on multi-word names + used the devicectl UUID
where xcodebuild wanted a generic destination (now extracts the UUID by pattern
and builds `-destination 'generic/platform=iOS'`).

**Follow-up (auto-connect):** the launch-time auto-connect did **not** fire on
this launch — the user had to tap **Connect** once (which worked). Likely the
`Task { await refresh() }` in `AppState.init` ran before the network was ready
or while the app was backgrounded (launched via `devicectl`). Fix: re-run
`refresh()` on `scenePhase == .active` and add a short retry/backoff on
auto-connect failure so the app is truly zero-tap.

## M2.1 hardening implementation (2026-08-20)

The M2.1 pass is now implemented in the working tree before M3 UI:

- `jarvisd` uses explicit `trusted-network`/`token` auth, trusted CIDRs,
  ingest-only dashboard token scope, origin-scoped CORS, bounded JSON input,
  sanitized diagnostics, and bounded event persistence.
- State collection runs in a background single-flight cache with subsystem
  freshness/stale metadata; warm `/api/v1/state` responses are cache reads.
- LaunchAgent start/stop/restart uses configured plist paths, `bootstrap`,
  `bootout`, `kickstart`, bounded verification, and event records.
- iOS connection/polling is scene- and network-path-aware, selected-tab-owned,
  cancellable, retrying, and uses desired-state plug commands.
- Home/Events/System show loading, stale, unavailable, busy, and operation-error
  states instead of fabricating zero/off/stopped telemetry.
- `WatchBridge` uses actual `WCSessionDelegate` callbacks, and the corrected
  XcodeGen target relationship embeds the watch companion under `Watch/` for
  Xcode 26.
- Daemon and mocked JARVISKit tests were added; live tests are opt-in via
  `JARVIS_LIVE_TESTS=1` and `JARVISD_TEST_URL`.

The physical iPhone M2.1 gate is partially exercised. The final free-provisioned
build was installed on the iPhone 11 (install sequence `1624`), including the
widget and embedded watch bundles. A physical-device XCTest run passed all 3
AppState tests. Cold launch/relaunch also succeeded: the running app issued
HTTP 200 health/state requests from the iPhone and remained active. The
remaining manual matrix—network permission/failover, background/foreground,
read/write UI, service controls, accessibility, and stale/error presentation—must
still be completed before marking M2.1 complete.

The paired Apple Watch remains unavailable to CoreDevice (`ddiServicesAvailable:
false`, `tunnelState: unavailable`), so physical WatchConnectivity and widget
validation could not start in this pass.

### M3 foundation implementation (code/build only)

The M3 foundations are now present behind that gate:

- iOS `JARVISWidget` and watchOS `JARVISWatchWidget` WidgetKit targets are
  embedded in their host bundles.
- Plug widgets use typed `SetPlugIntent` desired-state commands, cached state,
  stale/unavailable rendering, and a bounded timeline refresh fallback for
  free-provisioned development devices.
- `SnapshotStore` and the App Group identifier are prepared for
  app/widget/watch cache sharing; free provisioning currently rejects the App
  Group entitlement, so it is intentionally not signed into this build. Widget
  timelines have a bounded direct-daemon fallback; API credentials remain in
  Keychain.
- The watch app has direct-daemon, iPhone-relay, and cached-state paths with
  plug controls. Physical WatchConnectivity/complication testing remains
  blocked while the paired Watch is unavailable.

## Key links

- watchOS low-level networking: https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos
- Local network privacy: https://developer.apple.com/forums/thread/663858
- ATS: https://developer.apple.com/documentation/security/preventing-insecure-network-connections
- Complications/widgets: https://developer.apple.com/videos/play/wwdc2022/10050/ · https://developer.apple.com/videos/play/wwdc2022/10051/
- Membership options: https://developer.apple.com/support/compare-memberships/
- Tailscale: https://tailscale.com
