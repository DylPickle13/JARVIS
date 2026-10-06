# Menu-free capabilities — received frame

Audit/owner-confirmed acceptance: **2026-10-05 (EDT)**; TCP, wake and import follow-up **2026-10-06 (EDT)**. See the [import acceptance and staging limitation](IMPORT_ACCEPTANCE.md).

Here, **menu-free** means no settings page needs to be opened for each operation.
It does not mean the intended effect is invisible: a new photo may appear, a
slideshow swipe changes the picture, and sleep/wake changes the screen state.

The received unit exposes a generic Allwinner **Digital Photo Frame** identity,
Android **6.0.1**, and the installed package `net.frameo.frame`. Exact serials,
build pins, configuration, captures and photo hashes remain private, outside Git.
These results apply to this unit/software state, not all Frameo products.

## Capability matrix

| Operation | Menu-free route | Evidence / limit |
|---|---|---|
| Add an approved PNG | ADB transfer into existing DCIM while Frameo computer-transfer mode is enabled | **Confirmed:** one approved PNG passed `.part` staging, byte-count readback and no-clobber rename; owner confirmed it appeared in the slideshow |
| Add an approved JPEG | Private guarded USB batch pilot with temporary files outside DCIM | **Owner-reported import/count acceptance:** completed original-byte transfers without photo inspection. This is not acceptance of the checked-in CLI's in-DCIM staging; see the [known limitation](IMPORT_ACCEPTANCE.md) |
| Read identity and screen state | Exact-target ADB properties and Android diagnostics | **Confirmed:** private pairing, repeated identity matches and awake/display-state reads |
| Read actual backlight state | `backlight` via scoped `dumpsys display` / `dumpsys power` | **Confirmed over USB and Wi-Fi:** effective output/window override distinguish actual output from stored Android brightness; missing/ambiguous values remain unknown |
| Capture the screen privately | Explicit `screenshot --apply` | **Confirmed:** valid 1280×800 PNG captures without navigating the UI; images remain owner-only and may contain private photos |
| Wake the screen | Dedicated Android WAKEUP key | **Physically confirmed over Wi-Fi:** one dispatch, Android screen-state readback and owner-visible wake; no screenshot needed. Frameo's schedule may override state |
| Sleep the screen | Dedicated Android SLEEP key | Implemented but **not physically tested**; not device shutdown |
| Next / previous picture | A scoped horizontal swipe while the actual slideshow is visible | Implemented but **not physically tested**. This is gesture automation, not a native photo-selection API; exact app focus and owner-confirmed slideshow readiness are required |
| Change visible brightness | Standard Android setting is overridden by Frameo | **Not a verified menu-free control.** Setting 180 and then 0 changed Android readback but not visible brightness. Frameo's own slider changed the reported active backlight from 203 to 75 and the owner confirmed dimming |
| Captions, slideshow interval/order, choose a particular imported image, hide/delete library photos | No reviewed native app interface identified | **Unavailable through this controller.** Do not edit private app databases or assume deleting a DCIM source removes an imported photo |
| Control over Wi-Fi | Separately scoped, owner-approved legacy in-process ADB | **Selected:** owner explicitly accepted no authentication. USB-disconnected pins/status/backlight/capture and PNG import are verified; one wake is physically accepted. Sleep/gestures/reboot/persistence remain unaccepted. Strict RSA mode still rejects this firmware |
| Remove one disposable test card | Guarded native UI pilot after owner selection | **Physically confirmed for that single card only.** Exact test-card matching and separate native selection/confirmation; not a reusable/headless deletion API |

Computer-transfer mode was explicitly enabled by the owner before the accepted
upload. Bulk JPEG work later exposed a [temporary-file/importer timing issue](IMPORT_ACCEPTANCE.md);
byte-transfer receipts and native photo-count evidence remain distinct. Its availability after reboot, firmware changes, or disabling/re-enabling
that mode has not been tested. A successful file transfer is not general proof of
slideshow import; the uploader deliberately still returns
`transferred_import_unverified` and keeps a deduplication journal.

## Why there is no deeper headless Frameo control yet

Read-only inspection covered the installed package's intent resolvers/providers,
registered runtime receiver actions, relevant Android services, local TCP listeners,
and standard/vendor backlight-node permissions. No usable Frameo settings-control
intent, content-provider API or local HTTP service was identified. The observed
runtime actions were platform events, not a brightness/photo-management protocol.
This is **not proof that no private/internal interface exists**.

The vendor backlight node was not writable by the normal ADB shell. No root,
permission changes, guessed broadcasts, Binder transactions, app installation,
private app-data inspection, photo-library scan or broad network scan was attempted.
The audit itself made no device-setting changes and did not run sleep/wake, swipes,
wireless enablement or reboot tests.

The reviewed community servers are ADB wrappers, not native Frameo APIs:

- [phito/frameo-api](https://github.com/phito/frameo-api/blob/master/frameo.go)
  writes the same Android brightness setting that this unit overrides, uses a power
  toggle and fixed-coordinate swipes, and adds an HTTP listener. Its brightness
  endpoint does not establish visible brightness control on this unit.
- [maju6406/frameo-control-api](https://github.com/maju6406/frameo-control-api)
  advertises shell, upload and wireless operations. Those claims do not establish
  correct import paths, authentication boundaries or persistence on this firmware;
  it was not installed or run. See the [design review](DESIGN.md).
- [Frameo+ photo management](https://support.frameo.com/hc/en-us/articles/22349062052754--Manage-Frame-Photos)
  documents vendor-app remote delete, hide/unhide and display-now features with a
  subscription and frame-owner permission. It is not a documented local API for
  this project, and no vendor account or subscription was configured by JARVIS.

## Wireless commissioning follow-up

The owner confirmed the frame will remain on the home Wi-Fi and approved wireless
commissioning. Its private IPv4 address was read from the pinned frame's own active
Wi-Fi interface and policy route; address/transport identifiers are not recorded in
Git. `wifi-enable --apply` was dispatched once and acknowledged. Subsequent USB
readback confirmed the ADB listener and authentication property enabled.

Initial stock-ADB/Python 3.14 connection attempts failed with `No route to host`
although bidirectional ICMP worked. Native Network.framework reported
`unsatisfied` / `local_network_denied` inside that Python process. An ordinary
Terminal comparison and targeted permission refresh did not resolve it. Ad-hoc
signing/unbound metadata were observed, but the exact GUI/effective-policy mismatch
was not established. No blanket exception, signing change, router/VPN change or
existing-service restart was made.

At the owner's request for another implementation, the already owner-approved
Python 3.13 runtime used by JARVIS was verified: its native path is **satisfied** and
the exact TCP port reachable. The stock ADB binary still failed, including one
isolated foreground pilot with USB/mDNS/emulator discovery disabled. Only that
newly created pilot was stopped; the existing ADB server/phone were not changed.
A new in-process Python transport avoids that separate executable without borrowing
permission, creating an app/service or changing the shared runtime.

**Authentication safety stop:** the TCP backend reached `CNXN` without signing an
RSA challenge and rejected the peer before identity/property commands or saving a
transport. A separate key-free protocol-header check confirmed `CNXN` was the first
peer response, not `AUTH`; it sent no remote commands and retained no peer payload.
The advertised `ro.adb.secure=1` is therefore not proof of real TCP authentication.
See the [implementation and acceptance limits](DIRECT_TCP.md).

At that initial safety stop, USB remained selected and no wireless content/control
was accepted. The owner then approved disabling wireless ADB:
one exact-target USB-mode command was dispatched at **00:37 EDT, 2026-10-06**.
The TCP setting was disabled, IPv4/IPv6 snapshots showed no listener, the LAN
connection was refused, and no persistent TCP port was configured. Fresh USB pins
and status passed; configuration stayed unchanged and pending state was cleared
only after verification. No other device/host server was changed and no reboot or
persistence test was attempted.

The owner subsequently explicitly requested re-enablement accepting the known risk.
A separate exact-endpoint/package/build legacy consent policy was added; strict RSA
mode was not relaxed. One re-enable dispatch was listener-verified. Legacy TCP pins,
status, backlight reads and private 1280×800 capture then passed. A shell printf
formatting incompatibility was corrected with an exit-status echo; no enablement
was replayed for that correction. No approved photo was resent during that
commissioning correction. Later USB-disconnected PNG import, single-card native
removal and Wi-Fi wake were separately owner-confirmed; USB JPEG import used a
private corrected staging pilot. See the [controls guide](CONTROLS.md) and
[import acceptance](IMPORT_ACCEPTANCE.md).
The listener is now active and remains accessible to other reachable LAN clients.

## Recommended scope

Prioritize approved photo delivery and explicit private readbacks. Wake now has
owner-confirmed physical acceptance; add sleep or slideshow navigation only after
separate owner-approved physical tests. Unknown
outcomes stop further writes and are never replayed automatically.

Brightness UI automation is **not being added**: the owner deprioritized it in
favour of menu-free controls. The one successful slider commissioning action used
fresh identity/focus/layout checks, the controller lock, an explicit apply flag and
a durable pre-dispatch pending marker. It is not a reusable brightness API.

The separate [availability-only jarvisd integration](../../jarvisd/docs/picture-frame-health.md)
is deployed through its existing worker. No frame control/photo API, Pi control
schema, native-app control, new frame daemon or media scheduler was added. Follow
the [commissioning checklist](ARRIVAL.md) for any further tests.
