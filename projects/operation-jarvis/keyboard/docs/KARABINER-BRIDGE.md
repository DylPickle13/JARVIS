# Karabiner lighting bridge — implementation status

## Implemented

- Unified project at `projects/operation-jarvis/keyboard/`; mapping rules, lighting,
  watcher, presets and tests are preserved. Old project paths are compatibility links.
- Pinned Karabiner v16.3.0: `9312593e1a3bf72b94c63c524ebabe2637442e8a`.
- Patched Karabiner monitor sends asynchronously through its existing seized AK820
  handle. It does not open another connection or change the key-remapping pipeline.
- Exact model/USB-interface checks plus RGB collection membership. Read-only native
  inspection confirmed interface 1 matches and interface 0 does not. The combined
  interface's PRIMARY usage is keyboard; checking only primary usage would be wrong.
- Existing signed local IPC extended with a narrow settings request. Same-Team-ID
  verification is retained; kernel-reported peer UID must match the active console user.
- Root-owned durable journal, persist-before-send, bounded worker/queue, short request
  freshness, cooldowns, explicit acknowledgment, no automatic retries or raw reports.
- Custom CLI and Python backend, watcher error classification, and coordinated daemon/
  local acknowledgment. Bridge backend is NOT selected automatically.
- Guarded post-install `activate_bridge.py`: readiness checks, original cycle lock,
  atomic backend switch, graceful single-watcher restart, no state reset/manual write.
- Reproducible prepare/build/verification scripts and source patches.
- Full-package Xcode 27 compatibility fixes for upstream Swift initialization and
  cancellation diagnostics, without changing intended UI behaviour.
- Official rollback installer downloaded and signature/notarization verified; live
  configuration and watcher plist backed up privately.

## Verification so far

84 offline tests pass. Coverage includes:

- All original lighting/presence/alert tests.
- 1,700 Python/C++ encoder comparisons.
- Asynchronous lifetime tests under AddressSanitizer/UndefinedBehaviorSanitizer.
- Durable persist-before-send, corrupt/symlink journal rejection, stale/malformed
  requests, overflow/type validation, cooldowns, duplicate suppression, uncertainty
  across reload, acknowledgment, and late-success-after-timeout behaviour.
- Python one-shot IPC failure classification and refusal to fall back to direct HID.
- Activation refusal for local/daemon pending state or unavailable devices; state
  preservation and status-only preflight.

The COMPLETE package build finished. All 12 staged app/CLI principals pass strict
signature verification under one development signing team. However, the outer
installer is UNSIGNED: `productsign` cannot use the available Apple Development
identity. `pkgutil --check-signature` confirms no package signature. The verifier
records this and exits nonzero. The owner subsequently authorized the locally built
unsigned wrapper, and the native macOS installer reported a successful upgrade.
The owner explicitly approved the unsigned outer wrapper; it was installed using native
administrator authorization. Targeted Accessibility/Input Monitoring TCC approvals for
Core Service were reset only after owner consent, then re-approved normally by the owner.
Bridge status reports ready with the keyboard available and no pending write. The guarded
cutover completed; the watcher reports cycling with no faults. The owner confirmed RGB,
typing, knob volume and Play/Pause working. Reconnect, sleep/wake and additional presence
acceptance are not yet recorded.

Artifact: `karabiner/upstream/Karabiner-Elements-16.3.0.dmg`.
SHA256: `0ab93e26cf44d1a0ae4c562d8113440429e6f9063d74efa3133eacb6bba3c1b6`.
Exact input hashes and signature results: `karabiner/build/manifest.json`.
The custom package is installed; strict signature checks pass after removing inherited
cosmetic FinderInfo attributes. Core Service is approved and running. The bridge reports
`device_available: true`, `pending: false`, and `lighting_readback: false`. The guarded
backend cutover is active; owner-confirmed basic hardware acceptance is recorded, while
reconnect/sleep/wake lifecycle acceptance remains pending. Local build state details are
in ignored `karabiner/build/deployment.json`.

## Architecture

```text
presence watcher / manual CLI
    → bridge_client.py
    → consistently signed custom karabiner_cli
    → existing authenticated Core Service socket + console-UID check
    → one journal worker (no input-thread disk waits)
    → existing device monitor/run loop
    → async output report on the already-owned AK820 handle
```

Key mapping events retain the original pipeline. Status is bridge readiness, never
lighting readback. Request messages contain only validated settings, action, ID and
freshness timestamp—not raw reports, device paths or shell commands.

The daemon persists pending BEFORE scheduling output. Root worker timeout/IPC loss
never causes replay. Late completion cannot clear the durable pending journal.
Acknowledgment is explicit and refuses while an output remains outstanding. Device
stop also marks in-flight transport uncertain. Callback context retains buffer/device
lifetime without retaining a receiver; a missing callback retains one context safely
instead of freeing memory still referenced by IOKit.

## Remaining deployment gates

1. Installer approval COMPLETE: owner approved the local unsigned wrapper; native
   administrator authorization and installation succeeded. Automatic builds still
   fail closed on unsigned packages; this was a separately authorized deployment.
2. Confirm alternate input is available; install via ordinary macOS administrator
   approval and reapprove signer-dependent permissions as needed. Do not bypass TCC,
   Gatekeeper or signature checks. A restart may be required.
3. Verify remapping first; then run readiness check and guarded backend activation.
4. Owner-visible acceptance: typing/modifiers, knob press/volume, lighting, proximity,
   reconnect, sleep/wake and restart behaviour.
5. Only after successful live cutover, finish the optional lighting/automation module
   split and retire old service-path compatibility links. Current links deliberately
   avoid breaking the registered LaunchAgent and scheduler alert command.

See [DEPLOYMENT.md](DEPLOYMENT.md) for commands, backups, acceptance checklist and rollback.

## References

- https://github.com/pqrs-org/Karabiner-Elements/tree/9312593e1a3bf72b94c63c524ebabe2637442e8a
- https://github.com/pqrs-org/Karabiner-Elements/blob/v16.3.0/DEVELOPMENT.md
- https://github.com/libusb/hidapi/blob/hidapi-0.15.0/mac/hid.c
- https://github.com/apple-oss-distributions/IOHIDFamily/blob/main/IOHIDFamily/IOHIDDevice.cpp

hidapi passes the nonzero report ID both as the reportID argument and in the full
65-byte buffer. The bridge preserves this framing. SDK callback timeout is expressed
in milliseconds; Apple's report code converts supplied milliseconds to microseconds
before constructing the kernel deadline.
