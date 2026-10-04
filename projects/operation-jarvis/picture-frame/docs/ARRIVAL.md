# Arrival and commissioning checklist

No frame has been connected or controlled during preparation. All live checks below
are deferred until arrival and explicit owner approval. Do not test another Android
phone/dashboard as a substitute.

## 1. Inspect before changing settings

- [ ] Record actual brand/model, firmware/Frameo version and USB connector type.
- [ ] Confirm the frame powers up normally with its included adapter.
- [ ] Obtain the correct **data-capable** USB cable; charging-only cables will not work.
- [ ] Set up Wi-Fi/time normally. Do not change any household router settings.
- [ ] Look at Settings → About and confirm whether Beta Program / ADB Access exist.

Frameo's [official ADB instructions](https://support.frameo.com/hc/en-us/articles/6126183308434--How-to-Enable-ADB-on-Your-Frame)
say to enable **Beta Program**, then **ADB Access** in Settings → About. This is an
explicit device opt-in and may affect firmware eligibility; review the on-screen
explanation with the owner first. ADB is privileged access and Frameo warns it is
at your own risk. If unavailable, stop: do not root, flash or bypass the firmware.
Keep the frame usable via its normal Frameo app / supported SD-card import instead.

## 2. Authorize USB and inspect exact identity

Connect only the intended frame to the Mac with its data cable. Keep its normal
power supply attached if required. Approve the computer's USB-debugging prompt on
**that frame**; never treat another device's authorization as permission.

```bash
cd projects/operation-jarvis/picture-frame
python3 -B frame_cli.py doctor
python3 -B frame_cli.py devices
python3 -B frame_cli.py probe --serial FRAME_SERIAL_FROM_DEVICES
```

- [ ] Output is online/authorized and belongs to the physical frame, not the phone.
- [ ] Hardware serial, manufacturer, model and build match the inspected frame.
- [ ] Choose the **actual** Frameo package from `frameo_packages`; do not assume the example.
- [ ] If identity properties are empty/unknown or no Frameo namespace is found, stop
  and inspect compatibility rather than selecting the first Android device.

Only after reviewing:

```bash
python3 -B frame_cli.py pair --serial FRAME_SERIAL_FROM_DEVICES --package EXACT_FRAMEO_PACKAGE --apply
python3 -B frame_cli.py status
```

This creates private host configuration, not an app account and not a write on the
frame. Re-pairing is deliberately not automatic. For a verified firmware update,
review a new probe and archive the old private config locally before new pairing;
retain upload history and inspect/resolve pending state first. Do not repin an
unexpected/different device merely because it now occupies the same LAN address.

## 3. Minimal acceptance — one action at a time

Ask before applying each first-time test; do not run a scripted sleep/wake loop.

- [ ] Capture `screenshot --apply` privately; confirm dimensions and Frameo UI.
- [ ] Record current brightness/mode. Test a moderate `brightness 180 --apply`.
  This selects **manual** brightness; restoring a number does not restore auto mode.
  Restore the owner's preferred mode/setting on the frame afterwards if desired.
- [ ] Owner-approved `sleep --apply`, then a separate `wake --apply` when requested.
  Neither means full device shutdown. Frameo's own schedule may override Android state.
- [ ] With slideshow visible, try `next --slideshow-ready --apply` once. Visually
  verify direction/photo change; UI acceptance is not inferred from ADB success.
- [ ] If any result is uncertain, stop. Run `pending` locally and inspect the frame.
  `resolve-pending --apply` only acknowledges the inspection; it never replays.

## 4. One non-sensitive sample photo

Frameo's [computer-transfer guide](https://support.frameo.com/hc/en-us/articles/12109654353170--Transfer-via-USB-Cable)
says Settings → Manage photos → Transfer from computer → Enable transfer from
computer, then copy into **DCIM**. The documented route is Windows/Linux; this
Mac/ADB experiment must prove itself on the real firmware.

- [ ] Owner explicitly enables Transfer from computer on the frame, if available.
- [ ] Choose one approved JPEG/PNG, preferably resized near 1280×800 (or portrait
  equivalent), with sensitive EXIF/GPS removed. No private family-library bulk run.
- [ ] Preview dry-run, then perform a single authorized transfer:

```bash
python3 -B frame_cli.py upload /path/to/sample.jpg
python3 -B frame_cli.py upload /path/to/sample.jpg --import-ready --apply
```

- [ ] Wait for import and **physically confirm** the photo appears in the slideshow /
  photo count. Keep USB connected until import is finished.
- [ ] Record whether Frameo consumes/moves the DCIM file and how long import takes.
- [ ] Confirm `.part` staging, byte-count check and no-clobber rename are supported
  by this firmware. A leftover staging file is an uncertain outcome, not an invitation
  to resend. Inspect unsupported files/cleanup manually with the owner's approval.
- [ ] On failure, stop; do not write private app databases or guess `/sdcard/Frameo`.
- [ ] Inspect Settings → Manage photos → Show unsupported files if appropriate.

The local journal avoids resending identical bytes after a confirmed ADB transfer,
regardless of source filename. It does not prove import and cannot resolve a lost
transfer response. A pending/unknown upload may already have imported; inspection
comes before any new attempt.

## 5. Optional LAN ADB — supervised, not required

Only on a trusted private LAN and after USB acceptance. Opening wireless ADB exposes
privileged debugging access; authentication/firmware behavior varies. No port
forwarding, public host, guest-Wi-Fi workaround, automatic discovery or reconnect loop.

```bash
# Verified USB pairing is still selected:
python3 -B frame_cli.py wifi-enable --port 5555       # dry-run
python3 -B frame_cli.py wifi-enable --port 5555 --apply
# Read the frame's own Wi-Fi IP. Connect ONLY that explicit private address:
adb connect FRAME_PRIVATE_IPV4:5555
python3 -B frame_cli.py use-transport --serial FRAME_PRIVATE_IPV4:5555 --apply
python3 -B frame_cli.py status
```

`use-transport` rechecks every identity pin before selecting the new route; it does
not auto-connect. An address is a routing hint, not trusted device identity.
If `wifi-enable` times out, do not repeat it: inspect the listener/frame and pending
state first. It restarts ADB, so the USB connection may change.

- [ ] Compare on-device identity before accepting the LAN transport.
- [ ] After an owner-approved reboot, check whether wireless ADB survives.
  Do **not** promise persistence; many Android builds revert to USB debugging.
- [ ] If it needs repeated USB setup, prefer reliable USB operation for now.
- [ ] When retiring/debugging is no longer desired, disable ADB Access on the frame
  and verify the listener is inaccessible. Do not rely on a reboot alone.

Remote control at another home requires a separately approved secure network design,
not publishing TCP 5555. Nothing in this project is an internet photo-sharing service.

## Acceptance record (fill in after arrival)

| Item | Current result |
|---|---|
| Ordered listing | Amazon.ca `B088NHSVJN`, 10.1-inch Frameo / BIGASUO listing |
| Actual hardware / Frameo firmware | Not inspected |
| ADB menu / USB authorization | Not tested |
| Identity / installed package | Not paired |
| Android display / brightness effects | Not tested |
| Slideshow navigation | Not tested |
| JPEG/PNG import into slideshow | Not tested |
| Wireless ADB / reboot persistence | Not tested |
| Existing household devices/services | Not changed by this project |
