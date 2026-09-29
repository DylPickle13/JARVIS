# System dashboard — iPhone and Watch

**Installed: build 228**, installation, launch/process and final build readback
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
