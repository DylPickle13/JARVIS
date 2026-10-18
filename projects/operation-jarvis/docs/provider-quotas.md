# Codex and Claude subscription trackers

## Scope

Source implementation adds Claude **alongside** Codex, not in place of it:

- Separate iPhone and Watch cards, weekly as the main gauge, five-hour below.
- Neural Core retains its pre-Claude Codex-only appearance and behaviour. The
  owner requested removal of the added widget readouts/ring; that source reversal
  is installed on iPhone in build 262. App cards and Pi-desk remain separate.
- Both providers' weekly/five-hour percentages and reset countdowns in Pi-desk,
  visible without clicking. Narrow viewers use additional compact status rows.
- Claude exposes only overall weekly and five-hour windows, not Opus/Sonnet
  allowances, extra-usage billing, or account data.

Native **build 262 is wirelessly installed and version/process verified on iPhone**
as of **2026-10-17 19:13 EDT**. Watch was last independently verified at 261
(17:27 EDT); it was not targeted by the 262 deployment, and automatic companion
delivery was not queried. The backend collector is **live and verified**
(17:39 EDT), and quota-only Pi-desk updates are installed on all three hosts
(17:44 EDT). **Close/reopen all existing Pi Desk viewers on mac-mini-64** to load
the new renderer; agents remain running. Physical native/widget acceptance is
still owner review.
Building/testing source does **not** deploy it or authorize service restarts.
Earlier deployment-history entries describe earlier releases.

## Claude OAuth refresh repair — deployed 2026-10-18 EDT

Release `20261018T214000Z-claude-node-refresh` was installed and verified at
**17:43 EDT**. The Python refresh transport reproduced HTTP 403 / Cloudflare
1010 (`browser_signature_banned`); Pi's normal Node request reached OAuth.
The original incident response was not retained, so the historical cause remains
strongly supported rather than proven.

`quotas/anthropic-refresh.mjs` now uses Pi's Node fetch request shape, without
importing Pi's mutable extension or its retry policy. One request, no redirects,
15-second network timeout and 18-second parent deadline; no fallback/retry within
an attempt. Tokens travel through private subprocess pipes, never command-line
arguments. Node must be available on the service PATH (verified on this host).
The existing Python heartbeat lock, locked reread, ownership check and atomic
credential save remain unchanged. The helper validates token responses and
retains the original refresh token when the provider omits a replacement.
Only allowlisted failure stage/code/HTTP status reaches the daemon; provider
bodies and arbitrary errors are discarded. Usage-429 backoff is unchanged.

The installed-baseline candidate passed **881 backend, 13 quota/auth, 4 Node
helper and 84 SDK safety tests**. The larger checkout passed 1,013 backend tests.
An initial preflight stopped without service changes because the copied baseline
guard named an older release; the exact baseline assertion was corrected before
a separately recorded deployment attempt. Backend liveness returned in **0.330 s**;
Codex and Claude were fresh, all 27 device identities were preserved, and no
unrelated service/Pi/Minecraft identity changed. History, configuration and the
shared auth file remained unchanged. No forced live OAuth renewal was performed:
successful real-token renewal remains to be observed at its normal deadline.

The preceding `20261018T003031Z-claude-shared-cooldown-r2` source and daemon/watchdog
plists are retained. A separately authorized rollback must use the same quiet-state,
configuration/history preservation and authenticated readiness checks; do not
replay either one-use deployment helper. No app or household-device writes occurred.

## Data flow and contracts

```text
Pi anthropic OAuth credential
  -> quotas/quotas.py claude --json
  -> jarvisd claudeQuota single-flight collector
  -> /api/v1/state subsystems.claudeQuota
     -> JARVISKit -> iPhone / Watch / WidgetKit caches
     -> pi-desk/status_stream.py -> core.py -> provider_quotas.py / desktop.py
```

`quotas.py` reads `GET https://api.anthropic.com/api/oauth/usage` and normalizes
`seven_day` / `five_hour` utilization into the existing bounded quota window shape.
A combined `check` report adds `providers.anthropic`. The `claude` subcommand is
usage-only: it does not require a model catalog and has no probe option.
Neither command makes Claude model requests or changes extra-usage settings.

OAuth refresh matches Pi's installed Anthropic extension. The shared auth lock
has a heartbeat shorter than Pi's stale-lock threshold. Claude rechecks lock
ownership before atomically saving refreshed credentials, preserves unrelated
providers, and sanitizes OAuth/provider errors. `--no-refresh` performs no
credential write. Provider requests have 15-second timeouts; Claude's lock wait
is bounded to 10 seconds, and the Node refresh subprocess to 18 seconds, within
the default 45-second daemon subprocess deadline.

The daemon invokes fixed local commands, not the saved `latest.json` report.
`claudeQuota` and `codexQuota` are independently non-critical and cached at:

| Policy | Codex seconds | Claude seconds |
| --- | ---: | ---: |
| Active collection | 60 | 120 |
| Idle collection | 300 | 300 |
| Freshness limit | 900 | 900 |

Claude's active polling is two minutes (owner-requested reduction from one minute),
deployed at **20:21 EDT on 2026-10-17** as
`20261018T001936Z-claude-two-minute-polling`. The installed-baseline release changed
only the interval and its regression tests; **868 backend, 9 quota/auth and 84 SDK
tests passed**. Backend/watchdog cutover reached liveness in **0.365 s**, preserving
configuration, repaired registry, history and unrelated service/session identities.
The first Claude collection was unavailable; the owner subsequently confirmed the
Pi-desk reading returned. This does not establish that future rate limits are
eliminated. Exact prior release/plists remain retained.
That first interval-only rollout did not gate explicit refreshes; the owner later
reported intermittent staleness again. It is superseded by the shared cooldown below.

### Shared Claude cooldown — deployed 2026-10-17 EDT

Release `20261018T003031Z-claude-shared-cooldown-r2` activated at **20:33 EDT**.
All Claude collections within the shared backend now obey a **120-second minimum
after completion**, including explicit iPhone/Watch refreshes, active wakeups,
failed attempts and superseded results. Requests during collection coalesce;
the scheduler checks the same monotonic cooldown immediately before dispatch.

HTTP 429 is passed from the usage CLI as sanitized structured metadata, not a
provider body, account detail or credential. The CLI's structured failure exit
code is **2**; the collector preserves only the rate-limit flag and bounded delay.
429 waits increase **300 → 600 → 1,200 → 1,800 seconds** until a successful check
resets the backoff. A longer valid `Retry-After` (seconds or HTTP date) takes
precedence, bounded to 86,400 seconds. Zero, missing or malformed hints cannot
shorten the local backoff. Other failures retain the two-minute minimum.

Codex, Claude's five-minute idle cadence and 15-minute freshness limit are unchanged.
Last-good timestamps and failure/stale indicators remain honest; cooldown does not
make old data fresh. Pi-desk only reads the shared cache. The cooldown is in-memory
and resets on backend restart; standalone CLI checks and other applications are
outside this backend's request budget.

The 613-input installed-baseline candidate passed **880 backend, 12 quota/auth and
84 SDK tests**, including a synthetic HTTP-429 → CLI → collector → scheduler
contract. Only Claude-scoped files were layered over the installed baseline.
The first candidate was not deployed: a layout test caught an unrelated checkout
scheduler-default difference; r2 preserved the installed default with a scoped
patch. Both records remain retained.

Backend/watchdog cutover reached liveness in **0.336 s**; authentication, repaired
27-device registry, history/events, unrelated services, Pi panes and Minecraft
identities were preserved. The initial live Claude response was rate-limited and
correctly entered cooldown; deployment does not establish provider recovery.
Two authenticated cached diagnostic reads, **125 seconds apart**, verified that
Claude's attempt count stayed at one and the daemon PID was unchanged. The current
checkout also passed **997 backend tests**; its larger suite includes unrelated
previously committed work not layered into the installed baseline.
No forced quota refresh, model probe, physical command, app reinstall or Pi
session restart was performed. Exact prior release/plists remain available for
a separately authorized guarded rollback.

A failed collection preserves its last-good data with stale/error metadata; it
must not mark household controls stale. Public Claude data is whitelisted to
weekly/five-hour windows, timestamps, enforcement and exhaustion status.
`JARVISD_CLAUDE_QUOTAS_SCRIPT` overrides the trusted script path;
`JARVISD_CLAUDE_QUOTA_TIMEOUT` overrides its bounded timeout. Output is limited
to 64 KiB before decoding/projection.

Authenticated foreground apps request both collectors in one GET:

```text
/api/v1/state?refresh=codexQuota&refresh=claudeQuota
```

The older Codex-only client method and wire field remain supported. Older
snapshots decode with Claude absent; absence is shown as unknown/unavailable,
never 100%. Watch convergence waits for both collectors, with bounded follow-ups.
Passive pages and widgets remain cache readers. The widget reversal restores the
original reload comparison: provider-only changes do not add new reload triggers.
Claude remains in the shared snapshot for app cards, but Neural Core ignores it.

## Presentation

All percentages represent **remaining** quota. Weekly is primary and five-hour
secondary. Critical colouring is per value below 30%, using the existing palette.
The two accounts never share a minimum/combined gauge. Absolute reset timestamps
produce countdowns; passing a reset time never implies that quota has refilled.

Pi-desk example (illustrative values):

```text
Codex W:68%↻2d 5h:91%↻48m · Claude W:98%↻2d 5h:20%↻48m
```

Provider names may shorten to `Cx` / `Cl`. Hints yield before quota. When the
complete pair cannot fit beside session tabs, viewers add one quota row, or a
row per provider on narrower displays. Warnings keep their own row and pane
identities/focus do not change. Supported 40+ column layouts preserve both windows
and resets; physically narrower displays clip safely. A suffix `p` marks Codex's
paused five-hour enforcement; it is tracking, not an enforced limit. Stale or
unavailable providers suppress old percentages independently.

The optional legacy click detail remains, but is not needed to see usage/resets.
The host status stream retains numeric session keys and adds `claudeQuota` beside
`codexQuota`. No credentials or provider calls reach remote Pi-desk viewers.

## Main implementation paths

- `quotas/quotas.py`, `quotas/test_claude_quota.py`
- `jarvisd/jarvisd.py`, `jarvisd/jarvisd_core/{state,system_health}.py`
- `jarvis-app/JARVISKit/Sources/JARVISKit/{Models,JarvisClient,RefreshPolicy,SystemHealthPresentation,SystemVisualSummary}.swift`
- `jarvis-app/JARVIS/{AppState.swift,Views/HomeView.swift}`
- `jarvis-app/JARVISWatch/Views/{WatchConnectView,WatchDashboardContent}.swift`
- Neural Core's artwork/animation/telemetry files are restored to exact build-260 source in build 262 (installed on iPhone).
- `pi-desk/{provider_quotas,status_stream,core,desktop,install}.py`

## Verification / rollout

Offline quota/auth, daemon HTTP/cache, JARVISKit, Pi-desk and isolated-tmux tests
cover sanitization, old snapshots, partial windows, failures, independent expiry,
refresh routing, layout resizing and pane preservation. Native verification also
checks the restored original frozen/live artwork and builds iOS/watchOS targets.
A live `claude --no-refresh --json` read can verify the data source without a
model call or token refresh. Real-device visual acceptance remains separate.

### Neural Core reversal — build 262 installed on iPhone

After the owner requested removal of all Neural Core widget changes, the shared
artwork, continuous-animation wrapper, telemetry and render fixture were restored
**byte-for-byte to retained build 260**. The added provider readouts, second quota
ring, five-hour/reset labels, changed accessibility summary and quota-specific
reload comparison are removed. Original Codex ring, animation and refresh behaviour
are retained. Claude app cards, foreground refresh, backend and Pi-desk are unchanged.

Candidate **262** is frozen from exact installed 261, with only nine scoped
source/test/version changes; the other 261 inputs are byte-identical. At
**18:53 EDT, 2026-10-17**, validation/audit passed **202 iPhone tests, 353 shared
cases (3 expected skips), 39 terminal cases, 2,316 artwork assertions**, both
simulator builds and the signed Release archive. All eight candidate/rollback
signatures passed; profiles, entitlements, dependency lock and source/payload
seals are unchanged/verified. The owned validation simulator is shut down.

After owner authorization **“you can deploy to it wirelessly now”**, a new
iPhone-only guarded attempt passed wireless (`localNetwork`) identity, compatible
DDI, unlocked state and installed-261 checks, then repeated immediate gates.
**262 installed once on iPhone and was independently version/process verified
at 19:13 EDT, 2026-10-17**, including a final installed-version readback.

Source/payload seals and all eight candidate/rollback signatures passed again.
All **18 protected service records (17 continuous)** had no protected PID changes;
Pi/Minecraft identities, current provider-quota backend, repaired registry,
authentication and ten-second history cadence were preserved. No backend rollout,
service restart, terminal input, credentials/profile change or retry occurred.
No direct Watch action occurred; automatic companion delivery was not queried.
Physical widget appearance remains owner review.

Exact signed 261 and older 260 remain retained. Private evidence:
`signing-renewal/artifacts/20261017T224820Z-build262-neural-core-restore/`,
`deployment-20261017T231050Z/result.json` and
`final-deployment-verification.json`. Do not rebuild or replay the completed installer.

### Backend and Pi-desk — deployed 2026-10-17

After separate owner authorization, backend `20261017T213141Z-provider-quotas` activated
at **17:39 EDT**. Only the six quota-related source/test deltas and two new tests
were layered onto the exact installed baseline (612 frozen inputs); unrelated
working-tree changes were excluded. **867 backend tests, 9 quota/auth tests and
84 SDK safety tests passed.** The daemon reached liveness in **0.378 s** with its
existing watchdog coordinated/restored. Authenticated readback verified both
provider caches fresh, both health components, unchanged 27-device inventory,
configuration/authentication, Pi/Minecraft identities, SQLite history identities,
500 retained event bodies and ten-second cadence. No unrelated service PID changed.
The verified October 11 address-repair registry and Codex/monitoring configuration
were preserved. No model probes, physical commands or native reinstall occurred.

At **17:44 EDT**, quota-only Pi-desk files/manifest entries were installed on
**mac-mini-64, mac-mini-16 and raspberrypi**, with per-host rollback copies.
Only `core.py`, `desktop.py`, `status_stream.py`, `provider_quotas.py` and
`install.py` changed; no full installer was run. Host-specific older runtime
differences, the main Mac's patched private tmux, transport/restart behavior,
configurations, launchers, unrelated files and manifest entries were preserved.
The local staged suite passed **220 tests**; each actual remote host passed
**44 focused quota/isolated-tmux tests**. The installed host feed independently
returned ten fresh sessions and live Codex/Claude data with inline reset countdowns.

**Viewer activation remains:** close/detach all existing Pi Desk viewers on
mac-mini-64, then reopen `pi-desk`. Its 13 existing viewer/attachment/feed process
identities were intentionally preserved; the already-running Python monitor cannot
load the new renderer until reopened. No remote Pi-desk viewer was active; updated
files load on next opening. No agent restart, viewer signal, terminal input or
GUI focus/Space switch was performed. Physical UI acceptance remains separate.

Backend evidence/rollback: `jarvisd/deployments/20261017T213141Z-provider-quotas` in private
Application Support. Per-host Pi-desk rollback:
`~/.local/state/pi-desk/backups/provider-quotas-20261017T213141Z/`.
Earlier stopped native attempts and exact signed build-260 rollback remain retained.

### Build 261 — installed on both devices (2026-10-17)

The following records validation and retained failed attempts before the successful
17:27 EDT installation.

Xcode 27.1 setup completed; Metal 32023.921 runs and CoreSimulator now reports
the matching 1174.9.2 version. No explicit component download was needed.
The isolated 270-input build-261 candidate passed 202 iPhone tests (the existing
plain-Paste pixel exclusion is unchanged), 353 shared tests (three expected live
skips), 39 terminal tests and both simulator builds. The Release archive and exact
signed build-260 rollback passed all eight bundle signature audits, with unchanged
profiles, entitlements and pinned dependencies. Candidate source/payload seals passed.

The allowlisted iPhone passed identity/DDI/unlock/inventory checks at installed
build 260. Watch identity/DDI passed, but its unlock-state read stopped on Apple's
RSD resource-allocation error `-402653181`; its installed baseline was therefore
not rechecked. This was not evidence that the Watch was locked. No app-install
attempt, launch, live JARVIS-service restart, connection reset or retry followed.
A fresh owner readiness response and all immediate gates are required before
installation. Backend collector activation and installed Pi-desk rollout also
remain pending; this native candidate does not activate them.

After a fresh owner **ready**, a separate check at 17:06–17:07 EDT again verified
iPhone readiness/build 260. The Watch DDI query stopped on Bluetooth tunnel
invalidation (L2CAP open-channel failure), before unlock/inventory or any app write.
No install, launch, connection reset or automatic failed-check replay occurred.

After owner **“try watch again now”**, a new **17:10 EDT** preflight passed both
devices' identity/DDI/unlock/inventory checks at **260**. The first installer
stopped before writes on an outdated backend-configuration baseline. Read-only
reconciliation verified the October 11 address-only repair (registry path and
three host values); the replacement helper pinned the current exact hashes and
preserved the original stopped attempt without changing any live configuration.
Its backend and iPhone gates passed, but Watch's repeat unlock-state read stopped
at **17:16 EDT** on RSD allocation error **-402653181**. Neither app was installed
or launched. Post-stop backend/config/authentication, registry, Minecraft identity
and history-cadence checks passed. No reset/restart/failed-device-gate replay was
performed. New owner scope/readiness is required before another device attempt.

A further owner **“try again now”** authorized a new integrated guarded attempt
at **17:19–17:20 EDT**. Watch identity, compatible DDI and **unlocked** state passed,
but installed-app inventory failed when the Bluetooth developer tunnel dropped
(`RemotePairingError 1007`, transport Read EOF `-6753`). The attempt stopped
before the iPhone checks and before any app install/launch. Post-stop backend
preservation checks passed. No failed helper/check was replayed, no connection
was reset and no service was restarted. A fresh owner decision remains required.

After the owner restarted the Watch and said **“ready, try now”**, a new
one-shot attempt at **17:24–17:27 EDT** passed both-device readiness and every
immediate per-target gate. **Build 261 was installed once on each iPhone and
Watch**, with independent installed-version and running-process verification
on both, including final version readbacks. Candidate/rollback seals, 270 frozen
inputs and all eight bundle signatures passed again.

All **18 protected service records** (17 continuous), existing Pi panes,
Minecraft/gateway identities, backend source/configuration/authentication,
the verified address-repair registry and ten-second history cadence were
preserved. No service restart, terminal input, credential/profile/dependency
change, failed-write replay or cleanup occurred. Exact signed **260** remains
rollback and every earlier failure receipt is retained. Physical quota layout,
widgets and VoiceOver acceptance remain owner review. Backend/Pi-desk deployment
was separate and completed later under fresh owner authorization, as recorded above.

Private evidence: `20261017T205400Z-build261-provider-quotas`, final receipt
`deployment-20261017T212425Z/result.json`. All failed/successful readiness receipts,
stopped installer receipts and exact build-260 rollback are retained.

### Initial verification, before tooling repair (2026-10-17)

- 9 quota/auth tests, 984 daemon tests and 220 Pi-desk tests passed.
- JARVISKit: 353 tests executed, 3 expected live-test skips, no failures.
- 2,316 native artwork assertions passed; phone and smallest Watch renders reviewed.
- Standalone Watch simulator target built successfully (including its widget).
- Live Claude usage-only read succeeded with `--no-refresh`.
- Full iPhone build is blocked by Xcode's missing optional Metal toolchain.
  CoreSimulator also reports an older running service version than this Xcode.
  iPhone simulator tests and real-device acceptance are not claimed. No tooling
  installation, simulator-service repair, live-service restart or device deployment
  was performed.

Remaining acceptance: reopen the existing Pi Desk viewers to activate the installed
renderer, and review real iPhone/Watch/widget presentation. Do not restart hosted
Pi agents to update this tracker. Backend, Pi-desk file installs and native 261
are verified; do not replay their completed installers. Keep rollback evidence.
