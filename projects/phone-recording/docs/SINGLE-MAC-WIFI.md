# Single-Mac Wi-Fi controller

The current controller, dashboard, collector and Resolve preparation all run on
**mac-mini-64**. No SSH connection to mac-mini-16 is used by the live workflow.

## Use

Open `Phone Recording Dashboard.command` in this project. Bring the configured
phones online on the trusted LAN, foreground their camera apps, then **Check
cameras**. Start requires fresh verified idle state and readiness checks.

Android configuration must explicitly select Wi-Fi; absent configuration and USB
mode are rejected. Independent Homebrew ADB is used, not the OBS plugin's ADB.
The iPhone API remains certificate-pinned over Wi-Fi. iPhone file access requires
existing Network pairing (`autopair=False`); no USB fallback or new trust is
created. If Android trust is missing, use deliberate pairing/authorization rather
than copying another Mac's keys.

## Storage and safeguards

- Runtime configuration/state: this project (`.iphone-network.json`,
  `android-transports.json`, `.dashboard/`, `.dashboard-jobs/`, pending-take and
  deletion journals). Private runtime files are Git-ignored.
- Verified phone collection: `~/Movies/Phone Recordings Capture/<take-id>/`.
- Verified editing copy and Resolve output: `~/Movies/Phone Recordings/<take-id>/`.

These are **two folders on one Mac**, not independent backups. Collection retains
the existing policy of removing only managed phone originals after verified
transfer. Stop & review and exact-scope deletion confirmations remain in place.
The historical confirmation token `REMOTE` means the capture folder; `BOTH` means
capture and editing folders on this Mac. The UI explains the actual local scope.

The helper/module names `remote_jobs`, `remote_command`, and `remote_operation`
remain for compatibility, but dispatch and storage operations are local. Durable
job IDs, controller locks, no-replay recovery, checksum verification and guarded
Resolve-project deletion remain enforced.

## Migration validation

- No pending remote take, unresolved remote/local jobs, or running dashboard was
  found before cutover. Old cached readiness was invalidated.
- Shared helpers now use the project root and local interpreter. Installed
  `pymobiledevice3==11.9.2`, matching the former controller, in `.sync-venv`.
- Remote source/config/history snapshot retained privately at
  `.remote-migration/mac-mini-16/`; newer local source was not overwritten.
- Copied the retained iPhone diagnostic take from mac-mini-16 into Capture.
  Copy verified with rsync checksums and clip-manifest SHA-256/size. Rebased only
  its local `mac_path`; original receipt retained in `.remote-migration/`.
- 192 automated tests pass, including local dispatch, no-retry timeout,
  local capture-to-editing export/verification, pending-take gate and correct
  deletion-root routing. JavaScript syntax check passes.
- Read-only Wi-Fi checks could not reach/verify LG, Samsung or the pinned iPhone
  camera API during cutover. iPhone discovery alone had shown its Network
  transport earlier; authenticated file access is not thereby proven.

**Live readiness, recording, transfer, review/discard and Resolve end-to-end on
this host are not yet validated.** No recording, phone-media deletion, pairing or
camera-setting changes were performed. Do not claim the system is ready for a
session until a deliberate bounded live test succeeds.

The old `mac-mini-16:~/phone-recording/` runtime was subsequently deleted completely
at the user's explicit request, after checking for pending takes and unresolved
jobs. The private local source snapshot remains. The user then explicitly
requested deletion of remote `~/Movies/Phone Recordings/`; that folder was also
removed after a checksum comparison confirmed the local capture copy (only the
intentionally rebased transfer receipt differed). Local recordings remain intact.
Historical USB diagnostic scripts and older documentation are retained as history,
not current operating instructions.
