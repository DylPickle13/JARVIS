# Minimum CLI/Pi deployment

The owner explicitly replaced the exclusive-ownership project with a smaller,
best-effort rollout. **The older ownership/certification/recovery gates are not
requirements for this mode.** Do not activate the dormant ledger, grant issuer,
SDK ownership hooks, v2 protocol, or staged vendor copies.

## Selected behavior

- `local-main.py` starts the backend on the existing 8790 listener. It requires an
  explicitly provisioned 256-bit token in the account home's private
  `Library/Application Support/JARVIS/local-control/token` (directory 0700, file
  0600). No automatic enrollment, alternate host, proxy or key fallback.
- Exact `/api/v1/local-control`: GET is an authenticated, non-mutating readiness
  probe; POST accepts only the four existing device write actions. Both require
  numeric IPv4 loopback and the dedicated bearer token; browser origins,
  forwarding headers and duplicate authorization are rejected.
- Legacy `/api/v1/command` device writes return 409. Current native clients use
  `/api/v1/device-command`, with existing app authentication, one request ID per
  invocation, bounded process-local duplicate rejection and the same dispatcher.
  See [native controls](../../jarvis-app/docs/native-control-update.md).
  Status/events/services remain available; terminal and audio processing remain
  separate services. The server keeps the existing 64-connection bound.
  No new device capability is introduced.
- The installed `jarvis.py` entry selects `local_control.Router`; both `jarvis-cli`
  and Pi's existing `pi.exec(... jarvis.py ...)` therefore converge without a Pi
  extension reload. `local-cli.py` is the equivalent explicit entry. Read-only and
  unrelated CLI actions retain their existing handlers and runtime roots.
- The router reuses tested argument translation. Writes require configured plug
  aliases and normal timeouts; no direct-IP/config/discovery overrides. Purifier
  selection supports the backend default, opaque ID, exact CID or unique cached
  device name. Custom aliases not present in that cache require the default or ID.
- One HTTP request per command, no reconnect, redirect, retry or direct-vendor
  fallback. Errors/cancellation/lost replies warn that delivery may be unknown.
  Existing backend admission, fresh identity binding, private worker, Kasa/VeSync
  no-replay guards and ordinary observation handling remain unchanged.

## Explicit trade-offs

This is not durable deduplication, exactly-once execution, persistent quarantine,
exclusive SDK ownership or cross-process locking. A new invocation is a new
request; do not automatically repeat a failed/timed-out invocation. Inspect state
first. Restart loses process-local coordination. Direct SDK scripts, vendor apps
and physical controls can still coexist. The bearer token protects a local route;
it is not encrypted remote transport or same-user process attestation.

## Deployment and rollback

Freeze/test backend + candidate CLI; preserve configuration, events and existing
SDK source hashes. Explicitly provision only the local token, then stop watchdog
and daemon, install the new daemon plist and CLI entry as a pair, verify read-only
health/readiness/state, and restart the watchdog. Do not kill device workers to
force a cutover. Ordinary quiet-state checks reduce disruption but are **not**
exclusive-ownership handoff evidence.

Rollback restores the recorded prior backend plist and prior CLI together, leaving
all existing SDK no-replay guards, current events/configuration and token untouched.
Because this rollout never activates ownership or installs mandatory fences, the
prior mixed routing is a compatible rollback (including prior app write behavior).
This procedure must not be reused after any future exclusive-ownership activation.
With Build198 or newer native clients installed, rollback must retain support for
`/api/v1/device-command`; the original CLI-only backend would break app controls.
Session-10 rollback must also preserve the current shared conversation history;
see [Room Audio / Session 10](../../jarvis-app/docs/room-session10.md).

Verification uses synthetic effects/peers and the actual candidate CLI. Production
checks are GET-only; passing them is not physical device acceptance. The retained
release's `deployed.json`, not this design document, establishes activation.
