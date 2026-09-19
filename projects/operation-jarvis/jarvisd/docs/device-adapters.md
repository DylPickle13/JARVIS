# Private plug/purifier adapter boundary

## Implemented path

```text
HTTP authorization → command validation → daemon write admission/cache barriers
  → DeviceAdapterRunner → frozen device-worker.py → vendor CLI/environment

Device collectors → DeviceAdapterRunner → same private worker (events disabled)
```

- `device_transport.py` routes existing internal argv to an absolute frozen worker
  using the daemon's interpreter. It forwards the existing outer deadline and
  environment overrides. Missing/failed workers do **not** fall back to public CLI.
- `device-worker.py` is a local executable, not a new service/listener, public API,
  permission boundary, queue, or privileged broker. Its parser exposes only the
  eight existing command actions (including local `status --no-cast`) plus internal
  `purifier-status-all`. Writes require server-derived host/CID bindings.
  No discovery/save-discovery, Cast, security, arbitrary script/config paths,
  timeout overrides, or write-time cooldown bypass are admitted by that parser.
- `device_vendor.py` retains the existing vendor subprocesses: the smart-plug
  interpreter with `-m smart_plug.cli`, and `air-purifier/purifier-cli`. Those SDKs
  stay in their existing environments; they are never imported into the daemon.
- `device_translation.py` preserves legacy setting translation and result summaries.
  Public `jarvis.py` is deliberately unchanged and remains a separate legacy writer.
  Its low-level plug controller now also benefits from the safer wrapper behavior.
  This transitional compatibility implementation is checked against legacy ASTs,
  argv, environment, summaries, errors, and payload fixtures. Delete redundant
  public device handling during deliberate client convergence, not by redirecting
  this private worker back through that CLI.
- `device_collectors.py` owns the existing device collection/projection logic.
  Scheduling, revisions, freshness, pending commands, and private selector-map
  ownership remain in the coordinator/composition root. Collector concurrency,
  deadlines, event suppression, and explicit-only purifier recovery are unchanged.
- Worker environment loading preserves process → project `.env` → operation `.env`
  precedence, including legacy `export` lines. Vendor-local configuration still
  belongs to the vendor CLI. No configuration is loaded on core import.
- The worker emits the existing best-effort `operation-jarvis` lifecycle events,
  preferring the event token. These are **not** a new redacted command-audit store.
  An outer timeout can still prevent a completion event, just as before.

All daemon command actions now use the private worker. `status --no-cast` performs
local installation/file checks only, with the legacy payload and no public CLI,
Cast import, SDK call, or vendor subprocess. The CLI back-edge is removed.
Public CLI/tool device writers are still not serialized by the daemon's process-
local gate. No CLI/tool client has been switched to the API.

## Deadline and outcome limits

Outer command timeout remains 30 seconds; plug-list/status collector limits remain
12/10 seconds and purifier batch limit remains 25 seconds. The existing process
runner starts a worker process group and kills that group on timeout. Vendor
children do not create new sessions. Inner vendor timeouts, read retry behavior,
and purifier write-wait overrides are unchanged. Mutations now use reviewed
[Kasa](kasa-write-safety.md) and [VeSync](vesync-write-safety.md) request guards.
VeSync power/display/light-detection writes add validated preparation reads;
known Vital 200S status observations are validated before being marked fresh.
Plug credential fallback is now
limited to pre-write connection/status reads. An extra pre-write observation for
on/off is intentional and remains inside the existing deadline.

One daemon dispatch invokes one worker. This does not prove one wire-level write.
Process cancellation does not prove cancellation at the device/cloud. The existing
uncertain-result cache barriers remain required. There is no automatic fallback,
retry, durable queue, or replay added here. Vendor stdout buffering and process
shutdown/orphan handling still merit separate hardening; do not claim new resource
bounds beyond existing deadlines, collector concurrency, and write admission.

## Source retry/identity review — convergence blockers

This is a bounded review of repository wrappers and specified Kasa/VeSync mutation
paths, **not** a complete dependency audit or physical write certification:

- **Wrapper replay fixed:** Kasa credential fallback only surrounds pre-write
  connection/status reads. Once `turn_on`/`turn_off` is invoked, authentication
  failures, timeouts, cancellation, and verification failures exit without another
  wrapper mutation attempt. Unconfirmed desired state is an error, not success.
  Connections are closed on success/failure/cancellation. Direct CLI callers also
  use this safer controller, but remain outside daemon admission.
- **Toggle connection pinned:** Kasa toggle resolves once, reads and writes on the
  same authenticated connection. Other controllers can still race it. Native
  controls still use desired-state on/off; toggle remains compatibility-only.
- **Admitted identity checked before mutation:** the dispatcher adds private
  `--expected-host` / `--expected-cid` arguments from its admitted target, never
  from client-supplied metadata. The worker requires these bindings. Kasa rejects
  changed configuration/observed hosts before writing; VeSync requires an exact
  CID and cannot remap it through a default, alias, name, or model. Mismatches or
  missing/duplicate CIDs fail closed. Older vendor parsers reject unknown flags,
  rather than silently executing an unbound write under deployment skew.
- **Kasa SDK mutation guard implemented:** the reviewed IOT/SMART power paths
  force `retry_count=0`, cap query/transport/HTTP submissions independently, and
  disable HTTP redirects and persistent-connection retry during mutation only.
  Source fingerprints and exact protocol/transport checks reject unreviewed
  stacks. Guards are connection-local and restored before verification reads.
  Installed SDK files are untouched. Real-SDK loopback tests reproduce four
  unguarded attempts and verify one guarded submission after response loss.
  See [scope, operational limits and mandatory SDK gate](kasa-write-safety.md).
- Host/CID binding is not cryptographic device identity, DHCP replacement
  detection, immutable catalogue generation, or global locking. Direct legacy
  writes do not have a daemon-admitted identity. Concurrent catalogue edits
  remain maintenance-only.
- **VeSync SDK mutation guard implemented:** a device-local manager view blocks
  token reauthentication/replay during mutation; independent API/HTTP budgets and
  redirect/retry suppression bound the reviewed setting request. CID and payload
  are pinned. Known-model observations must be valid/new, not optimistic SDK
  state. Valid mismatches retain pending behavior; malformed responses fail.
  Read recovery/backoff remain separate. Raw selectors stay private; native
  default writes remain pinned to explicit observed CIDs. See
  [VeSync scope, observation checks and SDK gate](vesync-write-safety.md).
- VeSync cloud-session admission/backoff and `--retry-cooldown` remain in the vendor
  environment. Only explicit read recovery can pass that flag. No background
  verification loop or automatic cooldown bypass is introduced.

Do not converge additional writers or enable sensitive controls on the strength
of wrapper-level no-replay alone. Remaining gates include explicit client
outage/maintenance and write-ownership policy, scoped credentials, and separately
approved physical acceptance tests. The SDK application-request guards do not
certify exactly-once execution, all SDK paths, or device/cloud cancellation.

## Verification/deployment

`../verify.sh` runs hardware-free adapter parity, closed-parser, no-fallback,
process-group timeout, event, cache, and synthetic frozen-worker tests. Fake vendor
executables receive simulated writes; they do not load SDKs or contact devices.
Poisoned public CLI fixtures ensure device workers neither import nor execute it.
Also run **`../verify-kasa-sdk.sh` and `../verify-vesync-sdk.sh`** before deployment.
They use the existing vendor interpreters and real SDKs against synthetic loopback
peers, blocking discovery, DNS, external connections and private settings/auth
access. No dependency is installed or hardware accessed. All three gates support
`JARVIS_TEST_VENDOR_ROOT`.

Deploy **`jarvisd.py`, `device-worker.py`, and all of `jarvisd_core/` together**.
The matching vendor controller/CLI files must be installed as a paired update:
`smart-plug/smart_plug/{kasa_client,cli}.py` and
`air-purifier/air_purifier/{vesync_client,cli,write_safety}.py`. Stage and test before
replacing live vendor sources. Install the new helper before controllers, then
CLIs and backend. Retain hashes/prior files and original helper existence;
rollback CLIs before controllers, restore the old controller before removing a
newly introduced helper, and restore the prior backend. Never restore a stale event/configuration snapshot.
Vendor SDK installations/environments remain unchanged external dependencies.
Preserve private configuration, current events, protected sessions, and prior
complete artifacts. Restart only daemon/watchdog; verify live health/state/events
with reads, not physical write probes.

The backend verifier includes fake-device vendor safety tests. During staging,
`JARVIS_TEST_VENDOR_ROOT=/path/to/candidate-operation-root` selects candidate
wrapper sources for those tests; ordinary verification uses repository sources.
