# Verified browser recovery — supervised live rollout

Date: 2026-10-09, EDT. Maintenance and observation-mode deployment authorized by
sir's “ready, go ahead.” Source deployed on main:

- `57807b9`: execution receipts, journal, proof-gated recovery.
- `396bdeb`: guarded private SDK live fault fixture.

## Current state: final acknowledgment pending

Supervised checks passed. **The production bridge is deliberately unloaded.**
Production configuration remains observation mode (the default); `verified-only`
automatic fence release has not been enabled. The private fixture used its own
backend instance configured `verified-only`, without changing production mode.

The negative fixture intentionally exhausted its short test-only drain budget.
Its pure wait later finished with positively acknowledged controller execution,
but the operation correctly remains `blocked`. There is exactly one unresolved
journal record:

- Operation: `1e3f637c-d51c-48a5-b43c-39b7751d554c:36`.
- Action: `/wait`, synthetic duration 1,200 ms; test-only drain grace 200 ms.
- Window: `1477435257`; synthetic tab: `1477435949`.
- Both request and actual-snippet boundaries entered and terminated;
  outcome `completed`, pending commands `0`, unknown outcome `false`.
- Evidence revision and persisted revision both `20`.
- Reselection remained refused even after positive completion proof.

No evidence was cleared/resolved, no action was replayed, and no service restart
was used to bypass that fence. Two synthetic tabs remain (`1477435949`,
`1477435952`). The original work-tab ID is `1477435876`.

## Acceptance results

| Check | Result | Unchanged focus/Space samples |
| --- | --- | ---: |
| Bridge-only observation deployment/restart | Connected; no quarantine; original window/work-tab retained | 15 |
| Live reliability | Concurrent long fields, nested/page wheel delivery, failure isolation and retained drafts | 275 |
| Fresh full-interaction fixture | Navigation, typing/clear, click, wait, extract/links, PNG, scroll, local upload, isolation and cleanup | 164 |
| Two forced native anchor reconnects | Fresh anchor IDs; same window, independent selections/drafts, lease/handoff and closed-tab guards | 246 |
| Private SDK fault fixture | Positive verified late typing + negative grace exhaustion | 100 |
| **Total** | **All five monitored runs passed** | **800** |

For every monitored sample, foreground app, personal/non-automation window-tab,
and active Space on every display matched that run's baseline. These are sampled
observations, not an absolute no-switch guarantee; sir's visual confirmation is
still required. Chrome, its profile, installed extension/native helper and public
browser tool schemas/defaults were preserved. Existing account/application forms
were not navigated, filled, clicked or submitted; inventory metadata was inspected.

### Positive private fault

One SDK reply deadline was shortened privately to 5 ms; the controller body and
production action deadlines were unchanged. The 5,000-character replacement
completed with one input event, full-value verification and independent execution
proof. Recovery restored healthy control without replay. Peer draft/selection
and original work-tab identity were preserved.

Operation: `1e3f637c-d51c-48a5-b43c-39b7751d554c:23`.

### Harness interruption handling

The initial combined reliability/interaction command hit the harness's 120-second
limit after reliability passed. It did not establish interaction acceptance.
Before cleanup, the controller journal showed no unresolved operations, no test
process remained, and the interrupted fixture's selected tab/title/local origin
and ownership were verified. Only that synthetic tab was closed using its original
test-controller identity. A fresh separately monitored interaction fixture then
passed. No interrupted action was reissued on the original fixture.

### Limits

These injections test the real pinned SDK, execution receipts and fence policy;
they do not reproduce or explain the original wheel stall. Production scroll,
explicit zero-delay replacement typing and other action deadlines remain 15,
30 and 150 seconds respectively. The pure-wait diagnostic is labelled `preflight`
by the existing timed-action logging allowlist; journal evidence correctly binds
it to `/wait`. Unknown native launch/handshake or unresolved execution still needs
supervision, in every recovery mode.

## Next operator steps — only after fresh owner acknowledgment

1. Obtain sir's visual confirmation and approval to resolve this exact completed
   synthetic record, clean up the two fixture tabs, restore the bridge and enable
   verified recovery. Keep other browser sessions paused during maintenance.
2. Under exclusive journal ownership, re-read evidence; require the exact record,
   action, fixture tab, window and terminal proof above. Stop if any other unresolved
   evidence appears. Preserve a private evidence snapshot and resolve only this
   record through the ledger; never delete the journal or force-clear quarantine.
3. Set production `recoveryMode` to `verified-only` without changing backend,
   profile or fallback policy. Start only the bridge using the existing LaunchAgent.
4. Validate healthy status and the original window/work-tab ID. Verify the two
   explicit synthetic tab IDs/title/local origin before scoped cleanup. Never close
   or reselect an original application tab as an implied default.
5. Run a monitored restored-service smoke check, obtain final visual confirmation,
   and record activation evidence. Rollback is journal-aware `manual-only`, never
   an older journal-unaware artifact or deletion of unresolved evidence.

## Evidence

Private runtime reports in `.pi/runtime/browser-extension-review/`:

- `verified-recovery-deployment.json`
- `verified-recovery-reliability-focus.json`
- `verified-recovery-interactions-focus.json`
- `verified-recovery-reconnects-focus.json`
- `verified-recovery-sdk-focus.json`
- `verified-recovery-live.json`

Production journal: `~/.jarvis/browser-recovery/operations.json`. Deployment
backups: `.pi/runtime/browser-verified-recovery-deployment/`.

Offline suite: **103 Node + 19 Python = 122 checks**, including unauthorized-live
fixture guards. See [VERIFIED-RECOVERY-CANDIDATE.md](VERIFIED-RECOVERY-CANDIDATE.md)
for the implementation, dependency hook pins, journal guarantees and exclusions.
