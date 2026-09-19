# Simple on-demand security status

**Deployed and enabled:** `20260919T230024Z-security-status` (2026-09-19).
The source still defaults to disabled unless explicitly configured.
Simplified at the owner's request on 2026-09-19. The earlier asynchronous adapter,
batch-helper protocol, cache, refresh cooldown and packaging proposal were removed.

## What it does

`GET /api/v1/security/status?device=<configured-alias>` runs exactly:

```text
<existing-private-security-launcher> --json status <alias>
```

One request reads one device. There is no polling, background worker, last-good
cache, new SDK environment or new helper. The CLI retains its existing private
registry, identity validation and shared hub lock. No security data is added to
`/api/v1/state`, `/health`, events, widgets or request logs.

The endpoint requires the existing `x-jarvis-token` API token **even if the rest of
the backend uses trusted-network mode**, and applies existing Origin checks.
Event tokens cannot read security data. All API-token holders can use the route
when enabled; this is not a new per-client permission scope.

## Opt-in configuration (applied privately to this release)

Set `JARVISD_SECURITY_CLI` to the absolute path of the existing owner-controlled
`security` launcher in private backend configuration. Blank means disabled. The
launcher selects its existing Python 3.13 environment and private files. Do not
point this at a generic command dispatcher or experimental archive probe. No
credentials, hosts, device inventory or SDK dependencies are copied into Git.
An API token must already be configured; network trust alone is insufficient.

Only `device` is accepted as a query parameter, exactly once. The alias is bounded
and validated, then checked by the CLI's private registry. Requests cannot choose
a command, executable, environment file, host or recording range.

## Small safety boundary

- Fixed argv, no shell evaluation, no retries, minimal subprocess environment.
- 30-second process deadline and 128 KiB streaming stdout cap; stderr discarded.
  The dedicated worker process group is killed/reaped on exit, never a service.
- One process-local nonblocking lock prevents concurrent HTTP reads from piling
  up. Contention returns 503 `device_busy`; no queue or automatic retry.
- Existing CLI hub locks still coordinate with standalone reads/archive work.
- Output is allowlisted; raw features, credentials, identities, paths and exception
  text are not returned. Query strings/device selectors are omitted from this
  route's request log. Responses are `Cache-Control: no-store`.
- Success reports local attempt-start `observedAt` conservatively. Failures report
  `observedAt: null`, no cached data and a sanitized error. The CLI's completion
  timestamp is not treated as a successful observation.
- Sensor motion/contact, low-battery and RSSI are nullable. Successful reads are
  **hub snapshots, not proof of fresh sensor radio contact**; `radioFreshness`
  remains `unknown`. Hub/camera initially expose identity/read success only.
- Always `securityAssessment: "not_assessed"`. No arming, controls, storage health,
  recording changes, alerts, media, or inference of continuous coverage.

## Files and verification

- `jarvisd/jarvisd_core/security_status.py`: synchronous CLI wrapper and projection.
- `jarvisd/jarvisd.py`: token-protected route and selector-free logging.
- `jarvisd/tests/test_security_status.py`: **17 offline tests passed**, including
  real loopback HTTP with fake reader and temporary fixture CLI processes.
- `jarvisd/verify.sh`: **612 tests passed**, plus Python/plist/shell syntax checks.
  The pre-existing `control_runtime.py:99` finally-return warning remains.

Tests cover authentication/Origin rejection before reads, query validation,
read-only argv, privacy, no-store, busy rejection, unknown features, identity
mismatch, CLI errors, streaming limits and timeouts. These tests were offline.

## Deployment verification

The frozen release passed **612 backend / 32 Kasa / 38 VeSync** tests before
cutover and again after installation. Production GET-only checks verified:
- `/health` and existing authenticated local-control readiness.
- Security status without a token: **401**, no device read.
- One API-token-authenticated motion-sensor status request: **200**, successful
  hub snapshot with `radioFreshness: unknown` and `securityAssessment: not_assessed`.
- Existing state contract, event history, protected terminal/audio identities,
  vendor SDK source hashes and private configuration files preserved. Only the
  daemon plist changed to select the new release and opt in to the private CLI.
- Daemon, watchdog and Session10 supervision remain loaded. Prior backend/plists
  are retained in the private deployment record for rollback.

No physical device writes, native builds, media access or new credentials. The
sensor observation was not retained in this document. Comparison with the Tapo
app and physical acceptance remain separate; no batch helper is needed.

## Separate archive work

The earlier ten-second archive sample's TS and MP4 were deleted at the owner's
request; hub recordings were untouched. Audio/visual acceptance and current card
health remain unverified. This endpoint cannot fetch or expose media.
