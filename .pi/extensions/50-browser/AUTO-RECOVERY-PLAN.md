# Verified browser auto-recovery — implementation plan

**Status (2026-10-09): deployed in observation mode; supervised live checks passed;
final visual acknowledgment and scoped restoration approval pending.** See
[VERIFIED-RECOVERY-LIVE.md](VERIFIED-RECOVERY-LIVE.md) for the 122 offline checks,
800 unchanged focus/Space samples, private SDK fault results, and current state.
The bridge is deliberately unloaded after the negative fixture; its completed
synthetic wait record remains fenced. Production `verified-only` recovery is not
yet enabled. Chrome, its profile, installed extension/helper, public tool defaults
and stock fallback policy were preserved. No uncertain action was replayed.

The isolated `browser/verified-recovery-offline` branch preserves implementation
provenance. See [VERIFIED-RECOVERY-CANDIDATE.md](VERIFIED-RECOVERY-CANDIDATE.md) for
execution-proof, journal, recovery scope, and rollout/rollback constraints.

## Goal

Make safe background recovery automatic, without asking sir to approve routine
reconnection or known-tab recovery. Ask only when execution cannot be established,
recovery would be disruptive, or manual window placement is required.

This is recovery of browser control, not permission to repeat actions or authorize
account, private-data, purchase, destructive, or submission work.

## Findings verified in the current implementation

- `action-policy.mjs` uses a 15 s scroll deadline, 30 s explicit zero-delay field
  replacement deadline, and 150 s deadline for other MCP requests. These bound the
  caller's wait, not execution cancellation.
- MCP SDK 1.30.0 sends `notifications/cancelled` when its request deadline expires,
  deletes the response handler, and suppresses the eventual server reply when the
  server's abort signal is set. Watching late RPC responses is therefore insufficient.
- The pinned Playwright code runner races its actual snippet against a separate
  unhandled-rejection promise. An MCP error can arrive before the snippet stops.
  Even a settled MCP error is not, by itself, an execution-completion receipt.
- The relay rejects and clears outstanding callback promises when its connection
  closes. An empty callback map after disconnect is not proof Chrome stopped.
- `extension-browser-backend.mjs` currently quarantines on an unacknowledged
  deadline, disallows reset/reselection, and permits only cached inventory and
  lease release. Settled local errors instead fence the requesting session.
- The quarantine is currently in memory. A daemon crash/restart can lose it;
  crash-safe evidence must accompany any stronger recovery system.
- Reviewed native background reconnection already exists. There is no reason to
  relax the stock-handshake guard or replace the installed extension to obtain
  ordinary automatic reconnection.

Offline baseline verified for this plan: **78 tests passed** (59 Node + 19 Python),
using `npm --prefix .pi/extensions/50-browser test`. No live Chrome interaction,
installation, dependency patching, or service restart was performed.

## Recommended design

### 1. Independent execution receipts, not timeout-based guesses

Introduce a daemon-owned operation ledger and a small, reviewed, version-pinned
in-process hook at the **actual fixed-handler execution boundary**.

Each operation receives an internal boot/operation identity, connection generation,
session identity, stable tab/window identity, and phase. Register it before any
controller work can be dispatched, including preflight and tab creation.

The fixed handler emits entered/terminal receipts through an in-process observer
that remains available after MCP cancellation or an early code-runner error. It
must observe the real async handler, not just the outer MCP promise or an abort
signal. All owned parallel work must be joined or explicitly accounted for.

The hook is private, bound to a registered operation, and cannot be selected or
invoked by HTTP callers. Do not expose arbitrary JavaScript, receipt fabrication,
a caller-controlled target ID, or a public force-recovery switch.

**First implementation gate:** demonstrate this receipt boundary using the pinned
runner with fake pages and real in-memory MCP transports. If it cannot reliably
observe the actual handler after cancellation/early errors, keep manual recovery
and redesign the fixed execution adapter before proceeding. Do not weaken the
proof requirement to fit an inconvenient API.

### 2. Account for downstream work and ambiguous transport loss

Extend the existing pinned relay adaptation to account for commands issued by the
registered execution, their positive responses, and their connection generation.
Account for initialization/cleanup continuations as well as direct page input.

A terminal handler receipt is necessary but insufficient: a timed-out Playwright
operation can leave a previously issued command outstanding.

A recovery proof requires all of the following:

1. The exact fixed handler has reached its terminal boundary.
2. No owned controller continuation can issue further work for that operation.
3. Every dispatched downstream command has a positively established terminal
   outcome; none merely disappeared because a transport was closed.
4. Receipts match the original operation, window, tab, and generation; there is no
   unresolved command from an older generation.

Connection loss must retain a sticky unknown-outcome record. A reset, detached
debugger, killed process, aborted promise, healthy status flag, elapsed grace
period, or zero counter after disconnect is **not** a substitute for these facts.

This proves controller quiescence, not completion of a website's background
network requests or a business transaction. Never use `networkidle` to infer that
a submission succeeded or that repeating it would be safe.

### 3. Separate caller timeout, drain, and semantic outcome

Use an explicit recovery state machine:

```text
healthy -> executing -> healthy
                  |
                  +-> draining -> verifying -> healthy
                             |              +-> owner-needs-inspection
                             +-> blocked-needs-supervision
```

- Preserve the current caller deadlines. This is not a timeout increase or an
  alternate scrolling implementation.
- At timeout, report that the outcome is pending and retain the execution fence.
  Observe existing work; do not send another browser command to test whether the
  old command has stopped.
- Keep cached status and lease release responsive through a metadata-only lane.
  Mark inventory stale. Status must not activate tabs or implicitly reconnect
  while draining.
- Use a bounded observation grace (initial candidate: 30 s, to be validated
  offline) and the existing maximum of two eligible native preflight retries.
  No endless retries, scheduled watchers, or automatic service restarts.
- Reject stale queued mutations rather than dispatching them after a timeout.
  Unaffected sessions may issue fresh work once global quiescence is proven.
- Only after the proof succeeds may a serialized recovery step verify the recorded
  automation window/anchor and reconcile stable tab identities. Use only the
  reviewed native background path if a connection reset is actually necessary.
- A late verified success becomes a completed receipt, not an invitation to retry.
- A settled partial failure can unblock other sessions while keeping its owner
  fenced for inspection. Restored transport is not restored workflow certainty.
- If proof is unavailable or the recovery budget is exhausted, retain the fence
  and return one clear supervision-required reason. Later receipts may improve
  diagnostics but cannot silently override that manual-recovery state.

Automatic cancellation is **not required for v1**. Add it later only if execution
and downstream cancellation acknowledgements can meet the same proof. Never
interpret MCP's cancellation notification as an acknowledgement from Chrome.

### 4. Preserve session and action safety

- Preserve selected stable IDs and still-valid leases through a safe transport
  reconnect. Do not inherit Chrome's physical selection.
- Never adopt a personal window, substitute another tab, recover by URL/title, or
  take over another client's lease.
- Released/expired leases still require an explicit switch to a verified tab;
  this can use the existing tool without asking sir for routine permission.
- After quiescence, allow controlled screenshot/extraction inspection of the
  affected authorized tab while its workflow remains fenced. Inspection itself
  must validate identity/ownership and must not replay a mutation.
- Reuse existing full-value typing verification. A verified late field replacement
  can be reported as completed. A mismatch stays uncertain; do not silently repair
  it by typing again.
- Click, key, upload, navigation, tab creation/close, and submission-capable actions
  are never replayed automatically. A generic click/key cannot safely be classified
  as harmless from its API name.
- Submission/business outcome uncertainty remains an escalation if authorized
  read-only inspection cannot establish what happened. Recovery permission does
  not grant a new account/action permission.
- Explicit session close/release or user cancellation must not be undone by a late
  receipt. Reject duplicate, stale, unrelated, and wrong-generation receipts.

### 5. Make evidence crash-safe and recovery visible

Write a minimal owner-only journal atomically before dispatch. Store only internal
identities, fixed phase/outcome/reason codes, and timings: no URLs, selectors,
field contents, file contents, screenshots, tokens, or raw exceptions.

Fail before dispatch if the required journal cannot be recorded. Persist terminal
proof before considering the operation recoverable. On daemon startup, unresolved
records remain fenced; a service restart cannot erase uncertainty. Do not expire
unresolved evidence simply because it is old.

Bound resolved history and in-memory receipt summaries. Return each client's own
late-operation outcome through additive status/error metadata; do not expose
another client's results. Keep generic recovery diagnostics visible so other
clients understand why dispatch is blocked.

Suggested metadata:

- `recoveryState`, `operationId`, `outcome`, `inventoryStale`
- `recoveryReason`, `recoveryAttempts`, `requiresSupervision`

Messages should distinguish:

- "Automatic recovery pending; do not repeat the action."
- "Browser control recovered; previous action completed."
- "Browser control recovered; previous action needs inspection."
- "Recovery blocked: execution outcome unknown; supervision required."

Preserve public `browser_*` tool names, descriptions, parameters, and defaults.
Use additive protocol-v2 capabilities/results and typed internal errors instead
of a new model-controlled recovery argument. Old clients must remain conservative.

## Changes by file

- New `operation-ledger.mjs`: receipt state, bounded metadata, journal persistence,
  crash recovery, and immutable recovery-proof decisions.
- New `execution-observer.mjs`: narrowly scoped in-process receipt integration.
- New `execution-patch.mjs`: exact runner/relay hooks applied only by the pinned patcher.
- New `lock-operation-journal.py`: private locked atomic writer. Every physical
  write occurs in the process holding the kernel lock; helper death cannot leave
  a controller writing without its lock. It has no browser/network access.
  Intermediate command counters remain in memory; initial/state/terminal evidence
  is durable, avoiding per-keystroke journal fsyncs.
- `patch-playwright-background.mjs`: reviewed receipt/relay-accounting adaptation,
  exact pinned anchors, idempotence, and startup feature markers. Never hand-edit
  the installed dependency bundle or change the installed extension as a shortcut.
- `extension-browser-backend.mjs`: independent receipts, drain/verification states,
  serialized recovery, cached status lane, and startup fence restoration.
- `action-policy.mjs`: structured failure classification; preserve deadlines.
- `browser-sessions.mjs`: owner-scoped outcome fence, safe inspection, and explicit
  reselection semantics without lease theft or tombstone fallback.
- `chrome-bridge-daemon.mjs`: additive structured errors, private journal wiring,
  and startup/shutdown behavior that cannot clear unresolved evidence.
- `daemon-browser-manager.ts`: typed recovery metadata/errors without mutation
  retries. Public tool declarations remain unchanged.
- New/extended offline tests plus an explicitly opt-in synthetic live fixture.
- `README.md`, reliability documentation, and operational browser guidance: update
  approval rules only after deployment/acceptance; keep maintenance/focus gates.

## Test and acceptance matrix

### Offline, mandatory before deployment

- Real SDK deadline/cancellation with actual fixed execution completing later:
  receipt survives, execution happens once, and the failed reply is not replayed.
- MCP/code-runner error settles before its snippet: no early recovery.
- Handler exits while a relay command remains pending: fence stays closed.
- Pending command receives a positive response: proof becomes eligible exactly once.
- Disconnect clears SDK callbacks but command outcome is unknown: no recovery.
- Cancellation, callback races, duplicate receipts, reused request IDs, wrong
  generation/window/tab, and late receipt after session release: fail closed.
- Local failure remains owner-scoped only when controller quiescence is proven.
- Simultaneous clients, stale queued requests, lease expiry/handoff, and stable
  duplicate-URL identities: no cross-target action or implicit takeover.
- Known completed typing vs partial typing vs uncertain click/submission: correct
  outcome reporting and zero replay/automatic repair.
- Native handshake/cleanup outcome unknown, missing window, absent native helper,
  and blocked stock fallback: no alternate path or allowance generation.
- Daemon crash at every journal/dispatch/receipt boundary: unresolved evidence
  survives; journal failure stops dispatch; cached status never authorizes work.
- Recovery limits, responsive cached status/release, bounded completed history,
  privacy redaction, and unchanged public schemas/defaults.

### Supervised live acceptance, separate approval required

Use disposable localhost fixtures in the existing automation window. Pause other
browser clients and obtain a fresh idle maintenance window. No account forms,
real submissions, privileged browser pages, personal-tab changes, or Chrome restart.

Validate delayed completion, local-failure isolation, native reconnect, retained
unsaved fixture input/stable IDs, and an intentionally unresolved operation that
correctly remains blocked. Monitor foreground app, personal window/tab, and active
Spaces; obtain sir's visual confirmation. Telemetry is evidence, not an absolute
no-focus/no-Space-switch guarantee.

Do not assume a test can manufacture a realistic wheel stall; report synthetic
fault-injection results separately from production failure-cause claims.

## Delivery sequence and rollback

1. Implement the receipt/relay-proof feasibility spike entirely offline. This is
   the go/no-go gate before building automatic fence release.
2. Add the ledger/journal and tests; integrate in **observe-only** mode, preserving
   existing conservative recovery behavior.
3. Complete full offline regressions, review the exact dependency patch, and stage
   a scoped commit/artifact. No installer/postinstall against the live dependency
   tree during unsupervised development.
4. With fresh approval and browser clients paused, deploy/restart only the bridge
   and perform supervised fixture checks. Reload clients only if required by the
   changed result handling. Keep Chrome and the installed native extension/helper.
5. Enable **verified-only** auto-recovery after acceptance. Routine verified
   background recovery then requires no additional approval per occurrence.
6. Roll back first to **manual-only** mode in this candidate during approved
   maintenance; it retains the startup journal fence. Do not reinstall an older
   artifact that cannot read this journal while unresolved evidence exists.
   Returning to that artifact requires a retained journal-fence compatibility
   guard or separately supervised resolution of every pending record. Never
   delete/archive evidence automatically merely to make rollback start.

Remaining supervision cases: unresolved controller execution, unverified or
unknown native handshakes, stock/foreground fallback, missing automation-window
identity/manual Desktop 2 placement, disruptive maintenance, and unresolved
sensitive business outcomes. No policy or implementation should promise that all
browser failures can be recovered automatically.
