# Client convergence: outage, maintenance and write ownership

## Status and scope

**Source-only policy/storage/protocol-boundary phases. Nothing in this document activates
a live maintenance gate, migrates a writer, or grants permission to operate hardware.**
`jarvisd_core/client_policy.py` is an offline executable reference with tests; the
daemon, private worker, public CLI, Pi tools and native clients do not import it.
The installed frozen VeSync-safety deployment remains unchanged.

The next [persistent ledger foundation](control-ledger.md) now implements private
closed-start ownership, durable reservation/rejection, expiry and observation fences
in an isolated library. It is also unwired: no production store/path/API was added.
Bounded compaction, enforced protocol, legacy fences and client integration remain
activation gates; the offline policy model itself still performs no storage I/O.
The [candidate v2 protocol boundary](control-protocol.md) now exercises strict,
non-v1 envelopes and conservative receipts through the ledger with synthetic hosts.
It does not add a live endpoint, legacy fence or certified client. The subsequent
[dormant device host](device-host.md) now exercises real dispatcher/coordinator
binding and activated-epoch read checks with fake runners. Production composition,
post-callback ledger reconciliation and the other activation gates remain.

This policy is the contract for subsequent plug/purifier client convergence.
The current installation is **mixed legacy ownership**, not globally serialized:
daemon admission protects daemon commands only. Existing public CLI/tools and
low-level vendor CLIs remain independent writers. SDK guards constrain reviewed
individual mutations; they do not arbitrate different commands/connections.

Do not move audio, terminal transport, scheduler execution, Pi-local processing
or video into the daemon. Cast/media and private optional security are outside
this cutover. Reachability is not evidence that a home is secure.

## Reviewed client surfaces and open inventory

This is a source inventory, not certification of every installed binary, loaded
extension, scheduled job or external controller.

| Surface | Current device path | Cutover requirement |
| --- | --- | --- |
| Native JARVISKit `JarvisClient.command()` | POST `/api/v1/command`; injected `URLSession`, default `.shared` | Certify the actual transport, epoch-aware admission and response handling; one Swift call does not prove one HTTP submission. Update every installed writer before closing its cohort. |
| `operation-jarvis/jarvis-cli` / `jarvis.py` | Direct vendor subprocesses | API-only device adapter for migrated cohorts, explicit output/exit-code compatibility tests, no vendor fallback. |
| `.pi/extensions/45-jarvis.ts` tools | `pi.exec` of `jarvis.py --json ...` | Verify the **loaded** extension/CLI pair, cancellation/timeout behavior, and no tool/model retry of uncertain mutations. |
| Low-level plug/purifier CLIs and ad-hoc scripts | Direct vendor controllers | Fence normal direct writes for migrated cohorts; separately controlled operator maintenance only. Hidden host/CID flags are binding checks, not authorization. |
| Jobs, dashboard, other machines/clients | Not exhaustively inventoried in this phase | Read-only inventory of actual entry points, configuration and active jobs before any cutover. Do not infer absence from source search. |
| Official vendor apps, physical switches, external automation | Outside JARVIS admission | Declare coexistence; fresh readback can detect a mismatch but does not establish causal ownership or lock those writers out. |

The source review does **not** establish no-redirect/no-automatic-resubmission
behavior for default `URLSession`, `fetch`, HTTP libraries, proxies or connection
recovery. That remains a migration gate, not a deployed guarantee.

## Non-negotiable client behavior

1. One explicit intent, at most one application-level submission. Consume its
   local attempt budget **before** handing the request to the HTTP transport.
   Cancellation, timeout, reset, malformed output, response loss or app restart
   cannot refund it. A new correlation ID is not permission to repeat an old intent.
2. No automatic mutation retries, including on/off setters, 401 credential
   recovery, 409 contention, 429, redirects, 5xx or connection recovery. Do not
   switch endpoint after submission. Existing toggles retain the same rule;
   an uncertain toggle must never be repeated to “fix” it.
3. No durable outbox, offline write queue, reconnect catch-up or event-history
   replay. Jobs remain separate executors: do not catch up missed/uncertain device
   actions just because ownership or connectivity returns. Preserve job definitions
   and report skipped/failed runs; review their actual execution policy at cutover.
4. A converged client uses the configured backend or blocks. Outage, stale state,
   authentication failure, unsupported protocol and maintenance never select the
   public/vendor CLI, private worker, alternative credentials or another host as a
   write fallback. Daemon adapters never call the public CLI, so no fallback loop.
5. Human-facing cached reads may remain visible with age/staleness and the failure
   reason. Cached success, `/health` availability, model output and old events do
   not establish target freshness, ownership, completion or permission to write.
6. Resolve logical names only against the current approved catalogue; preserve
   opaque purifier IDs. Unknown/ambiguous identities fail closed. Never silently
   replace a vanished target with a default, similarly named unit or discovered host.
7. After an uncertain attempt, reconcile with reads, not another mutation. A later
   fresh matching observation describes current state; it cannot prove that this
   particular request executed or that a delayed cloud effect is impossible.
   Any later write is a **new explicit owner intent**, after current admission
   checks and acknowledgement of unresolved risk—not an automatic retry prompt.

Read recovery remains bounded and integration-specific: ordinary local plug
polling may continue; purifier reads remain foreground/owner-requested, serialized
and subject to the existing cloud cooldown. This policy never requests
`retryCooldown=true`, background cloud probes or direct SDK read fallback.

### Outcome/evidence contract (no new wire fields in this phase)

| Evidence | Client disposition | Follow-up |
| --- | --- | --- |
| Preflight blocks before transport handoff | `not-submitted` | Show reason; no stored intent to resume. |
| Complete authoritative current command-route error: 400/401/403/409/411/413, `ok:false`, valid error, no conflicting action | `rejected-before-adapter` | Surface rejection; do not retry or switch writers. |
| Complete, matching HTTP 200 `ok:true`, valid command-specific public result | `acknowledged` | Use authoritative state/readback for UI state; acknowledgement is not exactly-once proof. |
| Purifier `write_accepted:true`, `verification_pending:true` | `verification-pending` | Keep pending/uncertain barrier; eligible reads only. |
| After transport handoff: cancellation/timeout/reset, missing/truncated/malformed/mismatched response, redirect, 429/5xx, **HTTP 200 `ok:false`**, or insufficient evidence | `delivery-unknown` | Preserve uncertainty; no replay, fallback or optimistic success. |

“Authoritative” requires the intended approved current-v1 peer/route **and**
certified single-submission transport evidence, not a caller-supplied boolean,
proxy body, error prose or just one library call. A rejection after a hidden
resubmission cannot establish that the original intent never reached an adapter.
If origin/completeness/single-submission evidence is missing, classify unknown. Connection errors
after handoff are conservatively unknown even if a particular failure may have
occurred before any bytes were sent. Rejection does not clear prior uncertainty
on the target. HTTP success alone never establishes command success.

Future duplicate-reservation errors need distinct machine-readable semantics:
rejecting a duplicate must retain the original intent's uncertainty, not classify
that intent as never submitted. Do not reuse this v1 rejection classifier for the
future ownership protocol without that review.

The reference classifier validates the current public shape and expected plug
name/explicit on/off result. Purifier acknowledgements do not add or infer a raw
CID, requested-setting match or identity from a display name. Target binding and
readback remain coordinator responsibilities. No classifier result refunds the
attempt budget, and no `confirmed-exactly-once` state exists.

## Ownership and maintenance contract

### Cohorts and authority

Cut over **all cooperating writers for a device cohort**, not one frontend while
claiming exclusivity. Initial cohorts are configured plugs and the configured
purifier account/inventory; do not split the shared cloud account by alias or UI.
Per-target admission remains inside the cohort. No blanket claim covers physical
switches, vendor apps or arbitrary owner-written SDK programs.

The target is enforceable cooperation across enumerated JARVIS entry points, not
a new OS privilege boundary. The current worker is a local executable, and the
current owner account can access vendor sources/credentials. Strong isolation
from malicious same-user code would require separate credential/process authority;
flags, environment variables and this reference model cannot provide it.

A future authoritative private ownership record must survive crashes, be updated
atomically, and identify a monotonically advancing cohort epoch. Never infer it
from a reachable port, lock-file age, wall-clock timestamp or a request parameter.
Missing/corrupt/unsupported ownership state closes new writes. Epochs must not
wrap, collide across restarts or be restored from rollback snapshots. The model
bounds numeric epochs to the cross-language exact JSON range, `0..2^53-1`.
Ownership metadata must contain no credentials or raw private selectors.

### Transition model

```text
current mixed legacy / closed / api-owned
                  |
          close admission, epoch++
                  v
               draining  -- no new normal writes, no queued work
                  |
    scoped drain/fence evidence complete
                  v
             maintenance -- normal clients remain blocked
                  |
    recheck drain/fences, catalogue and client compatibility/transport
                  |       (after any manual work is finished)
                epoch++
                  v
              api-owned  -- only new, epoch-matching, freshly observed intents

restart/recovery -> closed, epoch++ -> controlled handoff again
```

Required scoped drain evidence: zero active daemon writes, quiescent local worker
processes, all enumerated direct/legacy writers fenced, and unresolved outcomes
preserved/quarantined. An absent daemon, zero admission slots, elapsed timeout or
killed worker is **not** proof that a vendor cloud/device canceled its request.
Evidence is cohort/epoch scoped; stale evidence cannot release a new transition.
A failed/timed-out drain stays closed/draining; it never expires into ownership.

Maintenance is an explicit owner operation, not an outage fallback or normal
command option. Any future manual/direct access must be separately controlled,
exclusive of daemon dispatch, bounded to approved existing capabilities and
separately authorized for physical testing. No new generic `--force`, network
maintenance write route or arbitrary-shell escape hatch is introduced here.
Read-only diagnostics are preferable. Preserve uncertainty across manual work,
configuration edits, restart and rollback; journal/quarantine it before handing
off. Such persistence is implemented only in the [dormant ledger library](control-ledger.md),
not today's live in-memory barriers/event ring. Production wiring and recovery
certification remain required.

Catalogue changes belong inside the fenced transition. Validate uniqueness,
alias-to-host and opaque-ID/selector mappings; make the new catalogue part of the
new ownership epoch. Old requests/observations must not bind to edited catalogue
entries. Host/CID equality alone is not immutable generation identity or
cryptographic device identity. Before new writes, collect valid fresh observations
in the activated epoch; maintenance-era cached state is insufficient.

### Server and transport prerequisites before wiring clients

The existing v1 route has **no required ownership epoch or durable intent
reservation**. Adding an ignored JSON field/header, or a client-side health check,
does not fix that. The reference model therefore cannot truthfully mark existing
v1-only clients ready for this policy.

Before cutover, implement and test:

- A negotiated, unambiguously enforced protocol for epoch-bound intents. An old
  daemon must reject it rather than silently execute while ignoring guard metadata.
  Choose the compatible/versioned route and rollout deliberately; no route or
  JSON contract changes are made here.
- An authoritative gate applying to **every** device write route and cooperating
  direct entry point, with ownership check + per-resource admission atomic against
  maintenance. Do not trust readiness/evidence booleans supplied in an HTTP body.
  Default/current settings must not claim the new enforcement until it exists.
- Persistent, bounded duplicate-intent rejection/reservation **before** adapter
  dispatch, scoped to epoch/client/request; uncertain reserved intents never get
  re-dispatched. Preserve reservations/uncertainty through crashes. Define freshness,
  expiry, clock-failure and retention rules so pruning cannot re-enable old intents.
  A correlation ID alone, current events, or process-local `WriteAttempt` is not
  this mechanism. Reservation is rejection bookkeeping, not a replay queue and
  not proof of exactly-once hardware execution. Clients still never auto-retry.
- Actual HTTP transport tests: suppress mutation redirects, credential-refresh
  resend, application retry and endpoint failover; review hidden library/proxy
  resubmission and ensure duplicates cannot cause another adapter dispatch. Inject
  response loss, cancellation, partial responses and connection failures against
  synthetic loopback peers. One `data(for:)`/`fetch()` call is insufficient evidence.
- Approved canonical origin/authentication, no credential forwarding or transport
  downgrade. Preserve the current explicitly approved loopback/trusted-network
  contract for existing devices; sensitive/remote integrations require separately
  approved authenticated encrypted transport and scoped permissions. Existing
  event credentials never become command/maintenance credentials.
- Enforced legacy fencing and installed-client compatibility, not just a source
  flag. Old clients that cannot supply/verify the required protocol must block for
  the migrated cohort, with a documented operator rollback path.

The pure model has no storage, API, transport, real fence or distributed lock. Its
local attempt lock only prevents reuse of the **same in-process object**. Production
checks must occur in the authoritative admission critical section; passing a stale
`Ownership` snapshot to the model cannot protect against a concurrent transition.

## Staged cutover and rollback gates

1. **Policy (reference complete):** document behavior and exercise the offline reference.
   Leave live clients, SDKs, physical devices and LaunchAgents untouched.
2. **Complete inventory/compatibility design:** identify running source/artifact
   versions and all affected writers/jobs/configuration paths using read-only
   inspection. Specify the enforced protocol, persistent record/reservation format,
   bounded retention and legacy fences. No configuration secrets in reports.
3. **Hardware-free implementation (persistent library begun):** build server ownership/admission and client
   transports behind closed gates; test old-daemon/old-client combinations,
   maintenance races, alias/config changes, malformed metadata, restart, reservation
   crash points, response loss, redirects, cancellation and rejection handling.
   Cross-language fixtures must preserve the same dispositions and no-replay rule.
4. **Compatibility:** preserve action/argument validation, exit codes, opaque
   identities and public fields intentionally. Legacy CLI JSON includes vendor
   details that the API intentionally omits; do not claim drop-in byte parity or
   leak selectors/argv to recreate it. Define a safe projection or explicitly
   approved versioned CLI contract before switching that cohort.
5. **Controlled activation:** only after preceding gates, stage complete paired
   deployment/rollback artifacts; fence **all** cooperating writers, drain, preserve
   uncertain outcomes, validate catalogue and activate a new epoch. Refresh read
   state before enabling controls. Physical/cloud acceptance and any required app
   installation are separate approvals, not implicit in this document.
6. **Rollback:** close admission first and drain; keep current events, configuration,
   reservations, uncertainty and monotonic ownership history. An old daemon that
   cannot honor the new fences must **not** simply resume writes. Restore software
   only into a closed/read-only state and perform an explicit compatible handoff.
   If closure cannot be verified for that old version, do not activate it; remain
   in maintenance. Never restore stale events/configuration/ownership from snapshots.

The dormant ledger supplies a strict private record schema and conservative fixed
capacity, not a finished retention/compaction or wire contract. Production
transport/nonce enforcement and installed-client upgrades remain implementation gates. This document does not waive them
or assert global ownership for the present mixed deployment.

## CLI/tools-first implementation status

The owner approved CLI/Pi-tools-first migration and temporary retirement of old
app device writes at cutover, while retaining v1 status/service APIs. The new
[source-only local-client candidate](local-control-client.md) implements dedicated
scoped identity, request/reply MACs and a tested one-submission socket transport.
The subsequent [connection candidate](control-connection.md) adds private bundle
implementation, bounded raw HTTP framing, an explicit backend-only CLI entry and
process-local v1 device-write retirement. Those paths are connected to the actual
parser/handler/dispatcher in fake-hardware tests, but production provisioning,
default-client migration and persistent/vendor fences remain unfinished. The live
backend remains the compatible mixed-legacy foundation release. Do not request the same
scope approval again merely because implementation is staged; complete the
remaining gates before executing the already-authorized cutover.

## Verification

`verify.sh` discovers `tests/test_client_policy.py`: 39 hardware-free policy tests
cover transition evidence, cohorts/epochs, outage defaults, no fallback/replay,
concurrent local claims, ambiguous responses, cloud recovery, import-time I/O and
the explicit non-wiring boundary. The existing backend/SDK suites remain required.

See [integration contracts](integration-contracts.md),
[device adapters](device-adapters.md),
[Kasa safety](kasa-write-safety.md), [VeSync safety](vesync-write-safety.md) and
[backend architecture](../../docs/backend-architecture.md). The SDK loopback gates
certify only their reviewed synthetic paths, not actual devices/cloud acceptance.
