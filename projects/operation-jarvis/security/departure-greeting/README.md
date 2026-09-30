# Departure greeting — outdoor doorbell only

Standalone security subproject, like `android-monitor/`. All departure-task code,
its tests, and documentation live here. Main security CLI/backend/Android monitor
code is unchanged. Credentials/registry and the approved audio app are reused, not
copied. Only the private saved hub address was corrected with owner approval;
credentials and registry contents remain unchanged.

## Owner-authorized audible trial

On 2026-09-29 the owner explicitly requested background activation for testing the
next day, then specified the exact phrase: **“Have a good trip, sir.”** The installer
opts in to an **experimental audible trial**, not a claim of physically verified
departure detection. The owner subsequently requested **24/7 operation**, with no
quiet hours. The owner then required **a fresh D235 person event after the door
opens**, to reduce package-pickup false farewells. There are no arrival greetings
or indoor speaker actions. Sensor-only speech is no longer permitted.

The foreground `observe` command remains silent. The separately installed
LaunchAgent reads paired sensor snapshots and speaks only on a qualifying departure
candidate and after all delivery gates pass. There is no immediate test speech
when installing or starting it.

Defaults:

- Clear → foyer motion while the door is closed, then closed → open within 20 s.
- Motion must precede opening by at least 0.5 s in the observed sequence.
- Simultaneous edges and motion starting with the door already open are suppressed.
- Initial/recovery readings establish silent baselines. Armed motion is never saved
  or reconstructed after restart, reconnect, a read gap, or playback.
- One candidate per door-opening session; **120 s durable household-wide cooldown**.
- Mandatory fresh, commissioned **person** event, strictly after the observed door
  opening. No old/ongoing person event, generic motion, guessed numeric code or
  unreadable response can authorize speech. Same-second records are ambiguous.
- Person-event reads have a **2 s total budget**, at most two explicit getters;
  this time is included in the original 8 s voice-onset deadline, never added to it.
- Audible eligibility **24/7**, including overnight; no quiet-hours restriction.
- Digital playback gain **60%**, consistent with earlier owner-confirmed D235 voice
  playback. Persistent camera speaker settings/saved CLI defaults are unchanged.
- New samples must be complete; reads over 2 s, sample gaps over 8 s, unknown states,
  duplicate/out-of-order samples, or clock discontinuities break continuity.
- No queued/backfilled/late greetings. At most 8 s from the observed door edge to
  voice onset, including the D235's existing 1.5 s leading-silence padding.
- Pre-generated local Piper/JARVIS phrase; existing approved go2rtc app, identity
  validation, hub-first device locks, PCMA/8 kHz transport, and 2 s trailing padding.
- One playback request, no loop, no automatic playback retry.

Everyone is eligible; no phone enrollment, facial recognition, personal identity,
LLM decision, camera video analysis, or recording is involved.

## Mandatory person-event commissioning

The gate is implemented but defaults **unverified and silent**. A read-only live
preview successfully obtained the H200/D235 identity binding and an empty detection
history response. That is not verification of real person events, their numeric
codes, UTC timestamps or publication latency. A later preview failed; the live
source is not yet reliable/commissioned. No code is inferred from unit tests.

At an owner-supervised test, run `person-preview` below and have someone walk outside
into the doorbell's view, noting the exact time and the corresponding Tapo-app person
label. Compare against separate generic motion/package activity. Verify the event
code, UTC-second time basis, source binding and whether records appear within the
2 s gate budget while leaving enough of the 8 s deadline for audio startup. Completed
archive records may arrive too late: in that case this source is unsuitable and
must remain unverified. Do not loosen freshness or play an old event as a workaround.

Only after that review populate the owner-only `person-gate.json` verification record
with the observed `person_code`, preview `binding`, `timestamp_basis` of
`unix_utc_seconds`, aware ISO `verified_at`, and `verified: true`. Its other keys are
`version: 1` and `source: h200_detection_history`. There is deliberately no automatic
commission/enable command or guessed mapping. Missing/invalid policy cannot revert
to sensor-only speech. Revalidate after firmware, camera or hub changes; identity and
reported firmware participate in the binding, but unreported changes need manual review.

A pre-existing `sensor_read_requires_review` fault was found during this update and
preserved, along with cooldown/pending/history. It also requires review before the
watcher can deliver; commissioning must not clear unknown/pending playback state.

## Controls

From the repository root:

```sh
# Local status only; does not contact household devices.
projects/operation-jarvis/security/departure-greeting/departure --json status

# Disable future automatic speech/reads (does not clear fault/pending markers).
projects/operation-jarvis/security/departure-greeting/departure disable --confirm

# Explicit live, silent, bounded sensor observation (10–300 s).
projects/operation-jarvis/security/departure-greeting/departure --json observe --seconds 60

# Explicit silent event-metadata preview for a supervised person test (10–60 s).
# Never commissions the gate or enables/plays speech; no video acquisition.
projects/operation-jarvis/security/departure-greeting/departure --json person-preview --seconds 60
```

Disabling is checked again before speech. It is not a guarantee to interrupt a
request that has already begun speaking. Disable is not fault recovery. Re-enabling
an existing installation, changing the phrase, or clearing uncertain state requires
explicit owner review; there is no automatic reset/reinstall path.

### Installation reference

```sh
projects/operation-jarvis/security/.venv-313/bin/python \
  projects/operation-jarvis/security/departure-greeting/install.py --enable-trial --confirm
```

Creates only `com.jarvis.departure-greeting` in the owner's user LaunchAgents. It
refuses an existing installation, pre-generates the phrase using the already-cached
voice (no model download), and bootstraps only this new agent. It does not restart
other services, alter security settings/recording, or emit a test greeting.

Runtime is owner-only at:

`~/Library/Application Support/JARVIS/departure-greeting/`

Config/journal/generated audio/logs stay private and outside Git. Private bounded
decision history retains at most 64 state-change entries for next-day troubleshooting;
it contains no raw payloads, account details, LAN addresses, device IDs, or recordings.
The separate owner-only address-change diagnostic records private routing and
verification evidence, not credentials; it is also outside Git.

## Read/delivery safeguards

The watcher establishes an authenticated, identity-checked H200 session and selects
unique T100/T110 children from the existing private registry. Each poll obtains
BOTH states in one explicit `getChildDeviceList` getter, not sequential CLI reads
or SDK cache reuse. Initial child selection uses exact registry nickname/model
matching on the same getter, bypassing the installed SDK's failing child cloud-state
initialization. A supported per-device HTTP client uses fresh connections to avoid
closed-socket reuse; SDK files, authentication and TLS policy are unchanged. It takes the existing hub lock only during setup/read; locks
are released before speaker work. Existing on-demand commands can still use the hub.
Poll delay is 2 s after a completed read, with no catch-up loop. Busy/transport
failures reset continuity and wait 15 s before read-only reconnection. Credentials,
identity, child schema/selection, or other unexpected failures latch for review;
there is no automatic authentication recovery.

After commissioning, the authenticated session resolves exactly one D235 from
`getGeneralDeviceList`, bound to its private child ID/MAC and H200 identity/reported
firmware. On a departure candidate, `searchDetectionList` requests only that camera,
with at most 20 rows, no SDK paging, request replay or cloud/notification scraping.
Full pages (potential truncation), unrecognized/ongoing-record schemas, invalid
clock data and identity mismatches fail closed. Only the exact commissioned type
and a start time strictly later than this opening count. No event cursor backfill
is used: old events cannot qualify for a later opening.

Before checking the event and launching the fixed speaker worker, the watcher
durably saves a unique pending reservation and last-attempt time. A known
no-person/timeout outcome consumes the opening and retains the household cooldown;
it cannot fall through to speech or retry the same departure. A crash, timeout, malformed result, or
uncertain audible outcome leaves a durable fault/pending marker blocking future
speech across restarts. A known pre-play failure consumes the event and retains
the two-minute cooldown: it is never retried. Cooldown includes reservation/storage
time and backward wall-clock jumps. A process singleton prevents duplicate watchers.

The speaker worker rechecks enablement, phrase/hash, configuration, registered D235,
and event expiry. A private per-attempt proof binds the event code/source, opening,
event timestamps and unchanged expiry to the durable reservation. The worker requires
that proof both before contacting the doorbell and again before sending audio;
missing, revoked, future, expired, wrong-attempt or changed-policy proofs cannot play. Identity/setup requests are bounded by expiry; playback
can begin only if the voice including leading padding will start before the deadline.
A durable started marker is saved before the potentially audible request. Cleanup
uses the existing session-specific helper; unrelated audio processes are never killed.
The short clip can finish once started, but is never replayed. “Completed” means
transport completion, not microphone-verified hearing.

## Limitations / tomorrow's physical test

**Hub state changes are not verified fresh sensor radio events or proof of actual
departure.** `radio_freshness` stays `unknown`, and physical acceptance is pending.
The owner authorized trial activation despite these limitations.

A resident opening for a delivery can match the sensor sequence. Person confirmation
reduces false positives when nobody steps into view, but **does not prove departure**:
a resident reaching for a package, or a visitor entering view after opening, may still
produce a matching person event. This gate is not a guarantee against package pickup. A T100 that remains
active cannot supply a second fresh clear→motion edge; subsequent departures may
be silently missed. Fast motion/open sequences may fall between polls and be
suppressed as simultaneous. People may walk out of earshot before audio starts.
Network failures/unknowns prefer silence, not guesses.

First perform the **silent person-event commissioning** described above. Speech
remains blocked until the mapping/timing are verified and the saved sensor fault is
reviewed. After owner-approved commissioning and fault recovery, test the audible
trial at any time, including overnight:

1. Walk through the foyer and leave normally; confirm the phrase/timing/loudness.
2. Several people leave together: only one phrase.
3. Arrive from outside: no phrase.
4. Open for a visitor or collect a parcel: check false farewell behaviour.
5. Try a quick return/re-exit: cooldown suppresses another phrase.

Review private timing/history afterward before changing detection windows or
volume. Snapshot-schema/read success and offline tests are not physical acceptance.

## Verification / files

```sh
projects/operation-jarvis/security/.venv-313/bin/python -m unittest discover \
  -s projects/operation-jarvis/security/departure-greeting/tests -v
```

**76 subproject tests pass**, plus **286 existing security tests** (two optional
skips). Tests are offline with synthetic fixtures and mocked network/speaker operations.
Gate coverage includes absent/unverified policy, exact-type/identity matching,
old/same-second/unknown/empty/truncated events, finite deadlines, private proof
validation/revocation, cancellation/pending safety and no sensor-only fallback.

Initial deployment checks verified the agent and paired sensor reads. This update
preserves unknown radio freshness and the existing sensor fault; the event query
accepted an empty response but physical person mapping/timing remain unverified.
Connection diagnostics later found the H200 at a different LAN address. With owner
approval, only `JARVIS_SECURITY_HUB_HOST` in the ignored private `.env` was corrected.
Three paired reads through the saved configuration then succeeded; all other env
lines and private permissions were unchanged. The existing fault remains latched
and the person gate remains unverified: no automatic speech is enabled by this repair.
No playback attempt was made. Only this trial's agent is installed/restarted;
other security services and the shared CLI/audio implementation are unchanged.
Tomorrow's owner test remains necessary before automatic speech can resume.

- `departure.py`: policy, bounded silent observer, local status/disable command.
- `watcher.py`: singleton background reader and guarded delivery coordinator.
- `speaker.py`: one expiring, reserved farewell through the outdoor D235 only.
- `runtime.py`: private configuration, durable journal/cooldown/fault state.
- `person_gate.py`: mandatory commissioned event source, bounded reads and proof;
  explicit metadata-only commissioning preview.
- `install.py`: explicit new-agent installation and offline phrase preparation.
- `departure`: isolated Python-interpreter launcher.
- `tests/`: offline policy, adapter, private-state, and delivery-safety checks.
