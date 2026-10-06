# Picture-frame controls

Reviewed public code/commands live in this project; private commissioning pilots
remain outside Git. The [availability-only backend](../../jarvisd/docs/picture-frame-health.md)
uses its existing worker. No frame control/photo route, Pi control schema, native
app control, new frame daemon or scheduled media job was added.

## Current received-unit acceptance

The owner explicitly requested re-enabling LAN ADB after reviewing the missing
RSA authentication. **Legacy LAN is now selected for this exact frame/address/build.**
Live TCP identity/status, effective-backlight diagnostics and a private **1280×800
PNG** screenshot passed. These commands used in-process TCP, not the USB transport.
USB remains available for deliberately selected recovery/retirement.

This mode is **not authenticated or encrypted**: other reachable LAN clients may
obtain privileged debugging access. A private consent record binds the exact
endpoint, package and build pins; every live result identifies the risk. Those
controller checks cannot secure the frame's listener against other clients.
Authenticated `connect-tcp` still requires a signed RSA challenge; it was not relaxed.
No Mac privacy gate, signing identity, existing ADB server or other device was changed.

One earlier **USB PNG** import and a later **USB-disconnected wireless PNG** import
were physically accepted. The disposable test card was removed through a guarded,
owner-assisted native UI pilot, not a generic/headless delete command. **Wi-Fi wake**
was separately physically confirmed after one dedicated wake-key dispatch.
USB JPEG import/count acceptance used a private outside-DCIM staging pilot; the
checked-in CLI's in-DCIM temporary paths can trigger unsupported-file warnings.
See [import acceptance and the known staging limitation](IMPORT_ACCEPTANCE.md).
No photo contents were previewed or analyzed during the batch. Sleep, slideshow
gestures and reboot/persistence remain unaccepted. Frameo's schedule may override
Android display state.

## Launcher

```bash
cd projects/operation-jarvis/picture-frame
./frame capabilities     # local supported/unsupported inventory
./frame --help
./frame status           # fresh hardware/package pins; no photo bytes
./frame backlight        # actual backlight + window override; missing/ambiguous = unknown
./frame pending          # local only
```

`./frame` executes the entire CLI under the already approved Python 3.13 runtime
used by JARVIS. It adds no permission proxy or automatic `--apply`. It never changes
that shared environment. `JARVIS_FRAME_PYTHON=/absolute/approved/python` is an explicit
runtime override, not permission registration. If the runtime is unavailable it
fails rather than falling back to the denied interpreter.

All applying commands default to **no-contact dry-run**, with no photo/key read or
runtime creation. Review each result and give explicit owner approval before
first-time display/transfer tests:

```bash
./frame screenshot                      # dry-run
./frame screenshot --apply              # private unique PNG, not shared
./frame sleep                           # dry-run
./frame wake                            # dry-run; neither is shutdown/reboot
./frame next --slideshow-ready           # dry-run
./frame previous --slideshow-ready       # dry-run
./frame brightness 180                  # stored Android setting, NOT visible dimming here
./frame upload /path/to/approved.png     # dry-run; no file read
# Applying upload remains experimental: review the staging limitation first.
# Do not use the current uploader for unattended bulk imports on this unit.
```

Sleep/wake use dedicated keycodes and verify Android screen state. Navigation
requires owner-confirmed visible slideshow, exact Frameo focus, valid screenshot
geometry, and guarded swipes. Brightness selects Android manual mode but Frameo
**overrides it on this unit**; a settings readback is not visible acceptance.
No menu-opening brightness automation was added.

Upload accepts bounded JPEG/PNG bytes into existing DCIM: private local staging,
content-hash `.part` destination, remote byte-count verification, no-clobber rename,
no overwrite, dedup journal and no claim of slideshow import. Source bytes/EXIF/GPS
are preserved: strip sensitive metadata/convert HEIC before selecting a source.
Unknown writes remain durably pending; no retry or cleanup/replay occurs.

**Known importer issue:** temporary `.part` files inside DCIM generated native
unsupported-file warnings on this unit. Only the private USB pilot has accepted
outside-DCIM staging; this is not implemented by the public CLI. Do not interpret
transfer success as native import, blindly resend files, delete raw sources, or
convert originals merely because temporary names appear in the unsupported list.
See [acceptance and cleanup boundaries](IMPORT_ACCEPTANCE.md).

## Deliberate transport lifecycle

The current private configuration already selects legacy LAN. **Do not repeat
this commissioning sequence** to fix a disconnect or uncertain operation:

```bash
# Only from the exact inspected USB pairing, with explicit owner approval:
./frame wifi-enable --port 5555 --apply
./frame connect-legacy-lan --serial PRIVATE_FRAME_IPV4:5555 \
  --accept-unauthenticated-lan --apply
```

Acceptance first rechecks the USB frame and its own Wi-Fi address, then compares
all pins/package over TCP before saving scoped consent. A new IP/package/build
requires USB review and fresh explicit acceptance; no discovery or auto-repinning.
The transport never reads/sends the Mac ADB key. If the frame begins requiring
RSA authentication, legacy mode fails and requires deliberate authenticated setup.

```bash
# Explicitly select the SAME device over its known USB transport:
./frame use-transport --serial EXACT_ORIGINAL_USB_SERIAL --apply
# Or retire the wireless listener and return to verified USB, revoking legacy consent:
./frame wifi-disable                     # dry-run
./frame wifi-disable --apply             # exact original USB required and checked
```

Retirement checks the disabled TCP setting, IPv4/IPv6 listener snapshots, persistence
property and fresh USB pins. Unexpected replies/readbacks keep pending state; only
known verification clears it. It does not stop/restart the Mac's existing ADB server.
USB selection alone does **not** disable the listener; use `wifi-disable` deliberately.

## Boundaries

No raw-shell CLI, root/flashing, app installs, photo deletion/hiding, guessed Frameo
database writes, arbitrary imported-image selection, captions, slideshow settings,
router changes, internet-facing port forwarding or automatic retry/reconnect loop.
No wireless reboot persistence is promised. Private identifiers, consent, diagnostics,
photos, keys and screenshots stay outside Git.
