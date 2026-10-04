# Research and controller design

## Primary sources

- [Frameo: enable ADB](https://support.frameo.com/hc/en-us/articles/6126183308434--How-to-Enable-ADB-on-Your-Frame)
  — Settings → About → Beta Program → ADB Access; USB authorization. Frameo
  explicitly warns ADB use is at the user's risk and does not provide ADB support.
- [Frameo: transfer by computer](https://support.frameo.com/hc/en-us/articles/12109654353170--Transfer-via-USB-Cable)
  — enable Transfer from computer, use DCIM, wait for import; documented for Windows/Linux.
- [Frameo: supported media](https://support.frameo.com/hc/en-us/articles/12110057465106--Supported-Media)
  — consult the current guide when preparing photos; initial code intentionally
  limits itself to signature-checked JPEG/PNG, not an exhaustive media decoder.
- [Android platform-tools / ADB](https://developer.android.com/tools/adb)
  — exact-serial transport selection, authorization, shell and TCP/IP operation.
- [Community Frameo control API](https://github.com/maju6406/frameo-control-api)
  — examined as feasibility research, **not installed, vendored or run**.

The official ADB and transfer articles were verified through Frameo's public
Zendesk article API when the human-readable URLs returned HTTP 403:

- [ADB article JSON](https://support.frameo.com/api/v2/help_center/en-us/articles/6126183308434.json)
- [Transfer article JSON](https://support.frameo.com/api/v2/help_center/en-us/articles/12109654353170.json)

## Why a small local controller instead of deploying that API

The examined community implementation exposes broad shell/file operations through
an HTTP listener on all interfaces, with no app-level authentication in its entry
point. Its upload path defaults to `/sdcard/Frameo` and broadcasts a media scan;
that does not establish Frameo slideshow ingestion. Its documentation overstates
wireless persistence for firmware we have not seen.

Our independent standard-library implementation avoids HTTP entirely and uses the
already-installed host `adb`. No dependency install, service or code from the
community project is needed. A future authenticated backend/tool must delegate to
the same pinned, locked, pending-aware controller, not invent another write path.
Do not expose arbitrary shell or direct ADB transport parameters to an app/API.

## Flow

```text
Owner-authorized command
    → validate bounded command/input
    → no --apply? return plan without ADB/device/file contact
    → acquire nonblocking private process lock
    → pending earlier write? block new writes
    → fresh exact-target identity/package check
    → validate operation preconditions
    → fsync durable pending marker
    → dispatch bounded ADB operation once
    → readback where supported / label unverifiable results honestly
    → persist upload deduplication journal where needed
    → clear pending only after known dispatch/readback result
```

Probe/pair are explicit: hardware serial (`ro.serialno`, fallback `ro.boot.serialno`),
manufacturer, model and build fingerprint must be nonempty. Package candidates
must include an exact `frameo` namespace component; unusual vendor builds fail
closed for review. All subsequent target operations use `-s` and recheck those pins.
Switching transport preserves the pins. Build updates deliberately require review.
This is not tamper-proof identity: Android properties can be spoofed and legacy
network ADB security depends on the device. Keep debugging local and supervised.

Brightness changes Android's manual mode and 0–255 setting, then reads both back.
It does not guess panel PWM limits. Sleep/wake use dedicated SLEEP/WAKEUP keycodes,
not the state-toggling POWER key. Unknown power output remains unknown.

Navigation requires explicit visible-slideshow confirmation and exact Frameo focus.
A transient screenshot supplies real rotated dimensions; those bytes stay in memory.
The horizontal swipe remains experimental and is not a verified next-photo API.
Screenshots requested by the owner are saved separately, owner-only, with unique
filenames; no automatic screen/photo recording or sharing occurs.

Uploads copy approved source bytes into temporary private staging, enforce a 50 MiB
limit, verify the JPEG/PNG signature, and use a SHA-256-based destination filename.
The existing `/sdcard/DCIM` directory must be present and both final/staging names
absent. Bytes are first pushed to a `.part` name, byte-count checked, then renamed
with no-clobber `mv -n`, so a half-transferred JPEG/PNG is not offered for import.
The staging name must disappear after rename. No overwrite or media-scanner/
guessed-database mutation occurs. Firmware must support this staging/rename flow;
unknown size/rename results leave pending state, not a repeated transfer.
Transfer success is not import success; `--import-ready` is an owner's assertion,
not an inferred setting.
A content-hash journal blocks repeat transfers after known ADB success, including
when Frameo has already consumed the DCIM file. No originals are edited or deleted.

No readback/retry loops are used. If a device takes time to settle, a one-shot check
may leave pending state even though the action later succeeds. That is intentional:
inspect the frame rather than send the action again. Interrupted/failed staging
before dispatch changes no device; interrupted/failed dispatch leaves a durable
marker. A crash may leave private host staging or a `.part` file on the frame;
inspect those during deliberate cleanup, never auto-replay them. Remote cleanup
is manual/owner-approved through the frame's UI; the CLI has no deletion command.

## Verification limits

Offline tests use synthetic image headers and a fake ADB transport. They cover dry
runs, exact selection/quoting, private permissions, identity/package mismatch,
concurrency, partial failures, durable pending state, explicit acknowledgement,
readback differences, screenshot dimensions/privacy, upload deduplication and
unsupported/oversized files. They do **not** prove hardware compatibility, authentic
Frameo identity, full PNG/JPEG decoding, app/UI behavior, import or reboot persistence.

Preparation deliberately does not touch the existing Android monitor/dashboard,
household devices, tool schemas, native app, running backend or scheduler.
