# Picture frame

Local-first preparation for the ordered **10.1-inch, 32GB, 1280×800 Frameo frame**
([Amazon.ca listing, BIGASUO](https://www.amazon.ca/dp/B088NHSVJN)). Exact hardware,
firmware, USB port and ADB compatibility remain **unverified until arrival**.

## What is ready

A dependency-free Python 3.9+ CLI using the host's Android platform-tools:

| Command | Purpose / acceptance limit |
|---|---|
| `doctor` | Local prerequisites only; does not start/connect to a device |
| `devices` | ADB transport list; never auto-selects a frame |
| `probe --serial SERIAL` | Read exact target's hardware/build identity and Frameo package candidates |
| `pair --serial SERIAL --package PACKAGE` | Pin the inspected identity in private local config |
| `status` | Identity-checked Android display/brightness settings; unknown is not off |
| `wake`, `sleep` | Dedicated Android wake/sleep keys, not power toggles or full shutdown |
| `brightness 180` | Set manual Android brightness (0–255); verify setting, not physical luminance |
| `screenshot` | On-demand private PNG capture; never uploads/shares the capture |
| `next`, `previous` | Experimental slideshow swipes, exact app focus + current display dimensions |
| `upload photo.jpg` | Experimental JPEG/PNG transfer into existing DCIM; never claims slideshow import |
| `wifi-enable` | Explicit USB-only LAN ADB setup; privileged/debug access, not a public API |
| `use-transport --serial IP:PORT` | Pin a previously connected USB/LAN transport to the SAME inspected identity |
| `pending`, `resolve-pending` | Inspect/acknowledge unknown outcomes locally, without replaying writes |

**Every applying command defaults to dry-run.** Without `--apply`, these commands
make **no ADB calls**, read no photos, and do not create pairing/runtime state.
Read commands (`devices`, `probe`, `status`) do contact ADB/the selected device.
`devices` may start the host's standard ADB server; the project adds no daemon.

## Start here

```bash
cd projects/operation-jarvis/picture-frame
python3 -B frame_cli.py doctor
python3 -B frame_cli.py --help
python3 -B frame_cli.py brightness 180  # harmless dry-run, even before pairing
python3 -B -m unittest discover -s tests -v
```

ADB is already available on `mac-mini-64`; no package installation or live-device
test was needed for preparation. Use local commands on this host, **not SSH**.

Follow the [arrival checklist](docs/ARRIVAL.md) before pairing or any applying action.
After that, examples (review before applying):

```bash
python3 -B frame_cli.py status
python3 -B frame_cli.py brightness 180 --apply
python3 -B frame_cli.py wake --apply
python3 -B frame_cli.py screenshot --apply
# Only while the actual slideshow is visible:
python3 -B frame_cli.py next --slideshow-ready --apply
# Only after enabling Transfer from computer on the frame:
python3 -B frame_cli.py upload /path/to/approved-photo.jpg --import-ready --apply
```

All results are JSON. A settings readback is not proof that a human saw the frame
change. Swipes report `dispatched_unverified`; successful transfers report
`transferred_import_unverified`. Inspect the actual slideshow to verify acceptance.

## Private state and safety

Default runtime (outside the source tree):

```text
~/Library/Application Support/JARVIS/picture-frame/
├── config.json             # exact ADB serial, package, hardware/build pins (0600)
├── controller.lock         # cooperating CLI-process lock
├── pending.json            # durable pre-dispatch marker, only while outcome needs review
├── last-resolved.json      # manual acknowledgement, not verification
├── uploads.json            # content-hash transfer journal, not original filenames/photos
└── screenshots/            # explicit captures (0700 directory, 0600 files)
```

A `--config PATH` override must use a **dedicated owner-only directory (0700)**;
do not point it into a shared repository directory. Globals go before the command.
The [config example](config.example.json) illustrates the shape only; do not copy its
placeholder identity as a real pairing. `pair` generates identity from an inspected
live probe and refuses to replace existing pairing/pending state.

- Every live control uses `adb -s EXACT_SERIAL`, with a fresh hardware serial,
  manufacturer, model, build fingerprint and installed-package check first.
- Firmware/build changes fail closed. Re-probe and deliberately review/re-pair;
  do not weaken the pins to get around a mismatch.
- Locks coordinate this controller only, not arbitrary external ADB users.
  Android property pins are safety checks, **not cryptographic attestation**.
- Durable markers are saved before writes. Timeout, disconnect, interruption,
  failed/unknown readback or partial brightness changes leave a pending marker.
  Later writes are blocked. No retry, rollback, catch-up queue or automatic replay.
- `pending` works without a connected frame. Only after physical inspection use
  `resolve-pending --apply`; it acknowledges uncertainty and performs no device action.
  An unknown upload may already have imported: do not blindly send it again.
- No root, app install/uninstall, factory reset, reboot, raw-shell endpoint, photo
  deletion, Frameo database edits, broad LAN scans or assumed import directories.
- Source allowlist ignores all accidental photos/configs/captures. Runtime never
  belongs in Git. The standard host ADB keys remain in `~/.android`, not this project.

## Compatibility boundaries / next milestones

1. **Arrival:** inspect real hardware, ADB opt-in and authorization; pin exact identity.
2. **Acceptance:** test one approved photo and one owner-approved display action;
   confirm slideshow behavior and navigation direction physically.
3. **LAN:** optional supervised wireless ADB setup; verify after a reboot before
   relying on it. Never forward ADB ports to the internet.
4. **JARVIS integration:** use this CLI for deliberate commissioning; only after
   device acceptance add a focused Pi tool/backend route. No current native-app
   routes, tool schemas, services, LaunchAgents or automations were changed.
5. **Future:** optional EXIF-safe resizing/HEIC conversion, bulk import with verified
   deduplication, captions/albums/schedules if the firmware exposes a reviewed path.

The controller sends photos **unchanged**, including any embedded EXIF/GPS metadata.
It only checks file signatures, not full image decodability. Remote `.part` staging,
byte-count readback and no-clobber rename avoid exposing a half-written JPEG/PNG;
this firmware-specific import flow still requires acceptance. Review/strip metadata
and convert HEIC to JPEG/PNG before transfer. The 50 MiB limit is a conservative
project limit, not a documented Frameo limit. No family library was scanned.

Frameo's documented computer transfer uses DCIM with its **Transfer from computer**
setting, and is documented for Windows/Linux. ADB-based Mac transfer is an
**experiment**, not a guaranteed replacement for the mobile app. There is no known
supported public Frameo control API here. See [research and design](docs/DESIGN.md).
