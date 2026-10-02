# Historical implementation notes — not current operating instructions

Use [README.md](README.md) and [the current operating guide](docs/OPERATIONS.md).
The snapshots below include retired USB/two-Mac workflows and historical test counts.

# Phone-local recording

**Current architecture: [single-Mac Wi-Fi controller](docs/SINGLE-MAC-WIFI.md).**
Camera control, capture, dashboard and Resolve preparation now run on **mac-mini-64**.
No mac-mini-16 or USB dependency in the live workflow. Capture and editing folders
are separate local copies, **not independent backups**. 192 automated tests pass;
live camera access/recording/collection on this host still needs validation.
The two-Mac instructions and milestones below describe the previous deployment.

**New:** [Stop & review, two decision pauses, and guarded Delete take](docs/DELETE-AND-REVIEW.md). 186 tests pass; live discard-path validation remains outstanding.

**Dashboard refresh:** [single-screen control panel and validation](docs/DASHBOARD-PRODUCTION.md) — 150 tests passing; hardware soak testing remains outstanding.

**Current Resolve workflow:** automatic native timeline drop is integrated after verified copy/audio sync. Each camera gets its own full-length named video track; no automatic rough cuts. Clean project rebuild and duplicate-safe retry passed. See [automatic Resolve workflow](docs/RESOLVE-AUTOMATIC.md), including the fix that moves per-run jobs out of protected app data.

## Current entry point: dashboard on mac-mini-64

**Editable Resolve proof now works:** the in-app Lua API created and saved `Synced Sources … v002` and `Rough Cut … v002` in **Phone Recordings Auto Sync**. The 72-second rough cut contains twelve editable camera shots and continuous Samsung audio. See [Resolve handoff](docs/RESOLVE-HANDOFF.md) for the App Store script path, finite menu-job workflow, backup and limitations. This succeeded through native API construction, not OTIO import; playback/visual sync still needs review.

**September 9 live milestone:** three-camera Wi-Fi Start/Stop, verified collection and managed phone-original deletion, verified copies on both Macs, full video decoding and cue-free music alignment passed for `20260909-160821-021d734f`. Fixed a streamed-export import-path error and retried preparation only. Timeline generated; actual Resolve import/playback and visual sync remain unverified. LG uneven cadence persists. See [test evidence](validation/three-camera-wifi-recording-validation.json).

Open **`/Users/dylanrapanan/JARVIS/projects/phone-recording/Phone Recording Dashboard.command`** here, then use **http://127.0.0.1:8768/**. Workflow: **Refresh cameras → Start recording → Stop & prepare**. Current scope: LG + Dyl Cam + iPhone. Target: **four cameras**, with Overhead to be onboarded next. Stop chains verified remote collection → verified local copy → cue-free synchronization → Resolve import attempt. Closing the browser does not cancel recording/jobs. External Resolve scripting remains unavailable; timeline generation and in-app import are reported separately.

- **[Readiness checks and shared four-camera registry](docs/READINESS.md)** — battery/storage/heat gates, honest unavailable-temperature warnings, and registry-generated camera cards. Overhead stays disabled until onboarded.
- **[Dashboard operations, recovery, CLI and runtime paths](docs/DASHBOARD.md)**
- **[Complete recording/file-location guide](docs/OPERATING-GUIDE.md)**
- **[Wi-Fi setup, validation, limitations and USB recovery](docs/WIFI.md)** — both Android dashboard connections now select Wi-Fi; identity checks, framing and 8 MiB checksum-verified diagnostic transfers passed. No wireless recording/large-video collection test yet. LG uses legacy unencrypted ADB on the trusted LAN; Samsung uses paired TLS. iPhone Wi-Fi API reads and an 8 MiB Network-only file test now pass with USB unplugged; iPhone is now integrated into managed dashboard Start/Stop; a bounded live wireless recording/collection test remains outstanding.
- Local source/UI/job engine: this directory. Remote helper only: `mac-mini-16:~/phone-recording/remote_jobs.py` (no remote dashboard).
- Shared CLI: `./phone-recording dashboard`, `status`, `refresh`, `start`, `stop`, `collect`, `prepare <take-id>`, `import <take-id>`, `recover <job-id>`.
- Dashboard validated in visible Chrome; both Androids observed idle; existing-take preparation passed, including a server restart mid-job. No new recording was started during dashboard validation. Combined suite: 131 tests, including managed three-camera control and recoverable iPhone collection. The streamlined UI has one contextual recording control, three camera cards, latest take, and an Advanced section. Idle-only Check framing snapshots are now visually confirmed for all three cameras, including the iPhone via a temporary Network developer screenshot connection; snapshots expire after 60 seconds and are cleared before Start. No continuous feed is running.
- Runtime secrets/journal/logs are excluded in `.gitignore`; no OS auto-start service or Pi extension is installed.

## Folder guide

- **Start here:** `Phone Recording Dashboard.command` (or `./phone-recording dashboard`).
- `docs/` — [current three-camera workflow](docs/THREE-CAMERA.md), [four-camera plan](docs/CAMERA-PLAN.md), operations and Wi-Fi guides.
- `tests/` — automated tests. Run `.sync-venv/bin/python -m unittest discover -s tests -p 'test_*.py'` here.
- `diagnostics/` — explicit-use development/recording probes; not everyday controls.
- `templates/` — remote GUI deployment template and example Android transport configuration.
- `validation/` — retained reports and historical logs; `folder-organization.json` records the moves.
- `dashboard/` — web UI assets. Root Python files are the shared live engine/CLI and keep their existing import/deployment paths. `camera-config.json` is the shared enabled/planned camera registry.
- Hidden `.dashboard/` and virtual environments remain in place. Launchers remain at the top level; latest Resolve pointers are generated there when an approved take exists (the deleted old take’s pointers were cleared). Recordings remain outside this project in `~/Movies/Phone Recordings/` on both Macs.

**The remaining sections are chronological implementation history, not the current operating procedure.**

Successor to `projects/obs-control`. Initial transport: **USB**, not Wi-Fi.

## Goal

Each phone records camera video to its own storage. The Mac sends small control commands and collects finalized clips afterward. No OBS, continuous video feeds, Mac video encoding, cloud uploads, or media transfers during intensive REAPER use. REAPER settings must remain untouched.

## Status

- OBS Pi extension, lazy tool group, old bridge, and OBS-specific tests removed.
- OBS application, its profiles, backups, and historical logs remain intact on mac-mini-16; OBS is closed.
- USB Android inventory is implemented and read-only (`inventory.py`). No recorder/control tool registered in Pi yet.
- LG: Open Camera 1.56.2 installed from official SourceForge APK, camera/microphone/storage permissions granted. USB volume-up start/stop verified with a two-minute local recording. Other phones unchanged; no wireless debugging enabled.
- `lg_usb_test.py` is an experimental LG-only bounded proof, not a production multi-camera controller. It leaves collection/deletion to a separate verified step. Do not run it without an explicit test request.
- See [device inspection and research](docs/phone-local-recording-assessment.md). Its network, battery and storage values are historical snapshots.

## Hardware

| Role | Platform | USB identifier |
|---|---|---|
| Dyl Cam | Samsung S21 FE SM-G990W, Android 16 | R5CRC27FBMP |
| Overhead | Samsung S21 FE SM-G990W, Android 16 | R5CT10S8GEY |
| Wide Angle | LG G6 LG-H873, Android 9 | LGH873bb5b4b79 |
| Bass Pedals | iPhone 11, iOS 26.6.1 | Discover via usbmuxd; do not store pairing secrets |

Controller/collection host for the initial proof-of-concept: mac-mini-16. The user also has an M4 Pro desk Mac about 25 ft away; moving it is not practical and it is not part of this initial USB deployment.

## USB-first plan

1. Install Open Camera on the LG after approval. Configure local video storage and volume-up record control; verify camera permissions, native supported resolutions/FPS and free storage.
2. Prove start, **confirmed recording**, stop, finalization, transfer and inspection on that phone using USB ADB. This is camera recording, not Android screen recording.
3. Repeat on both Samsungs. Capture diagnostic status without streaming previews.
4. Install/check Blackmagic Camera on the iPhone. It supports remote API control on recent versions, but **USB access to that API has not been proven**. Investigate USB port forwarding to a phone-exposed API; do not promise USB triggering until tested. If the app binds only to Wi-Fi, ask before using a hybrid Wi-Fi-control/USB-transfer setup. Android ADB does not control iPhones.
5. Only after device-specific state confirmation works, add a common controller: `status`, `start_all`, `stop_all`, `collect`. Mixed-device operation must handle partial failures explicitly.
6. Run a bounded two-minute local-recording test with intensive REAPER use. Test longer durations, power, heat, segmentation and storage before band sessions.

USB reduces setup complexity; it does not by itself guarantee the long cables/hub are reliable. A brief link loss should not interrupt an already-started phone-local recording, but could prevent stop/status/transfer. Test unplug/disconnect behavior with explicit consent, and retain manual phone controls.

## Control safety requirements

- A volume key is a toggle, not an idempotent start/stop API. Inspect state first, send at most once, verify result. Unknown state => report uncertainty, not a blind retry.
- Confirm each phone is actually recording; a successful shell command is insufficient.
- Never delete existing media while making room. Report insufficient storage.
- Collect only finalized files attributable to the requested test/take, never a whole personal camera roll by default.
- Transfer after recording/REAPER testing ends. Verify size/hash where available and probe/decode; retain originals until verified and deletion authorized.
- No raw pairing material, debugging keys, passwords or tokens in source, output or logs.
- Keep remote services disabled until explicitly authorized. Future Wi-Fi uses a trusted LAN; legacy LG wireless ADB needs special care.
- No REAPER edits, force-killing, background daemon, streaming, or automatic phone-app installation.

## Read-only inventory

The script runs **on the host physically attached to the phones**, not on the local JARVIS Mac by accident. Python 3 standard library only; no virtual environment required.

```bash
# On mac-mini-16 (remote deployment):
python3 ~/phone-recording/inventory.py

# Development tests, from this project:
python3 -m unittest -v test_inventory.py
node test_tool_retirement.mjs
```

The temporary default ADB path is the existing DroidCam plugin's bundled executable. It remains usable with OBS closed. Set `--adb /path/to/adb` when replacing that dependency. **Do not uninstall DroidCam before independent ADB is provisioned.** Inventory does not activate wireless ADB, start camera apps, or inspect media filenames. iPhone app/storage/network checks are still pending; the existing inspection obtained model/iOS through usbmuxd without changing trust.

## Migration

The source project was renamed to `projects/phone-recording`; the deployed helper directory is `mac-mini-16:~/phone-recording`. No OBS code or WebSocket dependency is retained in the new project. OBS settings/footage backups are outside this project and were not removed.

Run `/reload` in Pi after migration to unload the old OBS schema from the current session. Deleting an extension file does not retroactively remove already-loaded code/schemas until reload/new session.

## First LG USB proof — 2026-09-07

Host window approximately 17:31:27–17:33:34 EDT. Local H.264/AAC recording: 1920×1080, 120.000 seconds, 257,638,855 bytes. Declared rate 30 FPS, measured average approximately 26.49 FPS (variable delivery, not established constant 30). USB transfer SHA-256 matched. Complete video decode passed with a fine output timebase preserving VFR timing; default null-muxer timebase had produced repeated-DTS warnings. Test clip deleted from both phone and Mac after inspection. REAPER listening feedback pending. OBS remained closed.

The LG clock is incorrect (test filename dated 2025-10-29); do not associate takes by phone timestamps alone. Clock was not changed. Battery saver was observed enabled, which may affect performance; no battery settings changed.

APK SHA-256: `d1da901cd4adfaad8f70f389b06972b46ebb7b988e8a0912c2e661422736455f`. Installer retained at `mac-mini-16:~/phone-recording/downloads/OpenCamera.apk`.

## LG 30 FPS tuning — first attempt

Selected Video settings / Video frame rate (approx) = 30 (previously Default). Disabled LG Battery Saver with the supported `cmd power set-mode 0`; previous `low_power` value was 1, verified now 0. Stabilization was already off. Local 1080p trial yielded 1,057 frames over 38.542 seconds (~27.42 FPS), median frame interval 33.311 ms, largest gap 99.944 ms, 98 gaps over 50 ms. Not a constant-30 pass. Intended 30-second test ran longer because a transient accessibility null-root response prevented automatic stop verification; recording was then independently observed active and stopped once, confirmed idle. Verified SHA-256 transfer and probed frame timings; deleted both test copies. Updated `state()` to retry observations only, never toggles, on transient accessibility errors. Camera2/manual exposure and lighting are possible next investigations, not proven causes or changes already applied. Battery Saver is left off and explicit 30 FPS selected.

## Camera2 / exposure trials — 2026-09-07

- Camera2 enabled using Open Camera Settings / Camera API. Explicit 30 FPS and battery saver off retained.
- Camera2 auto exposure: 840 frames / 31.205433 s (~26.9 FPS), 95 inter-frame gaps >50 ms, maximum ~99.934 ms. Container r_frame_rate reported 120: do not confuse that nominal field with actual capture rate.
- Camera2 manual ISO 196, shutter 1/60 s (verified on screen): 883 frames / 32.213044 s (~27.4 FPS), 77 gaps >50 ms, maximum ~133.233 ms. No sustained 30 FPS pass. Initial test attempt aborted before recording because Back from the exposure panel had exited Open Camera; reopening and verifying idle allowed the actual test.
- Both trials were requested for 30 seconds; state verification adds stop latency. Start/stop confirmed and test clips copied with matching SHA-256 then deleted from phone and Mac. Frame timestamps inspected via ffprobe.
- Restored AUTO exposure after unsuccessful manual trial to avoid leaving a darker picture. Camera2, explicit 30 FPS, and battery saver off remain. Phone confirmed idle. No OBS or REAPER modifications.
- Next candidate is an A/B against LG stock Camera app; neither an Open Camera limitation nor a hardware/lighting bottleneck has been established. No stock-app test yet.

## First Samsung USB proof — 2026-09-07

Dyl Cam (R5CRC27FBMP): installed Open Camera 1.56.2 from the same official APK. Granted camera/microphone permissions, selected video mode, native 1080p and explicit approximate 30 FPS. No broad storage/location permissions granted. First trigger while a settings panel was open did not record; verified idle/no new clip before closing settings and attempting again. Important: underlying shutter nodes can remain in the accessibility hierarchy while settings obscure them; a production controller must detect modal/settings overlays, not merely find the shutter node.

Actual local recording: 121.202467 s, 3,635 frames, ~29.991 FPS, median frame interval 33.322 ms. Two >50 ms gaps, max 66.667 ms; near-30 but not perfectly uniform. Host interval approximately 17:53:18–17:55:27 EDT. USB transfer SHA-256 matched, full video decode passed. Test clip deleted on phone and Mac. Phone confirmed idle; OBS closed and REAPER untouched. Overhead Samsung and iPhone not yet installed/tested. No REAPER listening pass inferred.

## Shared-start test and retained defaults — 2026-09-07

- Samsung Dyl Cam: native 3840×2160, explicit target 30 FPS.
- LG: native 2880×2160 (4:3), largest listed Camera2 mode; explicit target 30 FPS. User requested largest available, not an upscale to UHD. Camera2/auto exposure and battery saver off retained.
- `pair_control.py`: prototype for these two phones only, with parallel preflight/commands/status verification, process lock, refusal to start unless both idle, and rollback of confirmed partial starts. Unknown states need manual inspection. Rejects settings overlays containing text so hidden shutter nodes do not count as ready.
- Mac GUI: double-click `~/phone-recording/Phone Recording.command` on mac-mini-16 for Start record / Stop record buttons. Both buttons call the same handler exercised by the test. No web server/daemon/live preview. GUI dialogs themselves have not been interaction-tested; shared handlers have been live-tested.
- Shared-start run: both independently confirmed recording after one start action; both confirmed idle after one stop action. It waits 120 seconds after verification; UI checks added latency, producing ~129.5–129.7 second files. Not synchronized/frame-accurate triggering.
- LG file: 2880×2160, 3,678 frames / 129.521167 s (~28.40 FPS); 203 intervals >50 ms, max 103.4 ms.
- Samsung file: 3840×2160, 3,888 frames / 129.666767 s (~29.985 FPS); 3 intervals >50 ms, max 66.7 ms.
- Both transferred afterward with matching SHA-256 and passed full video decode; both phone/Mac test copies deleted. First Samsung transfer hit the 15-second control-command timeout; inspected partial size, recopied with a 120-second transfer timeout and verified. Future collect implementation must use independent longer transfer timeouts.
- Ten unit tests passed (inventory + shared-controller state/rollback guards). This is a video/control pass with occasional gaps, not a REAPER audio listening pass. OBS remains closed; REAPER untouched.

Commands on mac-mini-16:

```bash
python3 ~/phone-recording/pair_control.py status
python3 ~/phone-recording/pair_control.py start
python3 ~/phone-recording/pair_control.py stop
```

No automatic collection/deletion in the shared controller. Test harness only: `test` explicitly records for ~2 minutes and saves state results; run only with user authorization and awareness that status latency extends duration. Do not run a test over an uncollected take. Other Samsung/iPhone not part of this pair yet.

## Automatic post-stop collection (supersedes manual-collection notes above)

User policy: completed camera clips should move to the Mac, not accumulate on phones. Shared GUI/CLI `start` now saves a durable take manifest before triggering. `stop` verifies both phones idle, then automatically copies all new MP4s in the app directory attributable to that take (including segmented files) to `~/Movies/Phone Recordings/<take-id>/<phone>/` on mac-mini-16. No transfers during recording. Hash checked against phone before/after copy, ffprobe duration checked, local file flushed and atomically finalized before deleting the phone original. Previously existing personal media are excluded. Transferred Mac recordings are retained.

If transfer/verification fails, retain the phone original and pending manifest; report failure. `collect` retries once both phones are idle. A pending take blocks a new start, preventing mixed-take cleanup. Unknown stop state defers all transfers. USB transfer timeout is 30 minutes, separate from shorter control calls. No daemon: recordings made outside this shared controller or stopped manually do not automatically transfer until a managed collection command is issued. Phone media must remain available until successful verification; never promise zero phone storage during capture.

Implemented in `collect.py` and wired to the shared GUI/CLI/test handler. Four collection unit tests plus ten existing tests pass. Deployed; new automatic integration has not yet been tested with a fresh live take. Prior manual transfers were live-tested. Future legacy single-phone diagnostic scripts must also collect/verify/delete immediately afterward or be migrated to this controller before use.

## iPhone onboarding started — 2026-09-07

Added/deployed `iphone_usb.py`: standard-library read-only usbmuxd/lockdownd discovery, no pairing secret access or new listener. Live check confirms iPhone12,1 / iOS 26.6.1 connected. Candidate Blackmagic API port 4444 is not currently reachable via USB; this does not prove USB is unsupported or the app is absent. App installation/foreground/remote-control settings remain unverified. Community Camera App 3.4 integration reports HTTPS port 4444 (https://github.com/bitfocus/companion-module-bmd-cameras/pull/7); API authentication/TLS trust and USB binding still require validation. No TLS verification bypass used. User needs to install/open Blackmagic Camera and grant camera/microphone permissions before the next step. Do not join iPhone to shared start or automatic cleanup until authenticated state control and verified file collection are proven.

### iPhone USB API breakthrough — supersedes initial unreachable-port result

After the user enabled the HTTP server and supplied its HTTPS LAN address, read-only REST discovery succeeded. The self-signed server certificate is explicitly pinned in `iphone_api.py` (trust on first observation; not independent identity verification); no system trust changes. **The same API was subsequently verified over usbmuxd port 4444 with pinned TLS, HTTP 200.** Deployed reader now uses USB exclusively, no TCP listener or LAN fallback. This supersedes the earlier failed USB probes: HTTP Server was the missing setup step, not demonstrated USB incompatibility.

Blackmagic app reports 3.4.100022, iPhone 11, idle, HEVC (H.265):High, native 3840x2160 at 24 fps, off-speed disabled, internal storage active. Native 3840x2160p30 is in the API-supported formats list but has not yet been set. Documentation saved remotely in `iphone-api-docs/` for transport/system/media/clips/video. Read endpoints returned HTTP 200 without an authentication header; do not equate the masked app-to-app remote password with REST authentication. Treat enabled LAN API as potentially accessible on the local network until protection is assessed.

No recording/settings mutations, preview, cloud upload, clip transfer or deletion performed. Clip-list API documents metadata only, not download/deletion; need a separate verified USB collection path before test capture or shared-controller integration. REAPER and Android controller unchanged.

### iPhone native 4K/30 configured and verified

`python3 ~/phone-recording/iphone_api.py setup-4k30` completed successfully over pinned TLS/USB. Guarded idle checks, supported-format check and off-speed check precede one PUT to `/system/videoFormat` with `{"name":"3840x2160p30"}`. Original format retained remotely in `iphone-before-4k30.json`. Readback verifies sensor and recording resolution 3840x2160, 30 fps, off-speed disabled, unchanged HEVC (H.265):High codec, still idle. Result `iphone-4k30-setup-result.json` mirrored locally. Safety checks rejected recording/unknown states and unapproved write routes. No test clip recorded: actual encoded cadence, sustained reliability and verified automatic collection/deletion remain untested. The setting readback is not a measured 30-FPS media result.

### Three-phone test interrupted — do not retry until recovery

Isolated remote `.iphone-venv` installed pymobiledevice3. Existing USB pairing verified with `autopair=False`; no new trust/pairing was initiated. Blackmagic bundle `com.blackmagic-design.DaVinciCamera` advertises file sharing. House Arrest `VendDocuments` exposes `/Documents/Media` (empty before test) and Proxy subfolder; root `/` is restricted. Implemented `three_phone_test.py` for a bounded overlapping capture, pending Android manifest, iPhone pretest inventory, USB AFC streaming transfer with independent second-device-read SHA-256 plus local disk reread, full decode before iPhone deletion. Not wired into the normal two-phone GUI.

Live attempt at 18:55 EDT: LG/Samsung toggles sent once and recording observed, iPhone POST record returned HTTP 204 but subsequent state became unknown. SSH session exited 255; runner no longer found, incomplete result file. USB iPhone discovery still works, but port 4444 unavailable; LAN port also refused. No root cause established. Recovery independently found LG recording and Samsung idle; a single verified LG stop returned both Android phones idle. iPhone state remains UNKNOWN; user asked to inspect/stop and reopen app. No transfers or deletions performed. `pending-take.json` and `three-phone-test-result.json` retained remotely; result mirrored locally. Test is NOT a pass. Do not start another take or collect while iPhone may still be recording. After recovery, collect the existing attributable take before retesting. Future runner must survive SSH disconnects (bounded detached process plus durable logs) and partial starts must retain cleanup state; avoid current interactive-session launch for unattended captures.

### Interrupted test recovered after app reopened

All three confirmed idle; iPhone retained native 4K/30. Read-only targeted crash-report inspection via existing USB pairing confirms `BlackmagicCam-2026-09-07-185527.ips`, capture time 18:55:23, EXC_BAD_ACCESS/SIGSEGV; faulting stack includes VideoToolbox callback symbols, not a proven root cause. Only sanitized crash summary saved (`iphone-crash-summary.json`), no full device crash-log sweep or crash-log deletion.

Android interrupted-take clips copied with matching hashes, duration inspection and phone-original deletion; subsequent full-video decode passed on both Mac copies. Samsung 3840x2160, 8.045222 s; LG 2880x2160, 44.650667 s. Mac folder `~/Movies/Phone Recordings/20260907-185523-dad539a5/`. iPhone created four zero-byte `.mov` placeholders (C002/C003 plus matching Proxy files), no playable footage. With all phones idle, explicitly allowlisted those four attributable files, copied byte-for-byte and flushed to `iphone-empty-artifacts/`, independently reread/verified zero size and empty hash, then removed the phone placeholders with absence checks. These are diagnostic artifacts, NOT successfully verified videos. Manifest and recovery result retained; no test media remain in the phones' inspected app media folders. Android pending take cleared after verified collection. Three-phone simultaneous test remains FAILED.

Proxy recording reads `enabled: true` on the iPhone. Next isolate an iPhone-only capture, preferably with proxies disabled and no active AFC service during recording, after hardening the bounded runner to survive SSH interruption. Do not attribute the crash to proxies, USB, REAPER or a specific codec without testing. Shared two-phone GUI remains unchanged; iPhone not integrated.

### Successful iPhone isolation and three-phone USB retest — 2026-09-07

User authorized disabling proxies and isolating iPhone before retrying all three. `iphone_isolated_test.py` explicitly disabled `/transports/0/proxyRecording` (HTTP 204, readback false), retained native 4K/30 HEVC High and off-speed disabled. It inventories app media through AFC then closes all file-sharing sessions before recording. A ~32.195-second iPhone-only clip succeeded (~30.005 FPS), copied via USB, independently re-read from phone and disk for SHA-256 match, fully decoded and removed from phone. Initial immediate post-stop status still reported recording; a later observation confirmed idle without another stop command. Added bounded observation-only stop retries.

`three_phone_test_v2.py` is a separate bounded diagnostic runner, **not yet integrated into the normal two-phone GUI**. It uses the shared lock, all-idle baseline, a durable pending manifest and three parallel start commands. Detached launch via Python `subprocess.Popen(..., start_new_session=True, stdin=DEVNULL, stdout=log, stderr=STDOUT)` survives SSH disconnects; do not use the earlier interactive launcher. iPhone AFC connections are closed during recording. Post-stop collection starts only after all three are confirmed idle. Existing unrelated media remain excluded.

Successful take: `20260907-190450-df439752`, started 19:04:44 EDT; all three verified recording before and after a 60-second hold, all three verified idle after stop, collection completed 19:07:27 EDT. App/control verification latency yields ~74-second clips; not frame-synchronized.

| Phone | Native video | Duration | Average FPS | Frames | Gaps >50 ms | Max gap |
|---|---|---:|---:|---:|---:|---:|
| iPhone 11 | 3840x2160 | 74.655 s | 30.005 | 2240 | 0 | 35.0 ms |
| Dyl Cam Samsung | 3840x2160 | 73.975 s | 29.981 | 2217 | 2 | 66.6 ms |
| LG | 2880x2160 | 73.920 s | 28.168 | 2083 | 121 | 123.8 ms |

All three transfers verified with SHA-256; all three phone originals deleted with per-file absence checks. All three retained Mac files passed full video decode and had increasing frame timestamps. Final Mac take folder: `~/Movies/Phone Recordings/20260907-190450-df439752/`; diagnostic Mac clips retained. Local result files: `iphone-isolated-test-result.json`, `three-phone-v2-result.json`, `three-phone-video-analysis.json`. `analyze_take.py` does read-only media analysis, no deletions. 17 unit tests pass across inventory, pair safety, collection and iPhone format guards. Live three-phone evidence is separate from unit coverage.

Retain iPhone defaults: native 4K/30, HEVC High, proxies OFF. Cause of previous crash remains unproven because both proxy setting and AFC session lifecycle changed. No intensive REAPER listening pass or long-session reliability claim. User disconnected iPhone after successful transfer/deletion; a later optional media inventory reported NoDeviceConnectedError, consistent with that disconnect, not a failed take. Do not reconnect/probe the absent iPhone until user requests. Android shared GUI remains LG + Dyl Cam only; incorporating iPhone production start/stop/recovery remains future work.

### Cue-free automatic audio alignment (local mac-mini-64)

User explicitly wants no claps, beeps, timecode hardware, or additional cues. Implemented `spectral_sync.py`: eight frequency-band log-energy envelopes, removal of slow gain changes, normalization across microphone frequency responses, and 200-Hz feature timing. It compares 9–25 distributed windows (8 seconds each for normal takes), checks correlation AND competing-match ambiguity, requires broad temporal coverage and consistent offsets/drift, and independently checks nonreference camera pairs for cycle consistency. This is audio feature correlation, not a guarantee of visual/lip synchronization; propagation delay, internal camera A/V offsets, and VFR interpretation remain considerations.

The original strict raw-waveform matcher is retained as `align_waveform` for diagnostics; its gates were not relaxed. Silence, tones, repetitive loops, unrelated audio, missing audio chunks, excessive drift and uncertain matches fail closed. No stretching, VFR conversion, video re-encoding, cues, cloud calls or REAPER operations. More than one clip per camera/proxies currently require review rather than guessed concatenation. Full audio extraction currently scales with take duration in local RAM; multi-hour operation has not been validated.

**Measured existing take `20260907-190450-df439752`:** reference Samsung; LG start +0.825 s, iPhone start -0.970 s relative to Samsung. Both reference matches accepted 9/9 windows; reverse LG→iPhone independent check accepted 8/9, rejected one weak window, measured -1.795 s and zero cycle residual at 5-ms feature resolution. Accepted offsets vary at most 5 ms per pair. Passing waveform evidence is not independently measured camera exposure synchronization. All original local copies were rehashed before analysis and remain unchanged.

**Generated timeline:** `~/Movies/Phone Recordings/20260907-190450-df439752/Resolve Sync/Synced.otio`. This is stacked camera tracks, **not a native multicam clip**. All original durations are preserved to the last whole 30-fps timeline frame; starts round to nearest frame (up to 16.7-ms quantization). Samsung reference audio enabled; other reference-audio tracks retained but disabled. Camera timeline starts: iPhone frame 0, Samsung 29, LG 54. OTIO serialization/roundtrip works using Python 3.13 (0.18.1 under Python 3.14 failed with `bad any cast`; isolated `.sync-venv` was rebuilt with 3.13). Resolve source timecode and VFR import behavior still require an in-app check.

**Run here:** double-click `projects/phone-recording/Prepare Resolve.command`, or:

```sh
cd /Users/dylanrapanan/JARVIS/projects/phone-recording
.sync-venv/bin/python prepare_resolve.py --take latest --import-resolve
# Reanalyze local verified footage without any remote/phone access:
.sync-venv/bin/python prepare_resolve.py --local "$HOME/Movies/Phone Recordings/20260907-190450-df439752" --import-resolve
```

`export_verified_take.py` runs read-only on mac-mini-16 via SSH, holds the shared controller lock throughout export, and refuses pending managed recording/collection. Only manifest-verified completed media are streamed; local safe extraction, SHA-256 verification, disk headroom, conflict refusal and atomic directory finalization precede analysis. Existing files are never blindly overwritten, no phone connections are used, and no Mac originals are deleted. Local copies are under `~/Movies/Phone Recordings/<take-id>/`. **No watcher, daemon, scheduled job or automatic post-stop hook is installed**: the preparation launcher is currently one click, separate from the Android recording GUI.

**Resolve 21.0.4:** installed at `/Applications/DaVinci Resolve.app`; opened for an API availability check. External `scriptapp('Resolve')` returned unavailable even with the app running. Did not enable external/network scripting, change permissions, or edit any existing Resolve project. `resolve_import.py` can import when local scripting is available; it refuses to switch away from unrelated projects, uses only `Phone Recordings Auto Sync`, pre-imports media, checks imported paths/track starts/durations, and mutes nonreference audio. Optional import failure is reported separately from successful sync. Actual in-app import/visual playback **not yet proven**.

Menu fallback generated at each approved take's `Resolve Sync/Import into Resolve.lua`. Installed user-only Utility wrapper at `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/JARVIS Import Latest Approved Take.lua`; Resolve scans scripts on startup, so this may require its next normal restart. Menu invocation is explicit and imports only the latest approved take; failed new takes do not replace that pointer. The Lua importer follows the same dedicated-project guard. Manual fallback: File → Import → Timeline, select `Synced.otio` in a suitable 30-fps project.

Validation: **35 unit tests passed**, including waveform signs, microphone EQ/gain/echo/noise, drift, repetition, silence, missing audio, checksum conflict, unverified export refusal, OTIO roundtrip and Resolve project safety guards. Results in `resolve-sync-validation-result.json`; execution log `resolve-sync-test-v2.log`; dependency pins `requirements-sync.txt`. Original take's weak raw-waveform result retained in `resolve-sync-test.log` for comparison. No new phone recording occurred; iPhone remains disconnected.
