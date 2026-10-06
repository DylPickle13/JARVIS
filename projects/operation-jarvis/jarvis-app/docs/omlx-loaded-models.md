# oMLX loaded-model visibility — retained in installed build 259

## Token reversal update — 2026-10-06

Owner subsequently requested removal of the token rollout. **259 installed once
on both devices**, independently version/process verified at 16:38 EDT on 2026-10-06.
It removes enrollment/provisioning and restores pre-rollout clients, retaining all
five oMLX runtime/regression inputs byte-identical to 258. Earlier zero-write Watch
failures are retained; a new fresh-ready continuation passed every immediate gate.
Target-local cleanup is owner-only. The owner deferred the unused Watch record
after a zero-relaunch developer-service failure; no cleanup/retry is pending.
Both-device removal is not confirmed. No physical UI/VoiceOver acceptance is inferred.
Backend token mode was never activated. Historical 258 release evidence below is
retained, not authority to preserve/resume enrollment. See
[reversal scope](api-authentication.md).


Owner requested that a model stay listed between turns while it remains loaded,
and approved the implementation plan. This is an app presentation change, not
permission to load/unload models, make inference requests or restart oMLX.

## Behavior

- iPhone Home uses fresh, known per-host model inventory for row visibility,
  rather than requiring active requests. Loading, queued, prefill, processing and
  generating behavior is retained; ready/idle loaded models now remain visible.
- Preserve one row per Mac and existing deterministic model/+N/Multi summaries.
  Full model names and Ready status remain available through VoiceOver.
- Idle rows keep independently fresh whole-Mac RAM, display `—` for generation
  speed and stop activity motion normally. All healthy visible rows ready means
  an Idle heading, including when the other healthy Mac has no models loaded.
- A fresh empty inventory removes that host row. If both fresh inventories are
  empty, the heading says No models loaded and metric columns are hidden.
- Stale, unavailable, checking and unknown telemetry retain existing warnings;
  none is treated as proof of unload or shown as live loaded inventory.
- Watch's full-row default, freshness limits, update dot, activity animation
  gates, foreground/coverage/AOD polling, read-only route and cadence are unchanged.
  No local sticky cache, new timer, wider network discovery or extra API call.

## Implementation and regression evidence

`JARVISKit/Sources/JARVISKit/OMLXHomePresentation.swift` now selects fresh,
non-unknown rows with nonempty model identities. `OMLXSummaryContent` names its
opt-in `homeRowsOnly`; iPhone opts in and Watch retains the default. The backend
normalizer already retains idle models; no daemon or oMLX service change is needed.

The new behavior tests first failed against the old filter (16 expected assertion
failures), then all **356 shared cases passed, with 3 expected live-test skips**.
Coverage includes generating → idle → generating with stable IDs/names/RAM,
actual unload/reload, independent host unloads, many idle models in one row,
partial peer outages, unknown state and inventory expiry. Existing phase,
concurrency, speed, motion and poll-ownership tests remain intact.

A native render regression exercises the actual iPhone `homeRowsOnly` path at
normal and accessibility Dynamic Type sizes: generating, idle, next turn,
one/all models unloaded, and an unavailable peer. It checks stable loaded-card
height across turns and shrinking only after fresh unload; screenshots and test
results are retained with the release. Frozen **269-input revision 2** passed
**191 native tests**, **356 shared cases (3 expected skips)**, **8 API-helper
checks**, **37 terminal tests**, both simulator builds and the signed archive.
Full checkout source verification passed, including **942 backend tests** and
production iPhone/Watch visibility wiring. All eight candidate/recovery bundle
signatures, byte-identical profiles, unchanged entitlements/dependencies and
source/payload seals passed; API-enrollment source is identical to audited 257.
Production API credentials were verified absent from source, payload and retained
log/JSON evidence. The twelve screenshot attachments were exported directly from
the passing `.xcresult`, not inferred from mutable `/tmp` files.

The first native compile stopped on a test harness's attempt to set the read-only
Reduce Motion environment property. Its frozen source/error evidence is retained.
Revision 2 removes that unnecessary override (motion was already disabled by the
view default) and uses explicit screenshot names; runtime behavior did not change.
Normal idle and accessibility outage renders were inspected. Existing fixed-column
truncation at large accessibility sizes is retained; VoiceOver has complete data.
Physical UI and VoiceOver acceptance remain unverified.

## Release and safety gates

Build 258 carries the existing API-enrollment work unchanged. Preserve the sealed,
audited but uninstalled build 257 and exact signed previous-build 256 recovery.
Use a new frozen source set, pinned dependencies and unchanged signing identities,
profiles, entitlements, protected controls and terminal/session behavior.

After fresh owner **“ready”**, the first scoped readiness check stopped because
the iPhone reported locked; no installation was attempted and Watch was not
queried. A second fresh owner **“ready”** authorized a new scoped check. Both
allowlisted devices then passed identity/pairing/DDI/unlock/baseline gates, and
**258 installed once on each device**, independently version/process verified at
**14:44 EDT on 2026-10-06**. Every immediate gate remained intact; no failed check
was bypassed, connection reset or write retried. Earlier Watch timeout and locked-
iPhone evidence are retained. All eight candidate/recovery signatures and frozen
source/payload seals passed again after installation; original 257 remains intact.

Backend source/configuration/authentication, all 18 protected service records,
Pi/Minecraft/gateway identities and chart cadence remain unchanged. The installer
performed no model operation, service restart, token rotation/export or enrollment.
The owner subsequently explicitly provisioned and confirmed both devices verified
in the app; this is owner-reported evidence, not agent inspection of Keychains.
Physical loaded/idle/unload behavior and VoiceOver acceptance await owner review.
Pi Desk's previously tokenless helper/feed was subsequently migrated and verified
with separate owner approval; see [deployment evidence](../../pi-desk/DEPLOYMENT.md).
Remaining required-consumer checks and separately authorized token-mode activation
remain gated.
