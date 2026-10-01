# Departure greeting — outdoor doorbell only

Standalone security subproject, like `android-monitor/`. All departure-task code,
its tests, and documentation live here. The shared security CLI/audio/Android
behavior is unchanged; jarvisd changes are limited to the opt-in paired-snapshot
reader documented below. Credentials/registry and the approved audio app are reused,
not copied. Only the private saved hub address was corrected with owner approval;
credentials and registry contents remain unchanged.

Current owner-selected greeting: **“Have a good day, sir”** (updated 2026-09-30).
The private offline-generated WAV and its hash metadata use this wording; no
immediate playback accompanies the change.

## Same-sample edge trial (2026-10-01)

The owner now permits motion and door-opening rising edges in the same paired
sample. The live watcher opts into this detector mode; silent standalone observation
retains its stricter default. Both edges must follow a valid consecutive baseline
showing no motion and a closed door. Initial/recovery samples, gaps, slow/unknown
readings, already-open doors and separately observed opening-before-motion remain
suppressed. Cooldown and one candidate per opening are unchanged. Same-sample
readings cannot establish order: some arrivals may now receive a farewell. Status
reports `same_sample_edges_allowed` and `arrival_false_positive_possible`; the
historical `arrival_enabled: false` means no dedicated arrival routine, not a promise
that this heuristic excludes arrivals. Earlier descriptions of suppressing all
simultaneous edges apply only to the strict mode.

## Latest physical trial and volume (2026-10-01)

The owner confirmed three audible greetings after the space-free scratch fix;
the journal recorded three completed playbacks with no fault/pending attempt. The
latest succeeded with same-sample acceptance enabled. This confirms these playback
trials, not general departure accuracy or person-event commissioning. The owner
subsequently requested maximum greeting volume: the private config is now 100% digital gain and
the config validator permits 1–100. Historical 60% descriptions below refer to the
earlier trial. No persistent camera speaker setting or shared audio default changed,
and no immediate test sound accompanied the volume change.

## Departure audio path fix (2026-10-01)

The private runtime lives under `Library/Application Support`. Two go2rtc v1.9.14
constraints matter: its FFmpeg command parser splits unquoted paths at whitespace,
and its HTTP source validator rejects whitespace even inside quotes. Quoting alone
fixed local decoding but NOT playback API validation. Using the installed approved
binary with only synthetic local sources reproduced HTTP 400 for the quoted runtime
path (`source with spaces may be insecure`); a private space-free scratch path
passed validation (HTTP 200) and local decoding (HTTP 200). No camera destination
or audible request was used in these reproductions.

The departure worker now creates a unique OS scratch directory (0700), verifies its
path is whitespace-free before preparing audio or opening a session, and removes
it after session-scoped cleanup. Persistent state/phrase files stay in their original
private runtime. The source argument is quoted and rejects whitespace, embedded
quote/URL delimiters and control characters. The shared audio module, installed
app, timeouts and onset deadline are unchanged. Offline tests use an
`Application Support` fixture root and assert that playback scratch is private and
outside it. The owner subsequently confirmed audible success (see above). The
unknown-playback latch is never cleared merely by changing source code.

Worker failures write private, attempt-scoped `speaker-diagnostic.json` with fixed
stage/error/reason labels only. No raw transport response, URLs, credentials or
media are logged. An uncertain playback still latches and is never retried. Fixing
source code does not clear the pending attempt or authorize replay.

## Sensor-only trial override (2026-10-01)

The owner explicitly authorized trying foyer motion → door opening without person
confirmation, after being warned about package-pickup/visitor/brief-exit false
farewells. Private `sensor-trial.json` opts into this mode; absent authorization
preserves the person-required behavior below. Malformed authorization fails closed.
Status explicitly reports `person_gate_required: false` and
`owner_authorized_sensor_only_trial`; no person evidence or commissioning is claimed.
The watcher skips person-source binding/history in this mode. An attempt-scoped
sensor proof is checked by the audio worker against current authorization, pending
reservation, enabled state and expiry, including immediately before playback.
Removing authorization invalidates sensor proofs. The 16-second onset deadline,
120-second household cooldown, sensor sequencing, silent baselines, outdoor-only
identity checks, 60% volume, and no replay/uncertain-playback retry remain unchanged.
No setup-time audio test is performed. Historical person-gate policies are preserved.

The supervised silent check obtained a person record approximately 39 seconds after
its recorded start, shortly after its 36-second duration ended. This is evidence of
late history publication in that test, not proof of universal firmware behavior.

## Previous person-gated trial authorization (2026-09-30)

The owner explicitly approved speech **without physical commissioning**, while
retaining the mandatory person-event check. An owner-only private `person-trial.json`
now authorizes code 6 against a freshly resolved source/firmware binding. This is
separate from `person-gate.json`, which remains unchanged and **unverified**.
Status reports `owner_authorized_unverified_trial`, `person_trial_authorized: true`,
`person_gate_verified: false`, and physical verification pending. Delivery may be
enabled in this state; “commissioned” is reserved for a verified policy.

The trial assumes community person-code/bitmask mappings and UTC seconds; latency
and physical departure accuracy are unverified. Motion → opening → fresh person
is still mandatory, with a 10-second check, 16-second onset deadline and 120-second
cooldown. No sensor-only fallback or immediate test playback was added. Revoking
the private trial authorization invalidates trial proofs before playback; the
existing disable command stops future automatic delivery. Malformed authorization
fails closed. Statements below about commissioning-required silence describe the
default mode, without this explicit owner override.

## Retryable sensor-read recovery (2026-09-30)

The SDK's `_RetryableError` is now treated as recoverable during sensor connection
and reads only, alongside transport failures. Each failure closes the session,
invalidates the shared snapshot and resets departure arming. Two reconnect attempts
are allowed with two-second backoff; a third consecutive failed read/connection
latches `sensor_read_requires_review`. Only a successful paired sample resets the
failure count. Existing per-read/connection timeouts remain in force. Authentication,
identity/schema failures and uncertain playback are not retried. Recovery always
starts from a silent baseline; missed openings cannot be replayed.

Private diagnostics record failure count, exhaustion and an SDK-enum device error
code when available, never raw response/exception text. An error without such a
code remains unknown; `_RetryableError` alone does not prove session contention.

## Shared hub contention recovery

Dashboard sensor polling also holds the hub lock. The watcher now retries lock
contention after 0.5 seconds instead of applying the 15-second transport backoff.
It reconnects because another client's hub access can invalidate the old session;
retaining that session failed a live check. Every interrupted sequence is reset,
and the next paired read establishes a silent baseline. Locks are never bypassed,
other services are unchanged, and non-contention faults still fail closed.

A 110-second live check after deployment recovered from contention in about nine
seconds, with no fault or playback. That first repair reduced self-imposed downtime but did not eliminate competing
readers. The later owner-authorized shared-reader deployment below removes the
dashboard's competing sessions; unrelated explicit hub operations can still cause gaps.

### Shared dashboard reader (deployed 2026-09-30)

The watcher atomically publishes owner-only `sensor-snapshot.json` after each valid
paired read. jarvisd opts in through `JARVISD_SECURITY_SHARED_SNAPSHOT`; both its
background poller and authenticated sensor-status endpoint use this same snapshot
for `motion-sensor` and `door-sensor`. They never fall back to hub access when the
snapshot is missing, malformed or stale. Other aliases retain their existing path.

Snapshots preserve the actual observation time, require matching wall/monotonic
ages no greater than eight seconds, and retain unknown radio freshness. Battery
and RSSI are currently unavailable rather than invented. The snapshot is removed
on interruption, disabled/faulted state and normal shutdown; abrupt death expires
by age. Disabling the departure watcher therefore also makes these dashboard
sensor readings unavailable. Departure decisions never consume this file.

Deployment `20260930T180949Z-shared-sensor-reader` copies the prior installed daemon
release and changes only `security_status.py` plus new `security_snapshot.py`.
The private launch plist backup and deployment audit are in the trial runtime.
A 150-second live check returned 264/264 HTTP 200 shared-snapshot responses, observed
57 paired samples, maximum sample gap 3.244 seconds and maximum response sample age
2.885 seconds. No hub contention, fault, candidate or playback occurred in that
window. This is a continuity check, not physical departure/audio commissioning.

## Owner-authorized audible trial

On 2026-09-29 the owner explicitly requested background activation for testing the
next day, initially specifying **“Have a good trip, sir.”** On 2026-09-30 the owner
changed the phrase to **“Have a good day, sir”**; the private WAV and hash metadata
were replaced without test playback. The installer opts in to an **experimental
audible trial**, not a claim of physically verified departure detection. The owner subsequently requested **24/7 operation**, with no
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
- Mandatory fresh **person** event, strictly after the observed door opening. In
  the explicitly authorized unverified trial, code 6 is bound to the live source but
  relies on a community mapping; this is not commissioning. No old/ongoing event,
  generic motion, or unreadable response can authorize speech. Same-second records
  are ambiguous.
- Person-event checks have an owner-requested **10 s total budget**, including
  at most ten explicit getters spaced 1 s apart; each getter remains capped at 2 s.
  The overall voice-onset deadline is **16 s from the observed opening**, preserving
  six seconds of audio setup/padding headroom. Gate time never extends that deadline.
- Audible eligibility **24/7**, including overnight; no quiet-hours restriction.
- Digital playback gain **60%**, consistent with earlier owner-confirmed D235 voice
  playback. Persistent camera speaker settings/saved CLI defaults are unchanged.
- New samples must be complete; reads over 2 s, sample gaps over 8 s, unknown states,
  duplicate/out-of-order samples, or clock discontinuities break continuity.
- No queued/backfilled greetings or speech past expiry. At most 16 s from the observed door edge to
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
The reader now accepts this H200's `alarm_type` + `events_1` schema as well as
single-code `event_type` rows. Multi-label flags normalize to individual alarm codes:
bit n means code n+1, limited to the documented 1–16 range. Missing/malformed flags,
unknown bits, a primary alarm absent from its flags, or conflicting `event_type`
fail closed. There is no fallback to a primary package/motion alarm as person evidence.
A live read of the owner-identified archived event decoded codes 2, 6 and 15
(motion/person/package under community mappings); offline tests cover combined labels
and rejection paths. This verifies parsing, **not** fresh publication latency or departure.
Supervised person mapping/timing verification is still required; the policy stays unverified.
References: [playback codes](https://github.com/JurajNyiri/pytapo/issues/199),
[bitmask](https://github.com/PeterkoCZ91/tapo-monitoring/blob/main/docs/events1-bitmask.md).

At an owner-supervised test, run `person-preview` below and have someone walk outside
into the doorbell's view, noting the exact time and the corresponding Tapo-app person
label. Compare against separate generic motion/package activity. Verify the event
code, UTC-second time basis, source binding and whether records appear within the
10 s gate budget while leaving enough of the 16 s deadline for audio startup. Completed
archive records may arrive too late: in that case this source is unsuitable and
must remain unverified. Do not loosen freshness or play an old event as a workaround.

Only after that review populate the owner-only `person-gate.json` verification record
with the observed `person_code`, preview `binding`, `timestamp_basis` of
`unix_utc_seconds`, aware ISO `verified_at`, and `verified: true`. Its other keys are
`version: 1` and `source: h200_detection_history`. There is deliberately no automatic
commission/enable command or guessed mapping. Missing/invalid policy cannot revert
to sensor-only speech. Revalidate after firmware, camera or hub changes; identity and
reported firmware participate in the binding, but unreported changes need manual review.

An earlier `sensor_read_requires_review` fault was cleared only after owner-authorized
review and fresh paired reads; cooldown, outcome, counters, configuration and the
unverified person policy were preserved. A later SDK `_RetryableError` during a
paired read was initially latched because it was not recognized as retryable. The
watcher now performs at most two bounded reconnect attempts, resets departure arming,
and latches review after three consecutive failures. After owner-authorized recovery,
the watcher returned to a silent baseline; current trial authorization remains
separate from physical commissioning. No greeting has been sent. Unknown/pending
playback state must never be cleared as a sensor-read recovery.

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
Poll delay is 2 s after a completed read, with no catch-up loop. Hub-lock contention
resets continuity and retries after 0.5 s. Retryable transport/read failures close the
session, invalidate the shared snapshot, reset departure arming and reconnect after
2 s; the third consecutive failure latches review. Credentials, identity, child
schema/selection, and other unexpected failures latch immediately. There is no
automatic authentication recovery.

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

## Limitations / supervised trial test

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

The owner has separately authorized an audible trial while the person mapping,
timing, radio freshness and departure accuracy remain unverified. This does not
commission the gate; false farewells and missed departures remain possible. For each
supervised trial, start indoors with the door closed and foyer motion clear, walk into
the foyer, pause about 2 seconds, then open the door and step outside. Stay in
doorbell view and earshot for up to 16 seconds; allow at least 120 seconds between
attempts. Review the private event/outcome record afterward and do not replay a missed
or uncertain greeting. If performing formal commissioning, follow the separate
silent person-event preview procedure above.

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

Tests are offline with synthetic fixtures and mocked network/speaker operations.
Run the suites for current totals; shared security work may add unrelated tests.
Gate coverage includes absent/unverified policy, exact-type/identity matching,
old/same-second/unknown/empty/truncated events, finite deadlines, private proof
validation/revocation, cancellation/pending safety and no sensor-only fallback.
Timeout coverage includes person publication beyond the former eight-second deadline,
bounded polling/slow-read suppression, rejection of old-deadline proofs, and matching
coordinator/worker onset and process budgets.

Initial deployment checks verified the agent and paired sensor reads. Radio freshness
remains unknown; physical person mapping/timing remain unverified.
Connection diagnostics later found the H200 at a different LAN address. With owner
approval, only `JARVIS_SECURITY_HUB_HOST` in the ignored private `.env` was corrected.
Three paired reads through the saved configuration then succeeded; all other env
lines and private permissions were unchanged. That address-only repair did not clear
the fault. A later owner-authorized review cleared it after bounded retry recovery;
the person gate remains unverified while the separate audible-trial authorization
remains active. No greeting has been sent. Only the trial agent and jarvisd shared
reader were reloaded; other security services and shared CLI/audio behavior are
unchanged. A supervised test is still required before treating physical event mapping
or departure accuracy as commissioned.

- `departure.py`: policy, bounded silent observer, local status/disable command.
- `watcher.py`: singleton background reader and guarded delivery coordinator.
- `speaker.py`: one expiring, reserved farewell through the outdoor D235 only.
- `runtime.py`: private configuration, durable journal/cooldown/fault state.
- `person_gate.py`: mandatory commissioned event source, bounded reads and proof;
  explicit metadata-only commissioning preview.
- `install.py`: explicit new-agent installation and offline phrase preparation.
- `departure`: isolated Python-interpreter launcher.
- `tests/`: offline policy, adapter, private-state, and delivery-safety checks.
