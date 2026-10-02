# Phone-local recording assessment

Inspection: 2026-09-07, mac-mini-16. OBS exited after guarded graceful quit; process absence verified. REAPER untouched. No phone apps installed, network debugging enabled, or recording started.

## Connected devices

| Role | Hardware | OS | Free storage snapshot | Battery snapshot | Wi-Fi snapshot |
|---|---|---|---|---|---|
| Dyl Cam | Samsung S21 FE SM-G990W | Android 16 / API 36 | ~33G (df) | 43%, 32.2 C | 192.168.21.12/24 |
| Overhead | Samsung S21 FE SM-G990W | Android 16 / API 36 | ~12G (df) | 28%, 35.5 C | 192.168.21.229/24 |
| Wide Angle | LG G6 LG-H873 | Android 9 / API 28 | ~13G (df) | 100%, 33.1 C | Disabled; no LAN address |
| Bass Pedals | iPhone 11 / iPhone12,1 | iOS 26.6.1 | Unverified | Unverified | Unverified |

Android USB ADB access is authorized and functioning on all three phones. No Open Camera or Blackmagic package found on these Androids. Wireless-debugging toggle is off on both Samsungs; no legacy ADB TCP port configured on any Android. LG reports no mounted public external-storage volume.

iPhone product/OS read using usbmuxd/lockdownd GetValue, without accessing pairing secrets or changing trust. Battery/storage domains returned GetProhibited; do not treat as zero or infer unavailable storage. iPhone installed apps and Wi-Fi connectivity remain unverified.

mac-mini-16: macOS 26.6.2, current LAN address 192.168.21.30/24 on en1. Existing ADB executable: /Users/dylanrapanan/Library/Application Support/obs-studio/plugins/droidcamobs.plugin/Contents/Resources/adb. Avoid uninstalling DroidCam before provision of independent ADB, because current binary resides in its plugin bundle.

## Proposed design (not implemented)

- Local camera recording on phones, small control commands over LAN, deferred verified file transfers; no continuous monitoring stream/cloud uploads during REAPER sessions.
- Android: Open Camera volume-up record toggle through ADB, with explicit state verification before/after any command. Requires installation and compatibility testing. Never blindly retry a toggle. LG wireless ADB normally requires initial USB activation; restrict legacy ADB to trusted LAN and disable when not needed. Prefer paired wireless debugging for newer Android if practical.
- iPhone: Blackmagic Camera local recording and remote API. Hardware/OS satisfy current App Store minimum, but app version, remote API auth/status/transfer behavior need testing. No assumption that API automatically supports downloading clips.
- First proof-of-concept on LG, then Samsungs, then iPhone. Test local 4K support, desired FPS, clip segmentation, thermal behavior, available storage, stop on lost controller connection, and REAPER audio. DroidCam resolution support does not establish native camera-app capability.
- Use phone-local storage; copy only finalized test/take files, verify transferred size/hash where possible and decode/probe, retain originals until verification and user-approved cleanup.
- Need LG connected to trusted Wi-Fi; iPhone storage/app/network inventory; app installations/permissions and consent before enabling remote services.

## Research references

- https://opencamera.sourceforge.io/help.html — volume-key start/stop, FPS limitations, clip-size limits.
- https://developer.android.com/tools/adb — wireless access and pull file transfers.
- https://www.blackmagicdesign.com/products/blackmagiccamera/techspecs — local storage, remote control, Android 13+; S21 family listed but FE variant not explicitly guaranteed; LG Android 9 excluded.
- https://apps.apple.com/ca/app/blackmagic-camera/id6449580241 — current listing requires iOS 17/A12 or later; Mac M1+/macOS14+.
- https://www.newsshooter.com/2026/07/21/blackmagic-camera-for-ios-3-4/ — iOS 3.4 REST control addition.

## OBS fallback

Left installed and closed, at corrected full-frame native 1080p/24. Four separate hardware-encoded files: main + Bass Pedals H.264, Overhead + Wide Angle ProRes Proxy. Latest 2-minute test finalized and four test clips deleted; no OBS skipped frames or DroidCam errors, but user possibly heard 1–2 clicks. Not proven reliably click-free. Backups/logs remain on mac-mini-16 under ~/Movies/OBS. Keep configuration until replacement is validated.
