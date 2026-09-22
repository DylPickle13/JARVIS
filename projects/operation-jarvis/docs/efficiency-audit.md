# Efficiency audit: source changes and acceptance gates

Backend/watchdog deployed as `20260922T152918Z-efficiency-audit` on 2026-09-22
at 11:33 EDT after owner approval. Notifications stay off; no dashboard, new
service, SDK installation, speed test, or physical device acceptance was added.
Voice and native-app source changes have **not** been rolled out to their running
services/devices. Existing terminal/mobile work remains separate.

## Reliability first

- Pi, services, and network observations now expire after 180, 660, and 1260
  seconds respectively (idle cadences: 60, 300, 600 seconds). Codex remains 900;
  control-device freshness and purifier cooldown/recovery are unchanged.
- Tailscale's local Unix HTTP read has a three-second total deadline, a 64 KiB
  response cap, and cleanup on every outcome. Slow headers cannot indefinitely
  renew a relative socket timeout. Existing discovery fallbacks remain.
- The watchdog needs three failed checks spanning at least 20 seconds. Recovery
  resets the streak. Every restart attempt, including a failed one, incurs a
  30-second backoff using shell elapsed time. Only `/health` triggers it—not
  device failures. Stop the watchdog before planned daemon quiescing as before.

## Work measurement (no additional polling)

`GET /api/v1/diagnostics` requires the API token even in trusted-network mode.
It returns bounded, process-local collector/adapter/security counters: starts,
completions, failures, contention, in-flight count, last/max/total elapsed seconds.
No arguments, credentials, error text, addresses, or device payloads are stored.
Reads of diagnostics never start collectors, refresh devices, or reset counters.
Counters reset on daemon restart; they are not incident history or proof of
physical reachability. Adapter invocation counts do **not** include descendants
or prove that a subprocess was successfully started.

For ongoing measurement, take two authenticated snapshots during
idle and visible-Home periods. Compare count/total-duration deltas over the same
elapsed interval. Also inspect security read-health age/failure streaks. Do not
force hardware refreshes to obtain a passive baseline. No live CPU, battery,
network, or latency improvement is claimed by the offline tests.

## Plug batching

The collector now invokes one private `plug-status-all` worker. That worker
invokes one vendor CLI process, loads configuration once, and reads configured
plugs with at most eight concurrent tasks. Each task has a seven-second budget
including semaphore wait; the daemon bounds the entire worker process group at
12 seconds. Configuration is bounded at 64 plugs. Large lists may return partial
failures rather than exceed the shared deadline.

For N plugs, the old path requested N+1 worker invocations and N+1 vendor CLI
invocations; the new path requests one of each. For four configured plugs, this
is **10 to 2 requested subprocess launches per sweep** by source-path accounting,
not a measured wall-time/CPU saving. Tests verify one collector invocation,
bounded concurrency, no replay, missing-state handling, and independent failures.
A failed batch never falls back to N individual reads. No persistent vendor
session or configuration cache has been introduced: each sweep sees current
configuration without a new invalidation/identity race.

## Shared H200 sensor read investigation

Both T100/T110 branches connect to their configured H200, validate its identity,
apply the pinned compatibility shim, call `device.update()`, select one validated
child, and inventory the child's hub-reported features. The update prepares a
child collection; a grouped read could reuse that one validated snapshot for
multiple configured children. Do not simply remove the update or identity query.

A safe future grouped command needs:

1. All requested aliases resolved from the private registry to the same hub.
2. One shared hub lock and one total retry/deadline budget—not per-child retries.
3. Hub identity validation and unambiguous child validation for every result.
4. Separate missing-state/selection results without inventing closed/no-motion.
5. One observation timestamp, `hub_reported_snapshot`, and unknown radio freshness.
6. Offline grouped-contract tests and separately approved physical/outage tests.

**Decision:** retain the existing single-alias sensor transport for now. Batching
plugs is implemented; hub batching is investigated, not enabled. The current
serial poller's worst-case sweep scales with aliases × 65 seconds. Its 120-second
minimum observation expiry may therefore expire during slow sweeps. This is an
honest unavailable observation, not proof of an outage. Do not silently widen
freshness windows to hide contention; collect timings first. Physical sensor
acceptance remains unverified.

## Narrow frontend demand

`GET /api/v1/state?mode=cached` returns a snapshot without starting workers,
renewing a foreground lease, or scheduling cloud reads. Combining cached mode
with refresh/recovery parameters is rejected. iPhone non-Home routine reads use
this mode and do not perform active convergence retries. Home and explicit
refreshes retain existing policy. Requires backend support before app rollout;
older servers may ignore an unknown query and still renew the lease. The Watch's
visible controls keep their existing active-read policy.

## Voice, dependencies, and release preparation

- Removed unused `requests.Session` allocation/reset machinery; requests remain
  independent and explicitly connection-closing. No unsafe shared session added.
- Only GET/HEAD transport/status failures retry. Model-management, ASR, inference,
  and TTS POSTs are single attempt at this layer, including ambiguous timeouts.
  Read failures are sanitized. No change to household command replay policy.
- Kasa is pinned to installed reviewed commit
  `dd92c05b12c9d55c0bbb7ee75a9352d5689e5f80`, not the moving PR ref. No dependency
  was installed/upgraded. The source-fence baseline is deliberately re-reviewed
  for the read-only batch addition; mutation paths and fence enforcement remain.
- The RPC activity parser now handles its list-shaped input branch correctly.

Offline verification, using existing environments only:

```sh
python3 projects/operation-jarvis/scripts/verify-offline.py
python3 projects/operation-jarvis/scripts/verify-offline.py --suite swift
```

The default includes backend, plug batch, sensor CLI/recovery, voice, presence,
selected room-session/layout/wake suites, and Kasa, VeSync, and ownership-fence
synthetic-peer tests.
It is not every optional camera/recording/SwiftUI/platform test. Missing
dependencies fail explicitly. Live Swift tests are disabled. No Xcode project
regeneration or device installation is performed.

Prepare an **uninstalled** artifact only after the desired changes are committed:

```sh
python3 projects/operation-jarvis/scripts/prepare-jarvisd-release.py \
  --revision COMMIT --output /private/tmp/jarvis-release-COMMIT \
  --python backend=/absolute/path/to/backend/python \
  --python kasa=/absolute/path/to/kasa/python \
  --python security=/absolute/path/to/security/python
```

The output freezes the committed repository tree, hashes every archived file,
and records interpreter/distribution versions and VCS commits without dependency
URLs. Tracked symlinks/private-key/database/.env files are rejected. Untracked
runtime configuration and working-tree edits are never copied. Existing targets
are refused. The manifest explicitly says tests were not run and activation did
not occur; this tool does not replace approved verification/cutover/rollback gates.
Run the offline entry point from that artifact using explicit existing interpreter
paths before proposing activation. No live plist/configuration is copied or changed.

## Verification checkpoint (2026-09-22 EDT)

- 972 Python tests passed: 681 backend, 5 plug batch, 147 security, 27 voice,
  11 presence, 17 selected audio, 32 Kasa, 38 VeSync, 14 delegation-fence tests.
- Swift package: 185 tests executed, 3 expected live-test skips, zero failures.
- Regression fixtures reproduce expired integration data, slow HTTP headers,
  watchdog hysteresis/backoff, bulk partial failures/timeouts, passive API reads,
  private diagnostic counters, and immutable uninstalled release preparation.
- Existing SmartPlugController methods were compared by AST against Git HEAD:
  unchanged; only the new read-only method was added. Source/staged fence pins
  were deliberately reviewed and advanced, not disabled or auto-refreshed.
- Full iOS/Watch app builds/UI tests, isolated before/after performance comparison,
  physical sensor transitions/outages, and notification display were **not**
  performed. The backend now supports the candidate passive-read client.
- Concurrent Home/mobile changes are outside this audit's staging scope.

## Deployment and live sample

- Activated `20260922T152918Z-efficiency-audit`; retained prior backend
  `20260922T143035Z-passive-monitoring` and daemon/watchdog rollback plists/source.
- Frozen staged tree `9b5d36de0568fb8a85594dddedf308cd024aa951` passed all 972 Python
  tests before activation. Runtime SDK-wrapper/configuration hashes were checked
  before/after cutover; dependencies and private configuration were not changed.
- Device workers were allowed to drain; none were killed to force the cutover.
  Only jarvisd and its watchdog were cycled. Protected terminal/audio services
  and tmux pane identities were unchanged; current incident history was retained.
- Authenticated diagnostics and cached-state mode passed live contract checks;
  unauthenticated diagnostics/monitoring were rejected. Refresh+cached mode was
  rejected. Dashboard routes stayed 404; notifications remained disabled.
- Four configured plugs had valid fresh readings after ordinary background
  collection. All nine incident monitors and both immediate sensor-read-health
  entries reported available at the end of the sample. This is read availability,
  not proof of radio freshness, physical transitions, or outage recovery.
- A 65.95-second window recorded 12 successful plug sweeps totaling 5.6791 seconds
  (about 0.47 seconds/sweep), one successful purifier collection, and 13 total
  adapter invocations. Source-path accounting attributes one invocation to each
  collector; the old four-plug path would request 60 plug-worker invocations for
  12 sweeps, versus 12 now. No before/after CPU or wall-time speedup is claimed.
- Foreground-cadence collection and one purifier collection were observed during
  the window; concurrent clients were not excluded. Therefore this was **not an
  isolated idle/cache-only benchmark**. Verification requests themselves used only
  GET health, diagnostics, cached state, and monitoring projections after startup.
- The previously committed network-speed endpoint is present and remained idle.
  No network-quality test, household write, ownership activation, app installation,
  voice/audio restart, or remote-host service change was performed.
