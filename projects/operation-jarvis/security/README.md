# JARVIS security tools

Local Tapo H200/C230 CLI, read-only paired T100/T110 sensor snapshots,
D235 direct status/settings, recording plans and archive downloads, speaker audio,
and HD live video/private snapshots. An explicit experimental **cloud** Smart Actions
adapter also manages app shortcuts/automations. Supported models describe code capabilities, **not
an installed-device inventory or a claim that a home is secure**.

The core CLI and its tests are `security_cli.py` and `test_security_cli.py`.
C230 and D235 speaker audio is implemented in `security_audio.py`, with a local Piper
JARVIS voice worker in `security_tts.py` and offline tests in
`test_security_audio.py`. See [speaker audio commands](CLI.md#camera-speaker-audio)
for full-length speech/files, gain, looping, status and stop.
See [CLI.md](CLI.md) for commands and safety limits. The backend's
[on-demand status endpoint](../docs/security-integration-plan.md) wraps the existing
CLI; it does not expose controls or media. No security polling service is installed.

The experimental D100C adapter (`security_chime.py`, `security_chime_worker.mjs`)
provides authenticated status/capabilities and confirmation-gated preset ring/stop
commands. Status and six preset tone IDs are verified; ring/stop were acknowledged
in owner-authorized tests, and preset ringing is owner-confirmed audible.
Active-sound interruption by stop is also owner-confirmed. Custom audio upload/streaming is not supported by this adapter. It uses
a narrow TPAP transport with isolated, pinned @noble/curves dependencies, not the
production camera environment; the superseded prototype has been removed;
see [chime commands and caveats](CLI.md#experimental-d100c-chime).

`security_smart_actions.py` adds explicit cloud list/describe/show/create/update/rename,
enable/disable/delete and separately confirmed shortcut execution. Writes require
confirmation, fresh revisions for existing rules, private backups and readback;
there are no automatic retries. Only cloud reads and name-change/restoration are
live-verified so far; other operations remain experimentally implemented, with
offline coverage. See [Smart Actions commands, setup and caveats](CLI.md#experimental-tapo-cloud-smart-actions).
Cloud account configuration and raw rule exports/backups remain private; tokens
are session-only. Local device commands remain local. The optional
[Operation JARVIS Pi suite](../../../.pi/docs/OPERATION_JARVIS_TOOLS.md) exposes
read-only devices/status/capabilities and cloud list/describe. Automation
enable/disable is live-accepted (owner approval 2026-09-20); the extension
checks the exact revision again and verifies readback.

## Local setup

Use a separate Python 3.13 environment; do not upgrade a working plug/purifier SDK:

```sh
python3.13 -m venv .venv-313
.venv-313/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
cp devices.example.json devices.json
chmod 600 devices.json
```

Fill `.env` locally using a private editor, never chat, command arguments or Git.
The blank template cannot authenticate. The example registry contains only a
hypothetical hub alias and resolves its address from `.env`; extend your private
registry only after commissioning and checking identity. Do not shell-source `.env`.
Camera Account/RTSP credentials are separate from the hub's cloud credentials;
`camera.env.example` is a blank reference, not an automatically loaded file.

```sh
./security --help
./security devices                       # offline configured aliases only
./security --json status hub             # explicit live read, after local setup
.venv-313/bin/python -m unittest discover -q  # offline; optional archive tests skip here
```

D235 direct reads/settings use `security_doorbell_direct.py` through the isolated
archive-environment worker. See [D235 commands and limits](CLI.md#d235-doorbell):
readback checks are implemented, but live write/physical acceptance is separate.
Recording modes/custom schedules, hub archive indexes, and confirmed short private
clip downloads are implemented in `security_recording.py`. Completed downloads
can be locally video-decoded if FFmpeg is installed. `security_video.py` provides
confirmation-gated local live view and private snapshots, defaulting to HD;
`--quality low` retains the original lower-resolution path. Both live video modes
and D235 JARVIS speech have owner-confirmed playback. HD snapshot output is separately verified at 2560×1920.

`security_events.py` stages bounded local detection-history reads and suppressed
notification previews (`events status/history/preview`). Physical event delivery
and type mapping are unverified; there is no background listener, notification
destination or delivery. Real notifications, archive playback UI, two-way audio,
persistent chime settings and quick responses remain follow-up work. A separate diagnostic
verified Tapo-private PCMU archive audio decoding from one short clip, and the
owner confirmed normal-sounding playback. AV sync and longer-term recording
continuity remain unassessed.
Device-advertised component lists are not a claim of CLI support.

Reads are snapshots. Hub-reported sensor values do not establish radio freshness.
Missing features stay unknown; `security_assessment` remains `not_assessed`.
Writes require explicit intent and separate physical acceptance. `--confirm` is
not an authentication boundary: protect the local account and credential files.

## Archive dependencies and legacy C230 tools (not backend routes)

Do not delete files merely because their names contain `probe`: the supported
D235 clip path imports `archive_download_probe.download`, which in turn imports
`archive_probe.ReadOnlyTapo`. These are live dependencies as well as legacy C230
command-line entry points. The C230-only commissioning writer is retained because
the D235 recording CLI does not replace its model-specific behavior.

`archive_probe.py` performs a bounded metadata query. `archive_download_probe.py`
limits downloads to ten seconds within the preceding day, at least a minute old,
with size/time limits and private local output. Metadata and media are sensitive;
do not publish command output. Audio/codec compatibility requires separate testing.

`continuous_recording.py --confirm` is a **real settings write** to the weekly
recording plan. It is not a read-only probe or an installation step. It expects the
private camera alias used in the script and must never be run merely to test setup.

These scripts expect local `hub` / `indoor-camera` aliases as applicable and exactly
one matching C230 for archive operations. They must not be repurposed for an
uncommissioned model. Their alias conventions do not enumerate actual devices.

Use a separate environment for these experiments:

```sh
python3.13 -m venv .venv-archive
.venv-archive/bin/python -m pip install -r requirements-archive.txt
.venv-archive/bin/python -m unittest test_archive_download_probe test_security_doorbell test_security_recording -q  # offline
```

Do not run probe mains during tests, CI, installation or backend startup.

## Repository privacy

`security/.gitignore` defaults to private and allows only individually reviewed
source, tests, sanitized documentation and blank/synthetic templates. New files
stay ignored until reviewed. Source visibility is not the security boundary;
credentials, API authentication, permissions and bounded operations are.

Never commit:
- `.env`, real camera credentials or secret-manager exports;
- `devices.json`, `planned-devices.json`, LAN addresses or device/account IDs;
- recordings, snapshots, clip indexes, logs, runtime state or lock files;
- `private-smart-actions/` rule exports/backups or private cloud account configuration;
- `.audio-runtime/`, `.audio-settings/`, `.video-runtime/`, `private-snapshots/`,
  `private-archive/`, generated speech, audio files or app binaries;
- virtual environments or caches;
- household commissioning notes (`SD-CARD.md`, `DOORBELL.md`, `private-notes/`).
  The obsolete “setup today” checklist is archived as
  `private-notes/commissioning/SETUP-BASELINE.md`, not current setup guidance.
  These private files are deliberately not published.

Test addresses/users/passwords are synthetic fixtures, not working credentials.
Never use `git add -f` to bypass this policy. Review staged contents before pushing;
ignore rules do not remove previously tracked files or replace secret scanning.
