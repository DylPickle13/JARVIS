# Phone Recording

Single-Mac Wi-Fi recording controller on **mac-mini-64**. Phones record locally;
this project controls capture, verifies collection, aligns audio, and prepares
source-linked camera tracks in DaVinci Resolve.

**Current operating instructions: [docs/OPERATIONS.md](docs/OPERATIONS.md).**
Older deployment milestones and test counts are preserved in [HISTORY.md](HISTORY.md).

## Start here

Open `Phone Recording Dashboard.command`, or run `./phone-recording dashboard`.
The authenticated dashboard listens only on **http://127.0.0.1:8768/**.

**Check cameras → Start recording → Stop & review → Transfer recording →
Verify copy & prepare.** Stop/review and transfer are separate decision points.
The older CLI `stop` action still collects and prepares automatically.

- Enabled cameras: LG Wide Angle, Samsung Dyl Cam, iPhone Bass Pedals.
  Overhead remains disabled until deliberately onboarded.
- Wi-Fi only in the live workflow; no SSH, USB fallback, or new pairing.
- Capture: `~/Movies/Phone Recordings Capture/<take-id>/`.
- Editing: `~/Movies/Phone Recordings/<take-id>/`.
- These are **two folders on one Mac, not independent backups**.
- Phone originals are removed only after verified managed collection. This is
  still the existing move policy; no independent-backup requirement is enabled.
- **One clip per camera** is supported by review and automatic synchronization.
  Segmented/multi-hour sessions are not production-validated.
- Audio alignment is not genlock. Review picture/audio sync and VFR playback.

## Installation and tests

Use Python **3.13** (tested with **3.13.14**; see `.python-version`).
Install Homebrew FFmpeg and independent ADB deliberately if not already present;
the application never installs phone apps or pairs devices automatically.

```sh
cd /Users/dylanrapanan/JARVIS/projects/phone-recording
python3.13 -m venv .sync-venv
.sync-venv/bin/python -m pip install -r requirements-sync.txt
.sync-venv/bin/python tests/run_isolated.py
node --check dashboard/app.js
node tests/test_tool_retirement.mjs
```

The isolated runner copies only source, fixtures and UI assets into a disposable
directory and supplies synthetic device configuration. It does not use live job
journals, auth tokens or pairing files. Unit tests mock device operations; media
validation also tests a tiny generated video through real FFmpeg when installed.

A fresh runtime needs deliberately configured `android-transports.json` and
`.iphone-network.json`; see [operations](docs/OPERATIONS.md).
Do not replace an existing live environment during a recording/job.

## Safety and recovery

- Camera toggles are single-send; uncertain outcomes require observation, not replay.
- Android/iPhone collection checks saved bytes on retry. Android records full media
  validation, size/hash, and durable deletion intent before removing originals.
- Android device hashing has a size-aware 60–3600-second budget, separate from
  15-second camera commands.
- Deletion jobs persist their approved scope and fingerprints. Changed scope,
  unexpected files, changed media or missing approval blocks execution.
- Old queued deletion jobs without an approval plan must be reconfirmed as new jobs;
  recovery of already-attempted deletion remains observation-only.
- Collection/deletion tests include simulated process exits at journal boundaries.

**Live camera/Resolve end-to-end validation is still required.** Automated tests
do not establish readiness for an important recording session.

## Repository layout

- Root Python modules: shared controller, collection, dashboard, sync and Resolve code.
- `dashboard/`: browser UI; `tests/`: synthetic regression tests.
- `docs/OPERATIONS.md`: canonical current guide.
- `docs/AUDIT-FIXES.md`: fixes, validation and remaining limitations.
- `docs/`, `HISTORY.md`: detailed reference and historical deployment evidence.
- `diagnostics/`: explicit-use historical probes, **not everyday controls**.
- `templates/`: example configuration and historical launcher templates.

Source is included in the JARVIS repository. Private state, device transports,
pairing identity, virtual environments, logs, historical machine-local validation
reports and migration snapshots remain ignored. No secrets or media are required
to run the isolated tests.
