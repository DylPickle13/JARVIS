# mac-mini-16 cleanup and source consolidation

**Update:** The code cutover is now implemented. See [single-Mac Wi-Fi operation
and validation](SINGLE-MAC-WIFI.md). The remaining text records the earlier
source-preservation stage; its "not completed" section is historical.

## Completed

The remote `~/phone-recording/` deployment has been copied to the private,
Git-ignored local directory `.remote-migration/mac-mini-16/` inside this project.
The snapshot is approximately 6.1 MB. A checksum-based rsync dry run reported no
remaining differences for the included files.

Excluded: `.iphone-venv/`, `__pycache__/`, `*.lock`, and `.wifi-validation/`.
The snapshot includes historical scripts, documentation, validation reports,
OpenCamera installer, deployment configuration and job records. Treat it as
private runtime data, not publishable source. Do not blindly restore old jobs or
configuration into the running dashboard.

113 non-hidden remote files have byte-identical counterparts somewhere in the
local project. Shared root recording helpers match. The remote dashboard docs,
README and some tests are older; newer local files were not overwritten.
Remote-only historical diagnostic scripts and API documentation are preserved
in the snapshot rather than installed as active entry points.

`mac-mini-16:~/JARVIS-host-services/` was removed. It held a public-key copy,
an old HTTP log and Finder metadata, not the recording runtime.

## Not completed: recording-host cutover

The remote `~/phone-recording/` directory is deliberately still in place.
The dashboard still executes helpers on mac-mini-16. Source consolidation is
NOT a migration of live recording execution.

A single-Mac cutover requires changes and tests across:

- `dashboard_jobs.py`: SSH dispatch and durable helper jobs.
- `android_transport.py`, `pair_control.py`, `iphone_network.py`,
  `remote_jobs.py`: controller roots and device configuration.
- `inventory.py`: replace the remote OBS/DroidCam bundled ADB default with
  independent local ADB.
- `prepare_resolve.py` and `export_verified_take.py`: replace the remote export
  stage without incorrectly claiming two independently verified Mac copies.
- `delete_take.py` and `delete_storage.py`: preserve exact-scope confirmations,
  locks and verification when remote and local storage are no longer two hosts.
- Device access: verify existing Android trust and iPhone Network pairing/file
  service access here; do not copy pairing secrets or silently create trust.
- Runtime state: reconcile active/uncertain jobs and pending takes before a
  cutover; do not replay snapshot job records.

Local independent ADB, ffmpeg and ffprobe are installed. A read-only usbmuxd
listing found the configured recording iPhone here on Network transport. This
is discovery only: authenticated file-service access, recording, collection,
delete/review and live reliability have NOT been validated here.

Recordings in `~/Movies/Phone Recordings/` on either Mac were not migrated or
deleted by this consolidation. No phone recording commands or media deletion
were issued. Do not remove the remote runtime until a cutover is validated.
