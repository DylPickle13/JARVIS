# Received-unit photo import acceptance and staging limitation

Owner-reported acceptance on **2026-10-06 EDT**. This is commissioning evidence
for the received unit, not a general Frameo compatibility guarantee. Photos,
archive/member names, source locations, frame identifiers, hashes and per-file
receipts remain in owner-only runtime storage outside Git.

## Accepted operations

- **USB-disconnected wireless PNG import:** one owner-approved disposable card
  appeared in the slideshow. Its later removal was physically confirmed through
  a guarded, owner-assisted native single-photo UI pilot. The pilot did not
  establish a generic/headless deletion API and must not be replayed.
- **Wi-Fi wake:** one dedicated wake-key dispatch passed Android display readback
  and the owner confirmed the frame visibly woke. Sleep, next/previous gestures
  and reboot persistence remain unaccepted.
- **USB JPEG import through a private batch pilot:** opaque archive extraction,
  bounded JPEG transfer and original-byte preservation were used without image
  previews, pixel decoding, EXIF analysis or photo-content descriptions. All
  archive entries had exact-once byte-transfer receipts, with no duplicate sends,
  pending writes or remaining temporary files. The original archive was unchanged.
  A corrected single-photo transfer triggered an owner-reported new-photo notice;
  the later frame photo-count increase matched the remaining transfer count.

The owner reported a final photo total matching the archive's file count and no
new unsupported-file warnings during the corrected transfers. This is aggregate
owner evidence, **not an individual identity/content check of every imported
photo**; a frame total can include pre-existing photos. The owner subsequently
reported native unsupported-list cleanup was satisfactory and manually removed
one unwanted photo. During the JPEG batch no assistant deletion or conversion
was performed, and no post-deletion total was measured.

## Known limitation: `.part` files inside DCIM

The checked-in standalone `upload` implementation still pushes its temporary
`*.jpg.part` / `*.png.part` file **inside `/sdcard/DCIM`**, verifies its byte count,
then renames it without clobbering the final JPEG/PNG. This unit's active Frameo
importer noticed temporary paths and retained unsupported-file warnings for them.
A successful transfer/rename therefore does not establish native import success,
and absence of remaining `.part` files does not itself clear the native warning
list. Do not treat these warnings as proof that the original JPEGs need conversion.

**Do not use the current standalone CLI for unattended bulk imports on this unit.**
The public uploader's staging location has not been changed in this commit. Its
existing PNG acceptance does not prove safe importer timing for JPEG batches.

The private, USB-only correction staged each file **outside the documented DCIM
import directory**, verified that staging and DCIM shared the same filesystem,
checked the complete byte count, then published only the finished JPEG with a
no-clobber rename. It retained the canonical controller lock, exact USB/hardware/
build/package checks, original deduplication journal, dry-run/apply and readiness
gates, and durable pending markers before directory creation or file writes.
The normally selected LAN configuration and the existing host ADB server were
unchanged. Fourteen synthetic-byte offline tests passed before the single-photo
physical check; later transfers used that accepted path.

That correction is **a private commissioning pilot, not a new public CLI mode,
backend upload route or reusable media-management tool**. Generalizing it requires
a separate reviewed patch and transport-policy tests. Do not copy private runners
or receipts into Git, loosen TCP write fences, automatically resend earlier
transfers, erase journals, or blindly remove DCIM files to reconcile an import.

## Native unsupported-file cleanup

On this firmware the unsupported list is on **Settings → Manage photos → Transfer
from computer**, not directly on Manage photos. The owner reported only `.part`
names and a button labelled **Remove unsupported files**. File-stat-only checks
found no actual temporary upload files remaining. The owner used the native UI
and subsequently reported the cleanup was satisfactory; the assistant did not
press that button or delete media. This is not a guaranteed metadata-only action
on other firmware. Review its target scope and compare native photo counts before
and after any owner-requested cleanup; never substitute a blanket photo deletion.

See [controls](CONTROLS.md), [capability limits](CAPABILITIES.md), and the
[status-only backend](../../jarvisd/docs/picture-frame-health.md). Backend
availability never establishes a lit screen, healthy slideshow or photo import.
