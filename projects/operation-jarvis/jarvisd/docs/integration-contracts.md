# Integration contracts and extraction boundaries

This is an incremental contract for the shared backend, not a claim that all
integrations or protections are already implemented. Existing native HTTP paths
and JSON shapes remain the compatibility boundary.

## Implemented foundation

`jarvisd_core` contains stdlib-only modules with no import-time I/O:

| Module | Responsibility | Explicit inputs / boundary |
|---|---|---|
| `config.py` | Environment-file and checkout-root helpers | Caller invokes loading and supplies the source/project roots. |
| `auth.py` | Current CIDR or token authentication, event-token isolation | Explicit policy values, peer address, token, scope; no implicit environment access. |
| `commands.py` | Closed command catalog and argv validation | Fixed CLI path and injected selected-purifier resolver; never executes commands. |
| `http_input.py` | Bounded UTF-8 JSON-object request decoding | Input stream, Content-Length, maximum bytes; HTTP status errors returned to handler. |
| `events.py` | Existing bounded event history and sequence persistence | Memory-only by default; persistence path and per-instance size limit supplied explicitly. |
| `logging.py` | Private rotating logs and repetitive-read coalescing | Path, size/retention, clock; no global log sink configured on import. |
| `diagnostics.py` | Existing bounded/path-redacted diagnostics | Not a general credential scrubber or security audit serializer. |
| `state.py` | Single-flight cache, freshness, revisions, write barriers | Explicit collectors, recovery callbacks, runtime identity, and clock. |
| `devices.py` | Pure existing device projections and opaque IDs | No vendor libraries, discovery, or device execution. |
| `admission.py` | Bounded process-local resource admission | At most 32 active device keys; reject conflicts without queueing. |
| `control.py` | Existing command execution and cache reconciliation | Injected cache, admission gate, adapter runner, and selected-purifier resolver. |
| `device_collectors.py` | Existing plug/purifier observations | Injected runner, fixed command path, event suppression; selector ownership stays in host. |
| `device_transport.py` | Private worker routing | Absolute frozen worker/interpreter/roots, existing runner deadlines; no CLI fallback. |
| `device_worker.py` | Closed worker lifecycle, environment, existing events | Explicit entry call; eight existing actions plus internal batch read, required private write identities, no listener. |
| `device_vendor.py`, `device_translation.py` | Legacy-compatible vendor invocation and projection | Existing vendor environments, injected subprocess runner/env, no SDK imports. |

`jarvisd.py` remains the composition root and compatibility facade. It loads
configuration, wires the modules, owns legacy routes/non-device collectors/service control,
and starts persistence and background work only through `main()`. Importing the
entry point still reads configured environment values/files, but no longer
rewrites event history or starts collectors/servers.

The command catalog is immutable and code-owned. Each existing action declares
its integration, read/write effect, fixed timeout, argv builder, and no-replay
policy. This metadata is **not** a permission grant. The dispatcher now serializes
conflicting daemon-originated writes, but not direct CLI/tool or external writers.

| Integration | Existing command actions | Effect |
|---|---|---|
| system | `status` (`--no-cast`) | read |
| plugs | `plug-list`, `plug-status` | read |
| plugs | `plug-on`, `plug-off`, `plug-toggle` | write |
| purifier | `purifier-status` | read |
| purifier | `purifier-set` | write |

All retain the existing 30-second handler timeout. Native plug controls use
on/off; toggle remains compatibility-only. Unknown actions remain rejected.
Selected purifiers resolve only through the existing private selector map and
fresh selected-device observation; an unknown selection never becomes a default
write. Public results continue using the existing projection, not argv or vendor
payloads. Execution remains one worker invocation with no queue/replay. A timeout does not
prove that the device did not receive a write. Repository/vendor retry behavior
is a separate boundary; see the [adapter path and retry review](device-adapters.md).

## Implemented daemon write admission

- Syntax/authentication checks precede admission. Writes require a known cached
  device; arbitrary plug hosts and unknown purifier IDs are not write targets.
- Plug cache names sharing the same normalized observed host share a gate.
  A default purifier is pinned to its observed opaque ID and explicit selector,
  sharing the selected-device gate even if the default changes during handling.
- A conflict or capacity/freshness rejection returns HTTP **409** with the existing
  `{ok, action, error}` shape and does not invoke an adapter. Invalid command syntax
  remains 400. Clients must not automatically retry a conflict.
- Freshness is rechecked under the cache lock inside resource admission. Cache
  revisions fence reads started before/during a write, including direct HTTP
  purifier status reads. Public snapshots use existing stale/error fields while
  a change is in flight; unrelated devices retain their own freshness.
- Confirmed results must match the selected device and, where represented, the
  requested desired state. Pending purifier verification stays pending until the
  batch collector reconciles its expectation. Pending settings without an
  expectation contract remain uncertain rather than becoming falsely fresh.
- Failures, malformed/mismatched results, or exceptions quarantine the affected
  cache row(s). A successful post-write observation can clear uncertainty; a
  failed read cannot clear it using last-good grace. No daemon write is queued,
  retried, or restored from history. Slots remain held until execution exits,
  rather than expiring while an adapter could still be writing.
- Plug reads retain their normal refresh behavior. Purifier uncertainty does
  not add a background verification loop or bypass existing cloud cooldowns.
- Admission is in-memory and process-local. Restart begins with cold cached
  state and does not replay writes. It is not a cross-process lock, durable
  command journal, or guarantee that an external/vendor operation has stopped.

Direct CLI/tools, other controllers, SDK-internal retries, and concurrent
catalogue/configuration edits remain outside this boundary. Plug wrapper credential
fallback is now limited to pre-write reads; admitted host/CID bindings are checked
in the vendor adapter before mutation. Kasa's reviewed mutation path now adds
connection-local SDK query/send/HTTP single-attempt guards; see
[Kasa scope and maintenance gates](kasa-write-safety.md). VeSync now has scoped
mutation replay guards and validated observations; see
[VeSync scope and maintenance gates](vesync-write-safety.md). The
[client outage/maintenance/ownership contract](client-convergence.md) and offline
reference model are now defined; a [dormant persistent ledger](control-ledger.md)
adds isolated ownership/reservation/uncertainty primitives. A subsequent
[candidate protocol boundary](control-protocol.md) adds strict non-v1 request and
receipt validation with synthetic hosts, not a live route. The [dormant device
host](device-host.md) now binds the real dispatcher/coordinator using an immutable
catalogue, epoch-read fences and fake runners. Production composition, ledger
reconciliation, legacy fencing, transport certification and client convergence
remain pending. Do not claim universal serialization or
exactly-once device execution. Treat catalogue changes as maintenance, not concurrent control.
No new device capability, integration, permission, or API route is enabled here.

## Requirements for subsequent extractions

1. **Observations:** collectors supply bounded sanitized data plus collection
   time and health. Preserve current per-device freshness, last-good retention,
   revisions, pending verification, and failure isolation. A late read must not
   overwrite a newer confirmed command. Offline/unknown must never imply safe.
2. **Capabilities:** only server-owned adapters register capabilities. Clients
   select public logical IDs, never shell text, paths, private selectors, or
   arbitrary remote hosts. Optional/private integrations remain unavailable
   unless deliberately configured; no automatic plugin discovery.
3. **Write admission:** the daemon dispatcher now owns bounded per-resource
   conflicts and freshness checks. Preserve its default/selected alias identity,
   read fencing, and no-queue behavior while extending integrations. Account for
   direct CLI/tool writers and configuration mutation before claiming cross-client
   or cross-process serialization.
4. **Outcomes:** distinguish rejected-before-send, confirmed, verification-pending,
   and delivery-unknown internally. Keep uncertain delivery visible; never
   automatically retry a write or restore it from history after restart. Introduce
   new public fields only with compatibility tests.
5. **Timeouts:** adapters own bounded vendor I/O. Worker/process isolation must
   prevent a stalled SDK from monopolizing unrelated integrations; cancellation
   is not proof of device-side cancellation. Avoid adding dependencies to the
   central stdlib service merely to load vendor SDKs.
6. **Audit:** add a separate allowlisted command-audit projection with resource,
   operation, request identifier, outcome, and timing. Do not forward raw command
   arguments, credentials, camera data, conversations, or vendor responses. The
   existing event ingestion API is not a new security audit/privacy boundary.
7. **Authorization:** existing LAN/token policy is preserved, not broadened.
   Scoped identities and encrypted sensitive transport must precede sensitive
   remote/security operations. Event credentials cannot authorize device control.

## Remaining phase-2 work

The coordinator, device dispatcher, plug/purifier collectors, and private device
workers are extracted and wired by the host composition root. No daemon command
calls public `jarvis-cli`; local `status --no-cast` is now a private file-check
handler too. Next extract remaining route/service and non-device collector domains. Preserve the cache and deterministic admission/concurrency
tests, and audit vendor retry/identity behavior before broader client convergence.
CLI convergence must follow adapter extraction so the backend cannot call a CLI
that calls the backend again. Before any cutover, implement the enforced ownership
protocol, integrate/certify the dormant persistent duplicate rejection/uncertainty
library, complete bounded retention and legacy fencing, and certify client
transports as described in [the convergence gates](client-convergence.md).
Current v1 metadata does not enforce an ownership epoch; a reachable daemon or
one client HTTP call is not proof of exclusive ownership or one submission.

Security, Cast/media control, Raspberry Pi management, fine-grained scopes, and a
new command-audit store are not activated by this foundation refactor.
