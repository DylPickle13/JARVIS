# Custom Karabiner deployment

## Current boundary

Source integration and 84 offline tests are complete. The full package was built;
12 staged app/CLI signatures verify under one development signing team. The OUTER
INSTALLER IS UNSIGNED because the available Apple Development identity cannot sign
installer packages. The owner explicitly approved this locally built wrapper, and
installation succeeded through native administrator authorization.

Actual payload verification: 12 signed principals, 222 files matched staging, scripts
matched reviewed source. Installed bundles inherited cosmetic FinderInfo attributes;
removing only `com.apple.FinderInfo` restored deep strict signature verification for
all nine top-level applications plus CLI. Quarantine, TCC and code signing protections
were not changed.

DEPLOYMENT COMPLETE; basic live acceptance confirmed by the owner. The outer wrapper
is unsigned, but the owner explicitly authorized this locally built wrapper and it was
installed through the native macOS installer with administrator authorization. After
targeted TCC resets for Core Service only, the owner re-approved Accessibility and
Input Monitoring normally. Bridge status is ready, the AK820 is available, and no write
is pending. Guarded backend activation succeeded; the watcher reports cycling without
faults. Owner confirmed lighting changes, typing, knob volume and Play/Pause. Reconnect,
sleep/wake and extended presence acceptance remain outstanding. Live
`global.check_for_updates` is false to protect the maintained custom build.

Artifact SHA256:
`0ab93e26cf44d1a0ae4c562d8113440429e6f9063d74efa3133eacb6bba3c1b6`.
Do not infer hardware success from build success.

## Build

Pinned revision and protocol reference: `karabiner/upstream.lock.json`.
Ignored checkout: `karabiner/upstream/`; generated output/logs: `karabiner/build/`.

```sh
cd /Users/dylanrapanan/JARVIS/projects/operation-jarvis/keyboard
# Use authorized identities from security find-identity; never export private keys.
export PQRS_ORG_CODE_SIGN_IDENTITY='<local signing identity>'
export PQRS_ORG_INSTALLER_CODE_SIGN_IDENTITY='<local installer/development identity>'
.venv/bin/python karabiner/build.py
```

The builder verifies the upstream revision, applies checked patches idempotently,
installs the reviewed bridge headers into the checkout, runs offline tests and builds
the COMPLETE package. It does not install or clean the launch-services database.
Patch 0002 fixes three upstream Swift initialization/cancellation errors under Xcode 27.

The prebuilt official virtual HID driver package is retained. All communicating
Karabiner applications/CLI must be consistently signed; never install only Core Service.
Development-signed packages are not equivalent to Developer-ID notarized releases.
Do not disable SIP, Gatekeeper, signature verification, or Input Monitoring checks.

## Before installation

1. Keep an alternate input method available. The signer change may temporarily stop
   remapping until permissions are re-approved.
2. Preserve the reviewed live Karabiner configuration and watcher plist. Backup created:
   `~/Library/Application Support/JARVIS/keyboard-deploy/20260925T044030Z/`.
3. Official rollback DMG: `karabiner/build/rollback/Karabiner-Elements-16.3.0.dmg`.
   SHA256: `19cce7bed3d48a722242ca683bd1bae406b6a87fed520728d1c91dee175b75e4`.
   Its package signature and Apple notarization were verified locally.
4. Verify every custom application/CLI signature and package identity. Retain a hash
   of the final artifact and the exact patch/header inputs used to build it.
5. Disable automatic update checks in Karabiner settings for this maintained custom
   build. Do not silently replace unrelated live configuration.

## Install and activate

- Install the complete custom package using the normal macOS installer. Administrator
  authentication must be entered locally by the owner, never supplied to the assistant.
- Reapprove background agents/daemons, Accessibility and Input Monitoring as required
  for the new signer. Upstream notes that a restart may be needed after a signer change.
  Never edit the TCC database or reset unrelated application permissions.
- Verify typing, knob Play/Pause and volume before enabling lighting automation.
- Run `./ajazz bridge-status`. It must return `status: ok`, `pending: false`,
  `device_available: true`, `lighting_readback: false`.
- Following this installation, the watcher was deliberately booted out. Run
  `.venv/bin/python activate_bridge.py --activate --bootstrap-watcher` after readiness
  checks. For an already-running watcher, omit `--bootstrap-watcher`.
  It holds the existing cycle
  lock, refuses local or daemon uncertainty, writes the backend selector atomically,
  and gracefully restarts the single existing watcher. It never clears a pending
  marker or sends an unconditional startup lighting command.
- Check `cycle.py --status` after fresh proximity and the normal cooldown. A successful
  write confirms transport only. Owner visual confirmation is still required.

## Acceptance checklist

- [x] Complete package installed and required permissions approved.
- [x] Normal typing/modifiers unaffected during lighting changes (owner confirmed).
- [x] Knob press is Play/Pause; rotation is volume (owner confirmed).
- [x] Lighting changes visible and confirmed by owner.
- [ ] Nearby effect rotation and away purple-ripples behavior.
- [ ] Unknown/stale presence leaves lighting unchanged.
- [ ] USB reconnect and sleep/wake preserve remapping and safety state.
- [ ] Service restart does not replay a pending request.
- [ ] An uncertain outcome requires explicit acknowledgment, not an automatic retry.
- [ ] Final module/path cleanup and removal of compatibility links after live acceptance.

## Safety journal

The daemon uses `/Library/Application Support/org.pqrs/Karabiner-Elements/jarvis-ak820/`
(0700, daemon-owned), with a validated 0600 atomic journal. Persist-before-send is
mandatory; failed storage prevents sending. Success/rejection is recorded; uncertainty
survives restarts. A timeout does not cancel or prove failure of a hardware report.

One worker and one report per selected device may be in flight. No queued catch-up,
raw report API, input-event exposure, or automatic replays. Server request freshness is
two seconds; worker response wait is two seconds. Output callback timeout is 500 ms
per the SDK and Apple's IOHIDDevice millisecond-to-microsecond conversion. Late
success after a worker timeout cannot clear the journal. Explicit acknowledgment
refuses while the device still has an outstanding report.

## Rollback

Stop the lighting watcher gracefully before rollback; preserve its uncertainty state.
Reinstall the verified official package, restore reviewed configuration if needed and
reapprove permissions for the official signer. Do not blindly restore a stale runtime
state snapshot or clear pending markers. Leave lighting paused: official Karabiner
still conflicts with direct lighting access when it grabs the combined interface.

The old `projects/operation-jarvis/ajazz-keyboard` path remains a compatibility symlink
for existing launch/scheduler references. The obsolete `projects/key-mappings` symlink
was removed after cutover; mappings live in `projects/operation-jarvis/keyboard/mappings/`.
