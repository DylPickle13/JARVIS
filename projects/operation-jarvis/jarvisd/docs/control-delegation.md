# Callback-bound worker and SDK delegation — uninstalled candidate

## Status

The producer, explicit fenced worker entry, and staged SDK checkpoints are now
implemented and tested together. They are **not selected by the live daemon,
default CLI/Pi tools or checkout vendor packages**. This is not an activated
cohort handoff or a complete deployable cutover. The owner's existing approval
stands; see [remaining gates](cutover-status.md).

## One delegation per actual admitted callback

`ControlLedger.claim_delegation()` requires the current callback thread established
by `execute_once()`, its still-active reservation, matching cohort/resource/command/
action, current API-owned epoch and unexpired original submission window. It
compares the publication ledger directory to the ledger's open directory identity.
A snapshot, another thread, a forked process, another store, or a finished callback
cannot mint a grant. Competing issuer instances share the same ledger claim budget.

The claim is consumed before randomness, file publication, or child invocation.
Cancellation, publication/sync failure, token collision and worker failure do not
refund it. The callback-local claim does not require a new disk schema: every
restart closes ownership and converts interrupted reservations to UNKNOWN. The
SDK checkpoint also rejects non-reserved/completed or old-incarnation rows.
No history is reset, evicted or restored. Existing capacity limits remain.

`DelegatingRunner.scope()` derives the exact SDK call from the validated bound
command and frozen catalogue entry. It publishes a private no-overwrite grant,
using timestamps from the **original window**, not a new TTL at issuance. The
scope is thread-local; one write child may be invoked. An inherited/supplied token
is overwritten with an empty value on reads. Tokens are environment-only, never
argv, public receipts or events. Files remain private; they contain private target
bindings and are not public command results.

`DeviceControlHost` accepts explicit paired runner/delegation composition. It
checks current authorization before issuance and retains the existing final
authorization, freshness, epoch and per-resource dispatcher checks. The default
host path remains unchanged. No production composition selects the new path yet.

## Exact call and worker binding

`control-worker.py` is a separate explicit entry. It parses the same private
worker arguments and holds a durable worker checkpoint around the entire existing
adapter lifecycle. The call transcript is derived from actual parsed arguments,
not copied from a grant. Missing/invalid authority never invokes the vendor write
handler. Existing local/status read handling is retained, without delegation.

Binding covers configured plug target and distinct on/off/toggle intentions;
purifier exact CID, SDK method, arguments and keyword arguments. Existing
settings include pet mode, speed 1–4, timer minute-to-second conversion, and auto
preference with the reviewed CLI's default room size 600. Parser/command mapping
parity tests cover all existing modes/settings and optional/default room size.
No new device capability is added.

## Mandatory SDK hooks in staged copies only

`stage-fenced-vendors.py SOURCE_OPERATION_ROOT NEW_STAGING_ROOT`:

- Requires exact retained hashes of the reviewed original Kasa wrapper and
  VeSync write-safety helper; drift is not automatically accepted/rehashed.
- Refuses existing destinations and destinations inside the source tree, including
  a symlinked parent hiding the live tree. Copies package Python source only;
  no credentials, configuration, dependencies or SDK installations.
- Adds identical `vendor_fence.py` copies to the two staged packages.
- Kasa checks the actual observed host, distinct intent and effective boolean
  before the existing single-attempt SDK guard. Save-discovery is closed before
  discovery/config writing, pending owner-maintenance implementation.
- VeSync enters its checkpoint with actual CID/method/args/kwargs before the
  existing guarded mutation. Existing no-replay, identity and response guards
  remain in place; exception/cancellation restoration is preserved.

The SDK checkpoint consumes a separate durable marker and holds its lease around
the mutation. Worker/SDK markers are not refunded on exceptions or process death.
An unlocked lease is not remote cancellation and never clears ledger uncertainty.
Recorded effective desired-state data is **not yet a readback/recovery authority**.

Staged packages alone must not be installed. Otherwise all existing direct writers
would fail while the production issuer/server/clients still are not composed.
A rollback must retain mandatory SDK closure, not restore older unfenced wrappers;
complete paired closed-rollback artifacts and procedures remain a deployment gate.

## Verification and limits

Backend tests use real ledger/protocol/host/dispatcher, callback-bound issuance,
temporary grants, actual fenced worker parsing/subprocess entry, and fake effects.
They cover cross-thread/fork rejection, duplicate issuer attempts, publication
faults/collisions, expiry, drain/restart, binding, non-device reads and no fallback.

`bash verify-delegation-sdk.sh` builds temporary copies and runs installed Kasa/
VeSync SDKs against synthetic numeric-loopback peers, using the actual issuer and
checkpoint. It tests missing/reused/mismatched grants, reply loss, cancellation,
SDK attribute restoration, existing purifier settings/payloads and catalogue
closure. Kasa post-write status is a synthetic observation; these tests establish
submission fencing, not genuine physical acceptance. The original SDK regression
suites continue to test the unchanged installed wrappers separately.

A synthetic XOR cancellation fixture initially hung during cleanup because its
server awaited a test release event; teardown now releases that peer before
protocol-close cleanup. No production timeout/retry behavior was weakened.

Still required: actual cooperating-writer inventory and drain evidence, installed
source-location/invocation certification, production lifecycle/transition owner,
credentials/defaults, scheduling/readback and unsupported-intent/store-loss/capacity
recovery, complete paired installation and closed rollback. No physical testing,
service restart, production profile/ledger or default-client migration occurred.
This remains cooperative code enforcement, not same-user OS isolation, a global
lock, anti-snapshot rollback, physical identity attestation or exactly-once delivery.
