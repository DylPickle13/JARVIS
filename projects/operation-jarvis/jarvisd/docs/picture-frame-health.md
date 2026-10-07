# Picture-frame availability — network only

The current worker reports **LAN reachability**, not ADB access or hardware/app
identity. It needs no wireless debugging, device keys, photo access, new daemon,
control route, native-app change, router change or reboot-persistent device setting.

## Scope

One opt-in `frame` entry reuses the existing [device-health](device-coverage.md)
worker and cached `deviceHealth` projection, with `scope: frame_network_reachability`:

- `available`: one fresh ICMP echo reply arrived from the privately commissioned
  frame address on the pinned local interface. A conflicting MAC, if exposed by
  the local neighbor cache, prevents green.
- `unavailable`: the bounded check reported one transmitted echo and zero replies,
  without a local process/permission error or visible conflicting MAC. This means
  the configured address did not answer, not proof of lost power.
- `unknown`: no result yet, evidence older than 150 seconds, controller busy,
  missing/invalid private configuration, visible MAC conflict, malformed output,
  process/permission failure, or timeout.

Existing fields include `lastAttemptAt`, `lastSuccessAt`, age and failure count.
Last-good evidence never substitutes for a current failure/unknown observation.
Unknown checks neither open nor recover a frame incident. Fresh failed checks use
existing incident thresholds; notification policy remains unchanged and disabled.

A ping is **not authenticated device identity**. On the commissioned Mac, the OS
neighbor query can report no entry even after a successful echo. An absent entry
therefore does not prevent address-reachability green and is not claimed as MAC
verification. The frame's address/MAC were read from its original pinned USB
identity during commissioning, not guessed or adopted from a scan.

Reachability does **not** establish that the screen is lit, Frameo is foregrounded,
the slideshow is healthy, a photo was imported, or Frameo's internet/cloud service
is connected. Address/MAC pins are targeting fences, not authentication.

## Relocation and address changes

Properly shut the frame down, wait for shutdown, then unplug and relocate normally.
After it boots and reconnects to the same Wi-Fi/address, this check can work without
USB recovery or ADB. No frame reboot is performed by the monitor.

The check does not reserve a DHCP lease. If the frame's address changes, explicitly
review/update the private target against the frame; do not scan for replacements,
automatically adopt another device, or change the router. A reused address may
answer for another device when the OS exposes no neighbor identity. This is the
explicit limitation of basic configured-address monitoring. Physical post-reboot
acceptance is distinct from verification with ADB disabled.

## Read path

```text
existing serial ProbeWorker (60s after completed cycle)
  -> frame_health.FrameProbe (one bounded subprocess)
  -> picture-frame/health_worker.py --check
  -> existing canonical lock + private network-health.json validation
  -> one interface-bound ICMP echo + one exact-address local ARP-cache query
```

The worker uses fixed macOS system binaries, a literal RFC1918 IPv4 address, an
`enN` interface and a commissioned unicast Wi-Fi MAC. Ping has a two-second overall
limit and a three-second subprocess deadline; the neighbor query has a one-second
deadline. Each command's output is bounded for parsing and discarded. It never
invokes a shell, scans neighbors, mutates the ARP cache, resolves DNS or retries.
A cache entry alone never establishes availability.

The adapter retains a six-second total deadline and a 4 KiB result cap. Its output
is only `{ok, reason}`, using a boolean/null and closed sanitized reasons. HTTP
overview requests read the cache; they never trigger a network probe. Each later
scheduled tick is a new independent read, never a replayed mutation.

The worker does not import the controller or any ADB/cryptography dependencies and
does not read controller configuration, keys, photos, screenshots, uploads or
pending-write state. It reuses the already-existing canonical lock without creating
or repairing state; an existing pending write is neither inspected nor cleared.
Default invocation remains a **no-I/O dry-run**; only `--check` performs a check.

## Explicit activation configuration

The existing private registry entry is unchanged:

```json
{"id":"picture-frame","name":"Picture frame","kind":"frame","expectation":"always"}
```

No selector, address, MAC, interface, port, serial, shell or path is accepted in that
entry or via HTTP. Only one frame entry is supported.

Private `network-health.json` in the account's existing owner-only picture-frame
runtime contains exactly `schema_version`, `policy`, `ipv4`, `mac_address` and
`interface`. Commissioning requires explicit owner approval and verified device
metadata. It remains outside Git. Missing state is unknown, never auto-created.
Controller/legacy transport configuration is separate and is not a worker input.

The backend retains its explicit owner-controlled absolute paths:

- `JARVISD_FRAME_HEALTH_WORKER`: frozen `picture-frame/health_worker.py`.
- `JARVISD_FRAME_HEALTH_PYTHON`: the existing reviewed interpreter, currently
  `security/.venv-313/bin/python`; no new dependencies or permission helper.

Worker source and its directory must be real owner-controlled files/directories
with no group/other write access. Runtime directory, configuration and lock must
be real owner-only state. Reviewed interpreter symlinks remain supported.

## Deployment acceptance

**Deployed 2026-10-06 EDT:** `20261006T230342Z-frame-network-health`, frozen
from installed `20261006T193632Z-picture-frame-health`. Exactly six source/test
files changed in the 610-file manifest. Verification passed **862 backend tests,
19 worker tests, syntax/plist checks and all SDK gates**. Only jarvisd and its
watchdog restarted; liveness returned in **0.311 seconds**. The 27-entry registry,
unrelated service/Pi identities, protected configuration, SQLite identities and
10-second history cadence were preserved. Retained events were content-hash checked.

The actual backend launch-context network check passed before retirement. The
original pinned USB route then disabled the temporary ADB listener **once**:
USB identity/listener/property checks and an external refused-port check passed,
persistent TCP remained unset, saved controller transport became USB-only, and
legacy LAN consent was revoked. No photos or unrelated ADB device/server were
changed; no pending write remains. A fresh scheduled observation at **19:12 EDT**
passed after retirement. A physical reboot/unplug test has **not** been performed.

Private manifests, prior service definitions, SQLite backups, rollback notes and
one-use authorization/receipts remain outside Git. No source commit/push is part
of this rollout.

Network-only activation and listener-retirement receipts are recorded separately
from code verification. Require the actual candidate backend's first bounded
network observation to pass before retiring ADB; an interactive ping does not prove
the daemon's launch-context permission. Then verify a fresh scheduled observation
with the listener closed. No TCC/signature changes, borrowed application permission,
lookalike diagnostic service or automatic restart/reconnection workaround.

Freeze from the installed baseline, preserve registry, credentials, history,
unrelated service/Pi identities and rollback artifacts. Restart only the approved
jarvisd/watchdog pair. Do not replay activation helpers after their started markers.
Rollback does not re-enable ADB, restore old consent or replay media transfers.

The prior **2026-10-06 15:52 EDT** release,
`20261006T193632Z-picture-frame-health`, used identity/package reads over temporary
legacy LAN ADB. Those historical checks did not survive the later power cycle;
that mechanism is superseded by the network-only implementation above. Its original
private deployment/rollback artifacts remain retained.

## Verification

Offline tests cover no-I/O dry-run, no ADB/private-media reads, exact command and
interface bounds, fresh echo versus stale cache, visible MAC conflicts, absent OS
neighbor metadata, packet loss versus local errors, ownership/symlink/FIFO/size
checks, invalid targets, busy locking, deadlines/no retries, output privacy,
up/failure/unknown/expiry, unknown-incident suppression and cache-only authenticated
HTTP routes. Fixtures are synthetic; no live network, photos, configuration or
services are used by these tests.
