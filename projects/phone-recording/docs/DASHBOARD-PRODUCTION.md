# Single-screen dashboard rollout

September 9, 2026 — local mac-mini-64 dashboard, existing guarded job engine.

## Shipped

- Viewport-sized control panel: session state/timer, camera cards, framing, delivery stages and latest take. Main page verified without vertical or horizontal scrolling at **1440×900, 1280×720, 1024×650 and 900×600 CSS viewports**, 100% zoom, with four synthetic enabled cameras.
- Take library, camera details, activity/recovery and logs use bounded overlays. Long histories/logs can scroll **inside** overlays; they never expand the main page. Extremely small windows/high accessibility zoom retain a scrolling fallback instead of hiding essential controls.
- Camera cards show configured format (not an unmeasured live format), last observation, stale readings, unavailable battery/storage/temperature and reported warnings/blockers. Full details remain available when small-window framing mode compresses metadata.
- Primary Check → Start → Stop & prepare action, with immediate duplicate-submission suppression. Independent idle Check/framing controls. Framing requires fresh, matching, all-idle observation in the UI; the existing remote worker independently verifies idle state again.
- Recording is labelled **last confirmed**, not continuously monitored. Timer is elapsed since the matching take's successful Start confirmation—not exact clip duration—and remains marked as last-known if the dashboard disconnects. Pending Start never displays as confirmed recording.
- Local preparation publishes actual **copy/verify → audio sync → Resolve import** phases through the owning running job. Remote Stop/collection remain grouped until the worker reports completion; no invented per-camera percentages or transfer-speed estimates.
- A successful audio sync is no longer labelled a successful Resolve import. Cached import receipts explicitly describe past completion. **Open Resolve** launches the app only: it does not switch projects, select a timeline or replay an import. Human edits remain untouched.
- Unknown requests remain fail-closed; recovery is labelled **Reconcile — no retry**. Disconnects disable commands and warn that recording/jobs may continue.
- Allowlisted diagnostic download: states, numeric health metrics, job phases/timestamps and counts. No credentials, paths, endpoint addresses, serials, media, full raw results or logs. Raw logs remain separately accessible and should be reviewed before sharing.
- Toronto time formatting automatically labels EDT/EST correctly. Native dialog keyboard/focus behaviour and visible focus outlines retained.

## Safety scope

No changes to phone command/deletion protocols, readiness thresholds, source formats, audio alignment algorithms or REAPER. No new background phone polling, preview stream, notification permission request, network listener or protected Resolve-container access. Existing authenticated loopback HTTP service is retained.

Update: guarded explicit deletion and two review pauses are now implemented; see [DELETE-AND-REVIEW.md](DELETE-AND-REVIEW.md). The remainder of this document describes the earlier single-screen rollout. The user's latest instruction not to create recording/project backups must be honoured for their requested cleanup; this release adds no automatic backups.

## Validation

**150 automated tests pass**, including the original safety/security suite, preparation progress ownership, the authenticated known-take Resolve app opener, and an isolated real-Chrome UI test. The UI test performs **26 checks at each of four viewport sizes**: healthy/stale/unknown states, recording timer identity, uncertain requests, actual sync phase, failed import, overlay opening, double-click submission, disconnects and four-camera framing fit.

Headless tests use synthetic state and images, a temporary browser profile and a mocked fetch function. They never call the real dashboard API or phones. Their private process group is bounded and closed without touching visible Chrome. Live visible Chrome also verified the actual dashboard and recovery overlay at 1920×873. Server was restarted only after confirming no active jobs.

**Not yet production-qualified hardware reliability:** no new recording was made for this UI rollout. Long-session recording, camera disconnects during actual collection, OS reboot recovery and four-camera hardware/VFR/playback validation remain outstanding. Existing durable-job recovery is retained and tested, not a new boot-time watchdog.

## Follow-up priorities

1. Bounded real recording through the updated dashboard, including framing and Resolve handoff.
2. Longer sessions, thermal/storage boundaries, lost connections and safe process-restart tests.
3. Instrument real per-camera byte progress before displaying speeds/ETAs.
4. Add guarded cleanup only after scope/intent/failure tests; do not expose a broad delete button.
5. Optional physical controls after the same shared engine proves reliable.
