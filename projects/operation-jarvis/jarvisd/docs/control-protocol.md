# Guarded control protocol — dormant candidate boundary

Release note: [compatible foundation deployment](foundation-rollout.md) can include
this library without mounting its routes. The source-only milestones below describe
implementation history, not live protocol activation or client cutover.

## Status and scope

`jarvisd_core/control_protocol.py` connects a strict candidate wire contract to the
[persistent ledger](control-ledger.md), using an explicitly injected **trusted
synthetic host** in tests. It is framework-neutral code, **not a listening server**.
The live `Handler`, dispatcher, collectors, private worker, vendor sources, native
client, CLI/tools and installed frozen deployment are unchanged. No production
store, configuration switch, authenticated principal registry or maintenance route
was created. The active backend does **not** advertise this protocol.

A subsequent [dormant device-host bridge](device-host.md) now exercises the real
checkout dispatcher/coordinator with fake runners, frozen catalogue bindings and
activated-epoch read evidence. It remains uncomposed in the live backend. The
original synthetic-host tests and wire/digest contract remain unchanged.

This is a candidate protocol implementation, not completed production API integration,
client convergence, transport certification, legacy fencing or retention work. The
candidate identifiers below must not be treated as deployed capabilities. Changing
the contract after client adoption would require explicit version negotiation, not
silently weakening validation.

## Non-downgradable envelope

Only these exact paths and method are recognized by the dormant boundary:

- `POST /api/v2/control/window`
- `POST /api/v2/control/command`

Requests and responses use the exact media type
`application/vnd.jarvis.control+json;version=2` and body protocol `jarvis-control/2`.
There are no v1 aliases, redirects, query parameters, trailing-slash normalization,
alternate-host fallback or default content-type acceptance. Responses are
`Cache-Control: no-store`; they carry no redirect or retry instruction.

The future HTTP listener must enforce approved origin/authentication, framing,
content length, transfer-encoding rules, timeouts and a **16 KiB limit before
buffering**. This library receives bounded raw UTF-8 bytes, not a reserialized v1
JSON dictionary (which could already have erased duplicate keys). It additionally
rejects duplicate keys at any depth, non-finite constants, invalid encoding/BOM,
excessive nesting, unknown fields and incorrect primitive types. No callback or
ledger operation follows invalid command syntax.

Window request:

```json
{"protocol":"jarvis-control/2","cohort":"plugs"}
```

A successful response has exactly `protocol`, `kind:"window"`, `cohort`,
`incarnation`, `epoch`, `window`, and `maxAgeMs:25000`. The ledger issues it only for
an API-owned cohort and binds it to the host-authenticated principal. `maxAgeMs`
is an upper bound, **not** a new client-relative deadline or extension of remaining
server validity. Issuing a window does not establish target freshness or permission
to write. Windows are neither authentication credentials nor persistent intents.

Command envelope (hex values are illustrative):

```json
{
  "protocol": "jarvis-control/2",
  "requestID": "00000000000000000000000000000001",
  "incarnation": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "epoch": 3,
  "window": "0000000000000001bbbbbbbbbbbbbbbb",
  "operation": {"action": "plug-on", "params": {"plug": "lamp"}}
}
```

IDs/window/incarnation are exact lowercase 32-hex strings. Epochs are positive
exact JSON integers below `2**53-1`; booleans/floats/overflow are rejected. The
cohort is derived from the code-owned action catalog, never caller evidence.

**There is deliberately no top-level v1 `action` or `params`.** The existing old
handler returns 404 for the new paths. Even if an unmodified body is mistakenly
routed to `/api/v1/command`, it lacks an executable v1 action and is rejected.
Tests exercise the actual unchanged handler with a pure validation seam. A future
client must still verify the protocol and intended peer, refuse any downgrade,
and never reconstruct a legacy request or fall back after a failed handshake.
This shape is not protection against an intermediary that actively rewrites bodies.

## Canonical commands, no new capabilities

The candidate accepts only existing writes: `plug-on`, `plug-off`, `plug-toggle`,
and `purifier-set`. Read/service/event/maintenance/unknown actions are rejected.
It deliberately narrows ambiguous legacy spellings rather than silently copying
every CLI argument convention:

- Plugs require exactly `plug`, already lowercase, existing name syntax, at most
  128 characters. No extra settings, target addresses or binding flags.
- Purifier requires explicit `deviceID` (the existing opaque 24-hex ID), `setting`,
  and the applicable fields below. No implicit default or raw CID/name selector.
- Power: `value` on/off/toggle. Display, child-lock and light-detection: on/off only.
- Mode: `value` auto/manual/sleep/pet.
- Speed: integer `level` 1–4, not a numeric string or alternate `value`.
- Auto-preference: `value` default/efficient/quiet, optionally integer `roomSize`
  1–10000; null is not an omitted field.
- Timer: integer `minutes` 1–1440 **or** `value:"clear"`, never both.

Unknown/irrelevant options, duplicate alternatives, aliases, whitespace cleanup,
cooldown bypass and request-supplied readiness/fence/identity evidence are rejected.
Pure fixtures check canonical purifier forms against existing command builders and
private-worker translation without running a worker or SDK. Real target capability
checks remain the dispatcher's responsibility. This is **not** CLI stdout/exit-code
compatibility or an installed-client upgrade.

## Trusted host seam and persistent admission

`Access` is constructed only by a future authenticated listener, never decoded
from JSON. It contains a stable host-derived principal fingerprint, permitted
cohorts, and a default-false transport-certification fact. Missing authentication,
uncertified transport or wrong cohort scope blocks before host preparation. The
class itself provides no authentication or transport proof. Existing trusted-network
reachability, an event-ingest credential or a caller-chosen installation ID must
not automatically become this authority. Principal identity must stay stable
across credential rotation so rotation cannot evade reservation history.

The injected host contract is:

1. `prepare(command, access)` resolves a local trusted immutable catalogue snapshot,
   without SDK/network calls or mutation. It returns `BoundWrite` containing the
   **same immutable parsed command object**, canonical target tuple and catalogue
   fingerprint. Returning a substituted action/command is refused.
2. `readiness(bound, access, epoch)` runs quickly under ledger admission. It must
   recheck authorization/revocation, the same catalogue/identity, protocol/transport
   certification, activated-epoch observations, freshness and uncertainty. It must
   not collect, wait on a network request or re-enter the ledger. Production lock
   ordering with `StateCoordinator` is implemented/tested in the dormant host
   bridge, but production composition remains an integration gate.
3. `execute(bound)` receives that same bound object only after durable reservation.
   It must retain the existing dispatcher's resource admission, identity/freshness
   recheck, expected-host/CID binding, revision fencing and SDK mutation guards.
   It must not simply call `execute(action, params)` and allow aliases/defaults to
   resolve again. A callback cannot return while local mutation work remains active.
   Catalogue or identity change after preparation must fail closed at real dispatch.

The boundary computes domain-separated fingerprints, not caller-selected ledger
keys. Resource identity uses the host's canonical `(cohort, identity)` tuple and a
stable `jarvis-resource/1` domain: **epoch/catalogue changes do not rename a resource
and escape its unresolved barrier**. Canonical aliases must produce the same tuple.
The command fingerprint covers action, immutable parameters, target and catalogue.
Hashing is not authentication, encryption, proof of physical identity or a defense
against a malicious host. Canonical identity/hash changes require a reviewed
migration preserving old uncertainty; do not change these domains casually.

All accepted writes pass `ControlLedger.execute_once()`: nonblocking admission,
scoped live window and ownership checks, durable duplicate reservation, resource
quarantine, and the single callback budget. Errors never open another store, invoke
a legacy path, replay a callback, enqueue work or clear history. Preparation may
fail before duplicate lookup (for example, a removed catalogue entry); that error
still makes **no claim** that an earlier intent was never submitted.

## Receipts and original-outcome uncertainty

Success-shaped HTTP 200 contains exactly `protocol`, `kind:"receipt"`, `requestID`,
`incarnation`, `epoch`, `action`, `requestDigest`, and `disposition`. Disposition is
one of `acknowledged`, `verification-pending`, or `delivery-unknown`, obtained from
a trusted host `DispatchResult`, **not** an arbitrary vendor `ok` field. Vendor
payloads, selectors, summaries, command lines, paths and exception prose are never
forwarded. Existing client result projection is not silently changed to this shape.

`requestDigest` binds the public canonical action/parameters **and** nonce, epoch,
incarnation and window. This prevents accepting a receipt for a different payload
or refreshed window under the same ID. It exposes neither the private binding nor
a credential, and is not an authenticity signature. Semantic JSON field order and
whitespace do not change it. The exact input is ASCII `jarvis-request/2`, one NUL
byte, then compact JSON of `[requestID, incarnation, epoch, window, action,
sortedParamPairs]`; parameter pairs are sorted by ASCII key and encoded as arrays.
All allowed public parameter strings are ASCII and numbers are bounded integers.
`tests/fixtures/control-protocol-v2.json` contains six fixed portable digest vectors
for future client implementations; they do not certify a Swift/Node transport.

Every error envelope contains `protocol`, `kind:"error"`, `code`, `requestID`
(or null before successful parsing), `disposition:"delivery-unknown"`, and
`priorDisposition` (bounded enum or null). Known ledger conflicts use 409;
parse/media/auth errors use their corresponding 4xx; storage/clock/host failures
use sanitized 503. Unexpected host errors after parsing are not mislabeled as
caller input errors. Cancellation propagates while ledger cleanup retains the
reservation/uncertainty. No error includes arbitrary exception text.

**Even a rejection does not prove original non-delivery.** In particular:

- Duplicate errors may describe a prior acknowledged/pending outcome but remain
  unknown for this handling, never a cached receipt or a fresh acknowledgement.
- Reserved/in-flight/crashed duplicates report prior delivery-unknown.
- Admission contention, stale windows, invalid payloads, lost/partial responses,
  store faults and HTTP 200 alone do not erase prior uncertainty.
- `classify_receipt()` requires the exact envelope, identifiers, public request
  digest, intended-peer evidence and certified single-submission transport evidence
  before recognizing acknowledgement/pending. Old v1 JSON, proxy/error JSON,
  malformed/mismatched results, duplicates or missing evidence return unknown.

This classifier grants neither freshness nor retry permission. Acknowledgement is
not causal proof, exactly-once execution, safe remote cancellation or a reason to
release quarantine. Reconciliation remains a separate genuine post-callback host
observation using ledger tickets; there is **no** public reconcile/read-refresh
route here and no background cloud polling or cooldown bypass.

## Tests and remaining gates

The 41 new hardware-free tests (five final repeated runs) use private temporary
stores and synthetic hosts, including
scope/schema failures, binding/fingerprint stability, actual old-handler refusal,
duplicate/payload/cohort rebinding, clock/restart fencing, corrupt/full stores,
reservation/completion failures, cancellation, concurrent duplicate/drain handling,
receipt correlation and redaction. A temporary loopback peer drops the response
**after** the synthetic effect; an intentionally adversarial duplicate receives
409 without another effect. This is a server-boundary test, **not** certification
of URLSession, fetch, CLI HTTP stacks, proxies, redirect behavior or hidden retries.

Before activation, still required:

1. Complete installed/running writer/job inventory and enforce all cooperating
   legacy fences in each cohort; keep catalogue changes inside fenced maintenance.
2. Certify and compose the [dormant host bridge](device-host.md), which now binds
   immutable catalogue targets to the dispatcher/coordinator and activated-epoch
   aggregate observations. Complete ledger reconciliation and real worker lifecycle
   integration; the bridge alone is not production activation.
3. Implement approved origin/auth/principal mapping and strict bounded raw HTTP
   framing; fence v1 device-write routes as well as direct cooperating writers.
4. Implement/certify real client transports and protocol/window parsing, including
   redirects, reconnection, credentials, response loss, cancellation, partial replies
   and failover. No fallback, automatic resubmission, outbox or offline replay.
5. Complete safe bounded retention/compaction, capacity operations, store-loss
   recovery and ownership-aware rollback. The ledger still refuses at its fixed
   capacity; no reservation was deleted to make these tests pass.
6. Review versioned client result/CLI exit-code compatibility, stage paired artifacts
   and obtain separate deployment/app/physical acceptance approval.

Run all three existing gates: `verify.sh`, `verify-kasa-sdk.sh`, and
`verify-vesync-sdk.sh`. This phase performs no physical/device/cloud writes,
SDK/app installations, service restart, deployment, configuration edits or commit.
