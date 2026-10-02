# Phone Recording dashboard — mac-mini-64

> Historical/reference document. Use [OPERATIONS.md](OPERATIONS.md) for the current single-Mac workflow and recovery rules.

**Current Resolve workflow:** automatic native timeline drop is integrated after verified copy/audio sync. Each camera gets its own full-length named video track; no automatic rough cuts. Clean project rebuild and duplicate-safe retry passed. See [automatic Resolve workflow](RESOLVE-AUTOMATIC.md), including the fix that moves per-run jobs out of protected app data.

**Single-screen redesign:** [layout, safety changes and validation](DASHBOARD-PRODUCTION.md). Main controls fit tested Mac viewports without scrolling; history and details live in overlays.

## Open it

Double-click **`/Users/dylanrapanan/JARVIS/projects/phone-recording/Phone Recording Dashboard.command`** on this Mac.

Dashboard: **http://127.0.0.1:8768/**

The launcher starts the local server if needed, then authorizes your browser. Once authorized, bookmark the plain dashboard URL. If authorization expires, rerun the launcher. The server is **loopback-only**, not available from other devices. It runs on **mac-mini-64**, never on mac-mini-16. There is no login agent, cron job, or automatic startup service.

## Everyday workflow

1. Keep LG + Dyl Cam + iPhone on the trusted LAN with their configured **Wi-Fi connections**. Leave Open Camera foregrounded on Androids and Blackmagic open on iPhone, with reference audio enabled. All three cards show the selected connection. USB remains available by deliberate configuration, not automatic fallback. See [Wi-Fi setup, limits and USB recovery](WIFI.md).
2. Here, open the dashboard. The main button says **Check cameras** when readiness needs checking, then **Start recording** once all enabled cameras pass readiness. Start requires observations and successful readiness checks newer than two minutes, matching camera configuration, adequate disk space on both Macs and no pending managed take. See [READINESS.md](READINESS.md) for battery/storage/heat thresholds and unsupported iPhone temperature warnings. Optionally click **Check framing** for still snapshots (see below).
3. Click **Start recording** and wait for confirmation. Use **Stop & review** when finished.
4. At the first pause, choose **Transfer recording** or **Delete take…** (phone originals; no saved Mac copy).
5. After verified collection on mac-mini-16, choose **Verify copy & prepare** or **Delete take…** before copying here.
6. Preparation verifies the second-Mac copy, aligns audio and imports the full named camera tracks into Resolve. **Delete take…** remains available afterward for both Mac folders and the sole dedicated Resolve project.

Deletion is permanent, requires a typed exact-take/scope confirmation, and creates no backups or Trash copies. Active/uncertain jobs and ambiguous identities block it. See [review pauses, safeguards and limitations](DELETE-AND-REVIEW.md). This is a user-confirmed cleanup action, not an automatic deletion schedule.

### Check framing: idle-only still snapshots

Click **Check framing** (or **Refresh framing**) to take one fresh screenshot from each enabled phone. All three camera images were visibly confirmed in Chrome, including Open Camera controls and the iPhone Blackmagic view. This is **not smooth/live video** and has no automatic refresh loop. Screenshots are resized to a maximum 960 pixels and transferred as JPEG; the original phone video files/settings are untouched.

All three phones must be confirmed idle before and after snapshot capture, under the recording controller lock. A pending take, unknown state, active job or recording prevents framing capture. Starting through the dashboard/CLI clears snapshots before the recording worker launches. Framing jobs never send camera toggles.

Snapshots expire from the dashboard after 60 seconds; ephemeral files are under `.dashboard/lg.jpg`, `samsung.jpg`, `iphone.jpg`, and `preview.json`, overwritten on refresh and removed on expiry/Start. Server housekeeping enforces expiry even when the browser is closed; a server restart clears leftover previews. Screenshots are not embedded in job logs or retained in the remote job journal. Temporary remote screenshot files are removed after capture. Existing downloaded browser images are not a live indication of later camera state.

The simplified main page shows the three integrated cameras, one contextual recording button, a workflow indicator during processing, and the latest take. Unintegrated cameras, historical jobs and technical details are out of the main view.

**Current scope:** LG Wide Angle + Samsung Dyl Cam + iPhone Bass Pedals. Overhead is the planned fourth camera, not yet enabled. Check framing now retrieves all three phone screens; see [iPhone framing](IPHONE-FRAMING.md). See [managed three-camera workflow](THREE-CAMERA.md) and [four-camera plan](CAMERA-PLAN.md). No recording was started to validate this integration.

### Safety and recovery

- Closing/reloading the page does not stop recording or cancel jobs.
- HTTP requests enqueue durable jobs; background workers are separate processes. The local web server can restart without killing a local preparation job (tested on the real retained take).
- A small CLI helper on mac-mini-16 launches detached recording/collection workers; there is **no remote web server**. Remote worker launch uses an immutable job ID and persists intent before sending recording commands.
- One active/uncertain operation at a time. Duplicate request IDs return the existing job, never another toggle.
- SSH timeout after submission is uncertain, not permission to retry. **Reconcile — no command retry** reads the existing remote job by ID. It never resends Start/Stop. A missing/crashed remote worker is reported for inspection, not automatically restarted.
- On ordinary collection failure, inspect the job result; **Finish collection** becomes available when a pending take is known. Refresh to see current states/pending ID. Do not delete `pending-take.json` to bypass recovery.
- Start is rejected for stale, unknown, recording, or pending-take status; the remote controller independently rechecks all three phones before starting.
- Local synchronization failure flags review and leaves Mac originals intact. No automatic drift correction or video re-encoding is performed.
- If mac-mini-64 powers off after remote Start, the phones may keep recording. Closing an app, rebooting a Mac, or stopping the web server is **not** a camera Stop. Reconcile/inspect after reconnecting. No automatic resume after OS reboot or unattended recording watchdog is installed.
- Legacy CLI/GUI users must not operate concurrently with dashboard jobs. Controller/sync locks protect critical work, but not every legacy mutation has the new idempotent remote journal.

## Current wireless validation

A bounded three-camera Wi-Fi recording, verified collection, managed-original deletion and verified second-Mac copy passed on September 9. Shared music alignment and native Resolve timeline creation also passed. The test take and project were subsequently permanently deleted at the user's request, including project backups. Longer-session/thermal/disconnect reliability and independent visual sync remain unproven. LG Wi-Fi ADB is trusted-LAN only; Samsung uses paired TLS; iPhone uses pinned API and existing Network pairing. The latest single-screen rollout is offline/UI validated: **150 tests pass**; no new recording was performed for this redesign.

## Where everything lives

| Item | Machine | Location |
|---|---|---|
| Project-folder launcher | mac-mini-64 | `/Users/dylanrapanan/JARVIS/projects/phone-recording/Phone Recording Dashboard.command` |
| Dashboard source, CLI, docs | mac-mini-64 | `/Users/dylanrapanan/JARVIS/projects/phone-recording/` |
| Server and job state | mac-mini-64 | `<source>/.dashboard/` |
| Local job journal | mac-mini-64 | `<source>/.dashboard/jobs.sqlite` (SQLite WAL) |
| Server log / PID | mac-mini-64 | `<source>/.dashboard/server.log`, `server.pid` |
| Local job logs | mac-mini-64 | `<source>/.dashboard/<job-id>.log` |
| Browser authorization secret | mac-mini-64 | `<source>/.dashboard/auth-token` (0600; do not share or commit) |
| Remote controller/helper | mac-mini-16 | `~/phone-recording/pair_control.py`, `remote_jobs.py` |
| Remote job records/logs | mac-mini-16 | `~/phone-recording/.dashboard-jobs/<job-id>.json` / `.log` |
| First verified footage copies | mac-mini-16 | `~/Movies/Phone Recordings/<take-id>/<camera>/` |
| Verified editing copies | mac-mini-64 | `~/Movies/Phone Recordings/<take-id>/<camera>/` |
| Timeline/report/import script | mac-mini-64 | `~/Movies/Phone Recordings/<take-id>/Resolve Sync/` |

Videos stay on **both Macs** after successful preparation. Only verified phone originals are automatically deleted during collection. Explicit pre-transfer discard is a separately confirmed exception. No automatic Mac cleanup or backup schedule is installed. The take library lists completed managed Android archives and verified local copies; an iPhone-only diagnostic without an Android transfer manifest is not listed there. The full historical file map is in [OPERATING-GUIDE.md](OPERATING-GUIDE.md).

## Resolve integration

Resolve 21.0.4 uses a finite in-app Lua menu job and native API construction because external scripting and OTIO import did not work in this installation. Native import and a clean project rebuild have been verified. Each camera gets one full-source named video/audio track; only reference audio is enabled. This is an editable stack, not a native multicam clip. Visual sync/VFR playback still requires review.

Routine automation files live outside the protected app container; no broad disk permission grant is required by the design. See [RESOLVE-AUTOMATIC.md](RESOLVE-AUTOMATIC.md). Never interpret a cached success receipt as a new project inspection after manually deleting or editing a timeline.

## Shared CLI (same engine as web)

Run on **this Mac**:

```sh
cd /Users/dylanrapanan/JARVIS/projects/phone-recording
./phone-recording dashboard     # start/open the dashboard
./phone-recording status        # cached state, jobs and take locations
./phone-recording refresh       # enqueue fresh Android observation
./phone-recording start         # enqueue guarded LG + Dyl Cam + iPhone start
./phone-recording stop          # enqueue stop → collect → copy → sync → import attempt
./phone-recording collect       # retry collection, then prepare the identified take
./phone-recording prepare 20260907-190450-df439752
./phone-recording import 20260907-190450-df439752
./phone-recording recover <job-id>  # reconcile an uncertain job; never reissue camera mutation
```

Commands return a job ID promptly; use `status` or the dashboard for completion. There is no Pi extension yet; it can later wrap this engine without duplicating camera logic. Battery/storage/available temperature checks now run on explicit status refresh and independently before Start. There is no continuous health watchdog or `doctor` command; see [READINESS.md](READINESS.md).

## Implementation and validation

- `dashboard_server.py`: standard-library HTTP server, binds only 127.0.0.1:8768, authenticated API, strict Host/Origin checks, JSON-only POST, CSRF header, HttpOnly/SameSite cookie, CSP, no arbitrary command/file-serving endpoint.
- `dashboard_jobs.py`: shared SQLite journal, detached local workers, operation gate, exact-take preparation, read-only reconciliation.
- `remote_jobs.py`: narrowly scoped SSH helper deployed on mac-mini-16; no HTTP service or daemon there. Uses existing pair controller and locks.
- `dashboard/`: local HTML/CSS/JS, no CDN/network dependencies, no live camera streams.
- `dashboard.py`, `Dashboard.command`: launch/open locally; do not start recording.
- `test_dashboard.py`: job idempotency, stale start guard, SSH ambiguity, recovery read-only behavior, exact-take post-stop chaining, failed-collection gate, remote duplicate submission, authentication/origin/CSRF/Host/GET protections.

**129 unit tests passed** in the combined suite, including three-camera control and recoverable iPhone collection. Tests now live in `tests/` under the project root. Live Chrome checks: authenticated page, camera refresh (both idle), take library and existing-take preparation all worked. A retained-take preparation job completed while the web server was deliberately restarted; evidence in `dashboard-validation-result.json`. Browser Start/Stop recording itself has not been exercised against phones in this release. No REAPER changes, new video recording, external scripting permission changes, or OS auto-start installation occurred. Later framing validation took only idle screen snapshots; no recording was started.
