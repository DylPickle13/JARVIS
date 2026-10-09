# Verified browser recovery — supervised live rollout

Date: 2026-10-09, EDT. Maintenance and observation-mode deployment authorized by
sir's “ready, go ahead.” Sir subsequently confirmed visual acceptance and approved
exact synthetic-record resolution, fixture cleanup, service restoration and
verified recovery activation.

Source deployed on main:

- `57807b9`: execution receipts, journal, proof-gated recovery.
- `396bdeb`: guarded private SDK live fault fixture.

## Current state: enabled and healthy

**Production `verified-only` recovery is enabled.** The existing bridge LaunchAgent
is restored; the public browser status reports connected, healthy, no quarantine,
no stale inventory and no supervision requirement. Journal unresolved count: **0**.

Automation window `1477435257` and original work-tab `1477435876` remain. Retained
fault-fixture tabs `1477435949` and `1477435952` were verified by exact ID, title,
localhost origin and absence of another controller, then closed once each. The
fresh restored-service interaction fixture also cleaned up its own tab. Final
work inventory contains only the original tab, with no implicit selected tab.

Chrome, its profile, installed extension/native helper and public browser tool
schemas/defaults were preserved. Existing account/application forms were not
navigated, filled, clicked or submitted; inventory metadata was inspected.
No failed action was replayed, no journal was cleared and no stock fallback used.

## Acceptance results

| Check | Result | Unchanged focus/Space samples |
| --- | --- | ---: |
| Bridge-only observation deployment/restart | Connected; no quarantine; original window/work-tab retained | 15 |
| Live reliability | Concurrent long fields, nested/page wheel delivery, failure isolation and retained drafts | 275 |
| Fresh full-interaction fixture | Navigation, typing/clear, click, wait, extract/links, PNG, scroll, local upload, isolation and cleanup | 164 |
| Two forced native anchor reconnects | Fresh anchor IDs; same window, independent selections/drafts, lease/handoff and closed-tab guards | 246 |
| Private SDK fault fixture | Positive verified late typing + negative grace exhaustion | 100 |
| Verified-mode service restoration and full-interaction smoke | Healthy verified mode, exact fixture cleanup, original tab retained, no unresolved evidence | 196 |
| **Total** | **All six monitored runs passed** | **996** |

For every monitored sample, foreground app, personal/non-automation window-tab,
and active Space on every display matched that run's baseline. These are sampled
observations, not an absolute no-switch guarantee. Sir confirmed the acceptance
run stayed visually unchanged and authorized activation. The activation run also
had unchanged telemetry; no automatic Space placement or focus restoration occurred.

Offline suite: **103 Node + 19 Python = 122 checks**, including unauthorized-live
fixture guards. These tests do not access live Chrome.

## Private SDK fault fixture

Production was deliberately unloaded first. The private backend instance used
`verified-only` and exclusive production-journal ownership; it did not change
production configuration. A 5 ms one-shot SDK reply deadline was private to the
fixture, with unchanged fixed controller bodies and production action deadlines.

### Positive: known completed replacement

Operation `1e3f637c-d51c-48a5-b43c-39b7751d554c:23` replaced a synthetic field with
5,000 characters. One input event, full-value verification and independent actual
execution proof were recorded. Recovery restored healthy control without replay;
peer draft/selection and the original work-tab identity were preserved.

### Negative: grace exhaustion remains fenced

Operation `1e3f637c-d51c-48a5-b43c-39b7751d554c:36` was a pure `/wait` for 1,200 ms,
with a deliberately short **test-only** 200 ms drain grace, on synthetic tab
`1477435949` in window `1477435257`. Both actual-snippet/request boundaries entered
and terminated; outcome was `completed`, pending commands `0`, unknown `false`,
evidence/persisted revision both `20`. The operation correctly stayed `blocked`,
and reselection remained refused even after positive completion proof.

The fixture did not resolve evidence, close its retained tabs or restore the
service. It left exactly that one unresolved record and the bridge unloaded until
sir's explicit confirmation. This negative case was not a production unknown
submission or an unfinished typing action.

## Authorized resolution and activation

After confirmation, the operator re-read the exact record under exclusive journal
ownership, required the terminal proof/action/session/window/tab/revision match,
and preserved private fsynced before-evidence/configuration/acknowledgment copies.
Only the completed synthetic wait changed from `blocked` to `resolved`.

The initial one-off operator's strict unchanged-record-count assertion stopped
**after** successful resolution: the ledger normally bounds resolved history to
64 entries, so resolving the 65th entry pruned one oldest already-resolved record
(`7da2f644-72af-4876-9c53-d6267ff7a171:226`). Inspection verified no added records,
only the synthetic record's state change, and unchanged other retained records.
The pruned historical row remains in the private before snapshot. Configuration
was still observation mode and the bridge still unloaded. A separate continuation
validated that saved state under lock; it did not rerun resolution or write the
journal again. It used an explicit process keep-alive while closing the unref'ed
lock child, avoiding the isolated operator's unsettled top-level-await exit.

Only then was configuration atomically changed to
`{"backend":"extension","recoveryMode":"verified-only"}` and fsynced. The existing
LaunchAgent was bootstrapped once, under read-only foreground/Space monitoring.
Startup status was retried only for connection refusal before any HTTP request
reached the daemon—not for errors, timeouts or uncertain outcomes. Fixture closes
were each sent once. The activated-service full-interaction smoke passed, followed
by healthy public browser status and a journal check showing no unresolved evidence.

## Earlier harness interruption handling

The initial combined reliability/interaction command hit its 120-second harness
limit after reliability passed; that attempt did not establish interaction
acceptance. Before cleanup, no test process or unresolved controller operation
remained. The interrupted fixture's selected tab/title/local origin and ownership
were verified, and only that synthetic tab was closed using its original controller
identity. A fresh separately monitored fixture then passed. No interrupted action
was reissued on the original fixture.

## Operational safeguards and limits

- Routine positively verified recovery requires no per-occurrence approval.
  Unknown execution, expired drain grace and disruptive maintenance still require
  supervision. Recovery does not grant account/private/submission/action permission.
- Never repeat a failed/uncertain mutation. During recovery, cached inventory and
  lease release do not authorize inspection/mutation of a running controller.
  Clicks/partial input retain owner inspection fencing even when others can resume.
- Production drain grace is still 30 seconds. Scroll, explicit zero-delay replacement
  typing and other action deadlines remain 15, 30 and 150 seconds respectively.
- Unknown native launch/handshake, unbound creation, bootstrap/anchor deadlines and
  unresolved startup evidence remain excluded from automatic fence release.
- No browser cancellation API is claimed. Process exit, empty pending maps,
  reconnect and a daemon restart are not completion proof.
- These injections exercise the real pinned SDK/receipts and policy; they do not
  reproduce or explain the original wheel stall. The pure-wait diagnostic is
  labelled `preflight` by the existing timed-action logging allowlist; journal
  evidence correctly binds it to `/wait`.
- Rollback is journal-aware `manual-only` during approved maintenance, never an
  older journal-unaware artifact, backend/profile switch or deletion of evidence
  to bypass unresolved execution. Stock/foreground fallback remains blocked.

## Evidence

Private reports in `.pi/runtime/browser-extension-review/`:

- `verified-recovery-deployment.json`
- `verified-recovery-reliability-focus.json`
- `verified-recovery-interactions-focus.json`
- `verified-recovery-reconnects-focus.json`
- `verified-recovery-sdk-focus.json`
- `verified-recovery-live.json`
- `verified-recovery-activation.json`

Production journal: `~/.jarvis/browser-recovery/operations.json`.
Private before/after snapshots and resolution receipt:
`.pi/runtime/browser-verified-recovery-deployment/acknowledged-resolution-8a9c6257-3d85-4f9f-b44f-c7aa93c7ed9e/`.
Deployment backups/operator scripts:
`.pi/runtime/browser-verified-recovery-deployment/`.

See [VERIFIED-RECOVERY-CANDIDATE.md](VERIFIED-RECOVERY-CANDIDATE.md) for implementation,
dependency hook pins, journal guarantees and v1 exclusions.
