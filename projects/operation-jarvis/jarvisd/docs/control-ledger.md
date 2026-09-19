# Persistent control ledger — dormant foundation

Release note: the [compatible rollout](foundation-rollout.md) may bundle this
library, but it remains uninstantiated by the live daemon. Historical source-only
notes below are not a claim that a shipped bundle activates ownership.

## Status

`jarvisd_core/control_ledger.py` implements the first persistent ownership/admission
slice of the [convergence policy](client-convergence.md). **It is not imported by
any live daemon entry point, dispatcher, worker or client.** No default storage
path, environment switch, HTTP route, maintenance CLI or production ledger has
been created. Every store exercised in this phase is a private temporary test
fixture; callbacks are synthetic, never device operations.

This is not activation, completed client convergence, a permission broker or
exactly-once hardware execution. Installed clients, SDKs, vendor files, frozen
backend, configuration and LaunchAgents are unchanged. Existing v1 and direct
writers still have their previous, mixed-legacy ownership behavior.

## What the library enforces when explicitly used

- Explicit initialization of a **new** dedicated private directory; no silent
  creation/reinitialization on open, missing files, corruption or version drift.
- One local owning process via a lifetime, nonblocking POSIX `flock`. A second
  owner fails immediately. Inherited objects reject forked-process access before
  acquiring an inherited mutex; child cleanup must not unlock the parent's lease.
- Every open advances cohort epochs, creates a fresh random incarnation and
  durably changes ownership to **closed**. No automatic API-owner restoration.
- Scoped `draining → maintenance → api-owned` transitions use the policy model.
  Maintenance checks actual local active grants, not merely a supplied zero count.
  External worker quiescence, legacy fencing and compatibility still need trusted
  host evidence; the library does not discover those facts.
- Device submission admission uses a nonblocking mutex. Contention rejects rather
  than storing/waiting an intent. Ownership, epoch, window, duplicate, resource
  quarantine, capacity and trusted readiness checks share the admission section.
- A reservation is file- and directory-synchronized **before** a callback can run.
  The callback runs outside the lock, at most once for the accepted invocation.
  A grant remains active until the callback/completion path exits; no elapsed-time
  lease expiry can release a still-running operation into maintenance.
- Duplicate `(host-derived client fingerprint, request ID)` pairs are rejected
  across the entire retained history, including changed payloads, resources,
  cohorts and epochs. There is no response-cache replay or retry permission.
- A reserved/crashed/ambiguous result remains unresolved. Even acknowledgement
  does not clear the target barrier merely because HTTP/SDK work returned success.
  Valid post-operation observation reconciliation is separate; the nonce remains
  consumed after that barrier is cleared.

`readiness()` is a fast, non-reentrant **trusted host** probe executed under the
admission lock, not a collector/network call and not request-supplied flags. The
host must derive the authenticated principal, canonical resource and validated
command fingerprint, and bind the actual callback to that same immutable command.
The library does not authenticate clients, resolve aliases, inspect SDK payloads
or prevent a buggy/malicious host callback from doing something else. Existing
per-device freshness/revision admission, target binding and SDK guards remain
mandatory inside future integration. Define one consistent coordinator/ledger
lock order before wiring; do not call this gate while holding arbitrary state
locks or re-enter it from `readiness()`.

A callback must not return while its local mutation work is still running. The
separate maintenance worker-quiescence check must also cover orphan/vendor workers.
Process exit, a killed worker or a released local lease is not cloud cancellation.

## Callback-bound worker delegation (uninstalled candidate)

`claim_delegation()` adds one-use, callback-thread-scoped issuance authority without
changing the persisted schema. It requires the active matching reservation, current
ownership/window and the exact ledger directory, and consumes before file publication.
Another issuer instance, a fork, another thread or a completed callback cannot reuse
it. Failed publication is never refunded; SDK expiry retains the original window.
See [worker/SDK delegation](control-delegation.md) for the explicit composition,
staged mandatory hooks, tests and outstanding production activation gates.

## Freshness and replay windows

A trusted host may issue a cohort/client-scoped submission window only while that
cohort is API-owned. The window binds incarnation, epoch and principal and is
valid for at most **25 seconds**, checked on both monotonic and wall clocks.
It is checked before/after readiness and again after reservation durability, before
callback handoff. Slow readiness or disk sync cannot extend its lifetime.

Both clocks must be nonnegative integers, never move backwards, and agree on
elapsed time within two seconds. Rollback or suspend-like skew beyond that bound
latches the store unavailable until close/reopen and controlled handoff. A normal
large elapsed interval expires windows. These are conservative freshness checks,
not a trusted-time attestation. They cannot cancel an already admitted cloud effect
or guarantee physical execution before a deadline.

Windows/observation tickets live in bounded in-memory maps, never survive restart
and are never reconstructed from request timestamps. Tokens include a monotonic
per-incarnation serial so expiry/pruning cannot reissue an old token even if the
random suffix repeats. Counter overflow fails closed. Tokens are **not credentials**.

Do not confuse window expiry with reservation retention: only expired ephemeral
windows/tickets are discarded. Durable intent reservations are never evicted in
this slice. A delayed old packet cannot become valid through clock rollback,
reopening the store, refreshing a window or replacing the payload under the same
retained principal/nonce.

`duplicate-intent` carries only the prior disposition, not raw arguments/results.
An in-flight/reserved duplicate is `delivery-unknown`, never “the original was not
submitted.” `admission-busy` also makes no claim about an earlier submission with
that nonce. The future protocol must preserve these semantics; the current-v1
rejection classifier must not reinterpret them as definitive original non-delivery.

## Observation barriers

The explicit [readback bridge](foundation-rollout.md) now joins these tickets to
coordinator read revisions via `reconcile_checked()`. It verifies the exact unresolved
command fingerprint and holds the state proof lock through the ledger commit
(ledger → state lock order). No wire route or automatic collector is added.

The host obtains `begin_observation()` **before starting a new read**, after the
local operation has ended and while in maintenance/API ownership. It records the
incarnation, epoch, resource and ledger revision. Reads started before/during a
write, expired tickets, copied/forged tickets, old epochs, or a later reservation
cannot clear a barrier. Each ticket is consumed even on failed validation.

`reconcile(..., reconciled=True)` is internal host evidence: the coordinator must
have validated a genuinely new response, identity, freshness and applicable pending
expectations. It cannot mean “HTTP 200,” optimistic SDK state, a cached response,
client assertion or a mismatching verification. No response/credentials are stored.

This slice deliberately requires a **post-callback read**; it cannot yet adopt a
readback performed inside the mutation callback. Efficient integration with existing
verified readbacks needs a separately tested revision/phase design. The library
never starts a read, bypasses account cooldown or adds background cloud polling.
Normal integration-specific scheduling/foreground policy remains authoritative.
Fresh observations describe current state, not causal proof of request execution
or proof against a delayed vendor/cloud effect.

## Private storage and durability

Local POSIX filesystems only, at an explicitly supplied absolute path:

```text
<dedicated owner-only directory>/  mode 0700
    owner.lock                    mode 0600, lifetime advisory lease
    record.json                   mode 0600, complete authoritative record
    record.next                   mode 0600, only while replacing/interrupted
```

The parent is resolved explicitly; the final directory and file components are
opened without following symlinks. Files must be regular, single-link, owned by
the current effective user and exactly private. Directory/lock identity and the
expected record digest are rechecked; live replacement, permissions drift or
record mutation latches failure rather than overwriting unexpected state. No
permission repair or alternate path fallback occurs. These checks cover POSIX
ownership/modes, not inherited ACLs or a filesystem's reliability. Production
must separately verify effective ACLs and local lock/rename/durability semantics;
network or cloud-synchronized storage is not an approved deployment target.

The closed JSON schema stores only schema/revision, incarnation, cohort epochs
and modes, and bounded reservations: principal/resource/command fingerprints,
request ID, cohort, originating incarnation/epoch, allowlisted write action,
outcome, unresolved flag and reservation revision. Fingerprints must be derived
by the host, not raw hosts/CIDs simply formatted as hex. Callback payloads, errors,
credentials, command lines and private selectors are never persisted. The record
is private bookkeeping, **not** the public event ring or a completed audit system.

Commit sequence: validate bounded complete state → exclusively create `record.next`
→ flush and `fsync` (plus `F_FULLFSYNC` where exposed) → atomic same-directory
replace → directory `fsync` → update in-memory state/grant. Storage failure latches
unavailable; no callback is granted by a failed reservation commit. A failure after
replacement may leave a conservative durable reservation even though no callback
ran. A failed completion commit leaves the earlier reservation unresolved.

On open, validate the complete authoritative record first, remove only a safe
bounded orphan `record.next`, then commit new closed ownership. Interrupted
`reserved` rows become `delivery-unknown` with unresolved barriers retained. No
recovery path calls a callback or recreates a submission window. A partial initial
bootstrap remains an error, never an excuse to reset a store.

These are OS/filesystem durability operations with injected-fault/process-death
tests, not physical power-loss certification. Advisory locks and digest checks do
not defend against malicious same-user code, a privileged attacker, unreliable
storage or out-of-protocol writers.

**Never restore old ledger snapshots.** Epochs are monotonic relative to the
preserved record, not a hardware anti-rollback counter. A fresh random incarnation
also fences normal old requests, but cannot reconstruct uncertainty erased by an
offline filesystem rollback. This library cannot detect every valid old snapshot.
Backup/rollback/recovery must retain current ownership and reservations; lost
history requires a separately reviewed closed recovery procedure, never activation
by merely restoring an old API-owned record.

## Bounds and deliberately missing compaction

- 1,024 retained reservations total; 32 local active grants maximum.
- 128 live submission windows and 128 live observation tickets.
- One MiB maximum per record/temporary record; strict schema and bounded fields.
- Cross-language exact integer bounds for epochs/revisions/counters; no wrapping.

Capacity exhaustion refuses new submissions but still permits reconciliation,
drain and maintenance while storage remains healthy. **There is no automatic
pruning, reset, TTL deletion of reservations, or maintenance cleanup that frees
nonces.** This avoids turning an old request back into a new one, but is intentionally
not a completed long-running production retention policy. Review/implement safe
compaction and operational capacity handling before deploying a converged cohort.

## Remaining gates before activation

1. Complete actual installed-writer/job inventory and enforce legacy fences.
2. Certify and wire the [dormant candidate protocol](control-protocol.md); old
   daemons must not ignore new guard metadata. The candidate supplies strict
   envelopes/conservative receipts, not live routes or authenticated principal mapping.
3. Certify/compose the [dormant device-host bridge](device-host.md), which connects
   the dispatcher/coordinator with catalogue and activated-epoch read fences.
   Complete post-callback ledger reconciliation and real worker lifecycle checks.
   Do not expose evidence booleans or callbacks as a public API.
4. Prove client transport no-redirect/no-resubmit behavior and duplicate safety using
   synthetic loopback peers; retain no fallback, no queues and no automatic retries.
5. Review bounded retention/compaction, clock/suspend behavior, filesystem deployment,
   store-loss recovery, read-only fault isolation and software rollback compatibility.
6. Stage complete paired artifacts, preserve current configuration/events/ledger,
   perform a controlled handoff, and obtain separate physical/app acceptance approval.

No live HTTP/API integration, installed-client update or deployment occurs in this slice.
A subsequent [candidate boundary](control-protocol.md) exercises this ledger with
synthetic hosts and a test-only loopback peer, still without production wiring.
The active backend cannot advertise these dormant guarantees.

## Verification

`tests/test_control_ledger.py` adds **45 tests**, repeated over five final runs,
using private temporary files and synthetic callbacks:
private paths/schema corruption, missing/changed files, same-/cross-process owner
exclusion, fork rejection, epochs/incarnations, scoped expiry/clock failures,
nonblocking admission, duplicate/payload-rebinding rejection, bounded capacities,
maintenance races, stale read fences, sync/completion failures and real child-process
death before replacement, after durable reservation, and after a synthetic effect.
Imports are I/O-free and production entry points remain unwired.

Run `verify.sh`, `verify-kasa-sdk.sh`, and `verify-vesync-sdk.sh` from the backend.
The existing SDK gates remain independent, hardware-free requirements; no installed
SDK changes or real-device/cloud writes are required or authorized by these tests.
