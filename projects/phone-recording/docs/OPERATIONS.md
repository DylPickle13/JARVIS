# Current operating guide

This is the canonical single-Mac Wi-Fi workflow. Older two-Mac/USB instructions,
including `OPERATING-GUIDE.md`, are historical references.

## Prerequisites

- Controller, dashboard, collection and Resolve preparation run on **mac-mini-64**.
- Keep every enabled camera's recording app open on the trusted LAN.
- Android: existing authorized Wi-Fi ADB; the bound hardware serial is checked
  before commands. Start with `templates/android-transports.wifi.json` only as an
  example; deliberately supply the correct devices' addresses/ports. LG uses
  unencrypted legacy ADB, so do not expose it beyond the trusted LAN.
- iPhone: pinned Blackmagic Camera HTTPS endpoint plus an existing Network pairing.
  `.iphone-network.json` contains `{"identifier":"<previously verified device ID>"}`.
  No automatic trust, new pairing, USB fallback or certificate replacement occurs.
- iPhone must be native 4K/30, off-speed disabled and proxies off.
- Python 3.13, dependencies in `requirements-sync.txt`, Homebrew FFmpeg and ADB.
  Endpoint/certificate trust changes remain deliberate commissioning work.

## Recording and decision points

1. Open `Phone Recording Dashboard.command` or `./phone-recording dashboard`.
   The launcher authorizes the browser at http://127.0.0.1:8768/.
2. **Check cameras.** Start requires fresh verified idle state, matching registry
   configuration, adequate battery/storage and acceptable available thermal data.
   Missing iPhone temperature is a manual-check warning, not proof it is cool.
3. Optionally **Check framing** while idle. Snapshots expire; no continuous feed.
4. **Start recording.** Confirm every camera actually entered recording.
   The displayed state is the last observation, not continuous telemetry.
5. **Stop & review.** Phones stop; exact new clips are fingerprinted. This may
   take time for large recordings. No saved Mac footage exists yet.
6. Choose **Transfer recording**, or explicitly confirm permanent phone-only
   discard. Transfer verifies managed bytes and video/audio decoding before
   removing originals. Do not interpret a successful copy as an independent backup.
7. Choose **Verify copy & prepare** to create the editing copy, align audio and
   attempt Resolve import. Only confidently aligned takes produce approved timelines.
8. Review picture/audio synchronization in Resolve. Native import, timeline
   creation and visual sync are distinct outcomes.

Review and synchronization currently require **one clip per camera**. Segmented
recordings fail closed rather than guessing concatenation. The collector can
retain verified segments, but automatic preparation still requires manual review.
Long-session memory use, thermal behavior, disconnections and sustained cadence
need deliberate testing before important sessions.

Closing the browser does not stop recording or cancel workers.

## Storage and permanent deletion

- Capture: `~/Movies/Phone Recordings Capture/<take-id>/`.
- Editing and generated timelines: `~/Movies/Phone Recordings/<take-id>/`.
- Runtime journal/logs: project `.dashboard/`, `.dashboard-jobs/`,
  `pending-take.json` and deletion receipts.
- Resolve automation receipts: `~/Movies/Phone Recordings/.resolve-automation/`.

Both footage folders reside on one Mac. Arrange an independent backup separately.
The existing automatic removal of verified phone originals is unchanged.

The UI explains and requires one of these exact scopes:

| Confirmation suffix | Authorized deletion |
| --- | --- |
| `PHONES` | Exact stopped originals, before any saved Mac copy |
| `REMOTE` | Local capture folder only (historical token name) |
| `BOTH` | Capture and editing folders; guarded dedicated Resolve project if applicable |

There is no Trash/backup step. Scope, media fingerprints and applicable Resolve
import identity are persisted at confirmation and rechecked before execution.
Unexpected files—including unmanifested recordings, partial copies and personal
notes—block recursive deletion. Only declared footage and explicitly known
generated outputs are allowed. Move/inspect unexpected files yourself; do not
delete journals or add arbitrary paths to the allowlist to bypass a block.

## Recovery

- An uncertain Start/Stop is not permission to repeat a toggle. Use **Activity &
  recovery → Reconcile**, then inspect state and the pending take.
- Reconcile reads the same durable job ID; it does not replay camera commands.
- Android retries verify retained path, size and hash, including entries already
  marked deleted. Missing/corrupt Mac copies keep the take pending.
- A phone file absent after durable deletion intent can be reconciled only with
  the matching validated Mac copy. Unexplained absence remains blocked.
- A previously deleted phone path reappearing or a new file arriving after
  discovery is not automatically swept.
- Legacy Android receipts are revalidated/decoded before upgrade. Old unexplained
  deletion gaps without intent still require manual inspection.
- Deletion is single-shot. Partial deletions remain uncertain; recovery observes
  receipts and never restarts recursive deletion or Resolve mutations.
- Pre-upgrade queued deletion jobs lacking durable approval are refused. Inspect
  and submit a newly confirmed job; do not fabricate an approval for old work.

## CLI

```sh
./phone-recording status
./phone-recording refresh
./phone-recording start
./phone-recording collect
./phone-recording prepare <take-id>
./phone-recording import <take-id>
./phone-recording recover <job-id>
```

The legacy `./phone-recording stop` action stops, collects and prepares
automatically; use the dashboard's **Stop & review** for the two decision pauses.
Diagnostics that intentionally record are not part of automated validation.

## Development / rollout

Run `.sync-venv/bin/python tests/run_isolated.py`; it avoids live runtime state.
The SQLite approval table is created lazily and preserves job history. Do not
mix old and new dashboard code: after confirming that no recording or job is
active, deliberately close/restart the dashboard server via its normal operating
procedure. This code change does not restart services or touch devices.

Before production use, explicitly authorize a bounded live take, interrupted
collection/recovery checks, and a Resolve visual sync review. Keep manual phone
controls available. Never perform destructive failure injection on valued footage.
