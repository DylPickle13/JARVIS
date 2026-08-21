# Operation JARVIS app — integration-aware next steps

**Revised:** 2026-08-20
**Installed build:** 0.2.0 (10) on iPhone and Watch
**Local candidate:** 0.2.0 (10)
**Goal:** finish the remaining M3 physical matrix, run one final verification pass, and release 0.3.0.

## 1. Current system boundary

The native app is not a replacement for all of Operation JARVIS. It is one control surface over the existing canonical adapters:

```text
iPhone app / iPhone widget / Watch app / Watch widget
                         │
                    JARVISKit
                         │
                  jarvisd :8790
          ┌──────────────┼──────────────┐
          │              │              │
  cached state       commands       services/events
          │              │              │
  Pi runtime files   jarvis-cli      launchctl registry
  network state          │           jarvisd event store
                    plugctl / purifierctl
```

`jarvisd` is the sole control plane **for native Apple clients**. It intentionally delegates hardware operations to the existing `projects/operation-jarvis/jarvis-cli`, smart-plug, and air-purifier subsystems instead of reimplementing them.

The deprecated Node/PWA dashboard has now been **completely removed**. Its room HUD,
phone voice, Pi/ADB tiles, camera/browser APIs, event view, PWA, LaunchAgent, and
`:8787` listener were retired without replacement. The native app does not absorb
those excluded features.

The final event flow has one sink:

```text
jarvis-cli action → jarvisd /api/jarvis/events → native app Events
```

`jarvisd` background collectors set `JARVIS_EMIT_EVENTS=0`; user commands retain
lifecycle events. No surviving runtime depends on `:8787`.

## 2. Completed checks that will not be repeated

The following are already closed unless relevant code changes again:

- iPhone cold terminate/relaunch and daemon-restart recovery.
- Warm cached-state latency measurement.
- Physical iPhone and Watch installation and launch.
- Watch pairing, Developer Mode, DDI services, and tunnel preparation.
- Embedded Watch/widget packaging, archive/export, installation, final icons,
  inventory, and both WatchConnectivity installed flags.
- Dylan-only deployment refusal checks.
- Current daemon, Swift package, simulator, live-integration, and AppState test baselines.
- Local paired-simulator state delivery over WatchConnectivity with a
  write-blocking mock backend.
- Automated duplicate Watch request-ID single-execution coverage.
- Real disposable LaunchAgent lifecycle gate: unloaded → start → stop → start →
  restart with a new PID → stop, with exactly one successful temporary event
  per action and complete cleanup.
- Deterministic discovery priority, fallback-after-higher-failure,
  early-return, deduplication, and cancellation tests; the discovered
  lower-priority-success race is fixed.
- iPhone simulator Home smoke at maximum Dynamic Type, dark appearance,
  increased contrast, and Reduce Motion against a write-blocking mock; the
  status, purifier, and plug layouts now switch to accessibility-safe
  vertical/single-column presentation. Physical VoiceOver and Watch checks
  remain open.

Do not spend another pass re-proving these before addressing the open integration defects.

## 3. Integration review findings

### P0 — background reads pollute both event systems — complete

`jarvisd` collectors now pass `JARVIS_EMIT_EVENTS=0` to read-only CLI
subprocesses. Targeted regression coverage proves collector reads remain silent,
while a user command emits one `action.start`/`action.complete` pair to
`jarvisd` only.

### P0 — Watch relay contract — implementation complete; physical gate pending

The pre-fix bridge carried request IDs but did not return a command result/error, deduplicate request IDs, or apply the endpoint included in application context. The Watch also cleared its busy state immediately after sending a relayed command and could only infer success from a later state update.

**Implementation complete:** the Watch applies endpoint context, receives typed
`commandResult`/`commandError` replies, remains pending through timeout, and the
iPhone maintains a bounded in-flight/result cache keyed by request ID. The iPhone
sends the result only after the `jarvisd` command returns. Physical direct/relay
validation remains in the consolidated matrix below.

### P0 — Watch companion packaging/deployment — complete; physical relay pending

The investigation separated build, registration, installation, and messaging:

- the Watch app and widget use the exact `.watchkitapp` hierarchy;
- `WKApplication=true`, the iPhone companion ID,
  `WKRunsIndependentlyOfCompanionApp=false`, and complete opaque icon catalogs
  are present; `WKWatchOnly` is absent;
- the corrected XcodeGen target relationship embeds the Watch app under
  `JARVIS.app/Watch/`, and Xcode archive/export accepts it;
- CoreDevice iPhone installation sets a skip-Watch flag, so the parent IPA is
  installed through `ideviceinstaller` when registration is under test;
- Apple's Watch app lists JARVIS but cannot install a free-profile app from its
  Bridge source (`MIInstallerErrorDomain Code=111`);
- after parent registration, installing the exact embedded Watch product via
  the developer service succeeds;
- iPhone now reports `paired=true installed=true`, and Watch reports
  `companionAppInstalled=true`;
- JARVIS `0.2.0 (10)` is installed on both devices from the same verified
  archive with the requested icon;
- physical consoles confirmed `reachable=true`, acknowledged repeated
  iPhone-to-Watch state delivery, and preserved both installed flags;
- removing the unnecessary `ALLOW_TARGET_PLATFORM_SPECIALIZATION` setting
  fixed combined simulator/package builds without changing signed physical
  packaging;
- a paired simulator with a write-blocking mock reached both directions and
  delivered state; duplicate request IDs are also covered by an AppState unit
  test.

Installed flags, bidirectional reachability observation, and acknowledged
iPhone-to-Watch state delivery are closed. A forced Watch-originated state
round trip, correlated relay command result, timeout, and offline behavior
remain open. Do not repeat bundle-ID, icon, `Watch/` embedding, Available Apps,
or Bridge-source experiments. The operational record is
[`watch-companion-packaging-deployment-and-recovery-2026-08-20.md`](watch-companion-packaging-deployment-and-recovery-2026-08-20.md).

### Physical hardware findings now closed

- All four iPhone plug controls were exercised with desired-state writes and
  restored to their starting states. The test exposed an immediate
  command/cache race; successful command results now update authoritative cache
  revisions, and older in-flight collector results cannot revert the UI.
- Native command responses are filtered to bounded typed fields and no longer
  expose adapter arguments, local paths, stdout/stderr, or private hardware
  identifiers.
- Direct Watch control passed with the representative lamp and restored it off.
- Purifier writes exposed VeSync cloud lag: accepted writes stayed stale and a
  later attempt timed out without an explicit HTTP 429. Pending writes are now
  represented as stale/read-only with bounded verification, but physical
  purifier validation is intentionally incomplete. The purifier remains off;
  do not retry writes unless explicitly requested.

### Home simplification — weather retired; services consolidated

Weather was removed from the native state model, Home UI, daemon collectors,
cache schedule, and external Open-Meteo request path. Home now presents Pi
sessions, plugs, then the air purifier. The registered service cards and
`jarvisd` information moved to the bottom of Home, Home owns their polling and
refresh, and the dedicated System tab/view were removed. This is a contract
removal rather than a hidden weather card; older snapshots with an extra weather
field remain harmless because Swift decoding ignores unknown fields.

### Physical cellular/Tailscale finding — cold launch and relaunch pass

With iPhone Wi-Fi disabled, cellular data active, and Tailscale connected, build
8 reached `jarvisd` through the Mac's Tailscale userspace proxy. The daemon saw
successful `/health` and `/api/v1/state` reads from the proxy rather than the
home-LAN client address. A terminate/relaunch immediately repeated successful
health and state polling, proving that the selected Tailscale endpoint persisted.
No command endpoint was called. Live path-change/foreground recovery and Local
Network permission behavior remain in the matrix.

### P0 — widget behavior — implementation complete; physical gate pending

With Personal Team signing, App Groups and cross-target shared Keychain access are unavailable. Each widget therefore uses its own direct `jarvisd` discovery path; it does not actually consume the main app’s cache/config. Token-mode widgets cannot inherit the app token under this profile.

The pre-fix Watch complication chose the first sorted plug without saying so, and widget buttons derived the opposite desired state from potentially stale data.

**Implementation complete:** widget writes are disabled for stale/unknown displayed
state; explicit desired-state intents remain non-inverting; the Watch complication
is named and described as controlling the first configured plug; and the free-team
lack of shared cache/token/relay support is documented. Physical widget and
complication validation remains in the consolidated matrix below.

### P0 — completely remove the deprecated dashboard — complete 2026-08-20

Complete removal was executed, not deferred. The dashboard-only HUD, phone voice,
camera/browser APIs, Pi/ADB tiles, event view, and PWA were retired without
replacement. No compatibility server, redirect, stub package, renamed archive
directory, or disabled dashboard LaunchAgent remains.

#### A. Cut over surviving dependencies first

1. Change `jarvis-cli`/`jarvis.py` to emit lifecycle events only to `jarvisd`.
2. Keep `POST /api/jarvis/events` as the stable ingest contract, but rename dashboard-specific helpers and flags to neutral JARVIS names.
3. Replace the `JARVIS_DASHBOARD_WRITE_TOKEN` fallback with the ingest-only `JARVISD_EVENT_TOKEN`; do not retain dashboard environment aliases.
4. Migrate any still-needed private Raspberry Pi, room-audio, or oMLX values to their canonical non-dashboard environment names before removing `JARVIS_DASHBOARD_*` keys.
5. Silence read-only `jarvisd` collectors so status refreshes do not generate events.

#### B. Remove runtime and service ownership

1. Unload `com.operation-jarvis.dashboard` through launchd.
2. Remove `~/Library/LaunchAgents/com.operation-jarvis.dashboard.plist`.
3. Stop only any remaining process whose executable/cwd belongs to `projects/operation-jarvis/dashboard`; do not kill unrelated Node processes.
4. Verify no listener remains on TCP port `8787` and a request to it fails.
5. Remove the `dashboard` entry from `jarvis-app/jarvisd/services.json`, then verify the iPhone Home services section no longer offers it.
6. Remove dashboard-only logs, caches, generated camera artifacts, and Node dependencies after confirming none are shared.
7. Remove the dashboard PWA/shortcut from its former client device and revoke its browser microphone/camera permissions and any insecure-origin exception.

#### C. Remove source, APIs, and tool contracts

1. Delete the complete tracked `projects/operation-jarvis/dashboard/` tree, including server, PWA assets, service scripts, package manifests, lockfile, and dashboard docs.
2. Remove dashboard camera actions (`look`, `photo`, `video`, `video-until`, `analyze-view`) and dashboard URL/timeout/quality parameters from `jarvis.py`.
3. Remove the same actions and parameters from `.pi/extensions/45-jarvis.ts`, plus dashboard/camera guidance from lazy-tool schemas and prompt snippets.
4. Remove dashboard status/camera/voice/event client code, port `8787` probes, LaunchAgent labels, package checks, and dashboard-specific test fixtures everywhere outside historical Git history.
5. Rename remaining comments that call generic Pi session telemetry “dashboard telemetry”; keep the telemetry because `jarvisd` consumes it.
6. Remove dashboard nodes and paths from the Operation JARVIS website architecture diagram.

#### D. Remove configuration and operational documentation

1. Remove dashboard-specific keys from the private root `.env` without printing values.
2. Remove all `JARVIS_DASHBOARD_*`, dashboard phone/voice/camera settings, and port `8787` examples from `.env.example`.
3. Add the non-secret `JARVISD_*` contract and `JARVISD_EVENT_TOKEN` placeholder to `.env.example`.
4. Update root `README.md`, `projects/operation-jarvis/README.md`, `.pi/docs/PI_EXTENSIONS.md`, `.pi/docs/REBUILD_FROM_SCRATCH.md`, `.pi/smoke-test.sh`, voice/room-audio docs, and app docs to describe the dashboard-free architecture.
5. Historical research may mention the retired dashboard only when clearly marked historical; it must contain no active runbook instructions or live links to deleted files.
6. Remove Node.js requirements only if no other surviving repository component needs them.

#### E. Preserve shared assets that merely have historical names

Do **not** delete `~/.ssh/jarvis_dashboard_host`: despite its filename, it is an active shared SSH credential used by Raspberry Pi, Minecraft, and other trusted hosts. Renaming that credential is a separate guarded migration, not dashboard deletion. Also preserve Pi session heartbeat files, `.pi/extensions/46-local-pi-session-status.ts`, Discord voice, room audio, Cast, smart-plug, purifier, and `jarvisd` functionality.

#### Complete-removal gate

The complete-removal gate passed:

- [x] launchd has no `com.operation-jarvis.dashboard` service or plist;
- [x] nothing listens on port `8787`;
- [x] `projects/operation-jarvis/dashboard/` no longer exists;
- [x] `jarvisd/services.json` and the app Home services section contain no dashboard service;
- [x] `jarvis-cli --help` and the Pi `jarvis` tool expose no dashboard/camera actions;
- [x] no operational code references `JARVIS_DASHBOARD_*`, the dashboard LaunchAgent label, dashboard API routes, or port `8787`;
- [x] no dashboard package, PWA, service worker, logs, cache, or generated dashboard-camera artifacts remain on this Mac;
- [x] all action events reach `jarvisd` without attempting a second sink;
- [x] `jarvisd`, `jarvis-cli`, Discord voice, room audio, Cast, plugs, purifier, Pi telemetry, iPhone, Watch, and widgets remain supported.

### P1 — startup redundant state request — complete

The Home polling scheduler now waits for its first interval after the successful
initial state fetch. Tab changes with no loaded data retain their immediate
refresh behavior. Simulator XCTest coverage confirms one initial Home fetch.

### P1 — top-level ownership documentation — complete

`README.md`, the Operation JARVIS service map, `.env.example`, Pi extension
references, rebuild runbook, and smoke test now describe the native
Apple/`jarvisd` ownership model and single event sink. Dashboard-only duplicate
probes and telemetry paths were removed; Pi session telemetry remains because
`jarvisd` consumes it.

---

## 4. Revised execution plan

### Phase A — completed removal; remaining integration corrections

Completed once:

1. Routed Operation JARVIS events only to `jarvisd` and silenced background collector events.
2. Unloaded the dashboard LaunchAgent and removed its service registry entry.
3. Removed the dashboard source, APIs, camera/tool actions, PWA/runtime artifacts, configuration, and operational references.
4. Updated root/Pi/app docs, smoke checks, diagrams, and environment examples.
5. Passed the complete-removal gate without repeating it in the Apple-device matrix.

Remaining targeted work:

6. Run the physical Watch reachability/state/relay/offline matrix against the now-registered build.
7. Run the physical widget/complication matrix against the completed stale-state implementation.
8. Run the remaining failover, disposable-service, event-audit, and accessibility rows. Inspect duplicate/event behavior only during those targeted checks; the separate timed observation is waived.

Run only targeted unit tests during these fixes. Do not run the full build matrix after every item.

**Exit:** all behavior required by the physical matrix exists below the UI layer.

### Phase B — one consolidated physical matrix

Each behavior has one owning test; other surfaces receive a representative smoke test rather than repeating the full hardware matrix.

| Owner | Test | Pass condition |
|---|---|---|
| `jarvisd` + `jarvis-cli` | Observe idle collectors | No new status/list lifecycle events |
| iPhone app | Cellular/Tailscale cold launch and relaunch (pass); launch before Wi-Fi, live foreground recovery, and Local Network permission remain | Automatic recovery and truthful error/path state |
| iPhone app | Every plug once (complete); do not retry purifier writes | Serialized desired-state writes, authoritative cache updates, and visible failures; purifier gate recorded incomplete |
| iPhone app | Disposable service Stop → Start → Restart | Reversible action and one terminal service event per action |
| Watch app direct | One representative plug Off → On on home LAN | Direct path, pending state, result, and refreshed state |
| Watch app relay | Make direct path unavailable and repeat one representative write | iPhone relay returns correlated result; duplicate request ID executes once |
| Watch app offline | Remove both direct and relay temporarily | Cached state is marked stale and writes are blocked/fail honestly |
| iPhone widget | One representative explicit desired-state write | Direct `jarvisd` call succeeds and timeline refreshes |
| Watch complication | One representative direct write | First configured plug identity is explicit, stale writes are blocked, and timeline refreshes |
| Events | Inspect events after the tests above | User actions are visible in `jarvisd`; collector noise is absent |
| Accessibility | VoiceOver, largest Dynamic Type, dark mode, Reduce Motion | Core iPhone and Watch controls remain usable |

Use the underlying `jarvis-cli`/hardware status once as the canonical truth source. Do not separately compare every Apple surface against every subsystem after each action.

### Phase C — reliability observation waived

The former 30–60 minute reliability observation is explicitly waived and is
not a release task. Retain the focused automated coverage and inspect for event
floods, duplicate writes, reconnect loops, excessive polling, and misleading
fresh state during the remaining targeted physical checks only.

### Phase D — one final verification and deployment pass

After all fixes and physical checks:

1. Run the updated repository `.pi/smoke-test.sh` once.
2. Run `scripts/verify-jarvis-app.sh` once.
3. Run the opt-in live JARVISKit integration suite once.
4. Verify `jarvis-cli --json help` and a safe read-only status path without retired-service errors.
5. Run `git diff --check` and inspect for secrets, device IDs, profiles, logs, or build products.
6. Build from fresh DerivedData and deploy once to Dylan’s iPhone and Watch.
7. Confirm the installed release candidate and run a brief direct/relay smoke test.

This replaces the former baseline, per-fix full suite, per-commit full suite, and release full suite duplication.

### Phase E — split the working tree — complete

The broad implementation was organized into reviewable local commits:

1. `590f937` — retire the dashboard runtime;
2. `4e47501` — harden the native `jarvisd` control plane;
3. `042fdd4` — complete reliable iPhone, Watch, widgets, packaging, and icons;
4. `b36877f` — record companion deployment and release operations.

The comprehensive suite remains owned by Phase D; do not repeat it solely for
commit organization.

### Phase F — close M2.1/M3 and release 0.3.0

- Mark M2.1 complete after the remaining iPhone rows pass.
- Mark M3 complete only after direct Watch, relay, offline cache, widgets, and duplicate-request protection pass physically.
- Document free-profile limitations: no App Group cache, no shared widget token, and no Watch-widget phone relay.
- Bump to 0.3.0 and the next build number only after the gate passes.

## 5. M4 after the consolidated gate

1. Publish the existing typed plug intents cleanly to Shortcuts/Siri.
2. Validate Watch-app relay through the iPhone over Tailscale/cellular away from home.
3. Improve direct/relay path indicators and concise command confirmations.
4. Revisit paid signing only if shared widget caches, shared credentials, APNs, or longer provisioning are worth it.

The deprecated dashboard and its room HUD, phone voice, camera/browser APIs, and Pi/ADB tiles are removed before M4. Spotify, Cast, camera, in-app voice/wake word, APNs, Live Activities, room HUD, Discord process control, Pi room control, and oMLX remain outside the native app’s scope.

## 6. Immediate order

1. With both physical apps foregrounded, repeat the forced-direct-failure test
   until the Watch-originated state request completes; baseline
   `reachable=true` and acknowledged iPhone-to-Watch state delivery already
   pass on the current companion registration.
2. After warning the user, run idempotent `lamp off`, prove exactly one correlated result/event pair, then perform and restore one reversible relay change.
3. Complete Watch offline/stale and iPhone/Watch widget/complication rows.
4. Complete the remaining live path-change/Local Network recovery,
   disposable-service, event-audit, and accessibility rows; cellular/Tailscale
   cold launch and relaunch already pass.
5. Run the final comprehensive verification from fresh build state.
6. Release 0.3.0 if every required row passes; the implementation is already
   split into reviewable local commits.
