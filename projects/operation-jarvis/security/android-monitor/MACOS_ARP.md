# macOS directed ARP helper

This replaces **only** the optional Pi ARP workaround. It is not an RTSP proxy,
backend replacement, phone screen controller, BLE scanner, or camera integration.
**Building/staging it does not establish live acceptance or retire the Pi.**

## Local deployment acceptance — 2026-10-20 UTC

The corrected helper is installed on `mac-mini-64` as
`com.jarvis.monitor-arp`, with automatic launchd startup. It ran as `nobody`
without a restart during acceptance. The Pi's `jarvis-monitor-arp.service` was
stopped once, then disabled after the Mac-only checks passed. At the owner's
subsequent request, its installed source directory, unit and configuration were
removed from their active locations into a private recovery archive. After a
systemd daemon reload, the unit reports `LoadState=not-found`, inactive, PID 0.
No other Pi service PID changed.

- More than seven minutes with the Pi helper stopped, with repeated successful
  Mac lookup relays and the phone's doorbell neighbour remaining `REACHABLE`.
- Advancing H264 video at 18–20 fps and advancing audio, preserving the existing
  audio preference, Android processes, pairing, player configuration and APK.
- One guarded built-in long-press test closed only the viewer's RTSP socket. Its
  normal five-second reconnect path opened exactly one new player and recovered
  video/audio without the Pi helper. No forced wake or Wi-Fi/route/ARP-table edits.
- Subsequent three-minute sampled playback remained continuous; Mac lookup count
  advanced from 31 to 49 during that span. Reboot, overnight and actual Pi-power-off
  behavior were not physically tested. Independent Pi workloads are not migrated.

Private evidence is under the Android monitor runtime directory's
`mac-arp-migration-20261020T020858Z/`; remote stop/disable evidence is under
`/var/backups/jarvis-monitor-arp/mac-migration-20261020T020858Z/`.
The original install and replacement attempt markers remain intact. The Pi removal
archive and guarded move/reload evidence are in the remote migration directory's
`uninstall/` subdirectory; it is inert, not an installed service. All 59 Android
monitor tests passed after removal, including the native sanitizer regressions.

## Design and privilege boundary

- `arp_repair_macos.c` uses the system libpcap/BPF API in ordinary Ethernet mode
  on the selected LAN interface. Monitor mode and promiscuous capture are disabled.
- Capture is filtered to ARP replies addressed to this host, snap length 64 bytes.
  No packet dumps, video, audio, camera credentials, shell commands, listeners,
  route edits, neighbour edits, or router/device configuration changes.
- The root-owned compiled executable starts as root solely to take a singleton
  lock and open/configure BPF. It removes supplementary groups, permanently changes
  UID/GID to `nobody`, and verifies that restoring root fails **before sending**.
  The backend, Python, and monitor relay do not gain privileges. The retained BPF
  descriptor still permits packet injection; this is not a general security sandbox.
- Both configured IP/MAC pairs must answer fresh, directed ARP requests each cycle.
  The validation is equivalent to the Pi helper's LAN association check, **not
  cryptographic device authentication**. Old queued replies, invalid frames,
  non-private addresses, duplicate peers and subnet mismatches fail closed.
- Relay Ethernet source stays the Mac. Only ARP sender fields carry the validated
  phone identity. The doorbell supplies its genuine reply directly to the phone.
- Local IPv4/subnet and interface index are rechecked each cycle. Before dropping
  privileges, the actual local MAC and interface index are bound to the BPF handle
  and rechecked after opening it. A redacted privileged MAC is rejected.
- macOS can redact the local MAC to `02:00:00:00:00:00` after the UID change. Only
  this exact privacy placeholder may use the privileged binding, on the unchanged
  interface index. It is **not fresh MAC proof**: both peers must still send fresh,
  fully matching replies addressed to the bound MAC through the non-promiscuous
  capture before any handset query is relayed. A different real MAC, index change,
  zero/multicast address, or placeholder used as a phone/doorbell identity is rejected.
  A MAC rotation hidden by redaction can prevent verification until BPF is reopened;
  it never authorizes an unverified relay.
- Detectable interface/MAC changes and capture failures exit, allowing launchd to
  reopen BPF with a 60-second restart throttle.
  Unverified devices are retried on the normal ten-second cycle. No permanently
  latched transient-network fault is introduced.
- Successful injection is **not proof of phone receipt or playback**. DHCP changes
  to either peer still require verified configuration maintenance.

## Offline tests

```sh
PYTHONDONTWRITEBYTECODE=1 ../.venv-313/bin/python -m unittest discover \
  -s tests -p 'test_macos_arp.py' -v
PYTHONDONTWRITEBYTECODE=1 ../.venv-313/bin/python -m unittest discover \
  -s tests -p 'test_arp_repair.py' -v
```

The native protocol tests use fake transport and address/undefined-behavior
sanitizers. They cover packet identity fields, request construction, bounded queues,
missing/wrong replies, both-peer verification, failed sends, and stopping. No BPF
access or real packet injection occurs. Production compilation treats warnings as
errors. `--check` validates current local interface/subnet and the configured peers
without opening BPF or verifying remote device identities.

## Stage and administrator install

Create a private JSON file with exactly `INTERFACE`, `PHONE_IP`, `PHONE_MAC`,
`DOORBELL_IP`, `DOORBELL_MAC`, using independently reviewed current identities.
No camera passwords or monitor pairing material belong in this configuration.

```sh
PYTHONDONTWRITEBYTECODE=1 ../.venv-313/bin/python build_macos_arp.py \
  --config /private/path/peers.json --output /private/path/new-staging-directory
```

Review `manifest.json` and generated `install.sh`. Then the owner runs the exact
printed `sudo /private/path/new-staging-directory/install.sh` command in Terminal.
The installer never prompts via AppleScript, changes sudo policy, or broadens BPF
permissions. Do not put a password into chat or the script.

The fresh-install-only installer verifies staged and installed hashes, rejects
unsafe parents/existing targets, and creates a durable attempt marker **before**
installation. It installs only:

- `/Library/PrivilegedHelperTools/com.jarvis.monitor-arp` — root-owned binary, 0555.
- `/Library/LaunchDaemons/com.jarvis.monitor-arp.plist` — root-owned service, 0644.
- `/var/db/com.jarvis.monitor-arp.install-attempted/` — private installation evidence.
- `/var/log/jarvis-monitor-arp.log` — sanitized status/counts only, root-owned 0644.

Runtime also creates `/var/run/com.jarvis.monitor-arp.lock`, root-owned 0600.
The installer dispatches `launchctl bootstrap` exactly once, with an attempt marker.
An error/timeout is **not permission to replay**: inspect loaded service, files,
hashes, process identity and logs first. An existing attempt requires reviewed maintenance; do not rerun the fresh installer.

For a reviewed **binary-only correction**, the builder also accepts
`--replace-existing-sha256 EXACT_INSTALLED_BINARY_SHA256`. It checks the installed
root-owned files, requires an identical service plist, and generates `replace.sh`.
The replacement verifies old/new hashes, creates its own durable attempt directory,
backs up the original binary/plist, dispatches one bootout, verifies process exit,
atomically replaces only the binary, then dispatches one bootstrap. The original
installation marker, service configuration, log and Pi helper are preserved.
Unknown outcomes require inspection rather than rerunning this script too.

### First installation finding

The first live installation opened BPF and successfully dropped privileges, but
exited with `interface-unavailable`, without relay dispatch. Unprivileged interface
enumeration on this Mac returns the privacy placeholder. The corrected candidate
handles that case as above, with offline regression tests and the subsequent
successful replacement/live acceptance recorded above. Root ownership or a
successful bootstrap alone does not establish that the helper works.

## Required live acceptance (not performed by the builder)

1. Keep the Pi helper running while confirming the Mac daemon has dropped to
   `nobody` and increments `lookup-relayed` without capture errors. Dispatch alone
   does not prove the phone received the reply.
2. With explicit maintenance authorization, record Pi enablement/runtime state and
   stop **only** `jarvis-monitor-arp.service` once. Do not power down the Pi yet.
3. Observe the phone's neighbour state plus advancing decoded/presented video and
   audio counters over repeated helper cycles. Test a guarded viewer reconnect when
   the phone is already awake, foreground, plugged in, and its presence helper is
   fresh/enabled. Preserve display safeguards and the viewer's existing mute state;
   do not unmute or force-wake for testing.
4. Do not flush neighbours, force Wi-Fi loss, fabricate presence or restart unrelated
   services just to manufacture a failure. Record what remains untested, including
   sleep/reboot/overnight behavior.
5. If the Mac-only test fails, inspect any uncertain operations, then restore only
   the previously running Pi helper. Leave its files and boot configuration intact
   until Mac-only acceptance succeeds.
6. Retire the Pi helper only after the approved Mac-only verification. A Pi shutdown
   also removes its independent living-room presence service; this helper does not
   replace that service or other Pi workloads.

Read-only inspection:

```sh
launchctl print system/com.jarvis.monitor-arp
ps -axo pid,uid,gid,command  # locate the specific helper, do not stop others
# Read /var/log/jarvis-monitor-arp.log with the file-reading tool.
```

Approved rollback: unload only `system/com.jarvis.monitor-arp` with `launchctl
bootout` and verify it exited. The retired local Pi deployment has now been
uninstalled: restoring it requires a separately reviewed restoration of its archived
unit, configuration and source to their original paths, followed by daemon reload
and explicit enable/start. Do not blindly run `systemctl start` against a removed
unit, delete attempt evidence, or overwrite installation files as a retry mechanism.
No infinite reconnect guarantee is made: the viewer still has its existing bounded
retry policy, and genuine doorbell/decoder failures remain separate.
