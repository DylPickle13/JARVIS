# Verified browser recovery — implementation record

**Current status (2026-10-09): deployed in observation mode; supervised live checks
passed; final visual acknowledgment and scoped restoration approval pending.**
The bridge is deliberately unloaded after the negative fixture. Production
`verified-only` recovery is not yet enabled. See
[VERIFIED-RECOVERY-LIVE.md](VERIFIED-RECOVERY-LIVE.md) for current evidence/state.

## Offline implementation provenance (historical)

The following describes the initial offline phase, before approved deployment.
Branch: `browser/verified-recovery-offline`.
Worktree: `.pi/runtime/browser-verified-recovery-offline/`.
Base commit: `37ee776`.

The worktree has its own APFS-cloned dependency directory, not a symlink or hard
link to the installed bundle. During the offline phase, the dependency patch was
run only in that copy.
The main checkout, installed extension/native helper, live dependency bundle,
owner configuration, automation window and bridge service were not changed.
No account/application tab was opened, read, filled, navigated or submitted.

## Implementation

- The private version-pinned hooks independently observe the **actual VM snippet**,
  the encompassing backend call (including postprocessing), and extension command
  responses. MCP cancellation/discarded replies cannot erase those receipts.
- RPC errors that precede actual completion remain fenced. An empty callback map
  after disconnect is not proof: unknown outcomes remain sticky, including across
  connection generations.
- A positively quiescent operation can enter one serialized native-window/tab
  verification transaction. There is no action replay, stock allowance generation,
  daemon/Chrome restart, alternative profile, foreground fallback, or new window.
- Successful late wheel/observation work and full-value verified typing may restore
  the same owner's workflow, only with a still-valid lease/selection. Clicks and
  partial input keep that owner fenced for inspection; other clients can resume.
- Cached stale status and lease release stay available during recovery. Old queued
  mutations are rejected, expired leases are not stolen, and a late result cannot
  resurrect a closed client. Inspection is enabled only after controller quiescence.
- An owner-only journal is durable before dispatch and before proof is accepted.
  Unresolved or invalid boot evidence blocks Chrome access, even in manual-only
  mode. Resolved history is bounded; unresolved evidence is not age-expired.
- A small Python child owns the kernel lock **and every physical atomic/fsynced
  write**. Competing daemons cannot overwrite its journal; writer loss prevents
  further persistence/dispatch. It has no Chrome, network, focus or Space API.
  Intermediate command counters stay in memory: the initial executing record
  already fences crashes, so normal typing does not cause per-keystroke fsyncs.
- Additive typed status/error metadata reports pending recovery versus required
  supervision and exposes only the requesting client's operation summaries.
- Public browser tool names, descriptions, parameters/defaults and existing action
  deadline values are unchanged. Normal field/scroll semantics are unchanged.

## Modes and journal

The staged daemon defaults to `observe-only` when its owner backend configuration
has no `recoveryMode` entry. That gathers proof but **does not release quarantine**.
The candidate also supports `manual-only` and `verified-only`. The latter must not
be enabled until the separate supervised live acceptance gate is complete.

The production journal destination, if deployed, is
`~/.jarvis/browser-recovery/operations.json`, in a private 0700 directory with a
0600 journal and kernel-lock file. Tests used temporary directories only.
No values, URLs, selectors, uploaded bytes, screenshots, credentials or raw
exceptions are journaled. The writer replies with fixed acknowledgement keywords
and sequence numbers, never its payload.

A bridge restart is not an unquarantine procedure. There is no model/HTTP
force-clear API. If an unresolved record survives a real crash, pause clients,
quiesce old execution and inspect its affected page under explicit supervision.
Any operator resolution/archival of specific evidence needs separate owner
approval after that investigation; do not remove the journal as a shortcut.

## Offline verification

**122 checks passed:** 103 Node + 19 Python (12 launcher, 7 native-helper checks).
Command, from the isolated worktree:

```sh
npm --prefix .pi/extensions/50-browser test
```

Additional syntax checks and an idempotent dependency-patcher rerun passed.
The patcher now refuses partial/changed execution-hook anchors rather than layering
an apparently healthy duplicate patch over a modified upstream runner.

New tests cover:

- Real pinned MCP/SDK timeout and cancellation, with fake pages: actual execution
  finishes later exactly once, receipts survive, and the missing reply is not replayed.
- Actual runner early-error behavior: the response can settle while its snippet
  remains alive; proof remains false until both execution boundaries complete.
- The actual pinned extension-connection implementation with a fake WebSocket:
  pending response, duplicate/foreign response, disconnect disposal and mixed
  connection generations cannot fabricate completion.
- Gated backend recovery using the real runner with fake pages: late wheel and
  verified 5,000-character replacement; partial typing/click owner isolation;
  cached status; stale queued requests; release and lease expiry; changed window,
  missing tab, stock mode and wrong-generation refusals; grace exhaustion and
  observation-only behavior.
- Journal persistence/permissions/symlink/validation failures, sticky unknown
  evidence, private payload omission, bounded history and durable latest revision.
- Abrupt child exit at six durable journal boundaries; startup remains fenced until
  an operation was genuinely recorded as resolved.
- Competing writers, writer loss and no per-command full-journal fsync behavior.
- Client typed recovery errors with no failed-mutation retry.
- All 78 pre-existing offline regressions.
- Three guards refuse the private live fixture/monitor before credentials or
  Chrome access unless the explicit maintenance flag is present.

These are not live Chrome/focus/Space checks. They do not establish why the original
wheel stalled, actual renderer behavior under that stall, or an absolute no-switch
guarantee. Backend verification fixtures mock preflight inventory; existing native
identity regressions remain in the suite, but live transaction acceptance is still
required.

## Explicit v1 limits

- Unknown native launch/handshake outcomes, unbound tab creation, and bootstrap or
  anchor-preparation deadlines are **not eligible** for automatic fence release.
- No cancellation API is claimed. Cancelled MCP promises, closed sockets and
  killed processes never stand in for acknowledged browser-command termination.
- The 30 s observation grace is bounded. If it expires, later proof improves
  diagnostics but does not silently undo the supervision-required state.
- Controller quiescence does not establish a website's business/submission outcome.
  Inspection/action authorization remains necessary; no semantic mutation retry.
- Missing automation window/manual Desktop 2 placement, stock reconnect, disruptive
  maintenance and unresolved execution still require the owner.

## Deployment / acceptance gate (not yet performed)

1. Obtain a fresh idle maintenance window and confirmation all browser clients are
   paused. Do not infer idleness, contact peers, or deploy automatically.
2. Review the scoped candidate and pinned patch. Preserve Chrome, its existing
   window/profile, installed extension/native helper and stock-focus guard.
3. Deploy in observation mode, patch only the bridge dependency bundle, restart
   only the bridge with approval, then have clients list/reselect stable IDs.
4. Run the existing opt-in synthetic reliability/full-interaction/native reconnect
   fixtures under foreground/personal-tab/per-display Space telemetry. Require
   unchanged telemetry plus sir's visual confirmation; neither is a universal
   focus guarantee.
5. Before enabling verified-only mode, run the guarded private SDK fixture:
   `JARVIS_TEST_VERIFIED_RECOVERY_MAINTENANCE=1 python3 test-extension-focus.py
   --spaces --script test-verified-recovery-live.py`. The bridge must be unloaded
   by the supervising operator first; the fixture acquires the same production
   journal's exclusive lock before accessing Chrome. It uses only new localhost
   fixture tabs and private one-shot SDK reply deadlines, never HTTP fault flags.
   A late verified replacement must execute once and preserve the peer draft.
   A deliberately short test-only drain budget on a pure wait must leave the
   journal fenced even after positive completion proof. That exact completed test
   record and retained fixture tabs require owner acknowledgment before supervised
   resolution/service restoration. The fixture never clears it or restarts the
   bridge itself. Acceptance remains pending; injection is not a wheel-stall cause
   claim.
6. Enable verified-only recovery only after these checks and owner acceptance.
   Routine positively verified recovery then requires no new per-occurrence approval.

Rollback first uses this candidate's manual-only mode, which retains startup
journal fences. Never revert to a journal-unaware artifact while unresolved
evidence exists, or automatically delete/archive evidence to make rollback work.
