# Dormant device-host integration

Release note: [compatible foundation rollout](foundation-rollout.md) bundles this
code without activating ownership or migrating clients. The source-only milestones
below describe the earlier development phase; installed plists/records identify
which bundle is running.

## What changed — and what did not

`jarvisd_core/device_host.py` connects the [candidate protocol](control-protocol.md)
to the **existing `DeviceCommandDispatcher` and `StateCoordinator`**, rather than
another synthetic dispatcher implementation. Tests use those real components with
a private temporary ledger, fake aggregate observations and a fake runner. No
physical device, worker process, SDK login or cloud mutation is involved.

**Ownership is not activated.** During the source-only bridge phase the installed
backend and clients remained unchanged. The compatible foundation rollout now
bundles the coordinated dispatcher/coordinator changes, with ordinary v1 behavior
under all existing regression tests. There is no new listener, environment switch,
maintenance endpoint or production store; the host is still not imported by the
production entry point. Do not copy only the host file into an older backend.

## Actual command path in hardware-free tests

```text
strict v2 request
  → host.prepare: immutable catalogue target + private host context
  → ledger admission + host.readiness: authorization, epoch, identity, freshness
  → durable reservation
  → host.execute
  → DeviceCommandDispatcher.execute_bound
  → shared WriteAdmission resource gate
  → identity check, frozen selector, final authorization probe
  → StateCoordinator.begin_device_write: atomic identity/freshness/epoch check
  → existing runner boundary (FAKE in tests), once
  → existing result application + cache revision/uncertainty barriers
  → ledger completion, persistent quarantine retained
  → correlated receipt, without private runner output
```

The bridge does not call ordinary `execute(action, params)` and permit a fresh
alias/default resolution after reservation. `execute_bound()` supplies an explicit
canonical resource and required epoch. The existing write implementation is shared
with legacy dispatch: target binding, process-local admission, deadlines, verification,
revision barriers, error behavior and final cleanup are not duplicated in the host.
Ordinary legacy execution does not require these new parameters.

## Immutable catalogue and authorization

`Catalogue` is a bounded immutable tuple of validated `CatalogueEntry` values plus
a trusted owner generation. Entries contain lowercase plug aliases/canonical hosts,
or explicit opaque purifier IDs with private selectors whose CID hashes match those
IDs. Duplicate logical keys, unknown cohorts, invalid selectors and malformed fields
are refused. No configuration file, environment variable, discovery or SDK is read
by this module. The composition root must supply an approved catalogue snapshot,
the existing private adapter runner, the shared admission object/coordinator, and
its configured purifier verification wait. The argv compatibility prefix is not
permission to launch the public CLI; the injected runner must remain the private
worker transport, without fallback.

The catalogue fingerprint includes its generation and sorted complete entries,
including selector bindings. Resource fingerprints still exclude catalogue/epoch,
so changing a generation cannot evade an unresolved resource barrier. Changing a
catalogue requires a new ownership epoch. Because one host fingerprints its entire
catalogue, all represented cohorts must receive a compatible handoff if that
catalogue changes; separate cohort composition can be designed later.

A host can be constructed only from ledger contexts already in API ownership. It
**does not activate ownership**. The new read-only `ControlLedger.context()` returns
an immutable ownership/incarnation snapshot; it is not admission or permission.
The ledger still checks live ownership/window state for every invocation. Constructor
failure never dispatches, resets a store or rolls back an epoch; a partially armed
state fence is conservative and requires controlled recovery/handoff.

The host keeps a private context on `BoundWrite`, binding the same parsed immutable
command, authenticated `Access` object, host instance and cohort epoch. It is never
serialized or included in public/ledger hashes. Substituted command/target/catalogue,
a different host's context, or a different principal's readiness call cannot use it.
The candidate wire contract and existing digest fixtures are unchanged.

The injected `authorize(access, command)` must return **exactly True**. It is checked
at preparation, ledger readiness and again immediately before atomic state admission
inside the existing resource grant. Tests revoke permission after durable reservation
and verify zero runner calls with persistent uncertainty retained. This callback is
an internal authorization seam, **not** a newly implemented credential registry or
authenticated HTTP listener. It must be fast/non-reentrant and derive current policy
from trusted host state, not request booleans. Revocation after the final admission
point cannot promise cancellation of an already admitted remote effect.

These are cooperating-code safeguards, not an OS privilege boundary. Calling an
internal host/dispatcher method directly is not a replacement for protocol/ledger
admission. Installed-writer inventory and real legacy fences remain mandatory before
claiming exclusive ownership; today those other writers still operate independently.

## Genuine activated-epoch read evidence

`StateCoordinator.arm_control_epoch(subsystem, (incarnation, epoch), catalogue=...)`
is an explicitly invoked internal fence. It does not start collectors, request a
read, activate the ledger or change public state fields. It increments the existing
read revision, invalidating collections started before the handoff, and clears
private per-device epoch evidence. Re-arming the same epoch/catalogue is idempotent;
older epochs, a different incarnation with the same number, and same-epoch catalogue
changes fail closed.

`inspect_device()` performs only a locked cache read; unlike ordinary `snapshot()`,
it never starts the scheduler. It reports canonical identity, existing freshness,
and whether that identity was successfully observed after the armed epoch boundary.
A recently fresh *pre-activation* cache may remain visible to existing readers but
cannot admit a guarded write.

Epoch evidence is recorded only after an accepted aggregate plug/purifier collector
completion through the existing `_complete()` path. The incoming device must actually
succeed with a boolean `isOn`, and the merged state must satisfy existing freshness
and pending-verification rules. Failed refreshes, per-device cached-success retention,
malformed states and rejected pre-epoch/during-write collections do not manufacture
fresh epoch evidence. Successful peers in a partial batch are handled independently.
The trusted existing collectors/SDK observation validators remain responsible for
obtaining genuinely new identity-valid responses, not optimistic vendor state.

Every device write, including a legacy call sharing this coordinator, invalidates
private epoch evidence for affected aliases at begin/finish. Applying a command
result or a standalone direct-status result does not mint a new epoch observation.
This slice deliberately requires an aggregate post-activation observation; adopting
other validated readback paths efficiently is future work.

The final `begin_device_write(..., control_epoch=...)` checks the epoch evidence,
identity and normal age/uncertainty under the same state lock that installs write
barriers. Tests change identity, epoch or time between the dispatcher's earlier
inspection and this final check; no runner is called. Existing unguarded callers
omit the argument and retain their prior behavior.

No new background purifier read, cooldown bypass or retry is added. The existing
successful-plug refresh request remains unchanged; purifier scheduling remains
foreground/owner-requested and single-flight. All tests complete synthetic collector
futures explicitly and suppress scheduler startup.

## Locks, completion and uncertainty

Lock order is explicit:

- Host construction: obtain/release ledger context lock, then arm state fences.
- Ledger readiness: ledger admission lock → short state inspection lock.
- Execution: the ledger lock is released; acquire the existing resource grant,
  perform the fast authorization probe, then acquire/release the state lock around
  write admission/application/finish. The runner executes without the state lock.
- Ledger completion happens after the dispatcher has finished its state cleanup and
  released the resource grant. State inspection/completion never calls the ledger.

The authorizer must not acquire locks in the opposite order or call back into the
ledger. A constructor's context snapshot is not concurrent-transition protection;
live ledger admission plus final state epoch checks supply the enforcement points.
Draining may begin while a callback is active, but maintenance cannot complete until
it exits. There is no elapsed-time slot release, replay or detached runner work.
Separate orphan-worker quiescence evidence is still needed for a real handoff.

Only an existing dispatcher-confirmed `ok:true` can become acknowledgement. Purifier
acceptance with `verification_pending:true` remains pending only with explicit
`write_accepted:true`; malformed pending flags, failures, identity mismatches,
exceptions and cancellation remain unknown. The host returns only a disposition,
never the raw vendor payload or private selectors. Existing SDK single-attempt
mutation guards and process-group timeout handling remain mandatory underneath.

**A good callback or later cache observation does not clear persistent quarantine.**
The subsequent [explicit readback bridge](foundation-rollout.md) now connects
post-callback read tickets to validated coordinator observations and exact command
fingerprints. It remains internal and inactive, with no automatic scheduling or
public route. It cannot refund an intent, erase its original disposition, infer
causality or prove remote cancellation. The ledger still retains every reservation
and refuses writes at its fixed capacity. Safe reconciliation/retention/recovery
must be reviewed before a live cohort is enabled.

## Verification and remaining activation gates

39 new hardware-free tests cover the real dispatcher/coordinator path, persistent
reservation ordering, frozen host/CID binding, pending/unknown results, revocation,
identity/epoch/age races, shared resource contention, legacy-write invalidation,
pre-epoch and partial/failed reads, catalogue replacement, opaque context isolation,
cancellation, duplicate/drain concurrency, store faults and non-wiring/import purity.
All existing API/SDK/client regressions remain required. Final verification passed
406 backend tests, all 39 host tests and 35 existing admission tests each repeated
five times, 32 Kasa and 38 VeSync SDK tests, 158 Swift tests (three expected skips),
and the separate live health/state test. Four intended checkout helpers changed;
98 other baseline files and protected runtime identities remained unchanged.

Remaining gates include:

1. Read-only inventory of actual installed clients/jobs/writers and enforced cohort
   legacy fences, including v1 write routes and direct cooperating entry points.
2. Actual authenticated principal/credential mapping and transport certification,
   bounded raw HTTP framing, and an approved runtime composition root/transition owner.
3. Certify/compose the explicit post-callback readback bridge with controlled
   catalogue/read scheduling and real worker-quiescence checks. No caller evidence booleans.
4. Safe bounded retention, capacity operations, store-loss recovery and ownership-aware
   deployment/rollback, preserving current configuration/events/reservations.
5. Certified client transports/result/exit-code compatibility and separately approved
   deployment, app updates and physical acceptance.

Run `verify.sh`, `verify-kasa-sdk.sh` and `verify-vesync-sdk.sh`. No hardware writes,
SDK/app installation, deployment, service restart or commit is part of this phase.
