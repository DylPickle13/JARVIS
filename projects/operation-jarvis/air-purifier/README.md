# Operation JARVIS Air Purifier

Standalone VeSync/Levoit air purifier control utilities for Operation JARVIS.

This subsystem is intentionally **not wired into JARVIS command/action tools yet**. It provides a clean CLI and Python package, and the dashboard reads its status for the compact header air-quality line.

Target device: **Levoit Vital 200S-P / Vital 200S**, VeSync model family `LAP-V201S`.

## Control path

- Uses the community `pyvesync` Python library.
- Talks to the **VeSync cloud API**, not a local/LAN API.
- Requires a normal VeSync account and the device paired in the official VeSync app first.

## Setup

`pyvesync 3.4.2` requires Python 3.11+. The main Operation JARVIS venv may be older, so this subsystem should have its own venv, like `smart-plug/`.

```bash
cd /Users/gemma/JARVIS/projects/operation-jarvis/air-purifier
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
JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS=60
```

`JARVIS_AIR_PURIFIER_NAME` is optional if there is only one purifier on the account.

VeSync writes may take several seconds to appear in status polling. The CLI waits up to `JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS` after write commands so returned status is less likely to be stale.

## Safe local check

This does not contact VeSync:

```bash
./purifier-cli --json doctor
```

## Commands for when the purifier arrives

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

## Supported Vital 200S features exposed

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

## Dashboard integration

The dashboard reads this CLI in read-only mode and shows a compact header line such as:

```text
AIR PM2.5: 4 · AUTO · 96%
```

The dashboard endpoint is:

```text
GET /api/jarvis/air-purifier/status
```

It only reads status, caches results, and does not send purifier control commands.

## Next command/action integration step

If voice/tool control is desired later, wire this into `projects/operation-jarvis/jarvis.py` and `.pi/extensions/45-jarvis.ts` as dedicated actions such as:

- `purifier-status`
- `purifier-on`
- `purifier-off`
- `purifier-mode`
- `purifier-speed`
- `purifier-filter`

Keep those separate from the dashboard read-only status integration.
