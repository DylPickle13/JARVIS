# Read-only Minecraft services

**Deployed with native build 250.** The owner-approved backend activated on
2026-10-04 at **23:55 EDT**; iPhone and Watch build **250** were independently
version/launch/process verified at **23:56 EDT**. This change does not start/stop
Paper, Mineflayer or its Pi agent, migrate `screen` to launchd, or change router
forwarding. Physical Services/Crown/VoiceOver acceptance remains owner review.

## Registry and ownership

The existing `services.json` adds two optional, continuous entries:

| ID | Adapter | Display name |
|---|---|---|
| `minecraft-server` | `minecraft-paper` | Minecraft Server |
| `minecraft-jarvis-bot` | `minecraft-bot` | Minecraft JARVIS Bot |

Legacy entries without an adapter continue using launchd, with unchanged status
and action rules. Minecraft adapters always expose `allowedActions: []` and reject
all lifecycle actions, even if the private registry accidentally grants them.
There are no client-selected commands, paths, ports or URLs. The fixed project root
is `JARVIS_ROOT/projects/minecraft-server`; a frozen deployment must retain its
existing explicit `JARVISD_JARVIS_ROOT`/root configuration.

The adapter lives in `jarvisd_core/minecraft_services.py`, performs no import-time
I/O, and is shared by cached state, service inventory and individual status reads.
The private Minecraft Git repository, runtime scripts, files and processes are
not modified by this feature.

## Observation contract

`ok` means process observation succeeded; it is not a claim that gameplay or model
inference works. Existing fields remain, with optional `ready` and
`readinessReason` additions:

- `running: true`: an owner-UID process has the expected entry point, exact project
  cwd and mapped private Java/Node executable. Java's macOS basename-only argv is
  supported; a `screen` name, command substring or listening port is insufficient.
- `running: false`: the complete bounded inventory establishes no matching process.
- `running: null, ok: false`: identity/observation is unavailable or ambiguous,
  not proof that the service stopped. Errors are fixed, sanitized messages.
- Paper `ready: true`: the verified Paper PID owns TCP 25565. This is **only a Java
  listener check**, not a protocol/gameplay, Geyser UDP, public-IP or internet-access
  check. A running process without that listener has `ready: false`.
- Bot `ready: true`: the verified Mineflayer PID owns its local RPC port and its
  non-mutating `POST 127.0.0.1:3100/health` reports the `jarvis` account spawned and
  not quarantined; a separately verified gateway PID owns 3101 and its
  `GET /health` reports `piRunning: true`. This does not test Qwen inference.
- A disconnected/quarantined bot or absent Pi agent has `ready: false` without
  losing the known `running: true`. Failed/malformed health checks have
  `ready: null, readinessReason: health_unavailable`.

The health projection treats optional stopped services as inactive, running but
not-ready services as degraded, and unverified readiness as unknown. History uses
`service_not_ready` / `service_readiness_unknown`; no raw RPC bodies, operation
paths, cancellation reasons, logs, conversations, world files or player data are
published. No readiness is inferred for legacy services.

## Bounds and freshness

A bulk collection shares one process/cwd/executable/listener inventory for both
rows. Only fixed `ps`/`lsof` argv are run, without a shell. A common four-second I/O
deadline, two-MiB command-output cap and eight-KiB health-body cap apply. HTTP has
no proxy/redirect/retry; a bounded socket watchdog interrupts a stalled/drip-fed
header read. A service-specific failure leaves unrelated verified rows available.

Native clients retain the existing cached-state refresh path. Services currently
collect every five seconds while active and every 300 seconds while idle, with a
660-second freshness ceiling. This feature changes none of those intervals and
adds no dedicated phone/Watch service poller. Direct service API reads remain
on-demand, as with existing LaunchAgent reads.

## Native presentation

Tap **Services** in the Home health card on either device. The platform-owned
sheet renders the entire generic service inventory, not just Minecraft:

- iPhone: named rows, status, observation age, optional/required and execution mode,
  description and bounded technical evidence.
- Watch: compact named/status/age rows; the existing Crown viewport provides
  overflow without competing with the dashboard's page-swipe recognizer.

The closed overview remains one screen. Shared `SystemServicesContent` is pure
rendering with no actions, networking or timers. Platforms own sheet lifecycle;
covered history polling pauses and Watch Crown ownership is suspended on the
underlying page. Existing state and WatchConnectivity serialization carry the
additive fields. Offline/stale evidence cannot become current merely by arriving
on the Watch; cached technical process/readiness values are explicitly labelled.

## Verification and rollout

Final source verification passed **916 backend tests**, **311 shared Swift cases
(3 expected live-test skips)**, **175 iPhone tests** and both iOS/watchOS simulator
builds. The iPhone suite retains only the pre-existing plain-Paste pixel-test
exclusion; all 12 dashboard/layout tests passed. Additional terminal/source
contracts passed. An initial native test run found small overview overflow and
stalled parallel result collection; the corrected layout and serial rerun passed.
The dedicated validation simulator was returned to Shutdown.

A read-only production adapter sample verified Paper running with its Java
listener and the bot stopped. No Minecraft process, router configuration or
in-game state was changed; active bot RPC acceptance remains offline-fixture
coverage until an owner-approved observation while it is already running.
The frozen installed-baseline backend passed **820 tests** and all three isolated
SDK gates. Its authoritative registry preserves every existing entry and adds only
the two Minecraft rows. Activation cycled only jarvisd and its resurrector, with a
**0.603-second** backend restart; all 16 unrelated protected service records,
existing Pi pane/process identities, credentials and history-file identity/cadence
were preserved. Both Minecraft process observations were unchanged.

Native build **250**, frozen from 254 inputs, passed **175 iPhone tests**, **311
shared Swift cases (3 expected skips)**, **37 terminal contracts** and both simulator
builds. An initial compact-layout validation measured 198 pt against a 197.5-pt
limit; the reviewed one-point-per-edge padding correction passed on source revision
2, with failed-source/test evidence retained. All four candidate and four exact
rollback **249** bundles passed signature/profile/unchanged-entitlement audits.
Both devices received exactly one install, followed by independent final version
and running-process readbacks. No app data, provisioning, dependency pins, terminal
behavior or capabilities changed. The app installer restarted no services.

Private evidence: backend `20261005T032800Z-minecraft-services` and native
`20261005T032800Z-build250-minecraft-services`. Exact previous backend/plists/registry,
history backup, signed build 249 and historical build 248 remain retained; no
artifacts were pruned. Live Paper's verified Java listener was ready; the bot was
stopped. This is not gameplay, public-access or inference acceptance. Physical
Services-list, Watch Crown and VoiceOver acceptance remain pending owner review.

Offline tests cover running/stopped independence, basename argv and private image
identity, wrong owner/cwd/runtime/port, duplicate or missing identity, partial
failure isolation, disconnected/absent/quarantined bot components, malformed RPC,
deadlines/output caps, mutation denial and legacy compatibility. Swift tests cover
model round trips, Watch snapshot expiry, readiness distinctions and generic rows.
Native layout fixtures exercise the Services action, compact overflow and unchanged
one-screen overview at small/large text sizes. Synthetic fixtures are not physical
Watch gesture, VoiceOver or gameplay acceptance.

Run `../verify.sh` and the native app verification workflow. The dedicated iPhone
layout suite is `JARVISTests/SystemDashboardViewTests`; disable Xcode parallel test
workers for the local validation simulator if result collection stalls.

Activation requires a separately approved frozen backend release: overlay the
reviewed files onto the actual installed baseline, **merge** the two new entries
into its private service registry (do not replace that registry with the checkout
example), preserve auth/root overrides and existing services, run isolated artifact
verification and retain the exact previous backend/plists/config for rollback.
Only approved jarvisd/watchdog maintenance is needed; Minecraft stays running and
the intentionally stopped bot stays stopped. Native rollout requires a separately
approved, signed/verified build and independent iPhone/Watch install/readbacks.
Do not claim a signed archive, activation or device installation from simulator
build/test success.
