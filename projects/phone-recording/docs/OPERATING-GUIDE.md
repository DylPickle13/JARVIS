# Phone recording → Resolve: operating guide

> Historical/reference document. Use [OPERATIONS.md](OPERATIONS.md) for the current single-Mac workflow and recovery rules.

Status documented September 7, 2026. User: Dylan. All host paths below are explicit because both Macs use the same username.

## Recommended interface: the local web dashboard

Open **`/Users/dylanrapanan/JARVIS/projects/phone-recording/Phone Recording Dashboard.command` on mac-mini-64**. The dashboard runs at **http://127.0.0.1:8768/** on this Mac. Use **Refresh cameras → Start recording → Stop & prepare**. Stop now automatically chains verified collection, an exact-take copy here, cue-free sync and a guarded Resolve import attempt. Current camera scope is LG + Dyl Cam + iPhone, with Overhead planned as the fourth camera. See [THREE-CAMERA.md](THREE-CAMERA.md) for the integrated controller and [CAMERA-PLAN.md](CAMERA-PLAN.md) for the target scope. Closing the browser does not stop recording. See **[DASHBOARD.md](DASHBOARD.md)** for authoritative current controls, authentication, durable-job recovery, CLI, validation and runtime file locations. Sections below retain the direct-controller/standalone workflows as fallbacks.

Readiness now checks battery, free storage, external power and available temperature readings before Start; see [READINESS.md](READINESS.md). Missing iPhone temperature remains an explicit manual-check warning.

## 1. What is ready—and what is not

- **Normal recording controller:** LG Wide Angle + Samsung Dyl Cam + iPhone Bass Pedals, using **Wi-Fi** from **mac-mini-16**. Android USB remains available by deliberate configuration; iPhone managed access is Network-only. Status, framing and 8 MiB checksum-verified diagnostic transfers passed wirelessly; a new wireless recording/managed-video collection test is still outstanding. Encoding stays on the phones. See [WIFI.md](WIFI.md), including LG's unencrypted-ADB limitation.
- **iPhone:** native 4K/30 recording, USB control, verified collection and a three-camera overlapping test passed. Proxies are OFF. After a one-time USB setup of Apple's wireless-connection flag, the iPhone is USB-disconnected again. Pinned Wi-Fi API reads and an 8 MiB Network-only file transfer with two checksum-matched reads passed cable-free. Wireless managed-video collection is still untested. **It is now part of managed Start/Stop; the live wireless recording/collection validation remains outstanding.**
- **Overhead Samsung:** not onboarded to this controller. There is no regular four-camera Start/Stop workflow yet.
- **Post-stop phone collection:** automatic for controller-managed Android takes, after both phones are confirmed idle. Failed/unknown state defers transfer.
- **Resolve preparation:** automatically chained after successful **dashboard Stop/collection** on **mac-mini-64**. The standalone preparation launcher is also available. Copies verified files here, aligns shared recorded audio without cues, and creates a timeline when confidence checks pass. No watcher or OS login service is installed; the dashboard server and detached jobs run only when launched.
- **Resolve import:** OTIO timeline generated and serialization checked. External Resolve scripting is currently unavailable; actual in-app import/playback has not been verified. A menu-script fallback is installed.
- No REAPER project/settings were modified. No intensive REAPER listening or long-session reliability pass is claimed.

## 2. Direct-controller fallback: shared three-camera engine

### Before recording

1. Keep LG and Dyl Cam on the trusted LAN with configured Wi-Fi ADB available to **mac-mini-16**. For deliberate USB recovery, see [WIFI.md](WIFI.md); connecting a cable alone does not change the selected transport. Long USB extensions/hub combinations still need testing.
2. Open **Open Camera** on both phones in video mode. Leave the camera screens visible and close settings/overlays. Keep reference audio enabled for later synchronization.
3. Confirm adequate battery/storage and that both phones are idle. Do not start manually on the phones if you want controller-managed collection.

Retained settings:

| Camera | App | Video |
|---|---|---|
| LG Wide Angle | Open Camera, Camera2 | 2880×2160, target 30; measured ~28 FPS with uneven cadence |
| Samsung Dyl Cam | Open Camera | 3840×2160, target 30 |
| iPhone, future integration | Blackmagic Camera | 3840×2160, 30, HEVC High, off-speed disabled, proxies OFF |

Direct `pair_control.py` commands and GUI now route through the same three-camera engine. Historical two-camera diagnostic scripts are not everyday launchers. Keep Blackmagic open on iPhone as well as Open Camera on both Androids.

### GUI on mac-mini-16

Open:

`/Users/dylanrapanan/phone-recording/Phone Recording.command`

- Choose **Start record** to start all three phones.
- Run it again and choose **Stop record** to stop both, then automatically transfer and verify their take.
- Wait for completion before disconnecting phones or starting another take.
- This is a one-shot dialog, not a continuously running app. Closing a dialog/Terminal window is **not** a stop command.
- The copy of this launcher in the local source directory is a deployment template for mac-mini-16; it is not a working local recording GUI on mac-mini-64.

### Terminal, on mac-mini-16

```sh
python3 ~/phone-recording/pair_control.py status
python3 ~/phone-recording/pair_control.py start
python3 ~/phone-recording/pair_control.py stop
```

### Terminal, from this Mac (mac-mini-64)

```sh
ssh mac-mini-16 'python3 ~/phone-recording/pair_control.py status'
ssh mac-mini-16 'python3 ~/phone-recording/pair_control.py start'
ssh mac-mini-16 'python3 ~/phone-recording/pair_control.py stop'
```

Keep the stop/collection command open until it finishes. The regular CLI is not yet a detached, disconnect-resilient production job runner. If disconnected, inspect state/pending results before further commands; do not blindly resend start/toggle commands.

### Collection retry

If phones are stopped but a transfer failed:

```sh
ssh mac-mini-16 'python3 ~/phone-recording/pair_control.py collect'
```

Unknown recording state blocks collection. Inspect/reopen the relevant camera app rather than blindly toggling. A `pending-take.json` blocks new managed starts until resolved; do not delete it to bypass recovery. For ambiguous/partial starts, inspect the report and phone states before retrying.

## 3. What happens to the footage

```text
Phones: locally encoded video
    │ Configured Wi-Fi/USB, after confirmed stop
    ▼
mac-mini-16: ~/Movies/Phone Recordings/<take-id>/
    │ verification passes → corresponding phone original deleted
    │ Mac copy retained
    │
    │ Run Prepare Resolve.command here
    │ SSH/network copy between Macs (not a phone USB transfer)
    ▼
mac-mini-64: ~/Movies/Phone Recordings/<take-id>/
    │ local SHA-256 verification → cue-free audio matching
    ▼
    Resolve Sync/Synced.otio + sync-report.json + import script
```

No live camera feeds are decoded/encoded by either Mac during capture. Local audio analysis occurs during the preparation stage, not the recording command.

### Phone locations before collection

- Android: `/sdcard/DCIM/OpenCamera/VID_*.mp4`
- iPhone Blackmagic app file sharing: `/Documents/Media/*.mov` (app-container path, not a macOS folder). A `Proxy` subfolder may exist; proxy recording is now off.

Only new files attributed by the managed pre-start inventory are collected. Personal/unrelated media are excluded. The LG clock is wrong, so do not use its filenames as real host recording dates.

### Transfer and deletion policy

- Completed controller-managed clips are automatically pulled off phones after stop.
- Phone/local SHA-256 and valid duration are checked before ordinary Android original deletion.
- iPhone test collector additionally independently rereads the phone file and performs a full video decode before deletion.
- All videos from the successful three-camera test also passed full video decoding on the Mac. Ordinary Android collection does not currently include that full-decode step.
- Failed verification retains phone originals; completed Mac copies are retained.
- Copying from mac-mini-16 to mac-mini-64 creates another verified copy; it does **not** delete the mac-mini-16 copy.
- These retained copies are not a configured long-term backup/retention service. No automatic Mac cleanup is enabled.

## 4. Prepare the take for Resolve on this Mac

Double-click:

`/Users/dylanrapanan/JARVIS/projects/phone-recording/Prepare Resolve.command`

It prepares the **latest completed managed take**. It does not start or stop cameras. An earlier completed take may be selected if a newer recording did not finish collection; inspect the printed take ID. For an exact take, use the CLI below.

It will:

1. Refuse export if a managed take is pending on mac-mini-16.
2. Read completed verification manifests and stream only their verified media under the controller lock.
3. Verify the copies on this Mac, retaining originals and refusing conflicting existing files.
4. Compare shared audio in multiple frequency bands across the take; independently cross-check camera pairs when there are three or more.
5. Reject weak/ambiguous matches, missing audio and excessive drift rather than guessing.
6. Generate a 30-FPS Resolve-importable OTIO timeline with one video/audio track per camera; only reference-camera audio enabled by default.
7. Attempt guarded Resolve import. Import failure is separate from sync success and is printed in the report.

```sh
cd /Users/dylanrapanan/JARVIS/projects/phone-recording
.sync-venv/bin/python prepare_resolve.py --take latest --import-resolve

# Select the known successful three-camera take explicitly:
.sync-venv/bin/python prepare_resolve.py --take 20260907-190450-df439752 --import-resolve

# Reprocess existing local copies without contacting mac-mini-16 or phones:
.sync-venv/bin/python prepare_resolve.py \
  --local "$HOME/Movies/Phone Recordings/20260907-190450-df439752" \
  --import-resolve
```

No clap, beep, shared clock, or timecode is required. All cameras need sufficiently similar recorded audio. No automatic drift correction or media re-encoding is applied. Multiple clips/proxies per camera and multi-hour memory use are not production-validated. Audio alignment does not prove frame-exposure synchronization; VFR and camera audio/video offsets still require a Resolve spot check.

### Resolve fallback

Installed application: `/Applications/DaVinci Resolve.app` (21.0.4).

Manual import: **File → Import → Timeline**, choose the take's `Resolve Sync/Synced.otio` in a suitable 30-FPS project. This is a stacked-camera timeline, not yet a native Resolve multicam clip.

Optional menu fallback, after Resolve's next normal script scan/restart:

**Workspace → Scripts → Utility → JARVIS Import Latest Approved Take**

The script uses only the dedicated project **Phone Recordings Auto Sync**. It refuses to switch away from an unrelated open project. Open the dedicated project first if needed. It checks imported paths, track starts and durations; mismatches require review. It imports the *latest approved* take, which may be older than a newly rejected take.

External scripting permissions were not changed. No existing Resolve project was edited by these tests. No successfully imported/saved Resolve project is claimed yet, and no project-library location has been verified. OTIO and Lua files are interchange/scripts, not a `.drp` project backup or rendered final video.

## 5. File locations: authoritative map

`~` on each host means `/Users/dylanrapanan`.

| What | Host | Path |
|---|---|---|
| Main source code, docs, tests, local preparation launcher | mac-mini-64 | `/Users/dylanrapanan/JARVIS/projects/phone-recording/` |
| This guide | mac-mini-64; mirrored to mac-mini-16 | `OPERATING-GUIDE.md` in each project folder |
| Deployed recording controller + recording GUI | mac-mini-16 | `/Users/dylanrapanan/phone-recording/` |
| Phone-collected originals | mac-mini-16 | `/Users/dylanrapanan/Movies/Phone Recordings/<take-id>/` |
| Verified editing copies | mac-mini-64 | `/Users/dylanrapanan/Movies/Phone Recordings/<take-id>/` |
| Synced timeline and report | mac-mini-64 | `<take-folder>/Resolve Sync/` |
| Android pending recovery state | mac-mini-16 | `~/phone-recording/pending-take.json` (exists only while unresolved) |
| Android completed manifest | mac-mini-16 | `<take-folder>/transfer-manifest.json` |
| iPhone completed test manifest | mac-mini-16 | `<take-folder>/iphone/iphone-transfer.json` |
| Local copied-media manifest | mac-mini-64 | `<take-folder>/_verified-export.json` |
| Local sync Python environment | mac-mini-64 | `<source-folder>/.sync-venv/` (Python 3.13) |
| iPhone test Python environment | mac-mini-16 | `~/phone-recording/.iphone-venv/` |
| Resolve Utility menu wrapper | mac-mini-64 | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/JARVIS Import Latest Approved Take.lua` |
| Latest approved import pointers | mac-mini-64 | `<source-folder>/latest-resolve-ready.json`, `latest-resolve-import.lua` |

### Successful three-camera take, currently on both Macs

ID: **`20260907-190450-df439752`**

```text
/Users/dylanrapanan/Movies/Phone Recordings/20260907-190450-df439752/
├── samsung/VID_20260907_190453.mp4
├── lg/VID_20251029_221206.mp4
└── iphone/iphone 11001_09071904_C002.mov
```

Additional files **here on mac-mini-64**:

```text
_verified-export.json
Resolve Sync/
├── Synced.otio
├── sync-report.json
└── Import into Resolve.lua
```

Additional verification files on **mac-mini-16** include `transfer-manifest.json`, `iphone/iphone-transfer.json`, and `video-analysis.json`.

Other retained takes currently on **mac-mini-16 only**:

- `20260907-185523-dad539a5/`: failed initial three-phone test; recovered usable Android footage and explicitly labeled zero-byte iPhone crash artifacts. **Not a successful three-camera take.**
- `iphone-isolated-20260907-190147-6a0802/`: successful ~32-second iPhone-only isolation test.

### Source files by purpose

- Recording: `inventory.py`, `pair_control.py`, `collect.py`, `Phone Recording.command`.
- iPhone USB/API: `iphone_usb.py`, `iphone_api.py`.
- Diagnostic recording runners: `iphone_isolated_test.py`, `three_phone_test_v2.py`, older `three_phone_test.py`, `lg_usb_test.py`. **Not regular Start/Stop interfaces; do not run casually.** The v2 test has a fixed recording hold and detached-launch requirement, not user-controlled recording duration.
- Editing preparation: `prepare_resolve.py`, `export_verified_take.py`, `audio_sync.py`, `spectral_sync.py`, `resolve_import.py`, `Prepare Resolve.command`.
- Analysis/development: `analyze_take.py`, `sync_feature_probe.py`.
- Documentation/dependencies: `README.md`, this guide, `phone-local-recording-assessment.md`, `requirements-sync.txt`.
- Tests: `tests/test_*.py`, `tests/test_tool_retirement.mjs`; the historical sync/controller suite had 35 Python tests. The current complete suite has **120 passing Python tests**.
- Results/logs: `*-result.json`, `*-analysis.json`, `*-summary.json`, `resolve-sync-test*.log`; these are diagnostic records, not footage. `resolve-sync-validation-result.json` contains the successful cue-free alignment evidence.
- `.pair-control.lock`, `.resolve-sync.lock`, `__pycache__` and virtual-environment folders are support files, not takes; don't delete pending state to resolve errors.

Remote deployment contains recording tools and historical test logs, but not every local-only sync module. Source changes are maintained under JARVIS on mac-mini-64; deploy recording changes intentionally, not by assuming the folders mirror automatically.

## 6. Remaining work toward one-button, four-phone automation

1. Integrate iPhone into the regular managed controller with persistent recovery and safe detached operation.
2. Onboard Overhead Samsung.
3. **Implemented for dashboard jobs:** successful post-stop collection automatically triggers local Resolve preparation. Legacy direct-controller commands still require separate preparation.
4. Establish available Resolve scripting/menu import and verify VFR/source-timecode handling in-app.
5. Validate sustained recording, thermal/storage readiness, audio drift and intensive REAPER listening.

Recommended now: **open the dashboard here → Refresh cameras → Start recording → Stop & prepare → inspect the timeline/import result.** The direct mac-mini-16 GUI plus standalone preparation launcher remain fallbacks.
