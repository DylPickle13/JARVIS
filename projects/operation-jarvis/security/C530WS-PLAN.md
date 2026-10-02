# C530WS arrival and integration plan

Status: proposed; documentation only. No camera commissioned, device settings
changed, service restarted, or integration implemented by this plan.

## Objective and scope

Add an adapter-powered outdoor Tapo C530WS to the security project, targeting a
hardware revision confirmed compatible with H200. Proposed private alias:
`backyard-camera` (not an installed-device assertion).

Two independent milestones:
1. **Operational camera:** Tapo app access, verified H200 association where
   supported, and continuous recording/playback that does not depend on JARVIS.
2. **JARVIS integration:** authenticated on-demand status/capabilities, followed
   by explicitly requested, bounded private live video and snapshots.

Always powered, continuously recording, continuously streaming, and continuously
monitored are different properties. This plan targets the first two; JARVIS video
is on demand. It does not introduce a surveillance daemon, automatic speech,
alarm rules, cloud uploads, or a camera feed on the existing Android display.

## Confirmed project boundaries

- `security/security_cli.py`: registry accepts known models via `WRITES`; C530WS
  is absent. Discovery and authenticated model checks already exist. C230 write,
  privacy and movement semantics must not be inherited just because this is
  another pan/tilt camera. Dependency is pinned to `python-kasa==0.10.2`.
- `security/security_video.py`: explicitly D235-only; uses private doorbell
  bridges, doorbell identity checks and hub/device locks. Not a generic RTSP path.
- `security/security_audio.py`: C230/D235-only, separately commissioned. No C530WS
  talkback support should be claimed or enabled by this work.
- `security/security_recording.py` and `security/security_events.py`: existing
  doorbell functionality is not evidence of C530WS compatibility. Legacy archive
  and continuous-recording scripts have C230-specific assumptions.
- `.pi/extensions/lib/operation-jarvis-security.ts`: model/result/feature
  projections are allowlisted and currently exclude C530WS.
- `jarvisd/jarvisd_core/security_status.py`: model allowlist excludes C530WS;
  camera status projection will need deliberate design, not just an extra model.
- The deployed paired sensor reader serves the departure watcher/dashboard.
  Preserve its freshness semantics and do not add competing hub polling. See
  [shared reader](../jarvisd/docs/shared-security-reader.md).
- Security inventory, credentials, media and household commissioning records stay
  private. Public docs/tests must contain only sanitized or synthetic examples.

## Phase 0 — Before arrival: prepare offline

- [ ] Prepare the read-only C530WS implementation and synthetic tests described
      below, without adding a fictitious device to the live private registry.
- [ ] Review mounting location, useful field of view, power route and network
      coverage. Ethernet is networking, **not PoE**; retain the specified adapter.
- [ ] Plan weather-protected power/connections, suitable outdoor/GFCI protection,
      cable strain relief and drip loops. Do not assume the adapter is IP66 just
      because the camera is. Follow the supplied installation instructions.
- [ ] Check the exact regional camera/adapter operating-temperature limits against
      the installation conditions. Outdoor/weatherproof does not promise operation
      through every winter temperature.
- [ ] Check H200 supported camera count and storage headroom against the actual
      private inventory, without altering or formatting existing storage.
- [ ] Decide desired retention and whether to obtain a supported high-endurance
      camera microSD card. H200 storage is the preferred integration target, but
      its actual recording modes and simultaneous camera-card behavior must be
      verified before choosing the final storage arrangement.

No new production service or dependency upgrade is required for planning/offline
work. If the pinned SDK cannot support the camera, evaluate a narrowly scoped
adapter or dependency change in an isolated test environment first.

## Phase 1 — Arrival gate: inspect and bench-test

Before permanent mounting:

- [ ] Inspect box/device label and Tapo Device Info: exact model, regional variant,
      hardware revision and firmware. Keep serials/MACs/addresses and photos private.
- [ ] Recheck the current regional H200 compatibility guidance. TP-Link's current
      chart lists **C530WS V2**. An unlisted revision is unconfirmed, not proof of
      incompatibility. A label such as V2.6/V2.8 needs its regional mapping checked;
      do not reject or approve it from the literal string alone.
- [ ] With owner approval, onboard through Tapo and apply supported firmware updates
      as needed. A hub update is a separate maintenance step because it can interrupt
      existing recording and sensor services. No region-crossing firmware or reset
      of existing devices.
- [ ] Verify Tapo live video, manual pan/tilt, home position, night modes and privacy
      controls on the bench. Leave automatic siren/spotlight alarms and patrol off
      initially; test audible/light actions only with explicit approval.
- [ ] Associate the camera with H200 and verify the association in the app, not just
      that both devices appear in the same account. If unavailable, stop the hub
      portion and choose seller exchange/support or an owner-approved standalone
      setup; do not silently redefine H200 compatibility as standalone operation.
- [ ] Reserve a stable LAN address. Create separate Camera Account credentials for
      local streaming if required; keep credentials in private owner-only storage.
      Do not expose ports to the internet or place credential-bearing URLs in chat,
      logs, command arguments or public configuration.

**Gate:** hardware identity and the supported storage/network arrangement are
known. App-level success is distinct from SDK/JARVIS support.

## Phase 2 — Make recording useful and independent

- [ ] Select the supported recording destination and explicitly enable the intended
      continuous schedule in Tapo. Formatting any card needs separate approval;
      do not repurpose/format the existing H200 card as an installation shortcut.
- [ ] Verify continuous footage at a time with **no motion**, not just event clips.
      Confirm actual resolution, timestamps/timezone, overwrite behavior and playback.
- [ ] If H200 cannot provide the intended mode, evaluate camera microSD continuous
      recording as the independent baseline and document any H200 feature limits.
      Do not promise simultaneous hub/card/RTSP/Tapo Care use without testing.
- [ ] Measure actual storage consumption and estimate retention from the configured
      bitrate and all cameras sharing the destination. Marketing retention figures
      are not an acceptance measurement.
- [ ] Mount only after bench success. Set a useful home view, privacy masks and
      activity zones that minimize neighboring/private areas. Check masks during
      pan/tilt/tracking; a movable camera does not watch every direction at once.
- [ ] Start with person-focused app notifications; tune foliage, pets and lighting
      false positives. App notifications remain independent of JARVIS.
- [ ] Verify daytime and nighttime walk-throughs, useful detail, tracking return to
      the home view if supported, and playback of those tests.

**Gate:** continuous recording/playback works without a JARVIS viewer or process.
Use an approved 24-hour soak to look for unexplained gaps, excessive false alerts
and storage pressure. Clearly record untested outage/weather conditions.

## Phase 3 — JARVIS read-only integration

Implementation targets:

1. **Registry and identity — `security/security_cli.py`**
   - Admit C530WS as a direct camera with a private LAN host. Keep the initial
     write/action sets empty and reject C530WS mutation commands before networking.
   - Preserve discovery plus authenticated identity checks; capture sanitized
     hardware/firmware information locally. If discovery needs a model variant,
     permit only a verified mapping, not a generic `C*` wildcard.
   - Use a per-camera lock for direct reads. Only future operations that actually
     use H200 should acquire its lock, following existing lock ordering.
   - Read bounded, allowlisted capabilities. Missing/error fields remain unknown.
     Do not infer recording health from reachability, LED state or privacy state.
   - Keep any verified H200 child binding separate from direct-camera identity;
     never select the first camera or the first child of a given model.

2. **Pi projection**
   - Extend `.pi/extensions/lib/operation-jarvis-security.ts` model handling and
     `.pi/tests/operation-jarvis-security.test.mjs` coverage.
   - Keep `devices`, `status` and `capabilities` read-only for the new model;
     preserve redaction of addresses, IDs, raw responses and credentials.
   - No camera movement, media or settings are added to the existing tool schema
     as a side effect. Update tool docs only for genuinely supported behavior.

3. **Backend and display, after direct CLI acceptance**
   - Extend `jarvisd/jarvisd_core/security_status.py` and its tests with a bounded
     camera projection for actually available fields, such as privacy/detection
     settings. Do not label a successful status read as `recording` or `secure`.
   - Add an on-demand camera entry to the appropriate UI/configuration if desired;
     validate downstream model decoders before enabling it. Preserve timestamps,
     unavailable/unknown states and `securityAssessment: not_assessed`.
   - No additional camera/hub polling by default. Existing shared sensor aliases,
     freshness deadlines and departure behavior remain unchanged.

**Gate:** identity-verified status works through CLI and Pi; backend support is
separately tested and deployed only when authorized. Device registration alone
must not be reported as successful integration.

## Phase 4 — Private on-demand video and snapshots

Prefer the camera's documented direct RTSP support after verifying it on the
arriving hardware/firmware. Confirm ONVIF capabilities separately if needed;
ONVIF support does not imply every PTZ or audio operation is supported.

- Add a dedicated C530WS transport module (proposed
  `security/security_camera_video.py`) and dispatch to it from the video CLI.
  Reuse bounded-process/private-file helpers where practical; do not route this
  camera through D235-specific bridges or weaken the D235 guards.
- Preserve explicit media confirmation, direct-camera identity preflight,
  1–120-second viewer limits, cancellation cleanup and private output permissions.
- Camera Account credentials must not reach FFmpeg/ffplay argv, errors or logs.
  If a loopback relay is needed, bind to loopback only and keep its config private,
  lifetime bounded and cleanup tested. No persistent relay is assumed.
- Verify actual main/substream codecs, dimensions and decoded frames. Keep preview
  and full-resolution choices explicit; a connected socket is not video acceptance.
- Exclude audio initially. Snapshot files remain local/ignored and are never
  automatically attached to chat or retained indefinitely.
- Test concurrent Tapo viewing, H200 recording and local viewing within the actual
  device session limits. A refused extra viewer must not stop recording or trigger
  unbounded reconnect attempts.

**Gate:** a short decode-only test, an owner-approved view and a private snapshot
all succeed; closing/cancelling leaves no orphan process/listener. Recording
continues during and after viewing. Existing doorbell video remains unchanged.

## Phase 5 — Optional follow-ups, not arrival requirements

- Capability-specific CLI privacy, PTZ/presets and detection settings, each with
  explicit confirmation, bounded values, readback and physical acceptance.
- C530WS archive listing/clip download and recording-plan management using a
  separately verified adapter; never reuse C230/D235 assumptions or scripts.
- Bounded event-history reads before considering a notification worker. Live
  delivery, event type mapping, timestamps, deduplication and cooldowns need tests.
- Camera talkback/JARVIS speech only after transport/audio-quality commissioning;
  no automatic outdoor announcements or alarm/protocol changes in the base work.
- Optional Android/native-app viewing is a separate scoped change; do not replace
  the commissioned doorbell display or its audio/presence behavior by default.

Unknown write outcomes stop for inspection, never automatic replay or rollback.

## Test and rollout checklist

### Offline tests before hardware access

- Registry accepts supported C530WS entries; rejects malformed/unknown entries.
- Wrong discovery/authenticated identity, missing capabilities, auth failure,
  timeouts and device-busy results fail conservatively without leaking secrets.
- Every initial C530WS write/PTZ/audio/archive command is rejected without I/O.
- Projection tests cover C530WS, unavailable fields and private nested payloads.
- Media tests cover missing confirmation, wrong model, bounds, credential
  redaction, permissions, symlinks, empty frames, timeout and process cleanup.
- Regression coverage: CLI/read recovery, D235 video/audio/recording/events,
  Pi security tests, backend security status/snapshot tests. Run broader project
  suites as appropriate and report unrelated baseline failures rather than
  weakening gates. No hardware probes from test discovery or CI.

### Live acceptance, explicitly authorized

- [ ] Hardware/firmware and H200 association confirmed; no duplicate child mapping.
- [ ] Full-resolution image verified from a decoded frame, not the listing title.
- [ ] Non-event footage, night footage and 24-hour timeline reviewed.
- [ ] Brief camera power/network interruption and recovery tested when approved;
      record unavoidable outage gaps and ensure recording resumes without JARVIS.
- [ ] CLI/Pi reads and optional backend status return truthful availability.
- [ ] Local viewing does not disrupt recording, doorbell playback or shared sensors.
- [ ] Privacy masks/home view physically accepted; secrets/media remain private.

### Deployment and rollback

Keep source-only work separate from activation. Adding a private registry entry,
reloading Pi extensions, updating the frozen backend and enabling UI/polling are
separate steps, not implicit consequences of merging code. Inspect the currently
installed release and preserve unrelated changes before any approved deployment;
restart only necessary services. Do not change room audio, departure services,
Android monitor or existing automations to commission this camera.

Rollback disables/removes only the new JARVIS integration and restores reviewed
code/configuration. Leave working Tapo recording intact. Never restore stale
runtime state, erase media, factory-reset hardware or downgrade firmware as an
automatic software rollback.

Record actual identity, firmware, private network mapping, app settings, storage
measurements and physical acceptance under ignored
`security/private-notes/commissioning/`; public docs should record only sanitized
capability/test outcomes. Review every new security source/test file before adding
an exception to its default-private `.gitignore`.

## First implementation slice

Build Phase 3's CLI + Pi read-only support with synthetic tests first. Defer live
registration and hardware acceptance until arrival. Recording setup is app-led;
C530WS media support follows independently. This delivers useful integration
without making reliable recording wait for custom video work.

## Vendor references

- [TP-Link Canada C530WS](https://www.tp-link.com/ca/home-networking/cloud-camera/tapo-c530ws/)
- [Current hub compatibility chart](https://www.tp-link.com/us/support/faq/4191/)
  (lists C530WS V2; confirm regional applicability and current firmware on arrival).
- [C530WS V2-family datasheet](https://static.tp-link.com/upload/product-overview/2024/202412/20241219/Tapo%20C530WS%202.0%262.6%262.8_Datasheet.pdf)

The previously shared `tapo.com/faq/686/` returned 404 during planning; use the
current chart rather than treating the stale link as proof of incompatibility.
