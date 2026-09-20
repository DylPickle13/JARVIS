# JARVIS security tools

Local Tapo H200/C230 CLI, read-only paired T100/T110 sensor snapshots, and separate
experimental archive probes. Supported models describe code capabilities, **not
an installed-device inventory or a claim that a home is secure**.

The core CLI and its tests are `security_cli.py` and `test_security_cli.py`.
C230 speaker audio is implemented in `security_audio.py`, with a local Piper
JARVIS voice worker in `security_tts.py` and offline tests in
`test_security_audio.py`. See [speaker audio commands](CLI.md#camera-speaker-audio)
for full-length speech/files, gain, looping, status and stop.
See [CLI.md](CLI.md) for commands and safety limits. The backend's
[on-demand status endpoint](../docs/security-integration-plan.md) wraps the existing
CLI; it does not expose controls or media. No security polling service is installed.

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
.venv-313/bin/python -m unittest test_security_cli test_security_audio -q  # offline tests
```

Reads are snapshots. Hub-reported sensor values do not establish radio freshness.
Missing features stay unknown; `security_assessment` remains `not_assessed`.
Writes require explicit intent and separate physical acceptance. `--confirm` is
not an authentication boundary: protect the local account and credential files.

## Experimental tools (not backend routes)

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
.venv-archive/bin/python -m unittest test_archive_download_probe -q  # offline
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
- `.audio-runtime/`, `.audio-settings/`, generated speech, audio files or app binaries;
- virtual environments or caches;
- household commissioning notes (`SD-CARD.md`, `DOORBELL.md`, `SETUP-TODAY.md`,
  `private-notes/`). These existing private files are deliberately not published.

Test addresses/users/passwords are synthetic fixtures, not working credentials.
Never use `git add -f` to bypass this policy. Review staged contents before pushing;
ignore rules do not remove previously tracked files or replace secret scanning.
