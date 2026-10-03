# Browser reliability update — DEPLOYED; LIVE ACCEPTANCE PENDING

Prepared 2026-10-03 on branch `browser/reliability-offline` in
`.pi/runtime/browser-reliability-offline/`, commit `e98889c`. Sir subsequently
confirmed sessions 7/8 were finished and explicitly authorized deployment.
The code was cherry-picked into main as `018be5b`; all 78 offline checks passed
again there. At approximately **18:20 EDT on 2026-10-03**, only
`com.jarvis.browser-bridge` was restarted with that approval.

Read-only post-restart status confirmed native reconnection, connection generation 1,
no current error/quarantine and all seven pre-existing work-tab IDs in window
`1477433592`. Chrome, the installed v2 extension/native host, profile and credentials
were not changed. No application page was filled, navigated or submitted by this
deployment. Form-field contents were not inspected, so preserved tab IDs are not
presented as a new unsaved-field verification. No live interaction/stress fixture
was run. **Live acceptance remains pending an explicitly idle maintenance window.**
No automatic deployment, watcher or session-completion job is installed.

## Evidence and scope

Session 7 had approximately 150-second wheel timeouts; session 8 then received the
shared uncertain-outcome fence. This chain was reproduced with mocked transport,
without Chrome. Session 8's identical 4,539-character input timed out at 151.6 s
with default 20 ms delay and succeeded at 77.1 s with explicit zero delay; the
intentional delay alone was 90.8 s. Successful status previously erased the error
and retained a stale connection timestamp while not counting action resets.

The native handshake/grouping patch is not changed. Wheel, typing and timeout
handling predate it. The initial reason Chrome stopped acknowledging wheel input
remains **unproven**. No speculative scroll replacement or foreground workaround
is included. This candidate contains bounded failure containment and a disposable
live diagnostic fixture, not a claim that wheel delivery is fixed.

## Changes

- `verified-input.mjs`: `browser_type(clear:true, delayMs:0)` bulk-fills ordinary
  text inputs/textareas using Playwright, then compares the entire resulting value.
  No fallback/replay on mismatch. The focused element handle is retained, including
  shadow-DOM focus; focus loss fails rather than claiming successful entry.
- Public tool schemas, descriptions and defaults are unchanged. Short default
  typing remains 20 ms/character; explicit slow typing remains available. Long
  input (>1,000 characters) must use explicit zero-delay plain-field replacement.
  Requests with >30 s of deliberate typing delay fail before focus/clear/input.
  These are conservative candidate limits requiring live acceptance. Non-clear
  insertion is verified against the original selection; fields that cannot expose
  an unambiguous selection require `clear:true`. Rich editor/key-specific workflows
  retain the short keyboard path; large rich-editor input is deliberately refused.
- `action-policy.mjs`: 15 s outer wheel deadline; 30 s for explicit zero-delay
  replacement; other MCP calls keep their existing 150 s ceiling. Field operations
  also retain Playwright's bounded action timeout. Expiry is **not cancellation**.
- A settled action-level timeout or verification failure fences only its requesting
  session. The next operation still performs normal authenticated preflight. Other
  sessions retain independent selected IDs and leases. No mutating action is retried.
- **Unacknowledged outer request deadline:** quarantine the entire bridge. Do not
  reset/reconnect, activate another tab or accept explicit reselection while the old
  action may still execute. Only cached/stale status and lease/session release work.
  This is intentionally conservative: prompt failure is safer than releasing an
  unresolved action to race another session. There is no automatic unquarantine API.
- Recognized transport-loss errors still use existing non-replaying recovery. All reset
  attempts are counted (`resetCount`); preflight retries remain `recoveryCount`.
  `connectedAt` changes on a new anchor generation; `connectionGeneration` increments.
  `lastFailure` and `lastReset` survive a successful status request. Quarantined status
  explicitly says disconnected/quarantined and marks its inventory stale.
- Fixed `JARVIS_BRIDGE` diagnostic events log operation IDs, allowlisted actions,
  numeric tab IDs, timings and failure categories—never values, selectors, URLs,
  credentials, code snippets or full exceptions.

## Offline acceptance

**78 offline tests passed (59 Node + 19 Python)** against the isolated dependency
copy. Python syntax checks passed and the live fixture's missing-permission guard
was verified to exit before loading credentials or contacting Chrome. No live
browser/focus/Space test was run for this candidate.

Run only this command during active application work:

```sh
npm --prefix .pi/runtime/browser-reliability-offline/.pi/extensions/50-browser test
```

The candidate worktree has its own APFS copy-on-write copy of the pinned dependency
directory, **not a symlink to live dependencies**. No installer or patcher was run.
Tests build extension fixtures only in temporary directories; they do not install
anything or connect to Chrome. Candidate dependency writes cannot modify the live
directory.

New coverage includes full-value verification, empty clear, newline normalization,
shadow focus, truncation, focus loss, pre-mutation budget rejection, simultaneous
long input through real fixed-action routing, lease conflicts, a stalled session
with another queued, local failure isolation, late underlying completion after
request rejection, quarantine bypass refusal, safe release, preflight deadline
handling, persistent reset/failure reporting, and actual MCP deadline selection.

## Deployment procedure / remaining live acceptance gate

Sir's explicit session-completion confirmation and deployment approval fulfilled
the deployment gate; the source deployment and bridge restart in steps 1–2 are
complete. Step 3 applies when any prior client resumes browser work. Steps 4–5
remain pending an explicitly idle maintenance window. Do not infer keyboard/mouse idleness from a
successful application submission or a finished session, and do not poll/watch
sessions to trigger deployment.

1. Obtain fresh approval, have all browser clients pause, record the deployed commit
   and prepare rollback. Preserve personal/application tabs and unsaved values.
2. Review/commit the candidate, merge or cherry-pick only its browser changes into
   main, and restart **only** the bridge with approval. This candidate needs no
   extension replacement, native-host change, Chrome restart or profile migration.
3. All sessions must list and explicitly reselect their own stable tab IDs after
   daemon restart. Never replay old actions or resubmit applications.
4. With the existing automation window still manually on Desktop 2 and a personal
   Chrome window first, run the opt-in fixture under foreground/Space telemetry:

   ```sh
   JARVIS_TEST_RELIABILITY_MAINTENANCE=1 \
     python3 .pi/extensions/50-browser/test-extension-focus.py \
     --spaces --script test-action-reliability-live.py
   ```

   The fixture opens only two local synthetic pages, validates simultaneous long
   fields, actual nested/page wheel movement, local selector-timeout isolation and
   retained drafts. It never restarts the bridge, creates another window, navigates
   existing tabs or submits anything. If quarantine occurs, it stops, retains the
   fixture tabs for evidence and does not bypass the fence. Full interaction and
   existing two-session reconnect tests remain required before final acceptance.
5. If wheel delivery fails, retain diagnostics and stop. Do not raise the timeout,
   foreground Chrome, disable guards, retry wheel blindly, or silently replace wheel
   semantics with DOM scrolling. Further investigation needs explicit supervision.

## Quarantine recovery / rollback

A timeout only bounds how long the caller waits. Underlying Chrome input may still
finish on its original page. Cached inventory is not proof that execution stopped.
Have clients stop sending browser requests; inspect the affected page under
supervision and determine what completed. Do not replay a submission/typing action.
Only after quiescing the old daemon execution and inspecting uncertain outcomes may
sir authorize restart/reconnection. No automatic reset is permitted to clear this
fence. Service restart destroys leases/selections, not the existing Chrome tabs.

Rollback reverts browser code commit `018be5b` (pre-deployment main was `6391988`)
and restarts only the daemon during an approved maintenance window. Use a scoped
revert, not a repository reset: unrelated work may be present. Keep the installed v2
background extension/helper and stock-handshake guard. No CDP/profile/window fallback.

Offline passes do not establish live wheel reliability, renderer behavior, or an
absolute no-focus/no-Space-switch guarantee. Keep those acceptance claims separate.
