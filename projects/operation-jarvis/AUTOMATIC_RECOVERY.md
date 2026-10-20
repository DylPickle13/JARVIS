# Autonomous recovery policy and rollout

Owner goal: no manual latch clearing. Genuine unresolved identity, authorization,
configuration, hardware or storage problems remain actionable. Once the underlying
problem is repaired, normal recovery must recognize it without a second reset.
Deliberate Off remains Off. Unknown outcomes are never relabelled as successful.

## Recovery paths

- **Shared sensor reader:** indefinite capped/jittered transport-read recovery;
  slower probes for identity/configuration/authentication problems. Previously
  reviewed hub/sensor identity hashes are checked on every connection. Three
  fresh, increasing-tick paired reads precede recovery and a new silent detection
  baseline. Never enroll a replacement device automatically. Fresh installs require
  `install.py --identity-pins`; existing pins live privately in `sensor-identity.json`.
- **Greeting/person evidence:** an uncertain speech event stays unknown and is never
  replayed. After its cooldown, exclusive speaker-worker and device locks permit
  retirement of the old reservation; fresh future events qualify independently.
  Person-evidence failures clear only through fresh verified evidence. No sensor-only
  permission is created, and disabling speech does not cancel an already spoken event.
- **LED:** known prewrite failures are paced. Uncertain commands need authenticated
  exact-device power observation; a later fresh-presence tick chooses current intent.
  No colour/effect changes or pre-emptive replay.
- **Keyboard/mouse:** signed bridge status plus its callback-idle acknowledgment
  (`hardware_write=false`) settle old requests without editing root journals. An
  outstanding OS callback still blocks recovery. Current intent is selected on a
  later fresh-presence tick. No lighting readback is claimed. Direct keyboard recovery
  uses its original writer lock and exact-interface enumeration, without opening HID.
  Legacy mouse records retire under their original lock after a settling interval and
  signed-bridge idle proof; the unknown report remains in diagnostic history. The old
  direct-mouse helper is retained only for offline protocol tests, not a CLI fallback.
- **Computer display:** exclusive helper lock and actual CoreGraphics/session state
  reconcile pending/faulted actions. Only a matching observed pending target can
  publish completion; a recovery tick does not issue another action. Fresh presence
  and three-away-check admission remain required before subsequent actions.
- **Android 1.10.1:** video reconnects continue with capped 60-second backoff, bounded
  counters and one scheduled retry. Screen recovery requires actual interactive/
  keyguard state, external power and fresh completed-Mac decisions. Errors and
  permission revocation preserve owner enable intent; restoring permission resumes
  an already-enabled helper. Boot/Enable never erase an unknown reservation. Explicit
  Disable remains authoritative. No secure-keyguard bypass or automatic permission
  grant. Charger handling releases wake/Wi-Fi locks even during network backoff.
- **Home controls:** identity-pinned Barn Door observations and locked Automatic Voice
  reads retire interrupted receipts. Live workers block settlement. Old request IDs
  stay consumed; no protocol execution, command resend or cloud-login override.
  Full active ledgers archive settled receipts individually, fsyncing before eviction;
  interrupted rollover cannot forget a consumed ID. Storage failures resume after
  actual storage repair rather than manual capacity resets.
- **Plugs/purifiers:** existing guarded vendor operations remain one-shot. Successful
  post-write reads remove uncertainty barriers; stale/inflight reads cannot do so.
  Local plug reads already recur. Purifier failures, pending observations and a fresh
  daemon schedule ordinary five-minute recovery reads; healthy state returns to
  foreground-only reads. Vendor cooldowns are never bypassed. SDK source/identity
  checks remain real prerequisites, not acknowledgment flags. This rollout does not
  activate dormant exclusive-ownership, grant or v2-control machinery.
- **Picture frame:** on-demand status/control requests reconcile under the exclusive
  controller lock, exact pinned device identity and a 130-second settling interval.
  Recovery never dispatches an old or new hardware action in the same invocation.
  Observable targets can be reported as observed; navigation/import outcomes remain
  unknown. Photo hashes are consumed durably before transfer, preventing duplicate
  import even if Frameo consumed the remote file. A legacy journal lacking its photo
  identity is genuine missing metadata: other controls recover, but further imports
  wait for the original metadata to be restored in `unidentified-upload.json`.
  The next upload automatically recognizes that repair and retains the original hash
  as consumed—there is no second guard-clear step. No guessing of the source photo.
  No background ADB polling, listener enablement, photo deletion or app-data changes.

## Audit boundaries

Existing freshness waits, locks, cooldowns and notification suppression are not
manual-clear blockers. Configuration/schema corruption, changed identity, missing
permission, unreviewed SDK changes and failed storage remain real problems to fix.
Install/replacement attempt journals and deliberate commissioning/transport changes
retain inspect-before-repeating safeguards; they do not authorize automatic repeated
installation or service manipulation. Optional manual acknowledgment commands are
not prerequisites for ordinary runtime recovery. Historical documents/acceptance
records describing manual latches are superseded by this policy, not rewritten as
if their original events had been automatic.

The D235 quick-response new-add guard was already owner-removed; its diagnostic
upload journal was not reinstated as a blocker. Existing at-most-once announcements
and consumed request/photo identities remain duplicate protection, not queues to replay.

## Deployed and verified

- Shared reader: reviewed pins, three paired preflight reads and three fresh published
  snapshots after its targeted restart. Its existing fault recovered automatically,
  without manual state edits, speech tests or event replay.
- Desk watcher: one guarded stop/start while the canonical cycle lock proved all
  controller futures finished. Three fresh post-start heartbeats passed. Configuration
  hashes stayed unchanged; no explicit display/HID/LED test command was sent.
- Backend: only `home_automations.py` and `state.py` changed in a copy of the active
  deployment. The prior release remains intact. Watchdog/daemon cutover preserved
  protected state; read-only readiness returned HTTP 200 and cached health was healthy.
  Measured loss of readable service was about **0.504 seconds**.
- Android: in-place, same-signing-identity update to **1.10.1 (versionCode 15)**.
  Actual installed APK hash matched the build; existing pairing, credentials and
  playback preferences remained unchanged. Helper authenticated over pinned TLS.
  Video/audio counters advanced; playback restoration used the exact viewer button,
  not a forced wake, permission reset or unsolicited audio test. The first 1.10 build
  was superseded after audit found the administrator-revocation enable-state latch.
- Picture-frame source is used by the existing on-demand launcher. Live ADB status
  could not be verified: the configured route is USB and no usable frame ADB connection
  was available. No pending frame journal existed. Existing network-only health is
  separate; USB connectivity was not fabricated or replaced with an open LAN listener.

Private runtime directories retain deployment plans, single-attempt markers,
protected-state hashes, prior APKs/plist, and observed acceptance results. None of
those files, credentials, endpoint identities or photos belong in this repository.

## Validation and remaining coverage

Offline suites: departure **121**, keyboard/display **241**, Android **62**, picture
frame **125**, full backend **1,021**: **1,570 passing tests**. Tests cover paced
recovery, wrong identities, busy writers, interrupted reservations, actual-state
mismatch, duplicate photos/requests, crash-safe receipt rollover and deliberate Off.

Synthetic writers must inject synthetic reconciliation readers too. One old parallel
fixture initially reached the installed bridge's no-write idle acknowledgment; it
was isolated before proceeding. That branch did not dispatch HID apply. Departure
fixtures now also isolate the household voice-policy path.

Physical fault injection, reboot/overnight acceptance, administrator revocation on
the actual handset, and live frame recovery remain **untested**. No universal
self-healing or exactly-once hardware guarantee is claimed. A repaired underlying
problem should resume the enabled feature without manual latch clearing; this is
not permission to repeat an uncertain physical operation or weaken its safeguards.
