# JARVIS native Apple app — unified documentation

**Last updated:** 2026-08-22 EDT

**Applies to:** Xcode 26, iOS 26, watchOS 26, XcodeGen 2.46, Personal Team/free provisioning

**App root:** `/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app`

**Current candidate:** `0.2.0 (20)`

**Physical installation:** iPhone and Apple Watch `0.2.0 (20)`; Siri invocation testing is owner-pending

This is the single architecture, security, packaging, deployment, validation,
and recovery reference for the JARVIS iPhone app, Apple Watch app, widgets, and
`jarvisd`. It replaces the earlier research, milestone, service-integration,
Watch-companion, widget, and post-deployment documents.

Do not commit secrets, device identifiers, signing identities, certificates,
provisioning profiles, device logs, screenshots, archives, exported IPAs,
DerivedData, or other build products. Keep device selectors in private
environment variables. Never unpair or erase the Watch during recovery, and
never deploy to a device outside Dylan's allowlist.

---

## 1. Current checkpoint

### Completed

- `jarvisd` is the sole Apple-client control plane on TCP `8790`.
- The deprecated Node/PWA dashboard, LaunchAgent, APIs, PWA, and TCP `8787`
  listener are fully removed.
- Weather and Open-Meteo are removed from the daemon and native contract.
- iPhone navigation is Home and Settings; build 18 removes the unused Events
  tab and its foreground event polling while retaining backend audit ingestion.
- Home order is Pi sessions, plugs, air purifier, then services/scheduled jobs
  and protected `jarvisd` information.
- Discord bot, room audio, scheduler, and sanitized scheduled-job telemetry are
  integrated. Bot and scheduler cards are read-only; room-audio actions remain
  server-allowlisted.
- Desired-state plug commands, authoritative cache revisions, stale-state UI,
  per-resource busy locks, and duplicate-write protection are implemented.
- The corrected Xcode 26 Watch companion hierarchy, `Watch/` embedding, signing,
  parent registration, developer installation, icons, and installed flags pass.
- Physical iPhone and Watch widget galleries expose the final four widget types.
- Physical plug-control tests restored their initial states and produced one
  command/event pair per intentional desired-state change.
- Cellular/Tailscale cold launch and relaunch pass without a hardware command.
- Build 14 embeds the canonical JARVIS artwork in the Watch widget and uses it
  for circular, corner, and rectangular Open JARVIS presentations. Inline keeps
  a system glyph.
- Build 15 applies one Apple-native holographic visual system across both host
  apps. Watch uses three vertical pages: branded overview, all-four 2×2 plug
  deck, and read-only system/air-quality status. iPhone adds a system-pulse
  header, device-specific plug cards, air-quality gauge, collapsed runtime/job
  sections, event cards, and branded Settings hero. Command and backend
  contracts are unchanged.
- Build 17 makes the circular Open JARVIS complication rendering-mode aware and
  the physical three-slot Smart Stack Combination widget now displays the
  JARVIS logo.
- Build 18 simplifies the iPhone shell to Home and Settings. `EventsView`, its
  tab/deep-link route, UI state, and five-second event polling are removed.
- Build 19 gives both host apps one shared immediate-then-15-second foreground
  refresh policy and removes normal refresh buttons from the visible UI.
- Build 20 adds exactly two dynamic, plug-only Siri shortcuts to both hosts.

### Build-20 dynamic Siri plug control

```text
Archive: /tmp/JARVIS-build20-siri.xcarchive
IPA:     /tmp/JARVIS-build20-siri-export/JARVIS.ipa
SHA-256: 26f2ccedb15ad0421eacd7623d01e7d97c54f3e82c20c9dfef3af6ec76e0b91e
```

The iPhone and Watch hosts expose only Turn On JARVIS Plug and Turn Off JARVIS
Plug through `AppShortcutsProvider`. Registered phrases are “Tell JARVIS to turn
on/off [plug]” and “Turn on/off [plug] with JARVIS.” `JARVISPlugEntityQuery`
builds its catalogue from `state.subsystems.plugs.plugs`; no production plug
identifier is compiled into the Siri source. Normalization handles case,
spaces, hyphens, and underscores. Exact matches win, ambiguous results remain
multiple for Siri disambiguation, and add/remove/rename calls
`updateAppShortcutParameters()`. A 15-second single-flight catalogue coordinator
coalesces the system's burst of parameter queries. Existing widget configuration
choices remain separate and unchanged.

Every intent obtains fresh state and validates the exact daemon identifier before
writing. Already-satisfied requests return without a POST. Other writes use only
`plug-on` or `plug-off`, and Siri reports success only after the command response
or a follow-up authoritative read confirms the desired state. Stale, unknown,
removed, rejected, and unconfirmed requests fail closed. The raw widget
`SetPlugIntent` is explicitly non-discoverable. Watch execution tries direct
`jarvisd` first and then a fresh, immediate-only, correlated iPhone relay. Siri
writes are never queued for execution after a spoken timeout.

All four archived products report `0.2.0 (20)`, pass deep signature, hierarchy,
entitlement, and synchronized-version audits, and contain exactly the two
dynamic shortcuts in host App Intent metadata. Automated verification passes
with 28 JARVISKit tests/3 live skips, 10 AppState tests, warning-free iOS and
watchOS simulator builds, and repository smoke `PASS=105 WARN=0 FAIL=0`. The
exact parent IPA and archived Watch product are
installed on the two allowlisted devices; both inventories report build 20 and
all four host/widget processes were active after launch. Installation and
read-only launch observation emitted zero mutation POSTs. Per Dylan's request,
no Siri phrase or plug write was physically exercised; owner validation remains
pending.

### Build-19 automatic host refresh

```text
Archive: /tmp/JARVIS-build19-refresh.xcarchive
IPA:     /tmp/JARVIS-build19-refresh-export/JARVIS.ipa
SHA-256: 18ce74f7a5143ecb3912068f9913087980bde87a8706415be64c68f44ad7003e
```

`JARVISRefreshPolicy` now defines one 15-second active cadence for iPhone and
Watch. Both refresh immediately on activation, continue only while visible, and
cancel polling when inactive. iPhone Home refreshes state, services, scheduled
jobs, and health together; Settings performs no polling. Its toolbar button is
removed while pull-to-refresh remains an optional recovery gesture. Watch
refreshes direct-first with automatic iPhone-relay fallback, coalesces concurrent
refreshes, requests a fresh phone snapshot when relaying, and blocks plug writes
while offline. Its normal Refresh status controls are replaced by passive
freshness feedback and a failure-only Retry now action. WidgetKit timelines stay
at approximately 15 minutes.

All four archived products report `0.2.0 (19)`, use the configured Personal
Team, pass deep signature verification, and preserve the required Watch bundle
hierarchy. Verification passes with 21 JARVISKit tests/3 live skips, 8 AppState
tests, warning-free iOS/watchOS simulator builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. The verifier also makes its negative source-contract
checks fail explicitly rather than relying on shell negation under `set -e`.
The exact parent IPA and archived Watch product installed on the two allowlisted
devices; both inventories report build 19 and all four host/widget processes
were active after launch. A 40-second physical observation showed immediate and
approximately 15-second read-only health/state/service/job request cycles. It
emitted no hardware, service, purifier, job, or event mutation POST.

### Build-18 two-tab iPhone cleanup

```text
Archive: /tmp/JARVIS-build18-two-tab.xcarchive
IPA:     /tmp/JARVIS-build18-two-tab-export/JARVIS.ipa
SHA-256: 63f1bcca99ac6773def2739052fe14b51150f2e6d25104c440e2a81403eb6370
```

Build 18 removes only the native Events presentation and polling path. It
deletes `EventsView`, its tab and deep-link route, AppState event UI/cache
fields, and the five-second selected-tab poller. The verifier now locks the
Home/Settings-only navigation contract. The bounded `jarvisd` event-ingest and
event-list APIs remain available for operational audit and compatibility;
hardware, service, widget, Watch relay, and command-safety contracts are
unchanged.

All four archived products report `0.2.0 (18)`, use the configured Personal
Team, pass deep signature verification, and preserve the required Watch bundle
hierarchy. Verification passes with 20 JARVISKit tests/3 live skips, 7 AppState
tests, warning-free iOS/watchOS simulator builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. The exact parent IPA was installed on the allowlisted
iPhone, whose inventory reports build 18; the phone host and widget extension
were active after launch. The Apple Watch intentionally remains on build 17.
Deployment and launch emitted no hardware, service, purifier, job, or event
mutation POST.

### Build-15 aesthetic candidate

```text
Archive: /tmp/JARVIS-build15-aesthetic.xcarchive
IPA:     /tmp/JARVIS-build15-aesthetic-export/JARVIS.ipa
SHA-256: 7247a43441d14f2ebbf7a1a133ef34b41b25217d27c723978b6f96b7d0be6f98
```

All four products report `0.2.0 (15)`. The archive passes deep signature,
bundle hierarchy, synchronized-version, embedded Watch, App Intent, host
`JARVISMark`, and widget `JARVISWidgetIcon` audits. The exported parent IPA and
exact archived Watch product installed successfully on the two allowlisted
physical devices; both inventories report build 15 and both host/extension
processes were observed active. JARVISKit ran 20 tests with
3 physical live tests skipped; AppState ran 7 tests with no failures; iOS and
watchOS simulator builds had no project warnings; repository smoke remains
`PASS=105 WARN=0 FAIL=0`. Light/dark iPhone Home, Events, and Settings plus all
three Watch pages were inspected in simulator. The iPhone accessibility-extra-
large layout remains scrollable without clipped core content; the watchOS 26.5
simulator does not support changing Dynamic Type, so physical Watch text sizing
remains a gate. Deployment and launch produced normal read-only health/state/
service/job requests and no command, service, job, purifier, or event POST.

Physical review then found that the circular Open JARVIS Watch widget reserved
its slot but rendered a blank image. Build 16 makes the resizable image consume
the full proposed accessory frame, resolves it explicitly from the extension
bundle, marks the asset for original rendering, retains watchOS full-colour
accented rendering, and asks WidgetKit to reload the static launcher timeline
whenever the Watch host launches.

### Build-16 Watch launcher correction

```text
Archive: /tmp/JARVIS-build16-watch-launcher-fix.xcarchive
IPA:     /tmp/JARVIS-build16-watch-launcher-fix-export/JARVIS.ipa
SHA-256: 16c05336347365327b64c8c88245e7090a7884e9e2ee8e13c579d9edf8b55f01
```

All four products report `0.2.0 (16)`. Full verification passes with the same
20 JARVISKit tests/3 live skips, 7 AppState tests, warning-free simulator builds,
and `PASS=105 WARN=0 FAIL=0` smoke result. The compiled Watch extension contains
the `JARVISWidgetIcon` rendition without automatic template rendering. The exact
Watch product and parent IPA are installed on the allowlisted devices and both
inventories report build 16. The first parent update waited while the JARVIS
host/widget processes were active; after those processes were terminated
normally, the same explicit upgrade completed. No uninstall, pairing change,
hardware command, or mutation POST occurred. Physical review confirmed that
this remained blank specifically in the three-slot Smart Stack Combination
widget, whose circular complications can use non-full-colour rendering.

### Build-17 three-slot Smart Stack correction

```text
Archive: /tmp/JARVIS-build17-combo-fix.xcarchive
IPA:     /tmp/JARVIS-build17-combo-fix-export/JARVIS.ipa
SHA-256: 8d5c8697a34aff7ef2e91ec521a74d2487095a25c0874b66f8d84517d5f8a234
```

All four archived products report `0.2.0 (17)`, use the configured Personal
Team, and pass deep signature validation. The Watch launcher now branches on
`widgetRenderingMode`: full-colour presentation uses an original-rendering
100×100 Watch `2x` asset, while accented/vibrant presentation uses a separate
high-contrast 100×100 Watch `2x` JARVIS ring rendition marked accentable. The
circular family receives explicit geometry and the launcher kind advances to
`JARVISWatchLauncherWidget.v2` to invalidate the failed cached rendition.
Verification passes with 20 JARVISKit tests/3 live skips, warning-free iOS
and watchOS simulator builds, and repository smoke `PASS=105 WARN=0 FAIL=0`. The exact archived Watch product installed on the
allowlisted Watch, its inventory reports build 17, and both host and widget
extension processes were active. After the old slot was removed and Open JARVIS
was re-added, Dylan physically confirmed the logo appears in the three-slot
Smart Stack Combination widget. No hardware, service, purifier, job, or event
mutation occurred.

### Build-14 physical checkpoint

```text
Archive: /tmp/JARVIS-build14-watch-launcher-icon.xcarchive
IPA:     /tmp/JARVIS-build14-watch-launcher-icon-export/JARVIS.ipa
SHA-256: f9abf05c1b77868c61e841d4d0eca8e33697c4c0e67b372459d1d786d85fcf23
```

All four archived products report `0.2.0 (14)`, use the configured Personal
Team, pass deep signature validation, and include the compiled
`JARVISWidgetIcon` rendition. The exact archived Watch product is installed and
its widget-extension process has been observed active. An automated Watch launch
was once denied because watchOS temporarily prohibited navigation away from the
clock; this was not a signing or installation rejection.

Three build-14 parent-IPA transfers initially did not finish iPhone package
activation, leaving the iPhone on build 13 at that checkpoint; it later activated
build 14 after reconnection. Build 15 and build 16 subsequently installed on both
devices. Do not repeat blind build-14 installs. No plug, purifier, scheduled-job,
or managed-service mutation was emitted during these deployments.

### Remaining release gates

1. Inspect the redesigned physical iPhone Home and Settings screens and all
   three Watch pages in normal and large-text presentation.
2. Inspect the remaining Watch accessory families.
3. Force stale, unknown, and offline widget states and prove writes are blocked.
4. Complete the Watch-originated state request, correlated relay command result,
   timeout, duplicate-request, direct/relay failover, and offline-cache matrix.
5. Complete live Wi-Fi/cellular path switching and Local Network permission
   recovery.
6. Complete physical VoiceOver, Dynamic Type, contrast, and remaining
   accessibility checks.
7. Run the remaining event audit and disposable-service UI smoke, then one final
   verification/deployment pass before `0.3.0`.

The purifier physical write gate remains intentionally incomplete after VeSync
cloud lag and timeouts. The purifier may remain off; do not retry a purifier
write without explicit authorization. The former 30-minute reliability
observation is waived and is not a release task.

---

## 2. Product scope and system boundary

JARVIS is a native SwiftUI control surface over the existing Operation JARVIS
adapters; it does not reimplement hardware protocols.

```text
iPhone app / iPhone widgets / Watch app / Watch widgets
                         │
                    JARVISKit
                         │
                  jarvisd :8790
          ┌──────────────┼────────────────┐
          │              │                │
     cached state     commands       services/events
          │              │                │
  Pi/network files   jarvis-cli     launchctl registry
                         │          jarvisd event store
                  plugctl / purifierctl
```

### Included

- Pi-session, network, daemon, plug, purifier, service, scheduler, and scheduled-
  job status.
- Idempotent plug control and guarded purifier controls in the main app.
- Bounded backend event ingestion and audit storage; no native event-feed UI.
- Server-allowlisted room-audio lifecycle control.
- Read-only Discord-bot and scheduler status.
- Sanitized, dynamic, read-only scheduled-job inventory.
- Direct Watch operation on LAN, iPhone relay when direct access fails, and
  cached stale fallback.
- Open JARVIS, configurable JARVIS Plug, JARVIS Plug Grid, and read-only Air
  Purifier widgets on iPhone and Watch.
- Typed App Intents and `jarvis://home` deep linking.
- LAN and Tailscale access.

### Excluded

- The retired dashboard, room-display HUD, phone-voice PWA, camera/browser APIs,
  Pi/ADB tiles, and port `8787`.
- Weather and Open-Meteo.
- Cast, Spotify, camera, in-app voice/wake word, Raspberry Pi room control, and
  oMLX.
- APNs, Live Activities, and TestFlight while using free provisioning.
- Discord-bot/scheduler mutations and scheduled-job add/remove/edit/setup in the
  current read-only rollout.
- Service, scheduled-job, or purifier controls in widgets; purifier widgets are
  always read-only.

Cast, room audio, Discord voice, Pi telemetry, smart plugs, purifier tooling,
and other Operation JARVIS subsystems continue to exist outside the native app.
The historically named `~/.ssh/jarvis_dashboard_host` key is shared active
infrastructure and must not be deleted as dashboard cleanup.

### Event ownership

There is one user-action event sink:

```text
jarvis-cli action → POST /api/jarvis/events on jarvisd → bounded audit store/API
```

Read-only collectors set `JARVIS_EMIT_EVENTS=0`; idle status polling must not
create lifecycle events. Accepted user writes produce bounded start/complete or
failure events. Native Apple clients do not poll or display the event feed. No
surviving runtime attempts a second dashboard event post.

---

## 3. Project layout and ownership

```text
jarvis-app/
├── README.md
├── docs/README.md              # this unified document
├── project.yml                 # XcodeGen source of truth
├── JARVIS.xcodeproj            # generated; never hand-edit
├── scripts/
│   ├── verify-jarvis-app.sh
│   ├── redeploy-jarvis-app.sh
│   ├── redeploy-jarvis-watch.sh
│   └── patch-watch-embedding.sh
├── jarvisd/
│   ├── jarvisd.py
│   ├── services.json
│   ├── tests/
│   ├── resurrector.sh
│   └── launchd/
├── JARVISKit/                  # models, API client, discovery, cache, WCSession
├── JARVIS/                     # iOS host app
├── JARVISWidget/               # iOS WidgetKit extension
├── JARVISWatch/                # watchOS host app
├── JARVISWatchWidget/          # watchOS WidgetKit extension
└── SharedAppIntents/           # compiled into all host/extension targets
```

Regenerate the project through XcodeGen and retain the post-generation Watch
embedding patch:

```bash
cd /Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app
xcodegen generate
```

`project.yml` and generated `JARVIS.xcodeproj` must remain synchronized. Never
repair packaging by manually editing `project.pbxproj`.

---

## 4. `jarvisd` contract and security

`jarvisd` is a small stdlib Python HTTP daemon managed by
`com.operation-jarvis.jarvisd`; a separate resurrector LaunchAgent health-checks
it and may restart it. The daemon delegates commands to the canonical
`jarvis-cli` with fixed argv and no shell.

### API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Minimal liveness, version, and uptime. |
| `GET /api/v1/state` | Cached network, Pi, plug, purifier, service, freshness, and stale metadata. |
| `POST /api/v1/command` | Allowlisted typed action and parameters. |
| `GET /api/v1/events` | Bounded event history with `since`/`limit`. |
| `POST /api/jarvis/events` | Scoped event ingestion from canonical JARVIS actions. |
| `GET /api/v1/services` | Registered LaunchAgent status and server metadata. |
| `POST /api/v1/services/{name}` | Server-allowlisted start/stop/restart. |
| `GET /api/v1/scheduled-jobs` | Sanitized read-only cron-runner inventory. |

Unknown paths/methods and malformed, scalar, empty, or oversized request bodies
are rejected with bounded JSON errors. Client responses do not expose local
argv, paths, stdout/stderr, secrets, or private hardware identifiers.

### Authentication modes

- `JARVISD_AUTH_MODE=trusted-network` is the zero-tap default. Only source
  addresses in `JARVISD_TRUSTED_CIDRS` are accepted. Configure loopback, the
  current home LAN, and Tailscale ranges as appropriate.
- `JARVISD_AUTH_MODE=token` requires `JARVIS_API_TOKEN` on protected
  `/api/v1/*` endpoints. Starting token mode without a token is an error.
- `/health` remains minimally public.
- `JARVISD_EVENT_TOKEN` authorizes event ingestion only and can never authorize
  state, command, or service access.
- Browser-originated writes and wildcard CORS are not allowed.
- Secret comparisons use constant-time comparison. Never store tokens in Git.

Trusted-network mode trusts allowed network peers; it is not per-user
authorization. Token mode is available when stricter client authentication is
required, but free-team widget extensions cannot inherit the host app's
Keychain token.

### State coordinator

- Expensive subsystem reads run in background, not per HTTP request.
- At most one refresh per subsystem is active.
- Last-good state survives collector failures and is marked stale/error.
- Warm `/state` reads compose directly from cache.
- Successful plug/purifier command results advance authoritative cache
  revisions immediately; older in-flight reads cannot roll back the UI.
- Plug refreshes are fast; purifier refreshes are deliberately slower to avoid
  VeSync rate limits.
- Disconnects and timeouts are bounded and cleaned up.

### Events

- Retain at most 500 logical events.
- Compact persistence atomically and preserve monotonically increasing sequence
  IDs across restart.
- Ignore individual corrupt persisted lines without losing later valid events.
- Service actions and user commands are audited; collector reads are silent.

### Services and scheduled jobs

`jarvisd/services.json` is the server-side authority for labels, plist paths,
display names, sort order, criticality, and `allowedActions`. Service state
separates configured, loaded, running, and PID values. `jarvisd` and its
resurrector are never controllable through this registry.

Current Home runtime order:

1. JARVIS Discord Bot — read-only.
2. Room Audio Server — existing allowlisted lifecycle controls.
3. Scheduled Jobs Runner — read-only.
4. Dynamic scheduled-job inventory.
5. Protected `jarvisd` status card.

Scheduled jobs remain canonical `.pi/discord-cron/runner.py` records, not fake
LaunchAgents. `list-public` output is sanitized again at the daemon boundary.
The app may receive only bounded fields such as ID, name, description, schedule,
enabled state, next/last run, last status, and run count. Prompts, model names,
Discord identifiers, paths, environment values, command lines, database details,
and raw output must never reach the native response.

Any future bot, scheduler, or job mutation requires a separate warning, explicit
authorization, a fixed backend allowlist, confirmation UI, duplicate protection,
and an audit event. Do not stop the Discord bot while the controlling
conversation depends on it, and do not stop the scheduler across an understood
due boundary.

---

## 5. Native app behavior

### iPhone

- **Home:** Pi sessions → plugs → air purifier → services/jobs/`jarvisd`.
- **Settings:** discovery, endpoint override, connection state, and About.
- Health establishes connectivity before the slower state resource is loaded.
- Scene lifecycle owns connection and polling; backgrounding cancels frequent
  work, foregrounding reconnects, and network-path changes trigger rediscovery.
- State, services, scheduled jobs, and health refresh together immediately and
  every 15 seconds while Home is active. Settings performs no background
  resource polling. Pull-to-refresh remains available but is not required.
- Failure in one resource preserves the last successful values from others.
- Missing data renders Loading, Stale, Unavailable, or Unknown—not plausible
  zero/off/stopped values.
- Plug writes always use `plug-on` or `plug-off`, never `plug-toggle`.
- Purifier writes serialize and remain stale/read-only while verification is
  pending; they are never automatically retried.

### Watch

The Watch chooses paths in this order:

1. Direct `jarvisd` access on the home LAN.
2. A correlated `WCSession` relay through the iPhone when direct access fails.
3. Last cached state marked stale when neither path is available.

The versioned Watch message envelope contains `version`, `type`, `requestID`,
`sentAt`, and a typed payload. Message types cover endpoint context, state,
state request, desired-state plug command, command result, and command error.
The iPhone keeps a bounded in-flight/result cache keyed by request ID so a
repeated relay request executes once. The Watch remains pending until a result,
error, or timeout instead of inferring success from a later snapshot.

The iPhone sends the latest endpoint and state through application context.
The Watch refreshes immediately whenever it becomes active and every 15 seconds
while visible, using a single coalesced refresh task. It cancels that task when
inactive. Normal refresh buttons are absent; passive freshness is always shown
and Retry now appears only after an automatic failure. The Watch cannot join the
iPhone's Tailscale client directly, so away-from-home operation relies on the
iPhone relay. Inventory, installed flags, reachability, state delivery, and
command correlation are separate assertions.

### Siri and Shortcuts

The discoverable host surface is deliberately plug-only:

- Turn On JARVIS Plug.
- Turn Off JARVIS Plug.

The plug parameter is a dynamic `AppEntity` sourced from current daemon state,
not the widget's fixed configuration enum. Cached state may help resolve a
spoken name, but only fresh direct or relayed state may authorize a write. The
system is notified when identifiers are added, removed, or renamed. Matching is
normalized but not fuzzy; ambiguity is handed back to Siri instead of guessing.
The widget-only raw intent remains non-discoverable. No purifier, service,
scheduler, status, launcher, or general JARVIS shortcut is published.

### Accessibility and presentation

- Use semantic colors plus text/icon state, never color alone.
- Controls expose roles, labels, hints, current state, and busy state to
  VoiceOver.
- Layouts adapt to accessibility Dynamic Type instead of clipping or preserving
  a forced multi-column layout.
- Dark mode, increased contrast, Reduce Motion, system margins, and minimum tap
  targets remain supported.

---

## 6. Widget catalogue and safety contract

Each platform publishes exactly four current widget kinds. The legacy JARVIS
Plugs and JARVIS First Plug kinds are removed.

### iPhone families

| Widget | Families | Behavior |
|---|---|---|
| Open JARVIS | system small; accessory circular, rectangular, inline | Static `jarvis://home` launcher. |
| JARVIS Plug | system small; accessory circular, rectangular, inline | Configurable approved plug with explicit ON/OFF/STALE state. |
| JARVIS Plug Grid | system medium and large | Separate desired-state controls; medium shows up to four and large up to eight. |
| Air Purifier | system small/medium; accessory circular, rectangular, inline | Read-only PM2.5, quality, power, mode, fan, filter, and stale status as space permits. |

### Watch families

| Widget | Families | Behavior |
|---|---|---|
| Open JARVIS | accessory circular, corner, rectangular, inline | Opens the Watch app; full-colour canonical art except inline system fallback. |
| JARVIS Plug | accessory circular, corner, rectangular, inline | One configurable approved plug. |
| JARVIS Plug Grid | accessory rectangular | All four approved plugs in a compact 2×2 layout. |
| Air Purifier | accessory circular, corner, rectangular, inline | Read-only glanceable status. |

Approved plug choices are Family Room Light, Lamp, Pedalboard, and TV. The Watch
gallery publishes one default selected-plug recommendation; editing that widget
exposes all four choices.

### Data and interaction rules

- Launcher timelines use `.never`; state timelines request refresh about every
  15 minutes, subject to WidgetKit scheduling.
- State becomes stale after 15 minutes or when `jarvisd` marks it stale.
- Stale or unknown plug controls are disabled.
- Only concurrent timeline reads are coalesced. A completed pre-command result
  is never replayed after a write.
- A plug command shows Updating, disables the control, applies confirmed state
  to the extension-local cache, and selectively reloads plug timelines.
- Repeated requests for the same desired state are suppressed for ten seconds.
- Every plug action is explicit `plug-on`/`plug-off`; no widget uses inversion.
- Purifier widgets have no intent or button.
- Non-button areas deep-link to JARVIS Home.

Personal Team provisioning cannot provide App Groups or shared cross-target
Keychain access. Each extension therefore keeps target-local state and directly
discovers `jarvisd`. Widget token-mode credentials are not inherited, and Watch
widgets do not claim iPhone relay support.

The Watch Open JARVIS circular image is scaled to fit, padded by three points,
and clipped to the system circle. Corner and rectangular variants use bounded
circle-clipped artwork. watchOS 11+ requests full-colour accented rendering;
inline retains a legible system glyph because it has no reliable full-colour
image area.

Simulator static rendering, light/dark/increased-contrast previews, and launcher
deep linking are useful, but unsigned Xcode 26 simulator extensions can be
rejected by `linkd` for App Intent execution. Signed physical execution is the
authoritative intent/configuration gate.

Apple references:

- [Widgets — Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/widgets/)
- [Making a configurable widget](https://developer.apple.com/documentation/widgetkit/making-a-configurable-widget)
- [Accessory widgets and Watch complications](https://developer.apple.com/documentation/widgetkit/creating-accessory-widgets-and-watch-complications)

---

## 7. Companion identity, embedding, and signing

### Exact bundle hierarchy

| Product | Bundle identifier |
|---|---|
| iPhone app | `com.operation-jarvis.jarvis` |
| iPhone widget | `com.operation-jarvis.jarvis.widget` |
| Watch app | `com.operation-jarvis.jarvis.watchkitapp` |
| Watch widget | `com.operation-jarvis.jarvis.watchkitapp.widget` |

Do not restore the obsolete `.watch` suffix. All products derive
`CFBundleShortVersionString` and `CFBundleVersion` from shared
`MARKETING_VERSION` and `CURRENT_PROJECT_VERSION`; keep them synchronized.

The built Watch plist must contain:

```xml
<key>WKApplication</key><true/>
<key>WKCompanionAppBundleIdentifier</key>
<string>com.operation-jarvis.jarvis</string>
<key>WKRunsIndependentlyOfCompanionApp</key><false/>
```

`WKWatchOnly` must be absent.

### Canonical target relationship and bundle layout

The iPhone target embeds the Watch dependency on iOS:

```yaml
- target: JARVISWatch
  platforms: [iOS]
  platformFilter: iOS
  embed: true
```

Accepted archive layout:

```text
JARVIS.app/
├── PlugIns/JARVISWidget.appex
└── Watch/JARVISWatch.app
    └── PlugIns/JARVISWatchWidget.appex
```

The copy phase destination is `$(CONTENTS_FOLDER_PATH)/Watch` with
`dstSubfolderSpec = 16`. `scripts/patch-watch-embedding.sh` enforces this after
XcodeGen. `PlugIns/JARVISWatch.app` must not exist.

Important Watch target settings include:

```yaml
PRODUCT_BUNDLE_IDENTIFIER: com.operation-jarvis.jarvis.watchkitapp
PRODUCT_NAME: JARVISWatch
INFOPLIST_FILE: JARVISWatch/Info.plist
GENERATE_INFOPLIST_FILE: NO
ALWAYS_EMBED_SWIFT_STANDARD_LIBRARIES: YES
ASSETCATALOG_COMPILER_APPICON_NAME: WatchAppIcon
GENERATE_PKGINFO_FILE: YES
SDKROOT: watchos
SKIP_INSTALL: YES
TARGETED_DEVICE_FAMILY: "4"
WRAPPER_EXTENSION: app
WATCHOS_DEPLOYMENT_TARGET: "10.0"
```

Do not set `ALLOW_TARGET_PLATFORM_SPECIALIZATION=YES`; it breaks the combined
simulator dependency graph. The canonical artwork source is
`projects/operation-jarvis/jarvis-icon.png`. App icons must be square and opaque.

### Personal Team limitations

- Provisioning expires after roughly seven days and must be refreshed.
- No TestFlight or APNs.
- No App Groups or shared cross-target Keychain entitlements.
- Apple Watch/Bridge may list the app but cannot install a free-profile build
  from that consumer source.
- A passing signature does not prove parent registration, Watch installation,
  installed flags, or reachability.

---

## 8. Verification, archive, and export

### Comprehensive local verification

```bash
cd /Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app
JARVIS_RUN_IOS_TESTS=1 ./scripts/verify-jarvis-app.sh
```

The verifier regenerates the project, runs Python and Swift tests, checks Python,
plist, JSON asset, shell, URL-scheme, icon, widget-kind, App Intent, embedding,
and compiled Watch asset contracts, then builds iOS and watchOS simulators.
Live package tests are opt-in:

```bash
JARVIS_LIVE_TESTS=1 \
JARVISD_TEST_URL=http://127.0.0.1:8790 \
JARVIS_RUN_IOS_TESTS=1 \
./scripts/verify-jarvis-app.sh
```

Before release also run from the repository root:

```bash
./.pi/smoke-test.sh
git diff --check
git status --short
```

Audit the diff for secrets, identifiers, profiles, logs, screenshots, and build
products.

### Signed archive

Use private environment variables such as `TEAM_ID`, `ARCHIVE`,
`DERIVED_DATA`, `EXPORT_PATH`, and `EXPORT_OPTIONS`:

```bash
rm -rf "$ARCHIVE" "$DERIVED_DATA"

xcodebuild \
  -project JARVIS.xcodeproj \
  -scheme JARVIS \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" \
  -derivedDataPath "$DERIVED_DATA" \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  archive
```

Use an uncommitted export-options plist:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>debugging</string>
  <key>destination</key><string>export</string>
  <key>signingStyle</key><string>automatic</string>
  <key>teamID</key><string>YOUR_TEAM_ID</string>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict></plist>
```

```bash
rm -rf "$EXPORT_PATH"
xcodebuild \
  -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -allowProvisioningUpdates
```

### Archive audit

```bash
APP="$ARCHIVE/Products/Applications/JARVIS.app"
WATCH="$APP/Watch/JARVISWatch.app"
PHONE_WIDGET="$APP/PlugIns/JARVISWidget.appex"
WATCH_WIDGET="$WATCH/PlugIns/JARVISWatchWidget.appex"
IPA="$EXPORT_PATH/JARVIS.ipa"

codesign --verify --deep --strict --verbose=4 "$APP"
codesign -d --entitlements :- "$APP" 2>/dev/null
codesign -d --entitlements :- "$PHONE_WIDGET" 2>/dev/null
codesign -d --entitlements :- "$WATCH" 2>/dev/null
codesign -d --entitlements :- "$WATCH_WIDGET" 2>/dev/null
unzip -l "$IPA" | grep 'Payload/JARVIS.app/Watch/JARVISWatch.app/Info.plist'

/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :WKCompanionAppBundleIdentifier' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :WKRunsIndependentlyOfCompanionApp' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIconName' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WATCH_WIDGET/Info.plist"
```

Expected Watch values are `.watchkitapp`, companion
`com.operation-jarvis.jarvis`, `false`, `WatchAppIcon`, and the nested
`.watchkitapp.widget` identifier. Confirm all four products use the intended
team, profiles are unexpired and include the required development devices, and
no App Group entitlement is present.

---

## 9. Canonical free-profile deployment

Use four distinct private selectors:

```bash
PHONE_COREDEVICE_ID=...
WATCH_COREDEVICE_ID=...
PHONE_UDID=...
WATCH_UDID=...
```

CoreDevice identifiers are used by `devicectl`; hardware UDIDs are used by
`ideviceinstaller` and `idevicesyslog`.

### Companion registration and installation

1. Verify, archive, export, and audit one exact product set.
2. Install or upgrade the parent IPA through the iPhone service so CoreDevice's
   skip-Watch flag is not requested:

   ```bash
   ideviceinstaller -u "$PHONE_UDID" install "$IPA"
   ```

3. For a clean install, trust the developer on the iPhone under **Settings →
   General → VPN & Device Management → Developer App**, then launch JARVIS once.
4. Do not use **My Watch → Available Apps → Install**. Free-profile installation
   from Bridge is expected to fail with `MIInstallerErrorDomain Code=111` /
   `ApplicationVerificationFailed`.
5. Install the exact Watch product from the same archive through developer
   services:

   ```bash
   xcrun devicectl device install app \
     --device "$WATCH_COREDEVICE_ID" \
     "$WATCH"
   ```

6. Confirm both inventories, both installed flags, then launch both apps and
   validate messaging.

A first inventory query may be empty while registries synchronize; wait and
retry before changing metadata or reinstalling.

### Iteration helpers

For iPhone-only iteration:

```bash
TEAM_ID=... ./scripts/redeploy-jarvis-app.sh --device "$PHONE_COREDEVICE_ID"
```

CoreDevice deliberately records `Setting skip watch app install flag` for this
route, so it does not prove parent companion transfer/registration.

For Watch-only developer iteration after parent registration:

```bash
TEAM_ID=... ./scripts/redeploy-jarvis-watch.sh --device "$WATCH_COREDEVICE_ID"
```

A direct Watch install by itself is not proof of a valid companion relationship.

---

## 10. Device diagnostics and non-destructive recovery

### Tunnel and inventory

```bash
xcrun devicectl list devices --timeout 30
xcrun devicectl device info details \
  --device "$WATCH_COREDEVICE_ID" --timeout 30
```

The Watch should be paired and booted, with Developer Mode enabled,
`ddiServicesAvailable: true`, and `tunnelState: connected`. A transient
`RemotePairingError 1001` often clears on serial retry; never unpair or erase the
Watch for it.

```bash
xcrun devicectl device info apps \
  --device "$PHONE_COREDEVICE_ID" --timeout 45 \
  | grep -E 'com\.operation-jarvis\.jarvis|JARVIS'

xcrun devicectl device info apps \
  --device "$WATCH_COREDEVICE_ID" --timeout 45 \
  | grep -E 'com\.operation-jarvis\.jarvis|JARVIS'
```

The Watch row must use `.watchkitapp` and the expected build number.

### Installation logs

```bash
idevicesyslog -u "$PHONE_UDID" > /tmp/jarvis-companion-install.log 2>&1
```

After the operation:

```bash
grep -Ei \
  'skip watch|operation-jarvis|watchkitapp|ACX|ApplicationVerificationFailed|MIInstallerErrorDomain|failed|error' \
  /tmp/jarvis-companion-install.log
```

Interpretation:

- `Setting skip watch app install flag` means the CoreDevice iPhone-only route.
- `enumerateLocallyAvailableApplications ... .watchkitapp` means parent
  registration found the embedded companion.
- `MIInstallerErrorDomain Code=111` from Bridge is the expected free-profile
  source restriction.
- `ProfileValidated=true` proves profile validation, but a clean iPhone install
  may still need explicit trust.

Never commit captured logs.

### WatchConnectivity consoles

```bash
xcrun devicectl device process launch \
  --device "$PHONE_COREDEVICE_ID" \
  --terminate-existing --console --timeout 60 \
  com.operation-jarvis.jarvis

xcrun devicectl device process launch \
  --device "$WATCH_COREDEVICE_ID" \
  --terminate-existing --console --timeout 60 \
  com.operation-jarvis.jarvis.watchkitapp
```

Relevant debug prefixes are `[JARVIS WatchBridge iPhone]`,
`[JARVIS WatchBridge Watch]`, and `[JARVIS Watch smoke]`.

### Guarded relay smoke

Force the Watch's direct endpoint to fail so it must relay through the iPhone:

```bash
xcrun devicectl device process launch \
  --device "$WATCH_COREDEVICE_ID" \
  --terminate-existing --console --timeout 100 \
  com.operation-jarvis.jarvis.watchkitapp -- \
  -jarvisSeedEndpoint http://127.0.0.1:9 \
  -jarvisForceEndpoint \
  -jarvisRelaySmokePlug lamp \
  -jarvisRelaySmokeState off
```

Before any physical write: warn the user, confirm canonical current state, send
that same desired state first, prove one correlated result/event pair, perform
at most one reversible change, and restore the original state. Never use
`plug-toggle`; do not test purifier writes during Watch recovery.

### Recovery order

Stop as soon as a gate passes:

1. Confirm the exact bundle hierarchy and synchronized versions.
2. Inspect the built Watch plist, not only source metadata.
3. Confirm complete opaque icon catalogs.
4. Confirm target dependency and `JARVIS.app/Watch/` embedding.
5. Deep-verify nested signatures and device coverage.
6. Run the verifier and signed generic-device/archive build.
7. Check pairing, unlock state, Developer Mode, DDI, and tunnel.
8. Use `ideviceinstaller` when parent registration is the goal.
9. Trust and launch the iPhone app if needed.
10. Install the exact archived Watch app through developer services.
11. Recheck inventories and both installed flags.
12. Launch both apps and validate reachability/state messaging.
13. Run an idempotent relay smoke before one reversible physical write.

Do not infer success from a build, icon, signature, direct Watch install,
`isReachable`, or Bridge listing alone. Remove only JARVIS if an explicitly
approved clean reinstall becomes necessary; never alter pairing records.

---

## 11. Physical validation and release procedure

### Already closed unless related code changes

- Cached-state latency and collector single-flight behavior.
- Daemon auth/input/event/service regression tests.
- Deterministic endpoint discovery priority, fallback, cancellation, and dedupe.
- Cold iPhone launch/relaunch and daemon-restart recovery.
- Cellular/Tailscale cold launch and relaunch.
- Xcode 26 Watch identities, icons, embedding, archive/export, and both installed
  flags.
- Paired-simulator bidirectional state delivery with a write-blocking backend.
- Automated duplicate Watch request-ID single execution.
- Disposable LaunchAgent unloaded → start → stop → start → restart/new PID →
  stop and cleanup.
- All four iPhone plug controls with initial-state restoration.
- Representative direct Watch lamp control with restoration.
- Signed iPhone widget launcher and one-command ON/OFF feedback round trip.
- Watch gallery, one editable selected-plug entry, all-four grid, launcher,
  read-only purifier, and four intentional non-duplicated lamp writes with final
  restoration.

### Remaining consolidated matrix

| Owner | Test | Pass condition |
|---|---|---|
| iPhone packaging | Activate existing build-14 IPA | Inventory reaches build 14 without data loss. |
| Watch launcher | Circular Smart Stack and remaining families | Artwork fits, stays full colour where supported, clips cleanly, and launches. |
| Watch app direct | One representative current-state command | Pending, correlated result, and refreshed state. |
| Watch app relay | Disable direct path and repeat guarded command | iPhone relay returns one result; duplicate request executes once. |
| Watch app offline | Remove direct and relay | Cached state is stale and writes fail/block honestly. |
| Widgets | Force stale/unknown/offline | Controls disable; purifier remains read-only. |
| iPhone networking | Wi-Fi/cellular switch and Local Network deny/re-enable | Automatic recovery and truthful path/error state. |
| Events | Inspect after targeted actions | User actions appear once; collector noise is absent. |
| Disposable service UI | One reversible approved smoke | Correct status, confirmation, action, and event. |
| Accessibility | Physical VoiceOver, large text, contrast, Reduce Motion | Core iPhone/Watch controls remain usable. |

Use underlying canonical CLI/hardware state as truth once per test. Do not
re-prove every surface after every action. Warn before any physical hardware
change, use desired-state actions, and restore the original state. Real bot,
scheduler, scheduled-job, or purifier mutations require separate explicit
permission.

### Final pass before `0.3.0`

1. Finish the remaining physical matrix.
2. Run `./.pi/smoke-test.sh` once.
3. Run `JARVIS_RUN_IOS_TESTS=1 ./scripts/verify-jarvis-app.sh` once.
4. Run the opt-in live JARVISKit suite once.
5. Verify `jarvis-cli --json help` and one safe read-only status path.
6. Run `git diff --check`, inspect repository status, and audit for forbidden
   artifacts or identities.
7. Build from fresh DerivedData and deploy one exact archive to both allowlisted
   devices.
8. Confirm versions and run a brief direct/relay smoke.
9. Bump/release `0.3.0` only after every required row passes.

All commits remain local unless Dylan separately requests a push.

---

## 12. Condensed implementation history

| Milestone/build | Result |
|---|---|
| M0 | Added `jarvisd`, launchd watchdog, JARVISKit, discovery, iOS/watch shells, and free-team deployment. Physical iPhone LAN auto-discovery passed. |
| M1 | Added Home plug/purifier/Pi controls. |
| M2 | Added Events and service lifecycle UI; later consolidated services into Home. |
| M2.1 | Added explicit auth modes, bounded HTTP/event storage, cached single-flight state, reversible services, lifecycle-aware polling, honest stale UI, deterministic deployment, tests, and real WCSession callbacks. |
| Build 8 | Corrected packaging/reliability baseline, companion registration, physical state delivery, and cellular/Tailscale validation. |
| Build 9 | Removed weather/Open-Meteo, reordered Home, removed System tab. |
| Build 10 | Added read-only Discord bot/scheduler and sanitized dynamic scheduled jobs. |
| Build 11 | Replaced legacy widgets with the four-type iPhone/Watch catalogue. |
| Build 12 | Removed completed-result replay, applied confirmed widget state, added Updating feedback and ten-second duplicate suppression. |
| Build 13 | Published one editable Watch plug recommendation and complete all-four 2×2 grid; physical widget tests passed. |
| Build 14 | Added canonical full-colour Watch launcher art and compiled-asset verification; Watch installed, iPhone remained build 13. |
| Build 15 | Unified both host apps under the holographic visual system; added the three-page Watch dashboard and refined iPhone Home, Events, and Settings; physical review exposed a blank circular launcher image. |
| Build 16 | Forces the Watch launcher asset to consume its accessory frame and render full-colour, reloads its static timeline on host launch, and is installed on both devices; the three-slot Combination widget remained blank. |
| Build 17 | Adds exact Watch-scale full-colour and accented launcher assets, rendering-mode selection, explicit circular geometry, and a fresh widget kind; the physical three-slot Smart Stack logo passed. |
| Build 18 | Removes the unused iPhone Events tab, view, deep-link route, UI state, and five-second polling while retaining bounded backend event audit APIs. |
| Build 19 | Gives both host apps a shared immediate-then-15-second foreground cadence, lifecycle cancellation, coalesced Watch refresh/relay fallback, passive freshness, and failure-only retry. |
| Build 20 | Adds exactly two dynamic plug-only Siri shortcuts, fresh-state validation, confirmed desired-state results, duplicate suppression, and immediate-only correlated Watch relay fallback. |

Notable local commits include dashboard retirement (`590f937`), daemon hardening
(`4e47501`), Apple reliability/packaging (`042fdd4`), deployment operations
(`b36877f`), weather retirement (`713a176`), Home service telemetry (`3151ecd`),
widget replacement (`ed5fd1e`), widget feedback correction (`9cf3eb5`), Watch
catalogue correction (`e6ee1fb`), and Watch launcher artwork (`80ef493`).

Historical plans that suggested weather, a System tab, `plug-toggle`, App Group
cache sharing, a `.watch` bundle suffix, `PlugIns/JARVISWatch.app`, dashboard
coexistence, or Bridge installation are superseded by this document.

---

## 13. External references

- [watchOS low-level networking — TN3135](https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos)
- [Preventing insecure network connections](https://developer.apple.com/documentation/security/preventing-insecure-network-connections)
- [Local network privacy discussion](https://developer.apple.com/forums/thread/663858)
- [Apple Developer membership comparison](https://developer.apple.com/support/compare-memberships/)
- [WidgetKit complications — WWDC22](https://developer.apple.com/videos/play/wwdc2022/10050/)
- [WidgetKit widgets — WWDC22](https://developer.apple.com/videos/play/wwdc2022/10051/)
- [Tailscale](https://tailscale.com/)
