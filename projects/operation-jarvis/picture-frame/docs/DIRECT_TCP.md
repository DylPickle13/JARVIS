# In-process TCP transports

## Current mode: explicit owner-approved legacy LAN

After reviewing the frame's lack of challenge-based ADB authentication, the owner
explicitly requested re-enabling wireless debugging and building the project controls.
**Legacy LAN is now selected for this exact endpoint/package/build.** Live TCP
identity/status, effective-backlight reads and a private **1280×800 PNG** capture
passed. See the [complete controls guide](CONTROLS.md).

This is **not authenticated/encrypted ADB**. Other reachable LAN clients may obtain
privileged debugging access. The controller's private consent, pins and command
gates protect its own actions, not the listener against other clients. No router,
VPN, Mac privacy/signing setting, existing ADB server, other device, app/backend
route or background service was changed. Firmware/reboot persistence is untested.

## Two separate policies

### Authenticated `connect-tcp`

`DirectTcpAdb` still requires an actual RSA challenge signed by the existing
owner-controlled Mac ADB key. It never generates/replaces/enrolls a key, sends a
new-public-key request or accepts a peer without that challenge. The received unit
still fails this policy; its `ro.adb.secure=1` is not authentication proof.

### Explicit `connect-legacy-lan`

`LegacyLanAdb` is a separate, non-default owner-accepted policy:

- Acceptance requires `--accept-unauthenticated-lan --apply`, starts from the exact
  USB-paired frame and compares the requested address with that frame's own Wi-Fi IP.
- Private consent binds endpoint, package, every identity/build pin and timestamp.
  Missing/false/stale scope fails before any socket/dependency/key access. There is
  no public endpoint, hostname/discovery, address migration or automatic repinning.
- The transport reads/sends **no Mac ADB key**. If firmware requests RSA authentication
  it fails rather than silently switching policy or authorizing a new key.
- Before content/control access, fresh properties/package must match consent and
  existing controller pins. Every live result reports unauthenticated mode/risk.
- Explicit USB selection revokes that consent but does not disable the listener.
  `wifi-disable --apply` uses exact verified USB, verifies shutdown and revokes consent.

Neither policy is a networking proxy or OS-permission workaround: the entire CLI
runs in the normally LAN-authorized Python process. The supplied `./frame` launcher
uses JARVIS's already approved Python 3.13 runtime and changes no shared environment.

## Shared transport safeguards

Both interfaces preserve the controller lock, private runtime, durable pre-dispatch
pending markers, readbacks and upload deduplication. Failed sessions are terminal;
there is no automatic reconnect/replay or generic shell/file/HTTP endpoint.

Shell v1 has no reliable native exit code: a randomized terminal marker carries the
actual shell status. This Android build's numeric `printf %d` returned an invalid
large integer during read-only commissioning; `echo` avoids that formatter and
correctly handles CRLF. Missing/nonzero status still fails closed, including DCIM
presence and no-clobber checks. No enablement command was replayed for that correction.

Private screenshots use `exec_out` unchanged; FileSync pushes are restricted to
bounded private staged images and exact controller-owned `.part` destinations.
Main-thread CLI hard deadlines also bound FileSync/EOF waits. Packet debug logging,
dependency bytecode writes and raw exception output are disabled.

## Private optional dependency

USB/platform-tools control remains standard-library-only. TCP uses hash-pinned
**adb-shell 0.4.4** source privately; authenticated mode uses `cryptography` already
in the approved runtime. `install_tcp_deps.py` validates the source archive SHA-256,
installs only regular source/licence files owner-only in private `tcp-deps/`, and
executes no setup/build script. It changes no shared virtualenv, installs no USB/async
extras and never automatically overwrites an installation. A manifest is verified
before imports. Neither reviewed community Frameo HTTP server was installed.

```bash
cd projects/operation-jarvis/picture-frame
../security/.venv-313/bin/python -B install_tcp_deps.py  # no-fetch/no-state dry-run
./frame --direct-tcp doctor                            # local prerequisites only
./frame capabilities                                  # no device contact
```

The dependency is already privately installed on this Mac. Do not reinstall or
repeat wireless commissioning as recovery for an unknown write. Inspect `pending`
and the physical frame first; acknowledgement never proves/replays the action.

## Commissioning history

Initial Python 3.14 and stock-ADB attempts returned `No route to host`. Native
Network.framework reported `local_network_denied` inside that Python runtime.
Terminal comparison/targeted permission refresh did not fix it; the exact GUI/policy
mismatch was not established. Approved Python 3.13 reported a satisfied path and
reached the port. One USB/mDNS/emulator-disabled ADB-server pilot still failed and
only that newly created pilot was stopped.

The strict Python transport and an independent key-free handshake both found
`CNXN` before any RSA `AUTH` challenge. The owner first approved retirement at
**00:37 EDT, 2026-10-06**: no listener, LAN refusal and fresh USB checks were verified.
The later explicit request superseded that retirement with scoped legacy acceptance.
Re-enablement was dispatched once, its listener verified, then TCP pins/status/capture
accepted. No photo was resent; sleep/wake/swipes, wireless upload, USB-unplug/reboot
and persistence remain untested.

References: [adb-shell release](https://pypi.org/project/adb-shell/0.4.4/),
[documented TCP/signing API](https://adb-shell.readthedocs.io/en/stable/adb_shell.adb_device.html),
[Apple local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy).
