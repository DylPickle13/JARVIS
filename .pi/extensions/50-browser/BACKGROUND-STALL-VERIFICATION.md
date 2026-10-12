# Browser stall investigation — 2026-10-11

## Conclusion

The historical Workday stall's underlying cause is **not verified**. The earlier
explanation that background/occluded rendering was the root cause was too strong.
Offline tests establish a possible mechanism, not the historical trigger. Do not
claim the rendering problem is fixed or disable safeguards on that assumption.

The reason repeated stalls require approval is established: commands remain
unacknowledged beyond the 30-second drain budget, after which the v1 fence is
intentionally sticky. That safety policy is unchanged.

## Verified offline

The actual pinned Playwright `_checkElementIsStable` implementation stays pending
when its animation frames are withheld, and completes when they resume. A local
action deadline can finish both request/snippet boundaries while a downstream
command remains pending. Neither RPC settlement nor callback disposal proves
quiescence. This reproduces the receipt shape, not the real Chrome trigger.

108 Node + 19 Python checks pass (127 total), including existing ownership,
no-replay, unknown-execution, crash-journal and expired-grace regressions. New
checks cover the pinned stability mechanism, allowlisted/payload-free/bounded
command diagnostics, exact relay-hook migration and the live-fixture guard.

## Supervised live checks

All experiments used a localhost synthetic page in the existing native automation
window. No application forms were navigated, filled, clicked or submitted. Each
trial clicked once and sent one wheel action, checking event counts and actual
scroll movement. Each action followed 70 seconds of host-side inactivity. Every
successful fixture action was new work, not a retry of an uncertain action.

1. An instrumented page with a continuous animation-frame counter succeeded for
   click and wheel. A macOS window-list query confirmed the fixture window was
   off-screen. This is not a clean isolation result: instrumentation could keep
   rendering active, and display topology/Space IDs changed during the run while
   the foreground app/window/tab stayed unchanged.
2. A passive page, with **no animation-frame loop, periodic timer, animation or
   DOM heartbeat**, also succeeded for click and wheel. Read-only display queries
   reported both displays asleep around this trial; WindowServer recorded display
   sleep/wake transitions. 422 foreground/personal-tab/per-display Space samples
   were unchanged. Neither off-screen placement nor sleeping displays alone
   sufficed to reproduce this case.
3. A further passive-page trial switched between two independently owned synthetic
   tabs, letting the target tab idle in the background before each action. Both
   click and wheel succeeded exactly once, with 448 unchanged foreground/window/
   tab/per-display Space samples. The two passive runs total 870 unchanged samples.

The earlier `pmset` search finding no transitions was not reliable negative
evidence of display sleep. WindowServer/CGDisplay observations supplied more
specific evidence. No test asserted physical screen visibility from page
`document.visibilityState`, which can remain `visible` off-screen/asleep.

## Diagnostic change (not a rendering fix)

The private execution observer now retains only an allowlisted command name and
monotonic start time while each command is pending. On an uncertain operation and
on drain exhaustion, logs include request/snippet terminal flags, pending count,
unknown flag and at most 32 pending command names/ages. This distinguishes a
stalled evaluation from a wheel acknowledgment during the next actual failure.

No expressions, selectors, input values, URLs, uploaded data or raw exceptions
are added to these diagnostics. Unknown command names become `other`. Diagnostics
cannot change completion proof. The existing crash-safe journal schema, action
deadlines, leases, public tool declarations and recovery policy are unchanged.
No Chrome restart, alternate profile, focus API, native-helper change, automatic
mutation replay or journal resolution is part of this change.

## Final service state

All three trials completed without an execution fence. Their four synthetic tabs
were closed exactly once; all 11 original work-tab IDs and the original automation
window (1477436266) were retained. The bridge was restored healthy in `verified-only`
mode, with zero unresolved journal records. The deployed diagnostic sources match
the isolated, live-tested candidate; production offline tests also passed. No
journal resolution, Chrome restart or actual-form test was needed. The rendering
problem itself remains unresolved because its cause was not reproduced.

## Follow-up: confirmed measurement gaps

A further read-only investigation found no post-deployment failure captured by
`execution-pending`/`execution-drain-exhausted` yet, and no unresolved journal
operation. It did establish two limitations in the synthetic trials:

- `test-extension-focus.py` repeatedly sends AppleEvents to Chrome during the
  supposed idle interval. These are real browser-process requests, not passive
  OS telemetry. They could mask an unattended-process condition; this causal
  effect is not yet demonstrated. Each trial also established a fresh connection,
  and its wrapper used a system-idle-sleep assertion (`caffeinate -i`).
- A contemporaneous comparison returned `com.microsoft.VSCode` from System Events
  while `NSWorkspace.shared.frontmostApplication` returned `com.apple.loginwindow`
  and `CGSessionCopyCurrentDictionary` reported `CGSSessionScreenIsLocked=true`.
  Both displays were asleep. Thus unchanged old foreground samples do **not**
  establish unchanged lock/unlock state. The earlier sample counts remain counts
  of the values actually sampled, not proof of console-session visibility.

The pinned extension connection also explicitly uses `noDefaults:true`. Its
Chromium initialization therefore skips `Emulation.setFocusEmulationEnabled` for
the default context. This is a source-verified configuration difference from a
normal Playwright launch, not proof of the historical stall and not authorization
to turn focus emulation on. Changing it could affect website focus semantics.

A new guarded experiment has been prepared only in the isolated worktree:
`test-unattended-browser-live.py`, with `test-passive-desktop-snapshot.swift` and
`test-unattended-fixture.mjs`. It uses the existing production daemon (no restart),
two private synthetic tabs, localhost/127.0.0.1 cross-site navigation, six minutes
without any browser requests, no power assertion, and OS-only foreground/Space/
display/lock telemetry. Browser activity or a foreground/Space/lock-state change
invalidates the interval before test input is sent. Personal tab contents are not
sampled, so this monitor does not claim continuous personal-tab identity coverage.
Three guard/structural tests pass; Swift compiles and its read-only snapshot works.
The owner subsequently confirmed a fresh paused-session maintenance window. The
new live experiment **completed without reproducing the failure**:

- Existing production daemon and connection generation retained; no restart or
  power assertion. Both synthetic tabs navigated from 127.0.0.1 to localhost.
- Six minutes with no browser requests; unchanged journal bytes verified that no
  other browser operation occurred during the idle interval.
- 355 OS-only samples: screen locked, both displays asleep, foreground loginwindow,
  and unchanged foreground/window/Space/lock identity throughout and at the end.
- One selector click produced exactly one event; one wheel produced exactly one
  event and 400 pixels of actual movement. Both pages reported `visible` and
  `focused:true` despite the locked console; these page values do not describe
  physical screen visibility.
- Both synthetic tabs closed exactly once; all 11 original work tabs preserved;
  zero unresolved journal records; no execution-pending diagnostic emitted.
- Private evidence: `.pi/runtime/browser-unattended-live-20261011/report.json`.

Thus the prior monitor flaw was real but has not been shown to explain the stall.
Lock/sleep/idle/cross-site conditions alone did not reproduce it in this fixture.
The remaining test gap is the affected website/document state. Inspecting actual
application pages requires a separately approved read-only scope and valid tab
ownership; no account-page inspection or interaction occurred in this experiment.

## Actual-site reproduction and acknowledged resolution

A subsequent owner-authorized read-only inspection reproduced the stall on the
original Workday tab (now Candidate Home, not the original application editor).
Text extraction and a viewport screenshot succeeded. An element screenshot of a
visible heading timed out waiting for element stability. The observer recorded a
`Runtime.callFunctionOn` still pending after 39,976ms; request and snippet were
terminal, but downstream completion was not. The operation correctly stayed fenced.

After the owner brought the existing automation window into view, independent
journal receipts showed pending=0, unknown=false and durable terminal proof.
There was no retry or browser dispatch between the pending observation and this
receipt check. This supports visibility-dependent completion; it does not alone
distinguish missing animation frames from perpetual geometry instability.

With separate exact owner acknowledgment, the journal-aware one-shot resolver
resolved only this failed screenshot. All other evidence and configuration were
preserved. Only the bridge was stopped/restored; Chrome was not restarted. Public
status verified healthy, verified-only, no quarantine and all 11 work tabs retained.
Private provenance: `.pi/runtime/browser-workday-readonly-stall-20261011/`.

Matching installed Chrome 154.0.8037.99 source provides a concrete hypothesis for
why never-shown synthetic tabs passed: `UpdateWebContentsVisibility` does not
transition initial visibility to HIDDEN/OCCLUDED before the first real VISIBLE
transition. The same method supports the startup switch
`--disable-backgrounding-occluded-windows`, mapping OCCLUDED to VISIBLE. This is a
candidate for supervised testing, **not an applied or verified fix**. A Chrome
restart requires separate approval, saved drafts and dedicated-window revalidation;
no automatic window adoption or placement is authorized by this finding.

Source: https://raw.githubusercontent.com/chromium/chromium/154.0.8037.99/content/browser/web_contents/web_contents_impl.cc

## Approved occlusion-flag trial — subsequently rolled back

After separate Chrome-restart approval, the bridge was stopped, Chrome quit
normally, and the same application/profile relaunched with
`--disable-backgrounding-occluded-windows --restore-last-session`. No force quit,
profile replacement or application replay occurred. The first preflight attempt
stopped before any changes because JXA returned string IDs; numeric normalization
was corrected before the actual restart. Both windows restored with their prior
tab counts. Automation membership was matched using all 11 prior work-URL hashes,
not by selecting an arbitrary/personal window. The owner confirmed Desktop 2
placement before identity rebinding and native bridge reconnection.

- Restored automation window: `1477436724`; Workday tab: `1477436725`.
- Chrome PID `37459` was verified to contain the occlusion flag.
- The exact heading selector that previously stalled completed twice, including
  after 70 seconds of no browser requests. Both screenshot records completed with
  pending=0, unknown=false and resolved journal state.
- 269 OS-only samples had unchanged display Space identities. Foreground changed
  from personal Chrome to VSCode during the overall interval, so this is **not**
  a wholly unchanged-foreground run. The final 172 samples, including idle and the
  second screenshot, had unchanged full sampled desktop state.
- All 11 work tabs remained; bridge healthy, verified-only, no quarantine or
  unresolved records. The inspection lease was released and monitor stopped.
- Workday's restored page was **signed out**, though the same heading and route
  remained. No login was attempted. This and the fresh renderer are confounds;
  the result supports the mitigation but does not prove the original logged-in
  application workflow is fixed.

The flag is active for **this Chrome launch only**. No Dock/login item, app bundle,
profile preference or persistent launch configuration was changed. An ordinary
future Chrome relaunch may omit it. Any future restart/rebinding remains supervised;
do not add flags to an already-running Chrome process and assume they took effect.
The flag affects all Chrome windows and can increase background CPU/GPU/power use.

Private results: `.pi/runtime/browser-workday-readonly-stall-20261011/chrome-restart-validated/`.

## Owner-requested rollback

The owner declined a separate automation browser and requested restoration of
normal Chrome behaviour. After fresh paused-job/saved-draft confirmation, the
bridge was stopped with no unresolved journal records. Chrome quit normally and
restarted with session restoration requested, without the occlusion flag. PID
62296 was checked: the flag is absent. Backend configuration is unchanged; no
profile migration or persistent startup configuration was introduced.

Both windows restored with their prior counts (12 and 4 tabs). The probable
restored automation window is 1477437045: it contains the restored internal anchor
1477437057 and 11 work tabs, with 10/11 prior work-URL hashes matching. Because the
match was not exact, the bridge remained stopped until the owner confirmed the
restored JARVIS window and Desktop 2 placement. After that confirmation, a fresh
inventory verified the same restored anchor and at least 10/11 work-URL matches;
the window identity was rebound and native reconnection succeeded. Public status
verified window 1477437045, all 11 work tabs (1477437046 through 1477437056), healthy
verified-only recovery, no quarantine and no supervision requirement. Final journal
inspection found no unresolved operations; Chrome's occlusion flag remains absent.
No automatic Space placement or exact restoration of application/session state is
claimed. The original stall remains possible under the restored configuration.

Private evidence: `.pi/runtime/browser-workday-readonly-stall-20261011/normal-chrome-restoration/`.

## Next evidence needed

Capture an actual affected-workflow recurrence using these diagnostics, or obtain
approval for a scoped synthetic reproduction that matches an identified missing
condition. A fresh connection and simple localhost page do not reproduce every
Workday or long-lived-renderer condition. Do not silently test account forms or
claim that passing these fixtures establishes the cause. No speculative rendering
policy changes or late-proof fence changes have been made.

## Artifacts

Private reports (not committed):
- `.pi/runtime/browser-background-stall-live-20261011/`
- `.pi/runtime/browser-background-stall-passive-20261011/`
- `.pi/runtime/browser-background-stall-tab-switch-20261011/`
- `.pi/runtime/browser-background-stall-main-tests.log`

The guarded private SDK fixture is `test-background-stall-live.mjs`. It requires
explicit supervised idle maintenance, an unloaded production bridge, a healthy
journal under its exclusive lock, the existing native automation window and an
explicit private report path. A failure retains its controller, evidence and tabs;
it never resets, resolves the journal or replays the action. Do not run it as a
routine test or terminate a pending controller as a substitute for proof.
