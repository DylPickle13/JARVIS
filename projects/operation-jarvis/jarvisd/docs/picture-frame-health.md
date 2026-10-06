# Picture-frame availability — status only

**Deployed 2026-10-06 EDT:** `20261006T193632Z-picture-frame-health`, activated at
**15:52 EDT**. The first bounded read under the actual backend launch context
passed; later periodic observations advanced and remained available. Only jarvisd
and its watchdog restarted; backend liveness returned in **0.334 seconds**.
No native app, tool schema, authentication mode or photo/control route changed.

The candidate was built from exact installed `20261006T014750Z-home-automations`,
not the broader working tree. Only nine source/test files differ. Frozen
verification passed **862 backend tests, 11 frame-worker tests and all SDK gates**.
The private registry now has 27 entries: the original 26 are unchanged. Their
configuration, unrelated service/Pi identities, SQLite history identities,
retained incident rows and 10-second history cadence were verified preserved.

Private rollback, manifests, authorization, receipts and audit stops remain
retained. An initial preflight dispatched no service action: it incorrectly
classified retained verified Home receipts as active. The corrected predicate
still rejects pending, unknown and blocked operations. A post-start audit also
stopped on the existing event store's atomic startup file replacement; read-only
finalization verified the byte-identical event implementation, ordered retained
pre-deployment events and SQLite preservation. Exact pre/post event-content
comparison was not performed. No service command or unknown write was replayed.

## Scope

One opt-in `frame` entry reuses the existing [device-health](device-coverage.md)
worker and cached `deviceHealth` projection:

- `available`: a fresh read matched the saved hardware/build pins and installed
  Frameo package, using the already-approved exact legacy LAN endpoint.
- `unavailable`: the identity/package read could not complete over that transport.
  This is check availability, not proof that the frame has lost power.
- `unknown`: no result yet, evidence older than 150 seconds, controller busy,
  missing/invalid local configuration or dependencies, unsupported transport,
  identity not verified, worker timeout, or invalid worker output.

Existing fields include `lastAttemptAt`, `lastSuccessAt`, age and failure count.
Last-good evidence never substitutes for a current failure/unknown observation.
Unknown checks neither open nor recover a frame incident. Fresh failed checks use
existing incident thresholds; notification policy is not enabled or changed.

`scope: frame_identity_read` does **not** establish that the screen is lit,
Frameo is foregrounded, the slideshow is running, or any photo was imported.
Android property pins are accident-prevention fences, not cryptographic identity.
This integration does not secure or change the unauthenticated ADB listener.

## Read path

```text
existing serial ProbeWorker (60s after completed cycle)
  -> frame_health.FrameProbe (one bounded subprocess)
  -> picture-frame/health_worker.py --check
  -> shared controller lock + private config/consent validation
  -> LegacyLanAdb + Controller.checked (identity/package reads only)
```

The subprocess has a six-second total deadline and a 4 KiB output cap. Its output
is limited to a boolean/null and a closed, sanitized reason. No automatic retry,
discovery, reconnect within a check, USB/key fallback, or build-pin refresh.
Each later scheduled tick is a new independent **read**, never a replayed write.
HTTP overview requests only read the cache; they do not trigger a frame probe.
No photo, screenshot, brightness, touch, file-push, listener, pairing, or
pending-write resolution operation is accessible through the worker.
An existing pending write is left unchanged; the identity read does not inspect it.

## Explicit activation configuration

Add this single entry to the existing **private** registry, preserving all other
entries and the inventory/monitor-key bounds:

```json
{"id":"picture-frame","name":"Picture frame","kind":"frame","expectation":"always"}
```

No selector, host, port, serial, shell, or file path is accepted in that entry.
Only one frame entry is supported; the controller's existing private configuration
selects and pins the target. Firmware, endpoint or consent changes require review.

Set these two owner-controlled absolute paths in the backend's deployment
configuration; they are **not** API/request parameters:

- `JARVISD_FRAME_HEALTH_WORKER`: frozen `picture-frame/health_worker.py`, alongside
  the matching reviewed `frame_control.py` and `frame_tcp.py` source.
- `JARVISD_FRAME_HEALTH_PYTHON`: the already-reviewed, normally LAN-approved Python
  runtime used by `./frame` (currently `security/.venv-313/bin/python`).

The worker uses only the existing owner-only frame runtime under the account's
Application Support directory. Missing state is unknown, never auto-created or
commissioned. USB or strict TCP selection is unknown; there is no transport fallback.
The worker source and its directory must be real owner-controlled files/directories
with no group/other write access. Normal reviewed venv interpreter symlinks remain
supported. No dependencies are installed and no permission helper is created.

During an approved rollout, require the actual candidate backend's first bounded
**read-only** worker observation to succeed before declaring activation verified.
Success from an interactive session does not prove its macOS LAN permission there.
Fail closed on denial and inspect/restore the retained backend deliberately;
do not create a lookalike diagnostic service or change TCC/signatures or borrow
another application's permissions to make it pass.
Freeze/test against the installed backend baseline, preserve private registry,
credentials, incident/history identity, and unrelated service/process state.
Rollback restores that baseline and registry without touching the frame/listener.

## Verification

Offline tests cover fixed opt-in configuration, no-I/O import/dry-run, one attempt,
output/deadline bounds, source ownership, exact identity, invalid consent, busy
locking, pending-write preservation, up/failure/unknown/expiry projections,
incident suppression on unknown, and existing authenticated/cache-only HTTP routes.
They use synthetic identities, fake transports and local fixture subprocesses;
no photos, live configuration, LAN devices or running services are used.
