# Local CLI-first control cutover: identity and transport candidate

## Status — source only, not activated

The owner approved a **CLI/Pi-tools-first** migration, temporarily disabling device
writes from older app versions at cutover while preserving v1 status, services
and unrelated APIs. This authorization does not waive the activation gates.

`jarvisd_core/control_identity.py`, `control_transport.py` and
`tests/test_control_transport.py` implement the candidate identity/transport.
The subsequent [connection phase](control-connection.md) adds an explicit candidate
CLI entry, private bundle implementation, bounded raw HTTP handler and process-local
v1 write retirement. The source handler imports that pure boundary, but normal
backend startup does not compose it; default CLI/Pi routing remains unchanged.
Only temporary test credentials exist. No production ledger/v2 route, cohort-wide
vendor fence or client cutover has been activated. The active compatible
`20260919T155241Z-control-foundations` deployment remains unchanged.

## Identity and peer authentication

- Explicit, bounded enrollment maps a client ID to a **dedicated 256-bit key**,
  stable principal fingerprint, cohort scopes and one reviewed transport profile.
  The principal is independent of the key, so rotating a key must not reset
  durable duplicate rejection. There is no default identity or network enrollment.
- Requests and replies use domain-separated HMAC-SHA256. The dedicated key is
  **never sent**, unlike a bearer token exposed to an unrelated process occupying
  the local port. Request proofs bind the numeric origin port, client, fresh
  challenge, exact method/path and body digest. Reply proofs additionally bind
  the original body digest, HTTP status and exact response body.
- This profile permits only numeric IPv4 `127.0.0.1`, default port **8790**, and
  exact POST `/api/v2/control/window` or `/api/v2/control/command`. A different
  explicitly constructed port is used for isolated test peers, never failover.
  Mapped IPv6, other loopback addresses, LAN sources, forwarding/Origin/cookie/
  legacy-auth headers, duplicate headers, unknown fields and alternate paths fail.
- Enrolled transport certification is checked against retained source/runtime
  hashes before issuing access. The inventory includes the client/codec/identity
  modules, relevant standard-library modules, interpreter, extension binaries and
  shared libpython (the installed uv CPython builds `_socket`/`_hashlib` into it).
  Checks are bounded regular-file reads; links, nonregular files, missing/drifted
  sources, unsupported profiles/runtime versions and read failures fail closed.
  Computing current hashes **is not certification**. Never auto-refresh accepted
  hashes after a failure; use independently retained successful review evidence.
  The connection phase extends this inventory to the candidate CLI entry, shared
  parser/router, credential helper and real handler. **It still does not certify
  the unmigrated default CLI/Pi invocation stack.** Review their behavior/source
  coverage before production enrollment; arbitrary callers may reconstruct intents.
- Issued access objects are registry-bound by identity, not just equal field values.
  The host's fast authorizer checks current revocation and scope without file I/O
  under ledger/coordinator locks. Weak bookkeeping is bounded to 2,048 live access
  objects. A reconstructed `Access(..., transport_verified=True)` is not authorized.
- Revocation prevents subsequent admission checks; it is not retroactive device
  cancellation. Private bundle persistence now exists in the connection candidate;
  production provisioning, rotation orchestration and transition ownership remain.

HMAC authenticates/integrity-protects messages; it **does not encrypt them**. This
profile is for approved local appliance control only, not remote/sensitive access.
It is not process/memory attestation, exhaustive transitive-library attestation or
same-user isolation: a process that steals the private key can impersonate the
client. Future provisioning must enforce private storage and distinct credentials.

## One-submission client

The client opens one `AF_INET` stream socket to the fixed numeric origin, connects
once and calls `sendall` once. It uses no HTTP pool, DNS/address iteration, proxy
environment, redirect handler, credential recovery, retry loop or alternate API.
TCP retransmissions/partial low-level writes are not additional HTTP submissions.

A single absolute monotonic deadline covers connection, sending, every response
read and EOF. Responses require bounded headers (16 KiB / at most 32 fields), an
unambiguous bounded Content-Length (16 KiB body), exact media type, no-store and
connection close. Duplicate/folded/control-character headers, chunking, extra or
missing bytes, informational responses and unauthenticated replies are refused.
Even an authenticated redirect is never followed.

A window must have exact schema, cohort, incarnation, epoch, token and TTL. Local
age is only an early rejection check; authoritative server expiry/readiness still
applies. The immutable command envelope uses the existing nested v2 format and
portable digest definition. A process-local intent budget is consumed atomically
**before transport**, including wrong-client use, connection failure, partial send,
cancellation and response loss. It cannot be reused after any result.

Only an authenticated, correlated v2 receipt can yield ACK/PENDING. Errors,
redirects, malformed/mismatched receipts and lost responses remain UNKNOWN. No
result grants freshness, clears quarantine, proves causality or authorizes replay.
There is no durable client outbox. Reconstructing an intent/new request ID is not
recovery; the backend's persistent ledger is still required to reject duplicates.

## Read-only inventory evidence and limits

- The local Pi extension invokes the public `jarvis.py` via `pi.exec`; it is not an
  API client yet. Native `JarvisClient` still calls v1 for device and non-device APIs.
- JARVIS scheduler status reports three enabled jobs. Previously inspected names
  were scraper/gear/backup jobs; names/status alone do not certify job behavior or
  establish an exhaustive writer inventory.
- Read-only SSH probes found no operation checkout at `~/JARVIS/projects/operation-jarvis`
  on `mac-mini-16`, nor at the checked `~/JARVIS`/`~/jarvis` operation paths on the
  Raspberry Pi. On `master-chief`, neither the checked user-profile `JARVIS` path
  nor user-profile `projects/operation-jarvis` path existed. The first Windows probe
  used an incompatible POSIX shell; the subsequent PowerShell probe succeeded.
  These are **bounded negative path checks**, not proof that hosts have no writers.
- The preceding local ADB check found no attached dashboard, so installed dashboard
  compatibility remains unverified. No remote ADB or physical acceptance was used.

## Remaining before cutover

1. Finish actual installed/running writer/job/configuration inventory. Implement
   cohort-wide fences on v1 device commands, public/vendor CLIs, private worker and
   other cooperating entry points. No writable outage fallback may survive.
2. Provision private enrolled credentials and independently reviewed certificate
   records using the new bundle implementation. The connection phase implements
   bounded raw framing and tests the actual handler; production composition is
   still pending, and the old transport suite's synthetic peer is not that listener.
3. Compose the ledger, catalogue, registry, dispatcher and real transition owner.
   Establish actual worker quiescence and post-activation observations; do not turn
   on API ownership by passing fabricated `HandoffEvidence` booleans.
4. Finish the default CLI/tool switch and invocation-stack review. The explicit
   candidate entry already exercises the actual parser/lifecycle/subprocess path;
   it is not selected by the default launchers. The receipt intentionally
   omits legacy vendor details/private selectors; do not recreate them by fallback.
5. Compose controlled readbacks under existing collector/cooldown rules and finish
   unsupported-setting/toggle recovery, store-loss/capacity and closed rollback
   procedures. Never erase uncertainty or recycle consumed intent IDs.
6. Freeze and verify complete paired artifacts, deploy and stage the cohort handoff.
   Only then disable legacy app **device** writes; preserve status/service APIs.

## Verification

`verify.sh` discovers the hardware-free suite. Synthetic peers exercise real sockets,
MACs, source checks, revocation, the persistent ledger and one end-to-end path through
real `DeviceControlHost`/dispatcher/coordinator with a fake runner. Cases include
response loss after an effect, deliberate duplicate rejection without another effect,
concurrent claims, partial sends, cancellation, connection failures, proxy/DNS bypass
attempts, authenticated redirects/errors, reply/body/status/digest tampering, captured
reply replay, bad windows, malformed/oversized/trickled replies and import purity.
No real device credentials, discovery, SDK mutations or production routes are used.

See [client convergence](client-convergence.md), [protocol](control-protocol.md),
[device host/readback](device-host.md) and [deployment boundary](foundation-rollout.md).
