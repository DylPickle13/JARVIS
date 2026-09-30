# System dashboard — iPhone and Watch

**Current installed build: 231.** Installed once on each approved iPhone/Watch,
with independent version, launch/process and final-version readbacks on 2026-09-30
at **12:59 EDT**. The signed release uses the exact build-230 source baseline plus
only reviewed sensor-health/history compatibility changes. All four bundles/profiles
and unchanged entitlements/dependencies were audited. Frozen tests: 307 passes,
3 expected skips. Build 230 is the retained rollback; owner-approved cleanup retires
superseded build 229 and sensor-update temporary build data.
Sixteen protected service identities/configuration hashes, tmux panes, credentials
and production database identities were unchanged; no backend/Pi restart or app-data
removal. Physical visual/gesture and actual-device history route acceptance awaits
owner review; localhost cached state and phone/Watch history returned 200.

**Previous checkpoint: build 230.** [System history UI](system-history-ui.md) preserves
the current-check ring and real backend history bands, and removes the extra
history-only missing-token gates. Both device installs, final version and
launch/process readbacks were independently verified on 2026-09-30 at 08:35 EDT.
The signed archive has unchanged entitlements/dependencies; 291 tests pass, with
3 expected live-test skips. Build 229 is the retained app rollback; superseded
227/228 artifacts and temporary build data are approved for cleanup.
No app data removal, backend/Pi-session restarts or duplicate installs. Physical
visual/gesture acceptance awaits owner review. The following is the prior compact
layout checkpoint; navigation and current-health semantics remain unchanged.

**Previous installed checkpoint: build 228**, installation, launch/process and final build readback
independently verified on iPhone and Watch on 2026-09-29 at 19:50 EDT. Exact sealed
signed archive used; all four bundles, unchanged entitlements and device profiles
verified. 267 tests pass, with 3 expected live-test skips. The overview fits one
screen without scrolling; detailed observations open separately. Build 227 is
retained for rollback.

The owner requested this smaller, Home-style design after reviewing build 227.
The Watch developer connection dropped before its install step; read-only checks
re-established it, then only the pending Watch installation resumed. Neither
app was installed twice. No app data removed, backend services or Pi sessions
restarted. Physical layout/gesture acceptance awaits owner review.

## Sensor-inclusive update (build 231)

Installed on both clients after backend release `20260930T153603Z-sensor-health`.
Shared `StateSnapshot` now preserves the sanitized cached health
summary through existing current-state serialization and confirmed plug projection.
No new endpoint, polling loop, foreground lease, credential setup or relay is added.

- Sensor status-read availability contributes a current ring segment and aggregate
  badge. Failed reads are issues; unchecked/expired/malformed evidence is unknown.
  Disabled/unconfigured monitoring is inactive, not an invented successful read.
- Absolute backend `validUntil` expires positive evidence locally; fresh receipt,
  generation or cache-write time cannot renew it. Missing/future timestamps fail
  closed. Sensor age labels describe status-read attempts, never failed attempts
  mislabeled as last-good reads. Availability is not radio freshness or home security.
- Backend overall failure/uncertainty cannot be overridden by local green; existing
  collector expiry, service requirements and periodic completion rules still win
  over an optimistic backend summary. Underlying issues are not double-counted.
- Watch retains six integration chips: **Sensors** uses the former service-data
  slot. Service rows remain in the Services panel; full service-data metadata stays
  in the integration inspector. Phone retains full integration details; overview and sheet
  input ownership, navigation and lifecycle gates are unchanged.
- Unknown raw states/reasons, malformed dates and unsupported component identifiers
  are not serialized into the new health field. Bad optional health data cannot
  break existing state/control decoding. Older hosts lacking `health` retain their
  original six-collector scope; no sensor evidence is invented for them.

Validation: **307 app tests passed, 3 expected live-test skips** (251 package
executed, including 3 skips; 59 iOS AppState/dashboard tests). Watch simulator build
passed. Normal/accessibility Watch and phone portrait/landscape layouts fit without
an overview scroll view; inspected synthetic light/dark attachments include sensor
success/failure. The Swift client validated live sanitized cached health and 1h/24h/7d
history, plus Watch overall and security drilldowns. These localhost/simulator checks
are not physical-device UI, route or gesture acceptance. Physical installation,
version and launch/process were independently verified as recorded above.

## Navigation

- iPhone: Home → **System** → JARVIS → Jobs → Settings. `jarvis://system`
  opens System. The former Home system-health disclosure is removed; other
  Home cards, including oMLX, remain in place.
- Watch top-to-bottom: **System → Terminal → Plugs → Overview → Jobs**.
  Terminal is still the default. Swipe **down** on its terminal face to open
  System, then **up** on System to return. Neither end wraps.
- The old Watch System page is now Overview, retaining its purifier, Codex and
  oMLX content and visibility-triggered refresh behavior. Jobs returns to Overview.
- System has no overview pan/Crown scrolling. The existing Overview and Jobs
  pages retain their Crown viewports; Terminal retains slot gestures and history.
  Detail sheets can scroll so technical text remains readable.

## Home-style, one-screen presentation

The large Grafana-style stat tiles and individual panels introduced in build 227
are replaced with quiet, rounded Home-style cards: health summary, compact service
rows, and integration status rows. No overview scrolling and no inline expansion.

- iPhone uses Home's purple palette/backdrop, 14pt rounded surfaces, and compact
  rows with status badges and last-good observation ages. `ViewThatFits` selects
  a denser grid on smaller/large-text screens or side-by-side cards in landscape.
- Watch shows a compact health header, its two registered services, and a 2×3
  integration grid. Whole-card taps open readable service/integration sheets.
  Backend response failures stay prominent in the aggregate header and details.
- Service panels remain issue-first. Larger inventories have an explicit all-
  services entry/count; they cannot silently lengthen or overflow the overview.
- Metadata, descriptions, connection errors, full freshness explanations, uptime,
  backend version and PID/exit information move to detail sheets. Those sheets
  retain scrolling for long technical text and uncapped semantic text styles.
- Pull-to-refresh is replaced by a small iPhone header refresh button, keeping the
  same cached-state/reconnection policy. Watch overview entry adds no requests.

No historical readings, traffic rates, or resource-utilisation graphs are
fabricated. Status symbols supplement colour and provide full accessibility
labels. The existing health/freshness classification is unchanged.

The inventory dynamically reflects `subsystems.services.services` in the existing
state response. `jarvisd/services.json` currently registers Room Audio Server and
Scheduled Jobs Runner. This UI change does not discover or register other launchd
services. Adding a broader daemon inventory is separate backend work.

## Health and refresh policy

- Existing classification remains authoritative: required continuous services
  must run; loaded scheduled services idle after successful checks are healthy;
  optional stopped services are inactive; failed scheduled completions remain
  issues even if the next run is active.
- Missing, stale or failed service collector metadata keeps the cached service
  inventory visible, with **current status unverified**, never a green process
  claim. Last-observed registration/PID/exit information is labelled accordingly.
- Offline dashboards show unverified services/subsystems, not current health.
  The overall summary covers collector issues as well as services; detail-sheet
  service counts explicitly count services only.
- iPhone System entry/connection/header refresh reads cached state. It remains
  on the existing passive-tab cadence and does not activate Home's device/cloud
  refresh policy, service diagnostics, recovery, or control endpoints.
- Watch consumes `WatchConnectModel.lastState` through the established refresh
  loop/phone relay. Opening this new page adds **no network requests**. Its local
  freshness clock uses `generatedAt`, not relay receipt or disk-save time, so
  delayed snapshots cannot rejuvenate stale readings. Missing/future timestamps
  remain unverified.
- Timeline redraws stop when hidden/inactive and use the actual render-time clock.
  No service start/stop/restart actions, notifications, or backend changes.

## Validation

- JARVISKit: 215 tests executed, 3 expected live-test skips, zero failures.
- iOS simulator: all 50 AppState tests and 5 dashboard layout/render tests pass.
  Natural overview extents fit 375×650 and 414×720 phone viewports, 320×450 small
  phones, 750×270 landscape, and 375×650 accessibility text. Watch content fits
  162×197 at normal/accessibility text. Tests also reject mounted overview scroll
  views. These are content-layout checks, not physical Watch gesture acceptance.
- iPhone and standalone Watch simulator builds compile with Xcode 27.
- Fixture-only light/dark/offline images are retained in local test results.
  Raster tests reject empty/black images. No live endpoint is used by those tests.
- Dashboard/pager/visibility source contracts and shell syntax checks pass.
  The broader legacy verifier stops at a pre-existing backend oMLX assertion
  expecting a literal inline `/admin/api/activity` request where the backend
  now passes `path` through a shared helper; backend code is untouched. A Jobs
  polling fixture race was corrected by waiting for its initial Home refresh to
  finish before measuring Jobs-only requests.
- Physical installation, version readback and launch/process checks succeeded
  on both devices for build 228. Owner acceptance of the no-scroll layout, sheet
  taps and header refresh remains pending. No backend services or Pi sessions
  were restarted.

## Sources

- `JARVIS/Views/SystemView.swift`
- `JARVISKit/Sources/JARVISKit/SystemDashboardPresentation.swift`
- `JARVISKit/Sources/JARVISKit/SystemDashboardContent.swift`
- `JARVISKit/Sources/JARVISKit/SystemHealthPresentation.swift`
- `JARVISKit/Sources/JARVISKit/WatchDashboardPage.swift`
- `JARVISWatch/Views/WatchSystemHealthView.swift`
- `JARVISWatch/Views/WatchDashboardContent.swift`
- `JARVISWatch/Views/WatchTerminalView.swift`
