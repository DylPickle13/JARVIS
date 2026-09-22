> **Deployment checkpoint (2026-09-19):** `20260919T215836Z-room-session10`.
> CLI/Pi device writes use authenticated loopback `/api/v1/local-control`;
> current native clients use `/api/v1/device-command` with existing app auth.
> Legacy `/api/v1/command` device writes return 409. The ownership stack remains
> inactive. See [minimum deployment](docs/simple-deployment.md),
> [native controls](../jarvis-app/docs/native-control-update.md) and
> [Room Audio / Session 10](../jarvis-app/docs/room-session10.md).
> Installed deployment records remain authoritative.

# jarvisd — shared control backend

The stdlib-only Python HTTP backend for Operation JARVIS. The native iPhone,
Watch, and widget clients use its existing API; backend ownership is independent
of those clients. See the [architecture and phased plan](../docs/backend-architecture.md).

**Exclusive-ownership cutover is not active:** see the historical
[candidate progress and blocking gates](docs/cutover-status.md). The deployed
best-effort CLI/Pi and native routing does not require that deferred machinery.

## oMLX update indicator (deployed 2026-09-20)

Deployment record: `20260920T230414Z-omlx-update-indicator`. Read-only health and
both server checks passed; protected terminal/audio services and pane identities
were unchanged. Only the backend daemon was replaced; oMLX was not restarted.

`GET /api/v1/omlx` includes optional per-server `update` metadata. Independent
hourly workers read each configured oMLX server's `/admin/api/update-check`,
using that server's installed-version comparison and selected release channel.
Only availability, a validated release version, and cache health/age are exposed;
no release URLs, credentials, downloads, installs, or service restarts.
The iPhone/Watch title dot requires fresh activity and a successful, non-stale
update result no older than two hours. Missing/unsupported checks show no dot.
Release checks do not block or change the existing activity polling cadence.

## Whole-Mac RAM telemetry

Deployed 2026-09-20 EDT: `20260921T023147Z-host-memory`, alongside native build
206. Both hosts returned fresh whole-Mac readings through the installed daemon.
Health checks passed and protected terminal/audio service and pane identities
were unchanged. Only jarvisd was replaced; neither oMLX server was restarted.

`GET /api/v1/omlx` adds optional per-server `hostMemory`: `ok`, `usedBytes`,
`totalBytes`, `definition`, `ageSeconds`, and `stale` (a sanitized `error` on cold
failure). This is backend-owned host telemetry, never oMLX process/model memory.
`jarvisd_core/host_memory.py` reads `sysctl hw.memsize` and `vm_stat` locally for
`mac-mini-64`, and through the existing trusted SSH alias `mac-mini-16` for that
host. The daemon account must already have noninteractive SSH access and a known
host key; the collector never provisions credentials or accepts new keys.

Independent single-flight workers sample every 10 seconds while the oMLX card is
visible and every 60 seconds while idle after the first request. Reads have a
four-second deadline, a 16 KiB output cap, no login prompts, and no retries.
A 30-second freshness limit and immediate failure invalidation apply independently
of oMLX activity/release checks. API polls only read cached snapshots; they do not
wait for SSH, and client code never collects host metrics itself.

Memory used is `(anonymous - purgeable + wired + physical compressor) * pageSize`.
This follows macOS's app/wired/compressed categories, excludes reclaimable
file-backed cache, and does not double-count logical compressed pages or swap.
It is not `total - free` or `total - available`; independent samples can differ
from Activity Monitor's live display. The wire definition is
`macos-nonpurgeable-anonymous-wired-compressed`. Missing/inconsistent counters
fail closed. The static card shows rounded GiB as `38G`; VoiceOver gives one
decimal and total capacity. Old backends and stale host reads show `—`, with no
fallback to the existing oMLX-only `memoryUsedBytes` field.

## Basement and living-room presence (2026-09-21)

`GET /api/v1/presence` exposes sanitized, read-only basement proximity from the
local Mac BLE listener. Requires API-token or authenticated loopback access;
not included in trusted-network aggregate state. Missing/stale data is unknown.
Deployment `20260921T051732Z-living-room-presence` adds independent basement and
living-room `zones`, retaining the legacy basement `presence` field. The Mac Watch
and iPhone are enrolled. The relocated Pi resolves both devices with private IRKs,
and its authenticated SSH bridge delivers living-room state. Both zones operate;
initial two-way seated and short idle-device checks passed. Broader physical
acceptance remains incomplete. See [presence](../presence/README.md).

## On-demand network speed diagnostic (source-only)

`GET /api/v1/network/speed-test` returns an in-memory snapshot without starting
work. `POST` to the same route with `{"acknowledgeBandwidth": true}` starts an
asynchronous local `/usr/bin/networkQuality -c -M 60` test. Both require the API
token or authenticated loopback local-control credentials, even in trusted-network
mode. Unapproved origins, query parameters, extra fields and remote selectors
are rejected. Clients must show the returned bandwidth warning before requesting
acknowledgement: tests consume substantial data and can disrupt streaming.

POST returns 202 when admitted, 409 while running, or 429 with `Retry-After`
during the five-minute start-to-start cooldown (including failed runs). GET
reports `idle`, `running`, `completed`, or `failed`, a test ID, Unix-second start/
finish timestamps, sanitized error, and `result` containing `downloadMbps`,
`uploadMbps`, and `idleLatencyMs`. Throughput is simultaneous upload/download,
not an Ookla-equivalent sequential benchmark. `ok` describes the API response;
inspect `status` for test success. Results are historical snapshots, never live
connectivity indicators; they and the cooldown reset when jarvisd restarts.

Only Home internet — mac-mini-64 is measured, not phone Wi-Fi/cellular. One
background worker has a 75-second hard deadline, 64 KiB output cap, fixed argv,
normal TLS validation, and no retries. No automatic polling tests, schedules,
new dependencies, raw provider metadata, or native-client changes. Parsing uses
this Mac's documented networkQuality JSON fields; live provider validation and
deployment remain pending. No daemon restart or actual bandwidth test was
performed during implementation.

## Native monitoring (deployed 2026-09-22 EDT)

Active release `20260922T143035Z-passive-monitoring` adds separate **on-demand**
read health for purifier, presence and Pi/Mac room audio. No extra device polling,
cloud authentication or recovery attempts; no incidents for expired passive data.
653 frozen-backend tests passed. Live sensor reads showed intermittent failures;
monitoring availability is not a claim of proven sensor reliability.

Release `20260922T142353Z-expanded-monitoring` also monitors existing Pi,
services, network and Codex quota caches. All nine configured read-health checks
were available after activation; 650 frozen-backend tests passed. Notifications
remain disabled and no dashboard is served. Physical sensor transition and real
hub outage tests were skipped at the owner's request, not marked passed.

Deployment `20260922T135534Z-native-monitoring` enables 60-second, completion-relative
polling for `door-sensor` and `motion-sensor`, with **notifications disabled**.
The frozen release passed 650 backend tests; both sensors completed two background
checks with available hub snapshots. Plug and both oMLX read-health checks passed.
Protected terminal/audio service identities were unchanged. The unrelated
network-speed work was excluded. The browser dashboard has been removed at the
owner's request in release `20260922T141423Z-remove-monitor-dashboard`;
monitoring remains available through authenticated APIs. Both removed dashboard
URLs return 404, 650 frozen-backend tests passed, and sensor polling resumed.
Physical transitions and radio freshness are not established by these checks.

The local implementation adds serialized security polling, bounded sensor-read
recovery, and authenticated cache-only `/api/v1/monitor/*` endpoints. It extends
the existing daemon with bounded SQLite incident history, sustained-failure and
recovery detection, and optional local Mac notifications. No browser dashboard,
Kuma, VM, container or separate daemon. Monitoring and
notifications default off in source; the installed activation above enables only
polling/monitoring, not notifications.
See [configuration and acceptance checks](docs/monitoring-native.md).
Purifier recovery protections remain unchanged.

## Current responsibilities

- Cached state with per-subsystem freshness and last-good observations.
- Validated plug/purifier commands through existing adapters, with per-device
  daemon write admission, freshness rechecks, and uncertain-result cache barriers.
- Private workers for all command actions, including local system status; no
  public-CLI dependency. Writes carry admitted host/CID checks into vendor wrappers.
- Read-only telemetry, scheduler projections, and sanitized event ingestion.
- Allowlisted service operations, room-audio status/exact-turn stop, and the
  existing native signing helper integration.

Security integration, general Raspberry Pi management, exclusive client ownership,
and new permission scopes are future phases. The deployed routes add no device
capabilities. Conflicting, unknown-device, or stale-cache writes are now rejected
before dispatch; see [integration contracts](docs/integration-contracts.md). `terminald`, room audio, and the scheduler remain
separate services. The daemon is not a shell or replacement agent runtime.

## Historical exclusive-ownership candidate notes

The following notes describe earlier milestones, not current deployment status.
In particular, the foundation rollout below was superseded by the minimum
CLI/Pi rollout and native-client/room-audio updates linked above.

The [client convergence contract](docs/client-convergence.md) now defines no
outage fallback/replay, explicit drained maintenance, and cohort ownership epochs.
Its tested reference model is not wired into any writer: the current deployment
remains mixed-legacy, without a cross-client maintenance fence or intent journal.
The [persistent ledger foundation](docs/control-ledger.md) now implements closed
startup, durable duplicate rejection and uncertainty/read fences in isolation;
production protocol, legacy fencing, client transport and retention gates remain.
A [dormant candidate v2 boundary](docs/control-protocol.md) now connects strict
non-v1 command envelopes to the ledger with synthetic hosts only. It adds no live
route. The [dormant device host](docs/device-host.md) now connects it to the real
dispatcher/coordinator with fake-runner tests and activated-epoch read fences.
Runtime composition, authentication, legacy fencing and client certification remain.
A new **source-only** [local-client identity/transport candidate](docs/local-control-client.md)
adds scoped enrollment, signed requests/replies and a one-submission loopback client.
It has not been deployed. The [connection candidate](docs/control-connection.md)
now supplies an explicit `control-cli.py` entry, private credential bundles, bounded
raw HTTP framing and an opt-in server that retires v1 device writes. Actual parser/
handler/dispatcher tests use fake hardware. Normal startup and default CLI/Pi routing
remain unchanged; persistent/vendor fences, production composition and cutover remain.

The [compatible foundation rollout](docs/foundation-rollout.md) bundles these
components and explicit readback reconciliation **without activating v2 ownership**.
Deployment `20260919T155241Z-control-foundations` was activated at that milestone
and read-only verification passed. Installed plists/deployment records identify the running
package; bundled code is not a completed client cutover. Existing v1/direct-client
behavior remains intact.

## Layout and configuration

- `jarvisd.py`: composition root and legacy API/non-device collector/service wiring.
- `device-worker.py`: private allowlisted worker entry, never the public CLI.
- `jarvisd_core/`: config, auth, commands, HTTP input, events, logging, diagnostics,
  state coordination, device adapters/collectors, and bounded write admission/dispatch;
  no import-time I/O.
- `docs/integration-contracts.md`: implemented boundaries and next extraction gates.
- `docs/device-adapters.md`: private worker path, legacy parity, and retry-review limits.
- `docs/client-convergence.md`: outage/maintenance/ownership policy and cutover gates;
  `jarvisd_core/client_policy.py` is an offline reference, **not live enforcement**.
- `docs/control-ledger.md`: dormant persistent ownership/reservation primitives in
  `jarvisd_core/control_ledger.py`; explicit private storage, no runtime wiring.
- `docs/control-protocol.md`: strict candidate protocol/receipt boundary in
  `jarvisd_core/control_protocol.py`, portable digest fixtures and remaining gates.
- `docs/device-host.md`: dormant protocol-to-dispatcher bridge, immutable catalogue,
  activated-epoch observations and authorization/identity rechecks.
- `docs/local-control-client.md`: source-only CLI-first identity/transport candidate,
  synthetic-peer evidence, inventory limits and remaining cutover gates.
- `docs/control-connection.md`: explicit candidate CLI, private bundles, real HTTP
  boundary, process-local v1 fence, compatibility limits and uncompleted live cutover.
- `docs/foundation-rollout.md`: compatible deployment/rollback scope, inactive
  ownership gates and explicit readback reconciliation.
- `tests/`: SDK-free API, infrastructure, vendor-wrapper, policy, and relocation tests.
- `tests_sdk/`: real Kasa/VeSync SDK tests against synthetic loopback peers only.
- `services.json`: existing service allowlist.
- `launchd/`: host-specific LaunchAgent templates; review paths before use.
- `resurrector.sh`: separate daemon health watchdog.
- `logs/`: ignored private logs/event history; never commit.

Port **8790** and labels `com.operation-jarvis.jarvisd` and
`com.operation-jarvis.jarvisd-resurrector` are unchanged. Authentication remains
explicit trusted-network or token mode; never expose the daemon publicly.
See the [native trust boundaries](../jarvis-app/docs/architecture.md#security-and-trust-boundaries).

Source-relative defaults now find `services.json` and `logs/` here. The signing
helper stays at `../jarvis-app/scripts/renew-free-signing.sh`, resolved through
`OPERATION_ROOT`, not the daemon's parent app directory. Existing environment
overrides remain supported. In a frozen artifact deployment explicitly configure
`JARVISD_OPERATION_ROOT`, `JARVISD_PROJECT_ROOT`, and private services/event/log
paths; preserve all existing authentication and runtime overrides.

## Verification

From any directory:

```bash
/path/to/JARVIS/projects/operation-jarvis/jarvisd/verify.sh
/path/to/JARVIS/projects/operation-jarvis/jarvisd/verify-kasa-sdk.sh
/path/to/JARVIS/projects/operation-jarvis/jarvisd/verify-vesync-sdk.sh
```

The separate SDK gates use the existing vendor interpreters, block external
network/device/configuration access, and install nothing. Run all three gates
before deployment; see [Kasa](docs/kasa-write-safety.md) and
[VeSync write safety and maintenance](docs/vesync-write-safety.md).

This isolates project configuration and event/log storage in a temporary runtime,
runs the Python tests, parses LaunchAgent plists, and checks Python/shell syntax.
It does not start installed services or operate hardware. Prefer this wrapper to
raw discovery so tests cannot load live configuration. Entry-point imports now
use memory-only events; persistent history is opened explicitly in `main()` after
configuration validation. Core imports do not read configuration or start work.
Use `PYTHON=/path/to/python` to select the deployed interpreter.

Read-only health of an intentionally running daemon:

```bash
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8790/health
```

Health is not proof of authorization, state freshness, app behavior, or device
write correctness. Full native verification remains in
[`jarvis-app/scripts/verify-jarvis-app.sh`](../jarvis-app/scripts/verify-jarvis-app.sh).

## Deployment and rollback

Do not overwrite an installed plist with a template: the installed service may
use a frozen artifact and private environment overrides. Frozen artifacts must
include **`jarvisd.py`, `device-worker.py`, and the entire `jarvisd_core/` package**. Verify imports
from the staged artifact without relying on the checkout/current directory.
The write-safety updates also require the four matching vendor controller/CLI
files plus `air-purifier/air_purifier/write_safety.py`; retain/verify those source
backups and the helper's original existence with the backend rollback. See
[paired update ordering and retry limits](docs/device-adapters.md).

For an ordinary backend update, preserve runtime paths/history, retain the old
artifact/plists, and switch only the daemon's source/working-directory paths.
Stop the watchdog before the daemon; wait for asynchronous launchd unloading,
then start the daemon, check health/state, and restore the watchdog. Rollback
switches back to the prior artifact; never restore a stale event-file snapshot.

For the initial directory relocation, after owner approval:

1. Save installed daemon/watchdog plists and the old source in an owner-only
   rollback directory outside Git. Record baseline health and unaffected service
   identities. Prepare and test the new source before stopping anything.
2. Stop the resurrector, then the daemon, using their exact launchd labels.
   Preserve event/log data while no daemon writer is active.
3. Relocate runtime data to this directory's ignored `logs/`. Update installed
   plist paths, including `JARVISD_SERVICES_FILE`, `JARVISD_EVENTS_FILE`,
   `JARVISD_LOG_FILE`, stdout/stderr, working directory, and source path as needed.
   Retain other overrides; keep the existing frozen-artifact deployment model.
4. Start only the daemon. Verify `/health` and authorized read-only API contracts,
   then restore the resurrector. Check unrelated service/session identities.
5. Remove the obsolete app-owned source directory only after verification.

Rollback: stop resurrector then daemon, restore the prior source and plists,
move the **current** event/log history back to its old path (do not replace it
with a stale snapshot), start the prior daemon, verify health, then restore the
resurrector. Keep new source for diagnosis. Never replay commands or roll back
Pi sessions, device state, or scheduler databases as part of daemon recovery.

No app rebuild, signing, device installation, hardware write, or other service
restart is implied by a backend relocation.
