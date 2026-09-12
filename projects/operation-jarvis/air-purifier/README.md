# Operation JARVIS Air Purifier

Read the air purifier's status or change its settings from a CLI, Python, or JARVIS. The adapter connects to `jarvis.py`, `jarvisd`, and Pi's optional `jarvis` tool group through `purifier-status` and `purifier-set`.

Target device: **Levoit Vital 200S-P / Vital 200S**, VeSync model family `LAP-V201S`.

## Control path

- Uses the community `pyvesync` Python library.
- Talks to the **VeSync cloud API**, not a local/LAN API.
- Requires a normal VeSync account and the device paired in the official VeSync app first.

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

After loading the optional Pi tool group with `load_tools({ groups: ["jarvis"] })`, use:

- `jarvis({ action: "purifier-status" })` for status/filter/air-quality info.
- `jarvis({ action: "purifier-set", setting: "mode", value: "sleep" })` for mode changes.
- `jarvis({ action: "purifier-set", setting: "speed", level: 1 })` for manual fan speed 1-4.
- `jarvis({ action: "purifier-set", setting: "display", value: "off" })` for display control.

If a change is still pending, say so and check status later. Do not immediately send another command to compensate.
