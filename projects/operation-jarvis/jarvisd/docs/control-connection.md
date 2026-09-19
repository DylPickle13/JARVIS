# Candidate CLI-to-backend connection

## Status: implemented and tested, not a live cutover

The approved target remains CLI/Pi-tools first, retiring older app device writes
while preserving status and service APIs. This phase connects real entry points
in hardware-free tests; it does **not** activate production ownership.

- `../control-cli.py` (relative to the backend directory) is an explicit candidate
  entry. It reuses the actual public CLI parser/lifecycle and routes plug on/off/
  toggle and purifier-set exclusively through the signed v2 client.
- `jarvis.py.main(..., command_router=...)` is the injection seam. Its default is
  still `None`, preserving normal `jarvis-cli` and current Pi-tool behavior.
  Router errors never reach direct vendor handlers. The candidate has no CLI/env
  endpoint, credential-directory or direct-vendor fallback option.
- The source daemon's `Handler` includes `ControlHTTPMixin`. The explicit
  `main(control_factory=...)` seam now selects the assembled runtime, but its
  unchanged default still uses the legacy server without an endpoint. The
  installed frozen daemon is unchanged. No v2 route is mounted in production.
  See [runtime/recovery assembly](control-runtime.md) for remaining startup gates.
- `ControlHTTPServer` is the opt-in bounded server; `ControlEndpoint.install()` is
  a trusted composition operation, not a network activation route. Tests explicitly
  supply temporary credentials/ledger, synthetic ownership evidence and fake runners.
- No production credential bundle, ledger, SDK fence or default-client switch has
  been created. These are not evidence of cohort-wide ownership.

## Private credentials

`control_credentials.py` implements explicit first provisioning and strict loading:

- New owner-only directory, `0700`; one committed `bundle.json`, `0600`, regular,
  owner-matching, single-link and at most 32 KiB. Symlink/nonregular/permissive/
  replaced/partial/malformed stores fail closed. Parent must already exist, belong
  to the owner and not be group/other writable. Descriptor identity checks bound
  reads and provisioning to the opened directory/file.
- Client ID, dedicated 256-bit key and independent stable principal are generated
  only by an explicit `initialize()` into a **new** directory. The caller supplies
  a separately reviewed certificate; the implementation never learns/approves its
  own current hashes automatically. Data is synced, atomically renamed, then the
  directory and parent synced. Errors leave a closed partial store for diagnosis.
- No overwrite, reset, rotation, deletion/recreation recovery or enrollment API.
  Missing data never manufactures a fresh principal/key. Provisioning after loss
  of an activated identity/history is **not** a supported recovery operation.
- Default path uses the OS account home, not `$HOME` or a caller-provided env flag:
  `~/Library/Application Support/JARVIS/control-client`. Nothing creates it at
  import, normal legacy CLI invocation, help, backend startup or client failure.
- Optional default purifier is an explicit opaque ID bound to an exact incarnation
  and ownership epoch. The client compares both against its authenticated window;
  stale bindings require owner revalidation, never fallback to another device.
- Source inventory now includes candidate entry, actual parser, CLI router,
  credential helper, raw HTTP boundary and daemon handler as well as the previous
  transport/runtime files. This does not certify the still-unmigrated Pi invocation
  stack or grant permission to provision production keys before remaining gates.

These are POSIX ownership/mode/identity checks, not inherited-ACL or filesystem
reliability attestation. The bundle is not encrypted or a hardware key vault.
Production provisioning, key rotation and safe default/certificate update workflow
remain owner-composition work. Never replace an old principal to bypass a consumed
intent or restore stale credential/ledger snapshots.

## Raw HTTP framing and legacy write retirement

The opt-in `ControlHTTPServer` admits at most 64 connections/threads **before**
creating a handler thread, with no application request queue. The endpoint has
at most 32 in-flight input/command slots. Exhaustion returns a bounded best-effort
503, never a retry instruction. These counts do not prove worker quiescence.

When the endpoint is installed, the shared handler reads the request line under
an absolute deadline before choosing v2 or legacy parsing. V2 parsing bypasses the
old JSON handler entirely:

- Exact POST paths and HTTP/1.1, strict CRLF and the seven approved headers only.
- At most 4 KiB per line, 16 KiB total headers and 16 KiB body. Duplicate/unknown/
  folded headers, transfer encoding, noncanonical/oversized Content-Length, old
  aliases and alternate media types/connection modes are refused before dispatch.
- Total input budget at most five seconds, using `read1` and rechecking remaining
  monotonic time before every raw read. A trickling sender cannot renew the budget.
- Authenticate exact raw bytes, then invoke the existing `ControlProtocol` with
  the registry-issued access object. Reply proofs bind status/body/request.
  Errors after admission remain unknown/unavailable, never mislabeled non-delivery.
- One request per v2 connection; unused pipelined bytes are discarded on close,
  never executed as another command. No redirect, v1 reinterpretation or replay.

The bounded server starts with v1 device writes closed even before an endpoint is
usable. Installing an endpoint on a server latches closure **before** exposing it.
Removing or failing that endpoint cannot reopen v1 on that same server; reinstallation
is refused. `plug-on`, `plug-off`, `plug-toggle` and `purifier-set` return the existing
409/error shape. Read commands, state, health and service APIs retain their handlers.
Legacy request-line limits become tighter only with the installed boundary; legacy
header/body contracts otherwise remain unchanged.

**This latch is process-local.** It is not a persistent or cohort-wide fence, does
not protect independent public/vendor/private-worker invocations and cannot establish
safe restart/rollback or drain already admitted work. Production must never start
an old write-capable server as an outage fallback. Complete persistent/vendor fences
and actual worker-drain evidence before composing or deploying an active owner.

## Candidate CLI compatibility

`control-cli.py --help` uses the existing parser with candidate-specific guidance.
Normal `jarvis-cli` and `.pi/extensions/45-jarvis.ts` still select `jarvis.py`; no
client has been silently migrated.

For candidate device writes:

- Configured plug aliases only, canonicalized to lowercase. No direct-IP target,
  alternate vendor config, discovery target or non-default vendor timeout.
- Existing pure purifier setting validator is reused without executing its argv.
  Canonical supported settings/convenience flags are preserved; conflicting or
  irrelevant flags are rejected rather than silently ignored.
- Purifier selection is an explicit opaque 24-hex `deviceID`, or the exact
  epoch-bound default in the private bundle. Names/models/raw CID fallback are
  rejected. No unsignaled cloud/default discovery is done to recreate old behavior.
- Saving discovery is blocked at this entry: catalogue mutation requires owner
  maintenance. Ordinary read and unrelated actions keep their existing path.
- Retain `--json`, `ok`, `action`, `summary` and normal exception/cancel exit handling.
  ACK/PENDING exit zero, UNKNOWN exits one with an explicit no-auto-retry message.
  Preflight/window/credential errors exit nonzero without vendor fallback.
- New `control` receipt fields include protocol, disposition, request ID and digest;
  `verificationPending` is explicit. There is **no fabricated vendor status**, raw
  selector or causal confirmation. A receipt is not a fresh device reading.
- The existing Pi tool consumes exit status, `ok`, `error` and `summary`, but actual
  invocation-stack certification and migration are still pending. Do not claim
  byte-for-byte compatibility with consumers of legacy `plug`/`purifier` data.

Non-device behavior and the default public CLI are unchanged. A caller cannot turn
an UNKNOWN result into permission for a new intent ID or a direct command.

## Verification and next gate

`tests/test_control_connection.py` exercises private modes/link/schema/failure
handling, actual CLI parser and subprocess entry, real shared HTTP handler, raw
framing/trickle/pipeline/thread-capacity defenses, endpoint-loss closure and
preservation of health/state/service routes. It includes a path through the actual
dispatcher/coordinator with a fake runner, plus receipt loss after a synthetic effect
without another effect or direct vendor invocation. No physical acceptance is done.

Production composition must also resolve the **source-location boundary**: the
certificate currently derives absolute entry/parser/handler paths from its core
package root. Tests use a complete same-root frozen layout. A frozen server and
checkout-loaded client are not interchangeable; silently ignoring path mismatches
or auto-rehashing would invalidate the review. Pin and test the actual installed
client/parser locations (and non-device runtime roots) before production enrollment.
The candidate now shares an absolute deadline across credential checks and the
window-plus-command transport sequence; metadata cannot renew the mutation budget.
The full invocation review remains unfinished: interpreter startup, lifecycle events,
local file IO and the existing Pi outer timeout/cancellation need installed-stack
certification before switching defaults. See [cutover status](cutover-status.md) for
the uninstalled worker/SDK delegation integration and outstanding activation gates.

Next: finish installed writer inventory and **persistent/cohort-wide fences** across
public/vendor/private-worker entry points; then compose production ownership and
credentials, approved readback/recovery/capacity/rollback procedures and the default
CLI/Pi switch. User approval for this same cutover scope remains in place; these
implementation gates must be satisfied rather than bypassed or repeatedly reapproved.

See [local transport](local-control-client.md), [client convergence](client-convergence.md),
[protocol](control-protocol.md), [device host](device-host.md) and
[deployment limits](foundation-rollout.md).
