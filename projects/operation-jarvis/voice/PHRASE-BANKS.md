# Pre-rendered announcement banks

Implementation is **opt-in**. The owner approved all 84 texts and the measured
recording lengths, including the 38 initially flagged clips, for staged deployment.
The 84 texts in
`phrase_catalogue.json` match the owner-approved `PHRASE-BANKS-DRAFT.md`:
24 wake, 24 processing (including steering), 12 arrival, 24 departure.
Each complete selection cycle is half straight and half dry humour. This is not
live model-generated wording. Fixed errors and ordinary responses are excluded.

## Assets and selection

- `render_phrase_banks.py` uses the existing voice configuration and locally cached
  Piper model only. It does not initialize a voice session, download, play audio,
  change runtime configuration, or restart a service. Output must be a new directory.
- Raw WAVs have no route padding. Manifest entries bind stable ID, exact approved
  text, WAV SHA-256, duration, format, quality checks, and voice-settings fingerprint.
  Model and model-config hashes are recorded as provenance.
- A bundle is usable only with an exact manifest hash, `reviewed: true`, all expected
  entries, valid private files, and per-event duration limits. Room voice settings
  must match the render settings. A corrupt/missing enabled bundle fails startup;
  departure validation fails before playback. No live synthesis fallback.
- Room servers preload validated audio and padded base64. Wake padding and ordinary
  room padding retain their existing separate settings. Sync/steering paths receive
  disposable raw WAV copies, never master paths; existing playback adds its padding.
- `phrase_banks.Selector` uses a shared private SQLite DB at
  `~/Library/Application Support/JARVIS/phrase-banks/selection.sqlite3`.
  SQLite transactions reserve entries durably before dispatch; no new daemon.
- Each bank is shuffled without replacement. The next cycle cannot begin with the
  previous cycle's final ID. No forced straight/dry alternation. Both rooms share
  progress, and restart does not reset it. Finite banks eventually recycle.
- Event keys suppress duplicate dispatch; claims are retained for seven days. Event
  IDs must be fresh random IDs, never intentionally reused. Cancellation/uncertain
  delivery may consume an entry; the ratio applies to *reservations*, not guaranteed
  audible output. Claims and cycle progress commit together.
- A 25 ms SQLite lock-wait bound is not a total I/O latency guarantee. Selection
  storage errors suppress that announcement, with a room health failure counter.
  This deliberately prefers silence to a potentially repeated canonical fallback.
  Original lines remain the explicit rollback behavior, not an uncertainty retry.
- Catalogue changes require a reviewed state migration. Never clear state as an
  automatic recovery mechanism. There is no automatic retry on corruption/contention.

## Room integration

Disabled by default. An approved deployment supplies both:

```dotenv
JARVIS_ROOM_PHRASE_BANK_DIR=/absolute/path/to/reviewed/private/bundle
JARVIS_ROOM_PHRASE_BANK_SHA256=<SHA-256 of exact manifest.json bytes>
```

These settings are installation-local; they are never enabled by source checkout alone.
`/health` exposes `phraseBanks` with configuration, counts, manifest hash, selection
failure count and whether processing has an override. Status/warm-up do not select.

Existing switches still apply. Disabled or blank processing text stays silent;
a custom noncanonical processing override retains its existing synthesis path and
**opts out** of processing-bank variation (including steering). The no-live-synthesis
promise applies to bank-selected announcements, not deliberately retained custom
text or ordinary answers. Disabled arrivals do not affect wake acknowledgements.

Wake selection follows verification; rejected/cancelled/duplicate wakes do not
advance a bank. Async processing selection follows job reservation and cancellation
checks. A second cancellation check suppresses audio if stop races selection.
Steering checks generation/cancellation both before and after preparing its copy.

Arrival keeps the existing owner-authorized request, idle-client admission,
at-most-once notice, cancellation and timeout behavior. The client sends its unique
arrival turn as `x-jarvis-arrival-id` to `/arrival-audio`; bank-enabled servers require
this ID. Update the client before enabling the server bank. No automatic HTTP retry.
Legacy connection `/greeting` remains silent. Startup, reconnect, quick-return and
time-of-day greetings remain removed. Watch/operator speech is not randomized.

## Protected farewell integration

Separate opt-in: a private (0600) `phrase-bank.json` under the existing departure
runtime root, with exactly:

```json
{"version": 1, "bundle": "/absolute/path/to/reviewed/private/bundle", "manifest_sha256": "<exact manifest SHA-256>"}
```

**Do not create this file until deployment is separately approved.** Its absence
keeps the original exact `runtime.PHRASE` / `phrase.wav` / `phrase.json` validation.
`phrase_bank_configured` in departure status only reports the pin file's existence;
it does not certify the bundle or physical delivery. The legacy `phrase` status
field continues to describe the rollback/default phrase.

The worker still accepts only `attempt` and `expires`, never caller-provided text,
phrase IDs, URLs, or audio paths. It selects only after checking the existing
pending journal, enabled/fault state, proof and device binding. The selected clip
and manifest hash are durably recorded against that attempt in
`phrase-selection.json`. Repeated worker attempts cannot reserve another clip.

Bundle validation preserves a **hard 4.5-second raw farewell limit**, even if a
manifest requests a larger duration. Validated in-memory bytes are copied into the
existing private scratch directory. The original identity checks, hub/device locks,
volume, doorbell padding, onset deadline, one-shot playback and unknown-outcome
latch remain authoritative. Broken enabled banks do not silently fall back.
Loading/selection time counts against the existing expiry; no deadline extension.

## Build, review, deploy

From the repository root, offline rendering (no playback):

```sh
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  projects/operation-jarvis/.venv/bin/python \
  projects/operation-jarvis/voice/render_phrase_banks.py \
  --output "$HOME/Library/Application Support/JARVIS/phrase-banks/NEW-STAGING-DIRECTORY"
```

The builder writes `manifest.json` with `reviewed: false` and a separate
`duration-report.json`. Its provisional tolerance is a canonical same-settings
render plus the larger of 0.5 seconds or 25%; departure is also capped at 4.5 seconds.
These tolerances are review aids, **not owner-approved expanded duration budgets**.
Do not shorten text, change speed, drop candidates (breaking balance), or widen
limits automatically. Resolve flagged durations with the owner first.

Automated checks detect malformed/truncated WAV containers, empty/silent output
and hard sample clipping. They do not establish pronunciation, naturalness,
phonetic truncation, live cached-clip equivalence or physical audibility. Review
playback requires separate permission; no diagnostic household audio is automatic.

Only after approval: finalize the duration limits and review marker, validate the
bundle against each consumer's effective configuration, pin the final manifest
hash, and publish the source-only change before activation. WAVs/manifests/state
stay outside Git. Health checks must be read-only, not test announcements.

Roll out rooms first while idle, preserving Session 10/history/shared wake. Activate
farewell separately after validating assets and pending/fault state. Never clear a
pending attempt or fault to enable a bank. Rollback removes the room opt-in settings
and, separately, the farewell pin under an approved maintenance window; preserve
selector history, protected legacy recording/metadata, journal and latches.

## Offline tests

New tests cover catalogue balance, asset integrity, settings/review pins, malformed
WAVs, duration caps, permission/symlink checks, cycle boundaries, persistence,
thread/process concurrency, duplicates, bounded contention, silent warm-up/status,
room switches, matching text/audio, disposable copies, steering cancellation,
arrival deduplication and protected farewell proof/deadline/unknown outcomes.
All inference, sessions and household playback in integration tests are mocked.

## Implementation validation result

- **331 offline tests passed:** 56 voice, 163 room-audio, 112 departure (39 new
  regressions above the prior 292). `git diff --check` passed.
- All **84 WAVs rendered** with unchanged effective voice settings, cached models
  only, and no playback. The original `staging-84-v1` bundle retains its unreviewed
  build record. An independently validated `approved-84-v1` copy under
  `~/Library/Application Support/JARVIS/phrase-banks/` records owner approval.
- All files passed format/frame-count checks; no silent outputs or hard sample
  clipping were detected. No farewell exceeded its protected 4.5-second cap.
- 500 uncontended synthetic offline reservations measured **0.340 ms median,
  0.518 ms p95, 1.862 ms maximum** on this Mac. These exclude rendering, startup,
  network, audio device wake-up and physical playback; they are not an SLA.

| Bank | Default raw render | Candidate raw range | Provisional limit | Flagged |
| --- | ---: | ---: | ---: | ---: |
| Wake | 0.673 s | 0.673–2.380 s | 1.173 s | 19 / 24 |
| Processing | 1.730 s | 0.952–2.543 s | 2.230 s | 6 / 24 |
| Arrival | 1.161 s | 0.952–2.415 s | 1.661 s | 5 / 12 |
| Departure | 1.289 s | 0.987–2.763 s | 1.789 s | 8 / 24 |

The existing protected farewell metadata reports **1.265 s**, close to the new
1.289-second canonical render. The room baselines above are fresh same-settings
renders, **not measurements of the currently cached live room clips**. Piper's
stochastic voice settings can vary duration slightly between renders.

**Owner decision: approved.** Keep all 84 recordings unchanged, including the 38
provisional duration flags. The approved bundle's raw duration ceilings are rounded
up to the next millisecond from the existing maximum in each bank: wake **2.381 s**,
processing **2.543 s**, arrival **2.415 s**, departure **2.764 s**. The independent
hard farewell cap remains 4.5 seconds. No wording, speed, volume or padding changes.

Approval covers the reported durations and wording, not a claim of audio audition
or physical playback verification. Publication must precede activation. Roll out
the two room endpoints first and the farewell pin separately, retaining Session 10,
its history, shared wake, and all pending/fault latches. No test announcements.
