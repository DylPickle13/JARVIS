# Control foundations: compatible deployment, not client cutover

## Deployed result

Deployment **`20260919T155241Z-control-foundations`** is active. Its daemon source is
`~/Library/Application Support/JARVIS/jarvisd/deployments/20260919T155241Z-control-foundations/source/repository/projects/operation-jarvis/jarvisd/`.
The repository-shaped frozen package includes the test references needed to rerun
all gates independently of mutable checkout files.

- 427 backend, 32 Kasa SDK and 38 VeSync SDK tests passed against the prepared,
  pre-cutover and installed frozen package; 21 readback tests passed five repetitions.
- 158 Swift tests passed with three expected skips; the separately selected live
  health/state test passed after activation.
- Live health/state/events/oMLX returned 200, configured devices were fresh, and
  candidate v2 paths remained unmounted (read-only GET returned 404).
- Loaded daemon arguments, installed manifests/plists, unchanged vendor/configuration
  hashes, bounded event history/sequence and protected service/pane identities verified.
- Only daemon/watchdog restarted. No physical writes, dependency/app installation,
  client migration, production ledger creation or commit occurred.

The complete prior VeSync-safety backend and paired vendor/plist rollback material
are retained, with current runtime history never restored from snapshots. The
initial preparation attempt lacked a mobile task-catalog test reference and stopped
before cutover; a new complete artifact passed every gate before activation.

## Rollout scope

This release bundles the tested policy, persistent ledger, candidate protocol,
device-host bridge and readback reconciliation foundations. **It does not activate
v2 ownership or migrate any client.** The production entry point still does not
import the ledger/protocol/host; no production ledger is created and no v2 route is
mounted. Existing v1 contracts, port 8790, authentication, direct CLI/tools and
mixed-legacy ownership remain unchanged. Bundled code is not a permission grant.

This distinction is intentional. Installed-writer fencing, real principal/transport
certification, safe retention/compaction and controlled recovery are not yet complete.
Those are activation gates, not reasons to describe a compatible backend package
update as exclusive ownership. Future client cutover requires its own validated,
cohort-wide handoff; no fallback, queued replay or SDK retry is introduced here.

## Readback reconciliation added in this release

The dormant host now exposes internal `begin_reconciliation(bound)` and
`finish_reconciliation(readback)` methods. Neither is an HTTP route, scheduler,
automatic retry, device operation or caller-evidence flag.

- Begin is allowed only after local mutation work ends. It captures a ledger read
  ticket, then increments the coordinator read revision. A collection already in
  flight cannot supply the proof; a new accepted aggregate observation is required.
- The caller retains existing foreground/single-flight/cooldown scheduling. These
  methods never start a collector, discover a device or bypass cloud cooldown.
- Finish requires the same host/command context, current authorization, identity,
  epoch, read revision, fresh successful observation and matching requested state.
  The unresolved ledger command fingerprint must match too: a different goal or
  catalogue cannot clear the original intent's uncertainty.
- Ledger admission lock is acquired before the state proof lock; the state lock is
  held through the ledger commit, so an intervening write/cache replacement cannot
  invalidate the proof between validation and persistence. State never acquires
  the ledger lock. Ticket expiry is rechecked after waiting for the state lock.
- Tickets are consumed even on failed validation. A cached/pre-ticket read, failed
  or mismatched result, identity/epoch change, expiration, permission revocation,
  storage fault or cancellation cannot refund a command or trigger another mutation.
- Successful reconciliation only clears the resource barrier. Reservation IDs and
  original acknowledged/pending/unknown dispositions remain in durable history.
  A later state match is not causal proof or proof against delayed remote effects.

This first readback bridge supports explicit plug on/off and the existing modeled
purifier power on/off, mode and speed expectations. Toggle, other settings, changed
catalogues and more general store-loss recovery remain fail-closed pending a
separately reviewed explicit recovery procedure. Expiration of the old purifier UI
verification deadline does not waive requested-state matching here.

The 21 new hardware-free tests use real ledger/coordinator/host components with
fake device IO. They cover new versus cached/in-flight reads, exact intent matching,
unknown/pending history preservation, failure/expiry/revocation, lock ordering and
durability faults. They do not certify physical hardware or client transports.

## Deployment and rollback rules

Prepare a private immutable, fully hashed deployment record under
`~/Library/Application Support/JARVIS/jarvisd/deployments/`. The new record retains:

- A complete backend package and minimal repository-shaped test references so all
  frozen tests run without depending on mutable checkout files.
- Complete matching plug/purifier Python source packages, backups of the five paired
  vendor files, and source/SDK verification manifests. This rollout does not modify
  vendor files or install dependencies.
- Original and prepared LaunchAgents plus a verified copy/reference of the complete
  prior backend. Only daemon `ProgramArguments`/working directory change; roots,
  runtime paths, environment/authentication and watchdog identity are preserved.
- Read-only health/state/contracts, protected service/pane identities, test logs,
  event history at cutover, and retained deploy/rollback tooling.

Before cutover, rerun the backend/Kasa/VeSync gates against the frozen sources,
verify the installed interpreters, require healthy fresh configured devices with
no pending/uncertain device state, and await cloud/worker read quiescence. Stop only
the watchdog then daemon; start/verify the daemon before restarting the watchdog.
Unloading a process does not establish remote cancellation or global legacy fencing.
An unexpected mutation/worker or unresolved device state must block the rollout,
not be discarded to force success.

After activation, verify the actual LaunchAgent target, all manifests, unchanged
paired vendor sources and runtime paths, health/state/events/oMLX contracts,
bounded event contents/sequence and protected identities. Repeat frozen gates and
the separate read-only native health/state check. No physical writes or app install
are part of this release.

Rollback restores only this release's verified prior code/plists (and paired vendor
sources if necessary); **never restore old event/configuration/ledger snapshots**.
The event snapshot is evidence, not a replay/recovery source. Refuse rollback over
unexpected newer plists/source edits. Once real ownership is activated in a future
release, old code unable to honor closure/epochs/reservations must not be activated.

The retained deployment record is the authoritative rollout result. Installed plists,
not checkout docs or historical app-build notes, identify the active source package.
