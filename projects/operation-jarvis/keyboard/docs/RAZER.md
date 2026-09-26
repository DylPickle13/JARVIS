# Razer DeathAdder Essential 2021 — Karabiner bridge

Exact model: `1532:0098` (decimal `5426:152`). Single-colour hardware, not RGB.
No Razer app, OpenRazer driver, pip dependency, or extra resident service is used.
The existing custom Karabiner package is extended, not replaced with a different
mouse-control app.

## Status (2026-09-25)

- **Live:** wheel click (`button3`) and side buttons 4/5 suppressed by Karabiner.
  The active rule matches `mappings/razer-side-buttons-disabled.json`; keyboard
  mappings remain unchanged.
- **Implemented:** authenticated `--jarvis-razer` IPC, exact interface matching,
  async feature set/get using Karabiner's already-owned mouse handle, validated
  device replies, independent persistent uncertainty journal, Python CLI.
- **97 offline tests pass**, including native AddressSanitizer/UBSan tests for
  encoding, replies, lifetime/disconnect handling, persist-before-send, cooldown,
  duplicate suppression and late-success-after-timeout handling.
- Native metadata-only inspection confirms the selector matches mouse interface 0
  and rejects both other Razer interfaces and the AK820. No USB reports were sent.
- Complete package built. All **12 signed principals** verify under the same
  development team. An expanded-package audit matched **222 payload files** to
  staging, verified payload signatures, and matched installer scripts to source.
  The outer installer is unsigned; the verifier correctly blocks installation.
  Details: `karabiner/build/razer-build.log`, `manifest.json`,
  `razer-package-audit.json`, and `razer-deployment.json` (ignored).
- Razer-capable artifact: `karabiner/upstream/Karabiner-Elements-16.3.0.dmg`;
  SHA256 `4c0cbcad4ffa265127a7b909dd488abb87b6ba065bc5c36a239fbf3eca3e5995`.
- **Installed with the owner's explicit approval of this unsigned wrapper and
  normal macOS administrator authorization.** All 222 installed payload files
  match staging. App/CLI strict signatures pass after removing only inherited
  cosmetic `com.apple.FinderInfo`; no TCC or security-attribute changes were needed.
- **Initial live feature transfers verified:** brightness readback was 66% (raw
  168), DPI 1600/1600, polling 1000 Hz. Brightness was set to 30% and read back
  (raw 77), then restored to raw 168. Steady, off, and breathing each returned a
  validated success reply; the owner then visually confirmed breathing and normal
  clicking/scrolling. DPI and polling were not changed. The later presence policy
  below supersedes breathing for the mouse. Reconnect, sleep/wake and restart
  acceptance remain pending.
- **Owner's default mouse brightness: 20%.** Applied and device-acknowledged after
  the initial 66% test. A subsequent brightness readback confirmed 20%. Steady/off
  presence transitions preserve brightness. Persistence across power loss has not
  been verified. The current watcher has acknowledged steady mode with no pending
  write; there is no effect readback.
- **Current automation supersedes the breathing acceptance setting:** the owner
  requests mouse steady-on for fresh basement nearby, off for fresh away, never
  breathing. `mouse_cycle.py` runs inside the existing keyboard watcher with
  separate durable state and no new scheduler/service. Keyboard effects now use
  white, and keyboard breathing remains permitted. See [automation](AUTOMATION.md).
- Both bridges report available with no pending write. The keyboard watcher was
  gracefully paused for installation, then bootstrapped once; it resumed cycling
  with no faults. Live Karabiner configuration matches the pre-install backup.

The earlier direct-HID attempt could not open the interface once Karabiner grabbed
it. The new implementation sends through that same owned handle; no conflicting
open or temporary disabling of remapping is needed. CLI writes now use Karabiner
only and never fall back to direct HID. Legacy direct helpers in `razer.py` are
retained for offline tests, not exposed as a write backend.

## Controls

| Control | Supported values | Device query |
| --- | --- | --- |
| Logo lighting effect | off, steady, breathing | No effect query exposed |
| Logo lighting brightness | 0–100% | Yes, raw 0–255 and rounded percentage |
| Sensitivity | X/Y 100–6400 DPI | Yes |
| Polling rate | 125, 500, 1000 Hz | Yes |
| Buttons | Karabiner mappings; wheel click and side buttons currently disabled | EventViewer when authorized |

Lighting writes and brightness/DPI/polling queries have been acknowledged on this
unit. The owner visually confirmed breathing and normal clicking/scrolling.
DPI/polling writes and visual acceptance of the other effects remain untested. No separate scroll-wheel control, RGB colours,
effect speed, firmware update, arbitrary packets, macros stored in firmware, or
sensor calibration commands are exposed. Button mappings live on the Mac.

## CLI

From `/Users/dylanrapanan/JARVIS/projects/operation-jarvis/keyboard`:

```sh
.venv/bin/python razer.py discover               # local metadata only
.venv/bin/python razer.py bridge-status          # readiness, not hardware state
.venv/bin/python razer.py read brightness        # one device query
.venv/bin/python razer.py read dpi
.venv/bin/python razer.py read poll

.venv/bin/python razer.py effect breathing       # dry-run is the default
.venv/bin/python razer.py effect steady --apply
.venv/bin/python razer.py effect off --apply
.venv/bin/python razer.py brightness 50 --apply
.venv/bin/python razer.py dpi 800 --apply         # X and Y together
.venv/bin/python razer.py dpi 800 --y 1600 --apply
.venv/bin/python razer.py poll 500 --apply
```

Each invocation performs one operation. Effect commands do not implicitly set
brightness; brightness does not implicitly enable an effect. Reads return actual
validated device replies; bridge-status does not send any device command.

## Safety and architecture

```text
razer.py → razer_bridge.py → consistently signed karabiner_cli --jarvis-razer
  → existing authenticated socket + active-console peer UID check
  → independent Razer journal/worker
  → exact 1532:0098 interface-0 seized monitor
  → feature SET_REPORT → 50ms run-loop timer → feature GET_REPORT
  → validate response identity, size, CRC and success status
```

Settings only cross IPC, never raw reports, paths or shell commands. Size and type
validation occurs at both ends. No change to the input/remapping pipeline.
One outstanding exchange maximum; no blocking sleeps or disk access on the input
thread. Device/buffer lifetime extends through callbacks. A stop/disconnect marks
pending work uncertain; a missing callback retains one bounded context rather
than freeing kernel-owned buffers. Late callbacks cannot clear durable uncertainty.

Root-owned journal:
`/Library/Application Support/org.pqrs/Karabiner-Elements/jarvis-razer/`.
It is independent of the AK820 journal. Pending is durable BEFORE submission,
including setting-query requests. Confirmed success requires a valid mouse reply,
not merely successful USB submission. Busy replies are uncertain, not success.
No immediate retries, replay, or automatic acknowledgement. The authorized
presence watcher now uses this bridge for steady/off transitions only; it retries
only known pre-write failures on a later tick after a full-minute cooldown.
Minimum spacing is three seconds after success, sixty seconds after a rejected
attempt or acknowledgement. Unknown results block further exchanges.

Only after inspecting an uncertain outcome and explicitly deciding to accept it:

```sh
.venv/bin/python razer.py acknowledge-uncertain
```

This sends no device report and refuses if any exchange remains outstanding.
Lighting and DPI writes use the protocol's persistent selector; endurance and
persistence have not been tested. Avoid frequent writes. Polling changes are
explicit only; initial acceptance must not alter the user's DPI or polling rate.

## Build and installation

The maintained patch is `karabiner/patches/0003-razer-owned-handle-transport.patch`.
Razer headers/tests are in `karabiner/prototype/`. The builder reconstructs the
sequential patch series from the pinned upstream commit and refuses unknown local
source modifications before applying overlays. Existing keyboard regression tests
remain in the full suite.

Follow [DEPLOYMENT.md](DEPLOYMENT.md): build and consistently sign the COMPLETE
package, verify every principal, obtain approval for the installer wrapper, then
use normal macOS administrator authorization. Do not replace only Core Service,
bypass TCC, or reset permissions automatically.

Current signing limitation remains: Apple Development can sign app/CLI payloads,
not the outer installer. The verifier fails closed if the wrapper is unsigned;
a new installation requires the owner's explicit approval of that local wrapper.
The owner approved artifact `4c0cbcad…e5995`, which is now installed.

Prior custom keyboard-capable rollback artifact is preserved at
`karabiner/build/pre-razer/Karabiner-Elements-16.3.0.dmg`:
`0ab93e26cf44d1a0ae4c562d8113440429e6f9063d74efa3133eacb6bba3c1b6`.
Private live config/LaunchAgent/backend backups:
`~/Library/Application Support/JARVIS/keyboard-deploy/razer-20260925T201309/`.
The earlier official signed rollback is also retained.

### Acceptance after authorized installation

1. Pause the keyboard watcher gracefully for the package replacement; preserve all
   pending markers. Verify it has exited and no keyboard write is pending.
2. Install through normal OS approval with an alternate input method available.
3. Verify signed app/CLI identities, keyboard bridge, keyboard typing/knob, mouse
   movement/left-right clicks/scrolling, plus wheel-click and side-button suppression before hardware testing.
4. Razer bridge-status must show the exact device available and no pending write.
5. Query brightness, DPI, and polling separately, spaced at least three seconds.
   Stop on the first uncertain response; do not auto-acknowledge or retry.
6. Test steady/off/breathing and brightness with owner visual confirmation;
   preserve or restore requested lighting. Do not change DPI/polling without a
   chosen target. Readback does not prove visual output.
7. Resume the one existing keyboard watcher only after its bridge remains healthy.
8. Reconnect, sleep/wake and restart acceptance remain separate follow-up checks.

## References

Protocol researched from OpenRazer master on 2026-09-25:

- https://github.com/openrazer/openrazer/blob/master/driver/razermouse_driver.c
- https://github.com/openrazer/openrazer/blob/master/driver/razerchromacommon.c
- https://github.com/openrazer/openrazer/blob/master/driver/razercommon.c
- https://github.com/openrazer/openrazer/blob/master/driver/razercommon.h

Interface 0, feature report ID 0, 90 bytes (no synthetic ID prefix in native IOKit).
Lighting transaction `3f`; DPI/poll transaction `ff`. Logo LED `04`;
XOR bytes 2–87 at byte 88. Read-only query opcodes are allowlisted individually.

To undo wheel-click/side-button suppression, remove or disable the named rule in
Karabiner Complex Modifications. Disabling Modify events also prevents the owned-handle bridge
from selecting that interface. Never restore an old full config over newer edits.
