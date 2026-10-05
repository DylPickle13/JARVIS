# System dashboard — iPhone and Watch

**Navigation update:** the health card lives at the top of iPhone **Home**, above
plugs and purifier. The restored Watch **Home** contains health only; Plugs has
a dedicated page, while purifier returns above Codex/oMLX on JARVIS.
Build 252 keeps **Minecraft** as its own health-card check and read-only server/bot
detail. **Services** now excludes those two rows; neither list duplicates the other.
Watch Home supports Crown overflow for large text.
See [navigation and Home](navigation-and-home.md) for the verified rollout and pending physical acceptance.
The build-specific records below retain their original navigation context.

## Read-only Services detail (installed build 250)

The Home **Services** indicator now delegates a platform-owned sheet on iPhone
and Watch. Shared `SystemServicesContent` renders every named service from cached
state, including the new optional continuous **Minecraft Server** and
**Minecraft JARVIS Bot** rows. There are no start/stop/restart buttons, direct
Minecraft connections or dedicated service polls in either client.

The phone list includes status, age, requirement/mode, description and technical
evidence. Watch uses compact status/age rows and the existing Crown viewport for
overflow. A small chevron identifies the Services action; the closed health card
still fits one screen, including the seven-group/small-Watch fixtures. Platforms
retain sheet, gesture, Crown and lifecycle ownership; covered history polling
pauses. The service sheet reevaluates cached freshness while visible and cannot
rejuvenate stale snapshots received from the phone or disk.

Optional `ready` / `readinessReason` fields distinguish a running-but-disconnected
bot or unavailable Pi agent from a stopped process. A probe failure is unverified,
not false proof of stopping. Legacy services remain compatible. Process/readiness
technical evidence shown while stale/offline is labelled cached.

See the [backend contract and deployment gates](../../jarvisd/docs/minecraft-services.md).
The owner-approved backend activated **2026-10-04 at 23:55 EDT**; sealed signed
build **250** was installed once on each allowlisted device and independently
version/launch/process verified at **23:56 EDT**. Frozen validation passed 175
iPhone tests, 311 shared Swift cases (3 expected skips), 37 terminal contracts and
both simulator builds; four candidate and four exact rollback-249 bundles passed
signature/profile/unchanged-entitlement audits. Fresh dual-device checks passed
before activation and again immediately before installation.

Live observation showed Paper running with its verified Java listener and the bot
stopped. Neither Minecraft process changed. The separate backend deployment cycled
only jarvisd/watchdog; the app installer preserved all 18 protected service records
and existing Pi identities. Exact rollback 249 and the prior backend are retained.
Physical list/gesture/Crown/VoiceOver acceptance is pending owner review. Historical
build records below retain their original scope and navigation context.

## Minecraft list deduplication (installed build 252)

Owner review found that build 251's **Services** detail still repeated the two
Minecraft rows despite the separate Minecraft check. The correction makes the
read-only lists disjoint on both platforms: **Services** contains non-Minecraft
rows; **Minecraft** contains only **Minecraft Server** and **Minecraft JARVIS Bot**.
The default list scope is Services, so callers cannot accidentally restore the
combined list. Filtering uses only the two exact registered IDs, not names or
prefixes; unrelated services and legacy hosts retain their inventory.

Complete cached/backend inventory and overall-health evidence are retained. Missing
Minecraft members remain unknown placeholders in Minecraft only; offline/stale/
expired/failed observations remain unverified. No requests, collector cadence,
lifecycle controls, backend registrations or Crown/input ownership change.
Validation passed **323 shared cases (3 expected live-test skips)**, **177 iPhone
tests**, both simulator builds and the source/terminal contracts, including disjoint
scopes, safe defaults, preserved statuses/evidence and compact/accessibility layouts.
An early read-only Watch resource-allocation failure stopped preparation without
writes. After the owner said ready, fresh dual-device identity/pairing/developer-
service/unlock/baseline checks passed. The iPhone installed 252 once, but a second
Watch readiness failure stopped the initial attempt before its Watch write.
Read-only inventory independently confirmed iPhone 252 / Watch 251. A reviewed
Watch-only continuation repeated **both** devices' fresh mixed-baseline checks and
completed the first/only Watch install without replaying/reinstalling the iPhone.

Both versions and running processes independently verified **252 on 2026-10-05 at
17:23 EDT**. Frozen source/payload seals, eight candidate/rollback bundle signatures,
unchanged profiles/entitlements/dependency pins, all 18 protected service records,
existing Pi panes, backend/config/authentication/registry and Minecraft/gateway/Pi
identities, and 10-second history cadence passed final verification. Signed rollback
**251**, historical archives, failed-readiness/partial receipts, unsigned/frozen
validation results and caches remain intact. No backend/Minecraft lifecycle action,
uncertain-write retry, reboot/recovery, credential/provisioning change or pruning
occurred. Physical disjoint-list/Crown/VoiceOver acceptance remains owner review.

## Dedicated Minecraft health-card check (installed build 251)

The owner-requested follow-up gives **Minecraft** its own indicator on iPhone and
Watch Home, beside **Services**. Tap Minecraft for just **Minecraft Server** and
**Minecraft JARVIS Bot**, with independent status/age/readiness evidence. Services
still opens the full inventory, but its card indicator/accessibility evidence no
longer folds in the Minecraft rows. The normal device-inclusive card has eight
checks rather than seven; older hosts without Minecraft registrations keep their
existing categories.

The Minecraft indicator aggregates the worst evidence without hiding a stopped
optional bot behind a running server's detail. A missing member of an advertised
pair remains visible as unknown and cannot leave a healthy header. Offline, failed
or expired collector observations remain unverified. Overall backend-only issues
still constrain the ring/header and are labelled as backend summary issues, not
falsely assigned to Services. No collector probes, polling cadence or backend behavior change.

Both platform-owned read-only scopes share the existing sheet/lifecycle gates;
Watch retains Crown overflow and suspends underlying input while covered. The
closed card remains non-scrolling, with explicit small/large Watch, phone portrait/
landscape and accessibility-text fixtures. Minecraft-enabled phone cards reuse
the existing denser spacing even on legacy device scopes; typography, hit targets
and test limits are unchanged. Frozen revision 2 passed **176 iPhone tests**, **320
shared cases (3 expected live-test skips)**, **37 terminal contracts** and both
simulator builds. The first revision's two accessibility-landscape failures and
immutable source/test/cache evidence are retained.

The owner-approved exact sealed **251** installed once on each device on
**2026-10-05 at 16:42 EDT**; independent final version/running-process and live
backend checks passed at **16:43 EDT**. Candidate and exact rollback **250** each
passed all four bundle signature/profile/unchanged-entitlement audits. Fresh
allowlisted identity, pairing, compatible developer services, unlock and installed
baseline 250 checks passed before installation and again at each write boundary.
No install retry, backend/Pi/Minecraft restart, credential/provisioning/dependency
change or cleanup occurred. All 18 protected service records, existing Pi panes,
Minecraft/gateway/Pi identities, registry/configuration/authentication fingerprints
and 10-second history cadence were preserved. At final verification the server
was listening; the bot process was running but disconnected, which the Minecraft
check correctly exposes as not ready. Physical card/detail/Crown/VoiceOver
acceptance remains owner review.

## Visual-only card on both devices (build 234)

Both platforms now show one noninteractive glass card: current ring and short
status, past-hour timeline, five labeled status symbols (Services, Pi, Network,
Devices, Sensors), and at most one compact exception line. The Watch uses a small
three-column icon grid. Phone refresh remains a separate button. Neither platform
has card buttons, tap handlers, detail routes, sheets or scrolling. Watch gestures
and Crown ownership are untouched; the retained detail-visibility callback only
reports false. Backend access, history window/cadence, and lifecycle gates are unchanged.

Grouping preserves the worst evidence: failure precedes unknown/checking, then
healthy/inactive. Services includes backend/collector evidence; Pi includes cached
Codex usage; Devices includes plugs/purifier. Missing sensor evidence is unknown,
not green. Symbols distinguish states independently of colour; gaps remain hatched.
VoiceOver retains row descriptions/ages, service requirements/technical evidence,
and history bucket times, states, reasons and observed/missing coverage. The visible
card omits repeated freshness labels, service paragraphs and history summaries.

Validated with 252 package passes (3 expected skips), 61 iOS AppState/dashboard
passes, Watch simulator build, and synthetic light/dark/compact previews. These
changes are **installed as build 234 on both devices**, completed 2026-09-30 at
21:36 EDT. Each device was installed once, with independent launch/process and
final-version verification. Frozen tests: 251 package passes plus 61 iOS passes,
3 expected skips (unrelated working-tree oMLX test excluded). All four bundles,
profiles, unchanged entitlements and source/payload seals passed audit.
Rollback 233 is retained. No backend/Pi restart, credentials or database changes.
Protected snapshots differed only because the 60-second periodic pi-scheduler
completed its run; read-only review confirmed exit0 and unchanged configuration.
All other protected state matched; cached health and hourly history returned
200/no-store. Physical UI/gesture acceptance remains owner review.

## Unified phone card (build 233)

The iPhone now uses one Liquid Glass card for current health and recent history.
No phone card or history band opens a detail sheet. Current service/integration
state, explanation, observation age and required/optional/scheduled semantics are
inline, including sensor-read and connection failures. Redundant fresh service-data
rows are omitted when individual services already carry the same freshness evidence.

The existing phone history request now selects **1h** (60 one-minute buckets), not
24h. The single overall band includes all cached-health components. Inline text
shows observed coverage, real gaps, unverified observations, error-bucket count and
the two most recent error buckets' time bounds and sanitized reasons. These are
bucket bounds, not exact incident times; earlier errors remain on the band and in
the total count. Missing/unknown data is never treated as healthy or as an error.
Current status and historical observations remain distinct even inside one card.

Phone portrait/landscape layouts remain non-scrolling, with denser inline text on
small canvases. Watch layout, detail sheets, hourly query and input ownership are
unchanged. Polling cadence, authorization, lifecycle/cancellation, backend and
hardware access are unchanged. Existing glass accessibility fallbacks are retained.

Validation: 250 package passes, 3 expected skips; 60 targeted iOS AppState/dashboard
passes; Watch simulator build passed. Light/dark synthetic history previews were
exported and reviewed. **Build 233 installed on both devices** on 2026-09-30 at
21:19 EDT, with independent final-version and launch/process verification. Frozen
release validation: 249 package passes plus 60 iOS passes, 3 expected skips; the
unrelated additional working-tree oMLX test was excluded. Four signed bundles,
profiles, unchanged entitlements and source/payload seals were audited.
The Watch developer tunnel disconnected before its install; a guarded Watch-only
continuation completed it without reinstalling the iPhone. Sixteen protected service
identities, credentials, tmux panes and database identities remained unchanged;
no backend/Pi restart. Both hourly cached history routes returned 200/no-store.
Signed rollback 232 is retained (231 also retained). Physical UI/gesture acceptance
remains owner review. Source is included in the subsequent visual-only System-card change set.

## Phone Liquid Glass simplification (build 232)

The iPhone System overview now uses the same `jarvisGlassSurface` helper as Home:
current checks, history and refresh use native Liquid Glass where supported, with
material/opaque accessibility fallbacks. The separate Services and Integrations
panels are removed from the phone overview. Tap current health for complete current
service and integration evidence; tap a history band for historical coverage.
History is not a substitute for current freshness or failure metadata.

The overview remains non-scrolling. Watch layout, history queries, polling,
authorization, cached-health aggregation and sheet visibility gates are unchanged.
Validation: 249 package tests passed (3 expected skips), 60 iOS AppState/dashboard
tests passed, Watch simulator build passed. Synthetic phone/Watch layout tests
cover portrait, landscape, accessibility text and high-contrast phone sizing.
**Installed build 232** on both devices on 2026-09-30 at **20:37 EDT**, with
independent final-version, launch and running-process checks. Frozen release tests:
248 package passes plus 60 iOS passes, 3 expected skips; the unrelated extra working-tree
oMLX test was excluded. Four signed bundles/profiles and unchanged entitlements were
audited. Sixteen protected services, credentials, tmux panes and database identities
were unchanged; no backend/Pi restart. Build 231 is the verified rollback.
Owner-approved cleanup retires superseded build 230 and this update's build caches,
while retaining signed 232/231, frozen sources and deployment evidence.
Physical UI/gesture acceptance remains owner review.

**Previous installed build: 231.** Installed once on each approved iPhone/Watch,
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
