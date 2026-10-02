# Managed three-camera Wi-Fi workflow

> Historical/reference document. Use [OPERATIONS.md](OPERATIONS.md) for the current single-Mac workflow and recovery rules.

**September 9 update:** the bounded Wi-Fi three-camera test passed recording, stop, verified collection, managed original deletion, both-Mac copy, full video decode and automatic music alignment. Actual clips are about 77–79 seconds because control/confirmation adds overhead around the 60-second hold. Resolve import/playback remains pending. Evidence: `validation/three-camera-wifi-recording-validation.json`. Later historical untested statements below describe the deployment before this test.

Implemented September 7, 2026. **No live three-camera wireless recording was started to validate this integration.**

## Current interface

Open `Phone Recording Dashboard.command` in the project root on **mac-mini-64**, or http://127.0.0.1:8768/ in its authorized browser. The dashboard now includes:

- LG **Wide Angle**, 2880×2160, legacy unencrypted Wi-Fi ADB on the trusted LAN.
- Samsung **Dyl Cam**, native 4K/30, paired TLS Wireless Debugging.
- iPhone **Bass Pedals**, native 4K/30 HEVC High, proxies off; pinned HTTPS control and existing-pairing Apple Network collection.

Overhead is not integrated. Framing snapshots from all three phones are manual and idle-only; iPhone uses a temporary Network-only developer screenshot connection. See [IPHONE-FRAMING.md](IPHONE-FRAMING.md). All three must be idle for framing, and all three must have fresh idle observations before Start. An old two-camera cache cannot authorize Start.

Current roles now come from the shared camera registry, with Overhead disabled. See [READINESS.md](READINESS.md) for the new battery/storage/heat checks and configuration safeguards.

## Start / stop / collection

1. Keep Open Camera foregrounded on both Androids and Blackmagic open on iPhone. Check storage, power and framing manually.
2. **Check cameras** observes all three. **Start recording** first checks iPhone format/proxies and takes file inventories on all three. The Network file session closes before durable take intent is written and before any recording command.
3. Commands are issued once in parallel. A partial start stops only cameras confirmed recording from the all-idle baseline. Unknown outcomes are never blindly replayed.
4. **Stop & prepare** stops only confirmed recordings. iPhone stop completion gets bounded observation-only polling. Unknown state on any camera defers collection.
5. iPhone collection fixes the new-file set from its pre-start inventory, persists a file plan, copies in 1 MiB chunks, performs an independent second Network read plus Mac SHA-256 reread, checks native 4K/duration and fully decodes. Atomic Mac finalization and durable verification/deletion intent precede phone cleanup.
6. A lost deletion acknowledgement is reconciled using the same journal and a still-valid Mac copy. A missing original without durable deletion intent is not silently counted as success. Changed Mac copies, unexplained new files, size/hash/decode failures and zero/missing clips defer collection.
7. Android collection runs only after iPhone completion and another all-idle check. The take cannot finalize without every managed camera. Existing exact-take copy → cue-free sync → guarded Resolve import attempt is unchanged.

No live preview, cue/clap, video retiming, cloud upload, automatic Mac cleanup or REAPER change is introduced. Phone originals are removed only after verification; both Mac copies are retained. Existing unverified partial Mac files are not automatically deleted on retry.

## Engine and recovery

- `managed_control.py`: shared three-camera orchestration.
- `iphone_wifi.py`: pinned GETs plus only explicit record/stop POSTs; no USB fallback.
- `iphone_network.py`: exact bound device, existing pairing only, Network-only app-file sessions.
- `iphone_collect.py`: resumable collection and deletion journal.
- `remote_jobs.py`: detached durable workers launched using mac-mini-16's `.iphone-venv/bin/python`.
- `collect.py`: Android finalization rejects incomplete managed iPhone collection and missing camera clips.
- `export_verified_take.py`: three-camera exports require the complete declared camera set and iPhone verification manifest.
- Direct `pair_control.py` CLI/GUI now routes through the same three-camera engine and remote environment. Historical diagnostic scripts retain their own experimental behavior; do not use them for everyday recording.

Keep `pending-take.json`; never remove it to bypass recovery. A legacy pending two-camera take is rejected by this engine and needs deliberate recovery. Closing the browser/server never stops phones. The web server upgrade was performed idle, without an active job or pending take. Remote pre-upgrade source copies are retained in `.three-camera-stage/before/`.

## Validation and remaining work

- **129 unit tests pass** with ` .sync-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` from the project root; JS syntax passes.
- Tests cover three-camera Start gates, closed file-session ordering, single-send ambiguity, selective rollback, asynchronous stop observation, independent hashes, decode failure, deletion-ack recovery, changed/missing copies, fixed media membership and export/collection guards.
- Live deployment check: all three idle, iPhone 3840×2160/30/off-speed false/proxies false; Network media inventory succeeded and closed, no pending take created.
- Earlier cable-free 8 MiB diagnostic transfers passed on all three. These are not a managed video recording/collection proof.
- **Outstanding:** an approved bounded three-camera Wi-Fi recording/collection test, long-session/reboot/storage/thermal validation, intensive REAPER listening and actual Resolve in-app/VFR playback checks.
