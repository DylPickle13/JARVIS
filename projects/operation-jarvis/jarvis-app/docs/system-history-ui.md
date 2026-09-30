# System history UI — iPhone and Watch

**Current installed: build 231**, installed once and independently version/launch/
process/final-version verified on both devices on **2026-09-30 at 12:59 EDT**.
Sensor read-health and history compatibility are included; fixed layouts, existing
access and polling are preserved. Four signed bundles/profiles, unchanged entitlements
and the pinned dependency lock were audited. Frozen validation: 307 passes,
3 expected skips. Build 230 is retained for rollback; owner-approved cleanup retires
superseded build 229 and sensor-update build caches.
Sixteen protected services/configuration hashes, tmux panes, credentials and database
identities were unchanged; no backend/Pi restart or app-data removal. Cached localhost
state/history reads returned 200; physical UI/gesture/direct-route acceptance is
pending owner review.

**Previous access checkpoint: build 230**, independently verified on both devices
on 2026-09-30 at 08:35 EDT; see the correction below.

**Original history checkpoint: build 229.** Installation, launch/process and final version readbacks
independently verified on both devices on 2026-09-29 at 23:13 EDT. The exact isolated
signed archive is based on build 228 plus only the reviewed history changes. All
four signed bundles, valid device profiles, unchanged entitlements and fixed
dependencies were audited. Only the isolated source project was regenerated and
versioned; the repository project/version remains unchanged. Build 228 is retained
for app rollback. No duplicate installations, app data removal, backend/Pi/audio
service or session restarts. Physical visual/gesture acceptance awaits owner review.

## Installed build-230 access correction

At the owner's request, history now shares ordinary cached-state authorization.
The backend correction is deployed and tokenless trusted-network requests return
200. Signed build 230 removes both client-side missing-token gates and passes
291 app tests (3 expected skips), with four bundles/profiles/unchanged entitlements
audited. **Build 230 was installed once on each device**, with independent launch,
process and final-version verification on 2026-09-30 at 08:35 EDT. Sixteen protected
service identities/configuration hashes and tmux panes remained unchanged; no
backend services or Pi sessions restarted during installation. The retention policy
keeps current build 230 and verified rollback 229; superseded builds 227/228,
uninstalled candidates and temporary build data are approved for cleanup.
Tokenless localhost phone/Watch history reads returned 200;
physical history UI acceptance remains owner review.
No provisioning UI, credential file, Keychain injection or new Watch credential
relay is included. See [history access](api-authentication.md).

## Sensor-inclusive compatibility update (installed build 231)

The shared client accepts `monitoring_disabled`, `not_checked`, `sensor_read_failed`
and `sensor_read_unknown` in Devices/System buckets. `security` is a bounded valid
component selector, but the overview still requests the existing five phone series
and single Watch `overall` series; no new history request or credential is added.
All existing window, bucket, gap, source-date and evidence-lease validation remains.

Current-state sensor health and overall-summary guards are described in
[System dashboard](system-dashboard.md#sensor-inclusive-update-build-231).
Device/System history inspectors explain the scope transition: sensor-read health
joins recording only after the backend extension; older buckets keep their original
collector scope and are never backfilled or reclassified. Availability is not proof
of radio freshness, door/motion state, continuous uptime or home security.
**Build 231 is installed and launch/version-verified on both devices.** Physical
history rendering, gestures and direct Watch route acceptance remain owner review.

## Presentation

- iPhone System: segmented current-check ring, 24-hour bands for Services, Pi,
  Network and Devices, compact current service/integration cards. Portrait,
  condensed small-screen and landscape layouts retain a fixed, non-scrolling
  overview. The ring encodes cached check states, **not a health percentage**.
- Watch System: small matching current-check ring and one-hour overall band,
  retaining current services/integrations. Terminal remains the default page;
  System/Terminal paging and Overview/Jobs Crown behavior are unchanged.
- Tap a history band to open a separate scrolling inspector. Its newest-first
  buckets expand to show local/UTC time, component, observed status, covered
  evidence seconds, missing seconds, source date and allowlisted reason codes.
  Watch uses explicit disclosure buttons because `DisclosureGroup` is unavailable
  there. The sheet owns input; the outer pager and history polling are suspended.
- Healthy evidence is mint/green, degraded amber, unavailable rose and unverified
  grey. Symbols/text supplement colour. **Unavailable observations are not proven
  physical outages.** Inactive optional services remain non-failing and identifiable
  in current/detail views.

## Honest coverage

The backend samples cached evaluations every minute and additionally limits
coverage by freshness and its recording lease. A 30-second plug freshness limit
can therefore leave honest holes in a one-minute sample interval.

- Hatches indicate missing coverage; a thin coloured cap indicates observed
  evidence in a partial bucket. No sequence/duration within an aggregated bucket
  is invented. Fully observed mixed buckets retain worst-state colour and a mixed
  mark; detailed state durations remain covered-evidence estimates, not exact
  physical outage duration.
- Entirely missing buckets are grey/hatched, never green. Fully healthy bars require
  complete coverage. Partial healthy evidence remains an unknown bucket.
- Band bounds remain the server's absolute `from`/`to`; the right axis says
  **Through [time]**, never stretches an old green band to the render clock's Now.
- Cached/failed/paused history keeps its original dates with a notice. A recent HTTP
  receipt cannot rejuvenate an old query or stalled recorder. Empty history never
  fabricates prior observations. Recording began 2026-09-29 at 21:08 EDT.
- Current state still uses `SystemHealthPresentation` unchanged, including required/
  optional and periodic-service semantics, stale inventory, request errors and
  Watch generation-time—not relay-receipt—freshness. Historical stale evidence is
  unknown even though the existing current presentation describes it as an issue.

## Networking and lifecycle

`JarvisAPI.systemHistory` performs a single GET using existing dashboard authorization to the existing
`/api/v1/system/history` endpoint, with a ten-second timeout, redirect refusal and
2 MiB accepted-response limit before JSON decoding. This is an accepted-envelope
cap, not a streaming transport-allocation guarantee. Old/mock API implementations
fail closed; there is no fallback to active state, hardware refresh, discovery,
commands, diagnostics, vendor/admin endpoints or authentication recovery.

Responses must have schema 1, the cached-status-health scope, exact fixed window/
resolution/bucket counts, unique expected series, bounded reason/state fields,
valid absolute dates and consistent coverage sums/worst-state/mixed flags. Coverage
cannot precede the first recorded sample or extend past the last recording lease.
Source evidence cannot be newer than the latest represented recording.

A memory-only `SystemHistoryModel` owns one single-flight, completion-relative
60-second read loop. Identical configuration deduplicates; endpoint/token/surface
changes clear old data synchronously; cancellation/generation guards reject late
replies. Manual refresh does not duplicate an in-flight request. Errors are generic
and do not expose tokens, URLs or raw response text, or invalidate current controls.
No history is written to app disk, widgets or shared Watch application context.

- Phone: requires the System view to actually be mounted, the System tab selected,
  scene active, current connection established and endpoint available. Hidden,
  background, disconnected and sheet-covered contexts cancel immediately. The
  existing System cached-state policy is unchanged. Offline tests inject a fixture
  endpoint provider/API without writing Keychain or contacting a live daemon.
- Watch: requires visible System, interactive wrist/scene, no input-owning overlay,
  and an existing authorized **direct** backend route. Only `1h&component=overall`
  is fetched (rather than five full series). No history phone-relay protocol,
  endpoint discovery or extra state/cloud read is introduced. Relay-only state may
  remain usable while direct history is unavailable. Always-On/background and other
  pages do not poll history. Existing state/relay/Overview polling is unchanged.

## Validation

- JARVISKit: **234 executed, 3 expected live-test skips, zero failures**.
- iOS simulator: **51 AppState + 6 dashboard tests, zero failures**.
  Total: **288 passed, 3 skipped**.
- Layout cases retain 375×650, 414×720, 320×450, 750×270 landscape and accessibility
  phone coverage, plus 162×197 Watch at normal/accessibility sizes. Closed overviews
  mount no scroll views. Synthetic history adds partial coverage and unavailable
  buckets; light/dark phone/Watch render attachments were inspected. These are
  fixture images, not real incidents or physical gesture acceptance.
- Standalone Watch simulator build passed; iOS test build also compiles its embedded
  Watch and widgets. Dependencies match the deployed build-228 lock. Xcode's existing
  pinned SwiftTerm metadata plugin was reviewed and enabled per build invocation;
  no global plugin-trust settings or package versions changed.
- The actual captured backend `1h`, `24h`, `7d` JSON payloads were decoded and
  validated by the compiled shared Swift implementation, without making device reads.
- Dashboard/history navigation, lifecycle, input ownership and network-scope source
  contracts and verifier shell syntax passed. The broader legacy verifier retains
  its pre-existing unrelated oMLX literal-source assertion blocker.
- After separate owner approval, the frozen build-229 source repeated all 288
  passing tests (3 expected skips) and produced a signed Release archive. Both
  physical devices were identified, paired, developer-enabled and unlocked before
  any install. Each received one installation attempt; both independently report
  build 229 and the launched process. Final cross-device version reads agree.
- Eleven protected LaunchAgent PID/configuration records matched before/after;
  jarvisd remained PID 86097. Post-deployment liveness and authenticated one-hour
  overall history returned HTTP 200; history retained `Cache-Control: no-store`.
  No physical failure/recovery or layout/gesture acceptance is claimed.

## Backend rollback cleanup

The owner separately authorized removing the just-completed backend rollback.
Its rollback folder and unreferenced prior job-categories release were removed;
active release/dependencies, production history databases and all unrelated app
artifacts were retained. See the backend's `docs/system-history.md` and private
`rollback-removal.json`. This cleanup did not restart jarvisd or remove app data.

## Deployment evidence

Private artifact directory:
`~/Library/Application Support/JARVIS/signing-renewal/artifacts/20260930T030421Z-build229-system-history`

It retains the exact source/payload manifests and seal, dependency lock, signed
archive, four-bundle audit, frozen test logs/results, synthetic previews, one-shot
`deploy.py`, unique installation/readback logs, `deployment/result.json`, protected
before/after records, post-deployment verification and `DEPLOYED.txt`. Do not rerun
a deployment with an existing `deploy.started` marker or retry an uncertain write.
The earlier deleted rollback concerns the backend, **not** this retained app build.

## Inputs

- `JARVISKit/Sources/JARVISKit/SystemHistory.swift`
- `JARVISKit/Sources/JARVISKit/SystemHistoryModel.swift`
- `JARVISKit/Sources/JARVISKit/SystemHealthVisuals.swift`
- `JARVISKit/Sources/JARVISKit/SystemDashboardContent.swift`
- `JARVISKit/Sources/JARVISKit/JarvisClient.swift`
- `JARVIS/AppState.swift`, `JARVIS/Views/SystemView.swift`
- `JARVISWatch/Views/WatchConnectView.swift`, `WatchDashboardContent.swift`,
  `WatchSystemHealthView.swift`
- `JARVISKit/Tests/JARVISKitTests/SystemHistoryTests.swift`, `JarvisClientTests.swift`
- `JARVISTests/AppStateTests.swift`, `SystemDashboardViewTests.swift`
- `scripts/verify-jarvis-app.sh`
