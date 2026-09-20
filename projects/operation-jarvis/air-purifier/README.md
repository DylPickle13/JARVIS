# Operation JARVIS Air Purifier

Read the air purifier's status or change its settings from a CLI, Python, or JARVIS. The adapter connects to `jarvis.py`, `jarvisd`, and Pi's optional `jarvis` tool group through `purifier-status` and `purifier-set`.

Target device: **Levoit Vital 200S-P / Vital 200S**, VeSync model family `LAP-V201S`.

## Control path

- Uses the community `pyvesync` Python library.
- Talks to the **VeSync cloud API**, not a local/LAN API.
- Requires a normal VeSync account and the device paired in the official VeSync app first.

Daemon writes now bind the admitted device to an exact CID through a private
worker/CLI check: aliases, defaults, names, and models cannot redirect that write.
Public CLI selection remains compatible and outside daemon write admission.
The reviewed SDK mutation path now blocks token-driven replay, additional API/HTTP
submissions and redirects. Source/version drift rejects writes until reviewed.
Power/display/light-detection writes observe first; known-model status and write
verification reject malformed/stale SDK observations instead of optimistic state.
Read recovery and cloud backoff remain separate. This is not exactly-once execution
or physical write certification; see [VeSync safety scope and test gate](../jarvisd/docs/vesync-write-safety.md)
and [backend adapter limits](../jarvisd/docs/device-adapters.md).

## Setup

`pyvesync 3.4.2` needs Python 3.11+. Use a separate virtual environment, as in `smart-plug/`, so it does not depend on the main Operation JARVIS environment's Python version.

```bash
cd /path/to/JARVIS/projects/operation-jarvis/air-purifier
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -e .
cp .env.example .env
```

Edit `.env`:

```env
VESYNC_EMAIL=you@example.com
VESYNC_PASSWORD=...
VESYNC_COUNTRY_CODE=CA
VESYNC_TIME_ZONE=America/Toronto
JARVIS_AIR_PURIFIER_NAME=Bedroom Air Purifier
JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS=150
```

`JARVIS_AIR_PURIFIER_NAME` is optional if there is only one purifier on the account.

The CLI caches VeSync's access token in the ignored `air-purifier/.vesync_auth` file and reuses it across JARVIS tool and `jarvisd` processes. Set `JARVIS_AIR_PURIFIER_AUTH_PATH` to override that private path. This avoids repeated password logins and VeSync's `REQUEST_HIGH` throttle; never commit the token file.

A VeSync change can take several seconds, and sometimes more than a minute, to appear in status. The CLI waits up to `JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS` for confirmation. If VeSync accepts the change but status has not caught up by then, the command exits successfully with `verification_pending: true`. That means accepted, not yet confirmed.

## Safe local check

This does not contact VeSync:

```bash
./purifier-cli --json doctor
```

## Commands

First pair the purifier in the official VeSync app, then run:

```bash
# List account purifiers
./purifier-cli --json list

# Read full status
./purifier-cli --json status

# Power
./purifier-cli on
./purifier-cli off
./purifier-cli toggle

# Modes
./purifier-cli mode auto
./purifier-cli mode manual
./purifier-cli mode sleep
./purifier-cli mode pet

# Fan speed, Vital 200S supports 1-4
./purifier-cli speed 1
./purifier-cli speed 4

# Other controls
./purifier-cli display off
./purifier-cli child-lock on
./purifier-cli light-detection on
./purifier-cli auto-preference quiet --room-size 400
./purifier-cli timer 60
./purifier-cli clear-timer

# Filter life only
./purifier-cli --json filter
```

If multiple purifiers are on the account, pass a device name/CID/model:

```bash
./purifier-cli --json status "Bedroom Air Purifier"
./purifier-cli mode sleep "Bedroom Air Purifier"
```

## Vital 200S controls and readings

- Power on/off/toggle
- Status
- Fan speed 1-4
- Modes: `manual`, `auto`, `sleep`, `pet`
- Auto preference: `default`, `efficient`, `quiet`
- PM2.5/PM1/PM10 fields when available from VeSync
- Filter life
- Display on/off
- Child lock on/off
- Light detection on/off
- Timer set/clear

## JARVIS tool integration

After loading `load_tools({ groups: ["operation_jarvis"] })`, use:

- `operation_jarvis_purifier({ action: "status" })` for status/filter/air-quality info.
- `operation_jarvis_purifier({ action: "set", setting: "mode", value: "sleep" })` for mode changes.
- `operation_jarvis_purifier({ action: "set", setting: "speed", level: 1 })` for manual fan speed 1-4.
- `operation_jarvis_purifier({ action: "set", setting: "display", value: "off" })` for display control.

If a change is still pending, say so and check status later. Do not immediately send another command to compensate.

### On-demand app refreshes

jarvisd no longer schedules purifier reads at startup, while idle, or while the
app remains open. The updated iPhone app requests `GET /api/v1/state?refresh=purifier`
on Home activation and pull-to-refresh. Ordinary state/widget requests only read
the cache. Explicit refreshes are single-flight and debounced for 60 seconds.
An already running cloud request cannot be cancelled by backgrounding the app.
Commands still perform their existing bounded inline confirmation, but do not
start a daemon verification loop. Cached values retain their age/stale markers.

A detected rate-limit exception starts local backoff at 5 minutes, doubling on
successive failures up to 1 hour. Structured `retry_after` guidance, when exposed
by an exception, is honoured if longer. These are conservative client delays,
not a claim about VeSync's reset time. Legacy epoch-only cooldown files remain
readable and retain their deadline until expiry or an explicit successful probe.
No expiry schedules a request. Owner-authorized `--retry-cooldown status` can
probe recovery once; writes cannot bypass cooldown. A successful cloud session
clears it. Invalid cooldown files fail closed even for recovery probes.

### Multiple purifiers

- `./purifier-cli --json list` discovers CID-keyed devices; its readings are NOT
  freshly queried. Duplicate display names no longer overwrite each other.
- `./purifier-cli --json status-all` explicitly reads devices sequentially in
  one session. Each CID has `ok` and `status` or an error. An ordinary device
  failure does not hide another device; rate limiting stops the whole batch.
- A unique name, exact CID or configured alias can select one purifier. Shared
  model names and duplicate names are rejected, including for writes.
- Set `JARVIS_AIR_PURIFIER_ALIASES` in private `.env` to a JSON object, for example
  `{"dylan":"<first CID>","bran":"<second CID>"}`. Replace placeholders using
  discovery. Aliases are CID-only, so a rename cannot retarget a command.
- The existing configured default remains supported. Set it to an alias or CID
  for rename-stable targeting. No implicit all-device writes are supported.
- One nonblocking file lock, beside the auth cache, serializes cloud sessions
  across daemon/CLI processes. Concurrent requests fail without a cloud call.
  Cooldown updates are atomic and mode 0600. Processes using different auth
  paths do not share a lock; keep one auth path for the same account.

Operation adapter actions: `purifier-list`, `purifier-status-all`, existing
`purifier-status --purifier <alias/CID/name>` and `purifier-set`. Explicit read
recovery uses `--retry-cooldown`; the Pi tool exposes `retryCooldown: true` only
for owner-approved status recovery, never automatic retries. Live Pi sessions
need a future tool reload to see new actions; do not reset sessions to activate.
The iPhone/Watch multi-device API/UI is separate work; this does not change its
single-purifier snapshot or enable background cloud polling.

Offline verification (no VeSync login or hardware writes):
```sh
python3 -m unittest discover -s projects/operation-jarvis/air-purifier/tests -v
node --test .pi/scripts/tests/jarvis-purifiers.test.mjs
```
