# Picture frame

Local-first control preparation for the received **10.1-inch, 32GB, 1280×800 Frameo frame**
([Amazon.ca listing, BIGASUO](https://www.amazon.ca/dp/B088NHSVJN)). **USB ADB pairing,
private screenshots and one PNG slideshow import are now verified on this unit.**
Retail branding/USB connector details have not been recorded. **Wireless identity,
status, backlight diagnostics and a private 1280×800 screenshot now pass using an
explicitly owner-approved legacy LAN mode. It is unauthenticated ADB, not secure
wireless debugging.** USB-disconnected wireless PNG import is now physically
confirmed. One disposable-card removal was also physically confirmed through an
owner-assisted native UI pilot; this is not a general/headless deletion API.
Wi-Fi wake is now physically confirmed. USB JPEG batch import/count acceptance
used a private corrected staging pilot, without viewing photo contents. Sleep,
gestures and reboot persistence remain untested. **The public CLI still has an
[in-DCIM temporary-file importer limitation](docs/IMPORT_ACCEPTANCE.md); do not use
it for unattended bulk imports on this unit.**
See the [complete controls guide](docs/CONTROLS.md), [TCP policies](docs/DIRECT_TCP.md)
and [capability audit](docs/CAPABILITIES.md).

## What is ready

A Python 3.9+ CLI: standard-library-only USB/platform-tools control, with an
[optional private TCP dependency](docs/DIRECT_TCP.md) with separate authenticated
and explicitly owner-accepted legacy LAN policies:

| Command | Purpose / acceptance limit |
|---|---|
| `doctor` | Local prerequisites only; does not start/connect to a device |
| `devices` | ADB transport list; never auto-selects a frame |
| `capabilities` | Local control/limitation inventory, no device contact |
| `probe --serial SERIAL` | Read exact target's hardware/build identity and Frameo package candidates |
| `pair --serial SERIAL --package PACKAGE` | Pin the inspected identity in private local config |
| `status` | Identity-checked Android display/brightness settings; unknown is not off |
| `backlight` | Effective backlight/window override reads; missing/ambiguous is unknown |
| `wake`, `sleep` | Dedicated Android wake/sleep keys, not power toggles or full shutdown |
| `brightness 180` | Set manual Android brightness (0–255); **Frameo overrides this on the received unit**, so readback is not visible brightness control |
| `screenshot` | On-demand private PNG capture; never uploads/shares the capture |
| `next`, `previous` | Experimental slideshow swipes, exact app focus + current display dimensions |
| `upload photo.jpg` | Experimental JPEG/PNG transfer into existing DCIM; never claims slideshow import |
| `wifi-enable` | Explicit USB-only LAN ADB setup; privileged/debug access, not a public API |
| `use-transport --serial IP:PORT` | Pin a previously connected USB/LAN transport to the SAME inspected identity |
| `connect-tcp --serial IP:PORT` | Strict signed-RSA TCP; this unauthenticated firmware is still rejected |
| `connect-legacy-lan --serial IP:PORT` | USB-first exact-frame risk acceptance; explicit acknowledgement + apply required |
| `wifi-disable` | Exact USB listener retirement, verified shutdown and legacy-consent revocation |
| `pending`, `resolve-pending` | Inspect/acknowledge unknown outcomes locally, without replaying writes |

**Every applying command defaults to dry-run.** Without `--apply`, these commands
make **no ADB calls**, read no photos, and do not create pairing/runtime state.
Read commands (`devices`, `probe`, `status`, `backlight`) do contact ADB/the selected device.
`capabilities`, `doctor`, and `pending` are local only.
`devices` may start the host's standard ADB server; the project adds no daemon.

## Status-only backend integration — deployed

The [jarvisd availability entry](../jarvisd/docs/picture-frame-health.md) activated
at **15:52 EDT on 2026-10-06** as `20261006T193632Z-picture-frame-health`.
`health_worker.py --check` performs a pinned identity/package read only, through
the existing serial health worker. Fresh results expose availability and last
check time; stale/unverified results remain unknown. Actual backend launch-context
and later periodic checks passed. No photos, controls, new API routes or background
screen capture. The worker's default invocation remains a no-I/O dry-run.

## Start here

```bash
cd projects/operation-jarvis/picture-frame
./frame doctor
./frame --help
./frame capabilities
./frame brightness 180  # harmless dry-run, even before pairing
../security/.venv-313/bin/python -B -m unittest discover -s tests -v
```

ADB is already available on `mac-mini-64`; no package installation or live-device
test was needed for preparation. Use local commands on this host, **not SSH**.

Follow the [arrival checklist](docs/ARRIVAL.md) before pairing or any applying action.
After that, examples (review before applying):

```bash
./frame status
./frame backlight
./frame screenshot --apply
./frame wake                         # dry-run; Wi-Fi visible wake is physically accepted
./frame next --slideshow-ready       # dry-run; slideshow/focus checks still required
# Applying upload remains experimental; read docs/IMPORT_ACCEPTANCE.md first.
# The current CLI's in-DCIM staging is not accepted for unattended bulk import.
```

`./frame` runs the entire CLI in the normally LAN-authorized Python 3.13 runtime;
it creates no proxy/service and never adds `--apply`. All results are JSON. Legacy
LAN results explicitly report the lack of authentication and its risk.
A settings readback is not proof that a human saw the frame
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
├── screenshots/            # explicit captures (0700 directory, 0600 files)
└── tcp-deps/                # optional hash-pinned source + manifest; owner-only
```

A `--config PATH` override must use a **dedicated owner-only directory (0700)**;
do not point it into a shared repository directory. Globals go before the command.
The [config example](config.example.json) illustrates the shape only; do not copy its
placeholder identity as a real pairing. `pair` generates identity from an inspected
live probe and refuses to replace existing pairing/pending state.

- Every live control uses one exact target: `adb -s EXACT_SERIAL` for platform-tools,
  or one explicit TCP endpoint under the saved authenticated/legacy policy. Both
  require fresh hardware serial, manufacturer, model, build fingerprint and package checks.
- Legacy LAN consent is private and bound to endpoint/package/build; no Mac key is
  read/sent in that mode. Other reachable LAN clients may still access the listener.
  USB selection revokes consent but does not disable it; `wifi-disable` does both.
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
4. **JARVIS integration:** availability-only tracking is deployed through the
   existing jarvisd worker. Keep uploads/controls as deliberate commissioning;
   no frame control/photo route, Pi control schema or native-app feature is added.
5. **Future:** optional EXIF-safe resizing/HEIC conversion, bulk import with verified
   deduplication, captions/albums/schedules if the firmware exposes a reviewed path.

The controller sends photos **unchanged**, including any embedded EXIF/GPS metadata.
It only checks file signatures, not full image decodability. The checked-in
uploader verifies remote `.part` byte counts before no-clobber rename, but its
in-DCIM staging can trigger Frameo's unsupported-file warnings. Existing PNG
acceptance does not generalize to bulk JPEG import. The private USB pilot's
accepted outside-DCIM staging is not a public CLI mode; see
[acceptance, privacy and cleanup limits](docs/IMPORT_ACCEPTANCE.md).
Review/strip metadata and convert HEIC to JPEG/PNG before selecting a source;
never analyze or convert owner photos without permission. The 50 MiB limit is a conservative
project limit, not a documented Frameo limit. No family library was scanned.

Frameo's documented computer transfer uses DCIM with its **Transfer from computer**
setting, and is documented for Windows/Linux. ADB-based Mac transfer is an
**experiment**, not a guaranteed replacement for the mobile app. There is no known
supported public Frameo control API here. See [research and design](docs/DESIGN.md)
and the [verified/untested capability matrix](docs/CAPABILITIES.md).
