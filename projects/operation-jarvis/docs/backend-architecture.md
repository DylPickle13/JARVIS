# Shared Operation JARVIS backend

> **2026-09-19 checkpoint:** deployment `20260919T215836Z-room-session10`
> serves CLI/Pi and native plug/purifier writes through the same dispatcher.
> See [current deployment](../jarvisd/docs/simple-deployment.md) and
> [Session 10](../jarvis-app/docs/room-session10.md). Candidate/foundation
> milestones below are historical; exclusive ownership remains inactive.

## Decision

`jarvisd` belongs at [`operation-jarvis/jarvisd/`](../jarvisd/), not inside the
Apple app. It is the shared control backend; the Apple apps are clients.
Centralize state, command policy, permissions, and sanitized events, not every
workload into a single process.

Target architecture:

```text
Apple apps / agent tools / CLI / dashboard
                    |
                 jarvisd
       state, commands, policy, events, health
                    |
       device adapters / service adapters / remote endpoints
```

This diagram is a target, not a claim that every client already uses the API.
Native clients use `jarvisd`; CLI/Pi plug and purifier writes also route through
it. Unrelated CLI actions retain their handlers. Direct SDK scripts and vendor
apps can still coexist. Security controls and media remain standalone/local-only;
the backend exposes only the on-demand status read described below.

[Security status](security-integration-plan.md) initially shipped as an on-demand
read in `20260919T230024Z-security-status`. Current native monitoring also supports
explicitly configured serial sensor polling and cached read-health/history;
source defaults remain off. See [current monitoring behavior](../jarvisd/docs/monitoring-native.md).
No security media route exists. Read availability never proves radio freshness.

[Efficiency audit and source improvements](efficiency-audit.md) documents bounded
I/O, freshness expiry, bulk plug reads, passive client reads, diagnostic counters,
and offline release preparation. Its deployment checkpoint identifies the active
backend/watchdog release; native-app and voice rollout remain separate.

## Boundaries

- `jarvisd` owns the control API, cached state/freshness, allowlisted operations,
  and bounded public projections. No general shell execution endpoint.
- Device adapters retain vendor-specific control. Slow or dependency-heavy SDKs
  can run in isolated workers/environments with bounded timeouts.
- Raspberry Pi owns local capture, wake detection, and playback. Future remote
  endpoint heartbeats and scoped operations must use authenticated transport.
- Room audio owns audio transport/processing; `terminald` owns terminal
  transport; the private scheduler owns job execution and retained results.
  Their current ports, process boundaries, and protected sessions stay intact.
- Future camera video belongs on a separate media path, not the state API.
- Security is optional and private. Reachability is not an assessment that the
  home is secure. Hub-local protection must not depend on the central Mac.

## Phases and acceptance gates

1. **Relocate, preserve behavior.** Move daemon source, tests, LaunchAgent
   templates, and runtime paths to `jarvisd/`; fix the app signing-helper path;
   update docs/verifiers. Preserve port 8790, labels, authentication, routes,
   and native JSON contracts. Verify offline tests and read-only HTTP contracts.
   Keep the prior deployed source/plists and event history for rollback.
2. **Modularize and establish shared contracts.** Extract API, configuration,
   collectors, command dispatch, authentication, events, and adapters in small
   changes. Specify health, freshness, capabilities, command outcomes, timeouts,
   per-device write serialization, and redacted audit records. No API rewrite
   or framework migration is required by the directory move.
3. **Integrate incrementally.** Preserve plugs/purifier first; add Raspberry Pi
   health and bounded operations, then Cast/media, then security reads. Review
   and physically validate sensitive security writes separately. Never move
   private security source/configuration into public Git as part of integration.
4. **Converge clients.** Move CLI and agent tools behind the API only after
   extracting internal adapters: daemon -> public CLI -> daemon is forbidden.
   Follow the [outage/maintenance/ownership contract](../jarvisd/docs/client-convergence.md):
   no silent fallback, queued replay or automatic mutation retry. Maintenance is
   an explicit drained/fenced handoff, not a second writer or outage bypass.
5. **Harden sensitive access.** Add scoped identities/permissions, authenticated
   remote endpoints, encrypted sensitive transport, bounded audit retention,
   fault isolation, and outage acceptance tests before expanding access.
   Network allowlisting alone is not sufficient authorization for new sensitive
   security controls.

Never queue/replay hardware writes or blindly retry ambiguous delivery. A stale
or unavailable integration must remain visibly stale/unavailable rather than
blocking unrelated devices or implying success. No new public inbound control.

## Relocation status (2026-09-17 EDT)

Phase 1 is deployed on the central Mac. Source, tests, templates, and live
runtime paths are outside `jarvis-app`; the daemon still runs from a frozen
artifact with its prior deployment retained for rollback. Only the daemon and
its resurrector were restarted. Protected terminal pane/process identities and
room-audio/terminald process identities were checked and preserved; event history
and sequence were retained.

Verification: 112 daemon tests passed; 156 shared Swift tests completed with
three expected live-test skips and no failures; the read-only live Swift
health/state test subsequently passed against the relocated service. Health,
state, events, and oMLX returned HTTP 200. No full Xcode app build, physical app
acceptance, hardware write, or security integration was performed.

## Phase 2: shared infrastructure extraction

The first slice extracts `jarvisd_core` configuration helpers, authentication,
logging, events, HTTP body decoding, and the closed command catalog. These modules
have no import-time I/O. The entry point now opens persistent event history in
`main()`, after configuration validation, instead of rewriting it on import.
Existing commands declare their integration, effect, timeout, and no-replay policy;
no new command/API or permission is introduced.

This slice was deployed on 2026-09-17 EDT with a complete frozen package and
prior-artifact rollback. Verification passed 136 backend tests (24 added), the
156-test shared Swift suite (three expected live skips), and the separate live
Swift health/state test. Event contents/sequence and protected service/session
identities were preserved. Only the backend and its watchdog restarted; no
hardware writes, new integrations, app installation, or full Xcode builds ran.

See [integration contracts and remaining extraction gates](../jarvisd/docs/integration-contracts.md).
The first slice did not complete phases 2–5.

### State coordinator and daemon write admission

The next slice moves the coordinator to `jarvisd_core/state.py`, with explicit
collectors, recovery callbacks, clock, and runtime identity. Pure device
projections live in `devices.py`. The host still owns collector adapter wiring.

`admission.py` and `control.py` add bounded, non-queued per-device daemon writes:
canonical plug hosts/default purifier identities, freshness checks inside
admission, and revision barriers against late reads. Failed/uncertain writes
remain stale until new observations arrive; no write is replayed. HTTP 409 uses
the existing error shape for busy/stale/unknown-target admission failures.

This is **daemon-only**, not a claim that direct CLI/tools, vendor retries, or
other controllers are serialized. Remaining work includes route/service domain
extraction, adapter/retry audit, client convergence, scoped permissions, and new
integrations. Physical write acceptance requires separate approved device tests.

This slice is deployed (2026-09-17 EDT), including the native plug-error-field
compatibility correction. Verification passed 168 backend tests, 32 admission
and concurrency tests on five consecutive runs, 158 shared Swift tests (three
expected live skips), and the separate live Swift health/state test. HTTP health,
state, oMLX, and event reads passed; event history/sequence and protected service/
terminal identities were preserved. Only backend/watchdog restarts occurred.
No physical writes, app installation, or full Xcode app builds were performed.

### Private plug/purifier adapters

Deployed 2026-09-17 EDT. Native device dispatch and device collectors now use an
allowlisted frozen `device-worker.py`, not the broad public CLI. The worker keeps
vendor SDKs in their existing subprocess environments. Collector scheduling,
authentication, API routes, freshness/revision barriers, timeouts, and existing
lifecycle events are preserved. Failed workers never fall back to the public CLI.

Public CLI/tools remain unchanged and are still separate writers. Only the local
`status --no-cast` backend action retains a public-CLI bridge. Remove that back-edge
and address the documented vendor retry/identity limits before client convergence.
The Kasa wrapper can repeat a desired-state write after an authentication-classified
verification failure; this extraction does not fix or certify SDK retries.
See [device adapters and retry review](../jarvisd/docs/device-adapters.md).

Verification: 196 backend tests (28 added), 158 shared Swift tests (three expected
live skips), and separate live Swift health/state passed. Both device collections
were fresh through read-only API checks; health/state/events/oMLX returned 200.
Frozen package/plists, event history/sequence, and protected service/session
identities were verified. Only daemon/watchdog restarted; no hardware writes,
SDK/configuration changes, app installation, or full Xcode builds were performed.

### Wrapper write safety and final CLI dependency removal

Deployed 2026-09-17 EDT as a paired backend/vendor-wrapper update. Kasa credential
fallback now occurs only during pre-write connection/status reads. Mutation and
post-write verification cannot trigger another wrapper write; cancellation and
uncertain verification close the connection and propagate failure. Toggle resolves
and uses one connection. This safer wrapper also serves existing direct CLI users.

Daemon writes carry server-derived expected host/CID bindings into the private
worker and matching vendor CLIs. Configuration/observed-host mismatches fail before
Kasa writes; purifier writes resolve exact admitted CIDs without alias/default/name
fallback. Public APIs and client parameters are unchanged. Host/CID binding is not
cryptographic identity or global serialization.

Local `status --no-cast` is now handled inside the private worker using file checks
only. No daemon command invokes public `jarvis-cli`. Client convergence remains
pending: installed Kasa protocol methods still default to SDK-level retries,
requiring further work before end-to-end no-replay claims.

Verification passed 232 backend tests (36 added), 26 isolated purifier regressions,
158 shared Swift tests (three expected live skips), and the separate live Swift
health/state test. Staged vendor imports/parsers passed with installed vendor
interpreters, without device calls. Live read-only APIs and fresh device collections,
paired source hashes, event history/sequence, and protected identities passed.
Only backend/watchdog restarted; no hardware writes, SDK installations, private
configuration changes, app installations, or full Xcode builds were performed.
Rollback retains the previous backend and all four replaced vendor-wrapper files.

### Reviewed Kasa SDK mutation guards

Deployed 2026-09-17 EDT without changing SDK installations. The plug controller
now surrounds the reviewed power mutation with connection-local guards: zero
protocol retries, one query/send/HTTP submission, and no HTTP redirects or
persistent-connection retry. Source/version fingerprints and exact device/protocol
checks reject unreviewed paths before mutation. Reads retain their retry policy.
This extends the earlier wrapper fix; it is not exactly-once device execution or
a promise that device-side work stops when the process is cancelled.

Verification passed 233 backend tests, 32 real-SDK loopback tests (five consecutive
runs), 158 Swift tests with three expected skips, and the separate live Swift
health/state test. Loopback regression reproduces four unguarded submissions on
response loss; the guarded paths submit once. Tests also cover HTTP redirects,
SDK errors/pagination, timeouts/cancellation, source drift, and restoration.
Live APIs returned 200, both device collections were fresh, and paired manifests,
event history/sequence, installed plists, and protected identities passed.
Only daemon/watchdog restarted; no physical writes, dependency installations,
private configuration changes, app installation, or full Xcode build occurred.

Both `jarvisd/verify.sh` and `jarvisd/verify-kasa-sdk.sh` are deployment gates.
See [reviewed stack, scope and maintenance](../jarvisd/docs/kasa-write-safety.md).
VeSync SDK/transport review, client outage/maintenance policy and convergence,
scoped permissions, and separately approved physical acceptance remain pending.

### Reviewed VeSync mutation and observation guards

Deployed 2026-09-17 EDT with the matching vendor helper/controller pair, without
changing installed SDKs. VeSync token-error mutation reauthentication/replay and
HTTP redirects are now blocked by a device-local manager view and independent
API/HTTP attempt limits. CID/operation payloads remain pinned; unknown SDK source
or device paths fail closed. Read token recovery and account backoff are retained.

Known Vital 200S observations now require complete successful response data,
including a new response object for ordinary status reads. This prevents SDK
optimistic state or silently rejected JSON from confirming a write or releasing
cache uncertainty. Skip-prone setters observe first, toggle pins its expected
result, and clear-timer no longer swallows a failed timer read. No new public
fields/routes, background polling, cooldown bypass, or automatic write retry.

Verification passed 242 backend tests, 38 real VeSync SDK loopback tests (five
consecutive runs), 32 Kasa SDK regressions, 26 isolated purifier tests, 158 Swift
tests with three expected skips, and the separate live Swift health/state test.
Loopback tests reproduce original token-error and redirect mutation replay, then
verify guarded single submissions. Live APIs returned 200 and both device
collections were fresh under the stricter observation checks. Frozen/vendor/SDK
hashes, current event history/sequence, plists and protected identities passed.
Only daemon/watchdog restarted; no physical writes, SDK installations, private
configuration changes, app installation, or full Xcode build occurred.

The frozen backend must be paired with the existing four vendor controller/CLI
files **plus** `air-purifier/air_purifier/write_safety.py`. Install the helper first;
restore the old controller before removing an introduced helper on rollback.
Current events/configuration are never restored from stale snapshots. All three
backend/Kasa/VeSync gates are required; see
[VeSync reviewed scope and maintenance](../jarvisd/docs/vesync-write-safety.md).
At that deployment, client outage/maintenance and cross-client ownership policy,
convergence, scoped permissions/auditing and physical acceptance remained pending.

### Client outage, maintenance and ownership policy (reference only)

The [convergence contract](../jarvisd/docs/client-convergence.md) now defines
API-only migrated clients, no automatic mutation retry/fallback/queue, conservative
outcome classification, and explicit cohort drain/maintenance/epoch transitions.
`jarvisd_core/client_policy.py` is a pure offline reference with 39 new tests,
including current public-result projection parity and local concurrent attempt
budgeting. It is **not imported by any live writer** and supplies no production
storage, maintenance fence, cross-process lock or transport.

Source review identified required gates: current v1 requests do not enforce an
ownership epoch/durable intent reservation, and default native `URLSession` usage
is not transport no-replay certification. Implement server enforcement, bounded
persistent duplicate rejection/uncertainty, legacy fences and actual client
transport tests before an exclusive cohort cutover. Complete installed-writer/job
inventory and output/exit-code compatibility review first; source search alone
cannot establish that no other writer exists.

No client/SDK/configuration/API changes, deployment, hardware writes or service
restarts occur in this policy phase. The active VeSync-safety artifact remains
unchanged; public CLI/tools are still independent writers. Client convergence,
remaining extractions, scoped permissions/auditing and separately approved
physical acceptance remain future work.

Verification passed: 281 backend tests, the 39 policy tests repeated five times,
32 Kasa SDK and 38 VeSync SDK loopback tests, 158 Swift tests (three expected skips)
and the separate live health/state Swift check. Read-only state/events/oMLX returned
HTTP 200. All 66 baseline hashes for existing client/vendor/dispatch sources,
installed plists and the active frozen artifact were unchanged, as were protected
service/pane identities. No deployment artifact was activated for this phase.

### Persistent ownership/admission foundation (dormant)

`jarvisd_core/control_ledger.py` now implements explicit private bounded storage,
a nonblocking single-owner process lease, atomic durable reservations before
synthetic dispatch, duplicate rejection, per-resource unresolved barriers and
closed startup with advancing cohort epochs/fresh incarnation. Scoped short-lived
windows use both clocks; clock/storage faults fail closed. Admission, ownership
and maintenance share a critical section, and active callbacks prevent handoff.
Post-operation observation tickets fence old/during-write reads without replaying
or deleting consumed intents.

This library is **not wired into any live writer**, creates no production path,
and adds no endpoint/configuration switch. Existing sources/clients/vendors and
the active frozen deployment remain unchanged. Its fixed reservation capacity
refuses new submissions instead of evicting history; safe compaction, store-loss
recovery, genuine collector/worker integration, legacy fences, enforced wire
protocol and client transport certification remain activation gates. A random
incarnation does not recover uncertainty lost by an offline snapshot rollback.
See [persistent ledger boundaries and tests](../jarvisd/docs/control-ledger.md).

The new hardware-free tests exercise real temporary-file commits, sync failures,
same-/cross-process exclusion, nonblocking admission, maintenance races, scoped
expiry, clock discontinuities, observation fencing, and child-process death before
replacement/dispatch and after a synthetic effect. No hardware, SDK installation,
app installation, service restart or deployment is part of this slice.

Verification passed: 326 backend tests including 45 new ledger tests, those 45
repeated five times, 32 Kasa and 38 VeSync SDK loopback tests, 158 Swift tests
(three expected skips), and the separate live health/state Swift check. Read-only
state/events/oMLX returned HTTP 200. All 83 original source/installed-artifact/plist
hashes and protected service/pane identities were preserved. No production store
was created and no source artifact was activated.

### Candidate guarded protocol boundary (dormant)

`jarvisd_core/control_protocol.py` now connects strict candidate v2 envelopes to
the persistent ledger through an injected trusted host seam. No listener, real
host adapter, runtime wiring, production store or client update was added. Existing
v1 routes, clients/vendors and the frozen deployment remain unchanged.

The boundary rejects wrong paths/media/protocols, unknown/duplicate fields and
caller-supplied authority; requires host principal/scope/transport evidence; binds
immutable commands to host-resolved canonical resources; and preserves conservative
original-outcome uncertainty through duplicates, faults and cancellation. Its nested
operation envelope cannot be executed by the old v1 handler even if an unmodified
body is misrouted there. Receipts correlate the complete public request by digest
without forwarding vendor payloads or treating acknowledgement as freshness.

The 41 new hardware-free tests exercise actual old-handler refusal, persistent
reservations through synthetic host callbacks, ownership/resource/identity races,
faults, redaction and test-only loopback response loss followed by duplicate refusal.
Six fixed digest fixtures support future cross-language implementations; they do
not certify any installed client transport. Actual catalogue/state/dispatcher/worker
binding, authentication/raw HTTP framing, installed-writer inventory/fencing, client
transport certification, retention and approved rollout remain gates. See the
[candidate contract and boundaries](../jarvisd/docs/control-protocol.md).

Verification passed: 367 backend tests, all 41 boundary tests repeated five times,
32 Kasa and 38 VeSync SDK loopback tests, 158 Swift tests (three expected skips),
and the separate live health/state check. Read-only state/events/oMLX returned
HTTP 200. All 118 baseline hash entries (100 distinct source/installed-artifact/
plist files) and protected service/pane identities were preserved. No hardware
writes, deployment, restart, installation or commit occurred.

### Device-host bridge and activated-epoch reads (dormant)

`jarvisd_core/device_host.py` now connects the candidate protocol to the real
`DeviceCommandDispatcher` and `StateCoordinator`, tested with a fake runner and
synthetic aggregate observations. An immutable catalogue pins canonical resources
and private purifier selectors; private bound context ties the command, access,
host and ownership incarnation/epoch together. Trusted authorization is rechecked
before final state admission, not just when decoding a request.

`execute_bound()` shares the existing write implementation rather than rebuilding
SDK execution or re-resolving aliases/defaults. The new state epoch fence rejects
pre-activation/failed/cached-success evidence and checks identity, freshness and
activated-epoch observation atomically before write barriers are installed. Every
write, including a legacy call through that coordinator, invalidates affected epoch
read evidence. Catalogue changes require a new epoch; direct status/command results
cannot mint aggregate epoch evidence. No new collector scheduling or purifier
cooldown bypass was added, and public cache projections remain unchanged.

This is still **source-only**: no live handler/client/worker integration, production
store, SDK/app install, service restart or deployment. The checkout changes are
coordinated across dispatcher/state/ledger/protocol helpers; only the frozen backend
remains active. Real authentication/runtime composition, installed-writer fencing,
post-callback ledger reconciliation, worker-quiescence evidence, bounded retention
and certified client/rollout gates remain. See [host boundaries and tests](../jarvisd/docs/device-host.md).

Verification passed: 406 backend tests including 39 new host tests; those 39 and
the 35 existing admission tests each passed five repeated runs. The 32 Kasa and
38 VeSync SDK tests, 158 Swift tests (three expected skips) and separate live
health/state check passed. Read-only state/events/oMLX returned HTTP 200. Of 102
baseline files, only the four intended checkout helpers changed; the other 98,
including active artifacts/plists, and protected service/pane identities were
preserved. No deployment, hardware writes, installation, restart or commit occurred.

### Compatible foundation deployment and explicit readback reconciliation

Historical deployment `20260919T155241Z-control-foundations` was activated using the complete
repository-shaped frozen backend under its private deployment record. This is a
**compatible backend update, not exclusive-ownership activation**: v1 behavior,
authentication/port, direct clients and mixed-legacy ownership remain unchanged;
the candidate policy/ledger/protocol/host are bundled but not imported by the daemon.
No production ledger or v2 route exists.

The dormant readback bridge now links ledger tickets to coordinator read revisions,
matching original command fingerprints and genuinely new aggregate observations.
Ledger → state lock order holds the checked state through durable reconciliation.
Old/cached/in-flight/mismatched/expired observations cannot clear uncertainty, and
successful reconciliation retains original dispositions and consumed request IDs.
Unsupported/toggle/settings or changed-catalogue recovery stays closed. It neither
schedules reads nor bypasses cooldown nor replays a mutation.

Prepared, pre-cutover and installed frozen gates passed: 427 backend, 32 Kasa SDK,
38 VeSync SDK tests. The 21 readback tests passed five repetitions, and 158 Swift
tests (three expected skips) plus the separate post-deployment live health/state test
passed. Health/state/events/oMLX returned 200; configured devices were fresh. Loaded
arguments/manifests, unchanged paired vendor/configuration files, bounded event
history and protected identities were verified. Only daemon/watchdog restarted;
no physical writes, app/dependency installation or commit occurred. Full prior
code/vendor/plist rollback material is retained, never stale runtime restoration.

Client inventory/fencing, authenticated runtime composition, real transport/output
compatibility, retention/compaction and broader recovery remain **activation gates**.
See [deployment result and remaining boundaries](../jarvisd/docs/foundation-rollout.md).

## Verification and rollout

Use [`jarvisd/verify.sh`](../jarvisd/verify.sh) for isolated daemon tests and the
[app verifier](../jarvis-app/scripts/verify-jarvis-app.sh) in a development checkout
for full native builds. Read-only host health/state checks cannot prove physical
app behavior or device write correctness.

A relocation deployment restarts only `jarvisd` and its resurrector. Stop the
resurrector first, retain installed plist overrides, move runtime files while
writers are stopped, start the daemon, verify health, then start the resurrector.
Do not restart room audio, terminald, scheduler, Pi sessions, or the Raspberry Pi.
See [daemon operations](../jarvisd/README.md) for rollback requirements.
