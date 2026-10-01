# Workflow-based System health mapping

Reviewed 2026-09-30 EDT. **Implemented in build 236**, installed and independently
version/process verified on the owner's iPhone and Watch. Automation behavior is
unchanged. Build 234 remains the audited rollback.

Owner requirements:

- Health stays on System; no Home health card.
- Group by what works together, not device technology.
- **Computer** is the UI category: keyboard, mouse, display, LED strip and Mac
  speaker (desk PowerConf endpoint). Keep the existing presence job name unchanged.
- **Security** groups hub, door/motion sensors, doorbell, indoor camera and camera
  speaker. This replaces separate Departure/Room conversations categories in the UI.
- **Cast playback** remains TV and Nest Audio. The LED strip stays under Computer,
  even though its adapter is in the security integration.
- iPhone USB, Apple Watch, and Master Chief are excluded from this monitoring
  inventory. Removing USB monitoring does not remove BLE enrollment or alter
  existing presence automation.

The live registry now contains **26 background checks**; all 26 passed the warm
verification after removal of iPhone USB. This is scoped check coverage, not proof
that every dependency below has a functional health check.

## Verified workflow relationships

| Workflow | Actual dependencies | Existing device checks | Missing/limited evidence |
| --- | --- | --- | --- |
| **Computer presence** | Basement/living-room presence inputs, local watcher, keyboard, mouse, Mac display control, LED strip | `keyboard-watcher`, `keyboard`, `mouse`, `led-strip`; Pi SSH and Mac host checks are shared infrastructure only | USB is attachment, not lighting success. Watcher heartbeat does not prove presence freshness, display state or successful output. Preserve the existing controller fault/uncertainty gates. |
| **Departure greeting** | H200, door and motion snapshots from the shared reader, D235 person-event gate and doorbell speech transport | `hub`, `door-sensor`, `motion-sensor`, `sensor-reader`, `front-doorbell` | Doorbell TCP is not event freshness or audio delivery. Do not use indoor/Cast speakers as departure dependencies. |
| **Room conversations — camera** | Mac-hosted C230 audio transport, camera controller on 8791, shared wake/voice pipeline and Pi RPC | `indoor-camera`, `room-audio-pi` (legacy ID; actually the local camera controller) | An open port is not microphone capture, wake detection, transcription or speech delivery. This is not a Raspberry Pi audio service. |
| **Room conversations — desk** | Mac USB PowerConf, local controller on 8793, shared wake/voice pipeline and Pi RPC | `room-audio-mac` | PowerConf capture/output and shared wake are not dedicated device-health checks. Do not substitute webcam/headset USB for PowerConf evidence. |
| **Cast playback** | Family-room Cast TV and Nest Audio endpoints | `family-room-tv`, `family-room-speaker` | Separate transport from room conversations. TCP is not active playback or successful speech. |
| **Plug controls** | The four configured Kasa plugs and the existing serialized control adapter | `family-room-light`, `lamp`, `pedalboard`, `tv` | Manual control capability, not a verified shared scheduled automation. A plug being off is not failure. No LED strip membership. |
| **Air purifier controls** | Both VeSync devices, account/session and existing rate-limited collector | `bran-purifier`, `dylan-purifier` | Status-cache freshness only; do not add cloud retries or bypass cooldowns. |
| **Local model serving** | oMLX services on the two Macs | `mac-mini-64`, `mac-mini-16` | Checks concern the model-server cache, not comprehensive host health; hosts are shared by other workflows. |
| **Living-room presence** | Pi BLE collector/export, authenticated snapshot transport, existing private enrollment | `raspberrypi` is only the SSH-reachability portion | SSH alone does not establish fresh BLE evidence. Pi presence remains distinct from the retired Pi room-audio transport. |
| **Android dashboard** | Nexus USB/ADB connection and the dashboard application | `android-dashboard` | Current coverage is USB attachment only, not ADB readiness, rendering or backend connectivity. |

`webcam` and `headset` remain inventory checks without a verified workflow owner
in this review. Do not force them into Computer presence or room conversations
just because they are attached to the same Mac. Their ownership needs clarification
before choosing a UI placement. The headset remains optional.

## Sources and confidence

- Live `jarvis_cron list`: **Computer presence**, enabled, one-minute interval.
  Other enabled jobs were shopping and backup jobs, not additional household
  device-control groupings. Listing did not run or modify jobs.
- `keyboard/watch.py:step`: shares one age-adjusted presence snapshot across
  keyboard, mouse, display and LED controllers. `relay` reports alerts; it does
  not perform device controls. The older README label "Keyboard lights" is not
  the current scheduler name.
- `security/departure-greeting/README.md`: paired sensors, mandatory fresh D235
  person-event gate, doorbell speech; expressly no indoor speaker/arrival actions.
- `room-audio/README.md`, `MACOS.md`, `CAMERA.md`: two Mac-hosted endpoints,
  PowerConf and C230; Cast is separate. The older note that the Pi was offline is
  not a current presence-service assessment.
- `presence/README.md`, `PI.md`: independent basement/living-room proximity
  architecture, Pi snapshot transport and private enrollment.
- Existing private device registry: explicit aliases, adapter kinds and current
  scope. No additional network discovery, BLE scanning or physical writes used.

## Implemented System grouping

Use the owner's revised display groups, rather than exposing every workflow as
its own category:

| System category | Membership / monitor keys |
| --- | --- |
| **Computer** | Keyboard, mouse, display, LED strip, Mac speaker; `keyboard-watcher`, `keyboard`, `mouse`, `led-strip`, `room-audio-mac`. Display is part of the workflow but does not yet have a dedicated device check. |
| **Security** | Hub, door/motion sensors, doorbell, indoor camera and camera speaker; `hub`, `door-sensor`, `motion-sensor`, `sensor-reader`, `front-doorbell`, `indoor-camera`, `room-audio-pi`. The last is the legacy key for the Mac-hosted camera audio controller. |
| **Cast playback** | Family-room TV and Nest Audio; `family-room-tv`, `family-room-speaker`. |

The verified workflow table above describes implementation dependencies, not the
final UI categories. Category membership does not make the Mac speaker part of
the presence automation, or the camera speaker part of departure playback.
No job names, device routing, dependencies or physical behavior are changed.

Services, Pi and Network retain their existing groups. Remaining inventory checks
(including direct controls and the unassigned peripherals) remain under Devices;
none are dropped or arbitrarily assigned to Computer/Security. The layout remains
compact and noninteractive, with adaptive columns. Watch shortens Cast playback
to Cast visually; accessibility retains the full title. Home is unchanged.

A device may support multiple workflows. Shared dependencies should be references,
not duplicated monitor probes or incident keys. A workflow cannot be labelled fully
healthy solely because its currently monitored subset passes. Present check counts
with explicit missing/limited evidence and preserve stale/unknown states.

Verification: 264 package tests ran (3 live tests skipped, no failures), and 62 iOS
regression/layout tests passed. Watch-sized, narrow-phone, landscape, offline and
large-text layouts were exercised; rendered previews were reviewed. The signed
archive's four bundles, profiles, unchanged entitlements, dependency lock and
rollback payload were audited. The exact archive was installed on both devices.
Physical on-device appearance and gestures remain for owner acceptance.

Failures contribute to their group and overall current health; stale/missing
required evidence cannot make a group green. The LED strip is not counted under
Security merely because its adapter lives there. Excluded Watch/Master Chief/iPhone
USB entries are ignored even if returned by an older configured host. Older hosts
without device coverage retain aggregate categories rather than invented evidence.
The existing history band keeps its original recorded component scope; this UI
change does not backfill history or invent per-workflow history.
