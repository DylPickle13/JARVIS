> **Backend checkpoint:** `20260919T230024Z-security-status`.
> Adds opt-in, API-token-protected on-demand security status via the existing
> private CLI. [Verification](../../docs/security-integration-plan.md): 612 backend,
> 32 Kasa and 38 VeSync tests; live 401/200 read-only probes passed. No media route.
> The owner now reports native Build201 on iPhone and Watch; the recorded
> Build200 verification remains historical evidence, not a Build201 audit.
> CLI/Pi and native device routing below are retained; shared Room Audio now uses
> Session 10. See [rollout evidence and limits](../../jarvis-app/docs/room-session10.md).
> The sections below record earlier milestones; installed records are authoritative.

## Native clients restored — 2026-09-19

Backend `20260919T204928Z-native-clients` is live. iPhone and Watch Build198
are installed and launched, using authenticated `/api/v1/device-command`.
Old `/api/v1/command` device writes remain retired; CLI/Pi routing is unchanged.
The native route rejects repeated request IDs within this server process (4096
bounded entries, no eviction); this is not durable deduplication across restart.
Existing authentication/admission/SDK guards remain in force.

# Current decision: minimum CLI/Pi deployment

**Deployed:** `20260919T203735Z-local-cli` (2026-09-19). CLI/Pi device writes
now use authenticated loopback backend control; old-app device writes are retired.
Health/state, authenticated readiness and installed CLI read-only status passed.
No physical test commands, durable ledger activation or SDK ownership hooks.

The owner explicitly approved simplifying to best-effort backend routing. See
[simple deployment](simple-deployment.md). The earlier exclusive-ownership gates
below are deferred, not blockers for this mode. No ledger or SDK ownership hooks
are to be activated. Release `deployed.json` records actual activation.

---

# CLI-first cutover status: not activated

The owner approved complete CLI/Pi-first cutover, with old-app **device writes**
retired and v1 status/services preserved. No further approval of that same scope
is needed. Approval is not evidence that the implementation gates have passed.

## Live versus candidate

The installed `20260919T155241Z-control-foundations` release remains unchanged.
Default `jarvis-cli`, Pi tools, independent vendor entry points and v1 device
writes retain their existing behavior. No production v2 ownership, credentials,
ledger, grant directory, new default client routing or persistent fencing has
been installed by this work. No physical device writes were used for testing.

### Shared deadline (implemented in the candidate)

`control_transport.ControlClient` now retains a single absolute monotonic deadline
across window acquisition and command submission. An earlier caller deadline
cannot be extended by client construction; per-exchange limits may only shorten
it. `control_cli.Router` starts its 60-second deadline before argument validation
and credential/source checks and passes the same deadline to the client.

Expired submissions remain consumed and return UNKNOWN, without making a new
connection. Slow metadata cannot buy a new mutation timeout. Invalid/nonfinite
or boolean deadlines fail closed. Tests cover real synthetic loopback exchanges
where metadata consumes most of the budget and a command reply arrives too late.

This does **not** certify the complete Pi process lifecycle: interpreter/imports,
parser/lifecycle events, blocking local file IO, outer process cancellation,
loaded tool versions and installed client/server source locations still require
review. It is not an interrupt mechanism for CPU/file IO or remote cancellation.
No accepted production certificate was generated or refreshed.

### SDK checkpoint and delegation (integrated candidate, not installed)

`jarvisd_core/vendor_fence.py` is now integrated with a callback-bound issuer,
an explicit fenced worker entry and SDK hooks in **staged package copies**. See
[worker/SDK delegation](control-delegation.md). Current checkout/installed vendor
controllers and the default worker remain unchanged. These uninstalled tests are
**not** cohort-wide deployment or drain evidence.

It checks a private fixed account-home `control-owner` directory, a held ledger
owner lock, closed-schema ledger/grant records, the exact still-reserved intent,
API-owned epoch/incarnation, bounded monotonic/wall age and an exact typed call
transcript. It consumes durable no-overwrite worker/mutation marker names and
holds kernel leases through guarded execution. Expiry, closure, missing state,
owner loss, link/mode/schema faults and token reuse never select a legacy route.
Exceptions/cancellation do not refund names or erase ledger uncertainty. A free
lease is not proof of remote cancellation or permission to clear quarantine.

The initial checkpoint tests mint synthetic grants in temporary callbacks; newer
integration tests use the actual callback-bound issuer. They cover thread/process
contention, process death, exception preservation, expiry/skew, owner/drain/restart,
sync failure, filesystem replacement, malformed records and exact operation binding.
Additional staged-wrapper tests use real SDKs against synthetic loopback peers,
never physical devices. No test handoff booleans are live transition evidence.
Temporary fixture corruption restoration is not an approved runtime rollback.

### Runtime and closed recovery assembly (not deployed)

The [runtime assembly](control-runtime.md) now connects registry/protocol/issuer/
host/worker and bounded ordinary readback. `main(control_factory=...)` is explicit;
the default still selects no runtime. A separate tested write-closed recovery role
preserves history and rejects SDK drift/unfenced rollback. Neither role supplies
the missing trusted production startup/handoff owner or installed client layout.
Readback still excludes toggles/unmodeled settings; this is a functional blocker.

## Unfinished activation gates

- Select and certify the implemented callback-bound issuer in the production
  composition. Its **one delegation per active reservation** budget is independent
  of issuer instances; a disk snapshot cannot issue. It is not selected live.
- Complete review/deployment of every cooperating public/vendor/private-worker mutation entry,
  including target/payload binding, read compatibility, worker lifetime leases,
  catalogue maintenance, and restart/endpoint-loss/closed-rollback behavior.
- Complete actual installed/running writer/job/configuration inventory and real
  drain evidence; path searches or synthetic tests do not prove writer absence.
- Supply the production startup transition owner and select the assembled runtime
  with real ledger/catalogue/registry/server dependencies. Finish unsupported-intent,
  restart/manual, store-loss and capacity recovery; ordinary bounded readback is
  implemented only for the previously supported explicit expectations.
- Pin and test actual installed caller/parser/server/vendor/tool locations and
  the entire invocation/cancellation/output contract. Same-root fixture hashes
  are not interchangeable with checkout clients plus frozen servers.
- Review explicit private enrollment, certificate/default/key updates, complete
  paired deployment/closed rollback, and only then perform the approved cutover.

The prototype is cooperative enforcement, not same-user OS isolation, source
attestation, snapshot anti-rollback, a distributed lock, or exactly-once delivery.
Do not install the SDK hooks alone: missing authority intentionally rejects
writes, and production composition/recovery/closed rollback remain unfinished.
