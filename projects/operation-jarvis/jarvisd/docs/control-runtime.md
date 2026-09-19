# Runtime assembly, bounded readback, and write-closed recovery

## Deployment status

**Implemented and tested in source; not selected or deployed live.** The current
LaunchAgent still runs `20260919T155241Z-control-foundations`. Production writer
inventory/drain, trusted startup transition owner, installed CLI/Pi source layout,
credential/default update and unsupported-intent/history-loss recovery remain
unfinished. These components are not permission to fabricate handoff evidence or
install SDK fences alone. The existing complete-cutover approval remains valid.

## Runtime assembly

`control_runtime.ControlRuntime` connects the real identity registry, protocol,
callback-bound issuer, host/dispatcher, exact fenced worker, HTTP endpoint and
owner readback loop. It requires an **already-open, already-API-owned** ledger,
reviewed credentials/certificate, frozen catalogue and real adapter dependencies.
It does not create credentials/stores, restore API ownership or invent evidence.

It checks the worker/interpreter/store layout, scopes and actual installed vendor
files against retained stage pins. The two mandatory mutator hashes must match
the independently reviewed fenced build; a manifest cannot bless old unfenced
wrappers merely by adding helper files. Source certification, vendor pins and
ownership epochs are checked again immediately before mounting the endpoint.

`jarvisd.main(control_factory=...)` is the explicit composition seam. Only a
trusted factory can select the bounded server/runtime; no env or request boolean
activates it. The current default and `__main__` invocation still pass no factory.
Factory/startup failures close the socket and collectors. This seam is not the
missing production startup owner; that owner must manage handoff/store lifetime
correctly if construction fails before returning a runtime.

Draining revokes the enrollment, closes submission windows by advancing ownership
to DRAINING, and stops the readback loop. Shutdown waits for real admitted callbacks
rather than expiring their slots. Timeout refuses store closure and retains its
lease; it never claims remote cancellation. A failed readback thread start/loop
also closes admission. Successful close discards ephemeral read tickets, never
history or unresolved reservations. The v1 device-write latch never reopens.

## Bounded ordinary readback

The protocol's optional post-dispatch hook runs only after an actual callback's
ledger outcome/active-slot cleanup. Rejections/duplicates do not enqueue reads.
Scheduler errors do not reinterpret the original receipt or replay a mutation.

`ReadbackQueue` retains at most 32 commands, with at most one active read per
cohort and one ordinary read attempt per completed command. It waits for the
existing single-flight slot and, for purifier reads, 60-second request spacing.
It does not replace an already-due foreground/periodic collection, set
`retryCooldown=True`, use a vendor write, or create an unbounded polling loop.

Coordinator scheduling methods probe without IO, then atomically recheck the
read fence and availability. The final reconciliation still uses the existing
ledger→state locked proof: a new successful aggregate reading at the exact epoch,
revision, identity and desired state. A polling hint is never authority. Failed,
mismatched or expired reads consume/discard only tickets and retain quarantine;
shutdown, capacity refusal and unsupported intents do not clear anything.

**Recovery is deliberately not broadened:** supported expectations remain explicit
plug on/off and purifier power on/off/mode/speed. Toggle and unmodeled purifier
settings still require explicit recovery. The SDK marker's desired data is not
yet accepted as recovery authority. Restart reconstruction/manual recovery,
capacity retention and store-loss handling are not implemented by this queue.
This limitation is a functional deployment blocker, not an approval checkbox.

## Write-closed recovery role

`closed-main.py` loads a deployment-supplied, owner-only bounded
`closed-vendor-pins.json` (`{"schema":1,"files":{...}}`). It never creates or
recomputes accepted pins from current live files. `control_closed.run_closed()`:

- Verifies all 12 staged vendor package files and mandatory reviewed mutator hashes.
- Opens healthy existing ledger history **CLOSED**, advances incarnation/epochs,
  preserves reservations/uncertainty, and holds the owner lease while serving.
- Refuses busy or corrupt history; does not repair, delete or recreate it.
- With absent history, can serve only the closed legacy status/service role; it
  creates no store or ownership authority. Lost history remains unrecoverable by
  normal activation and requires a separate controlled procedure.
- Uses the bounded server with v1 device writes closed before dispatch and no v2
  endpoint. Status/services remain on the existing API contracts.
- Never restores older unfenced SDK files, events, configuration or ledger snapshots.

This is a **tested recovery role**, not a completed paired deployment/rollback
procedure. An operator must still establish actual worker drain, package the
approved pins/files, manage LaunchAgents and verify the installed role. Do not
run it against unfenced checkout vendor packages; it will refuse the mismatch.

## Tests

Temporary stores, real HTTP/auth/protocol/dispatcher/worker checkpoints and fake
SDK effects cover runtime admission, post-callback readback, deadlines/cooldown,
duplicates, failure cleanup, shutdown with active work, source/layout mismatch,
and closed recovery retaining history and refusing unfenced/drifted files. Native
and SDK regressions remain separate; no physical acceptance or live activation is
inferred from these tests. macOS temporary-directory ancestor aliases are
canonicalized for store/worker comparisons while the root and worker file reject symlinks;
this does not resolve the separate frozen-server/checkout-client source-pin gate.
