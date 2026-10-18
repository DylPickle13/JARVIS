# Home health — Telemetry redesign

Implementation of the owner-selected graph-first iPhone/Watch concept, originally deployed in 263. **Follow-up build 264 installed once on each device and independently version/process verified at 22:22 EDT, October 17, 2026.** iPhone used USB; Watch used wireless. Exact signed 263 is retained for both. The owner reports the follow-up works. Broader physical gesture, Crown and VoiceOver acceptance remains separate. See [validation and deployment](operations.md#watch-health-corrections--build-264-installed-on-both-devices).

## Follow-up correction — build 264 installed

The owner reported Watch history alternating between healthy and “History cached or paused”. The code coupled history polling eligibility to `isViaPhone`, which describes the latest state snapshot's origin: unsolicited phone snapshots set it true and direct Watch refreshes set it false. Direct history availability is now tracked independently and bound to the verified endpoint. Relay updates neither revoke nor establish that availability. A real direct failure, backgrounding or endpoint replacement invalidates it; covered/Always-On states still stop polling, and stale/failed history remains visibly unverified. No freshness threshold or polling interval is relaxed.

The separate three-dot details chooser is removed on both platforms. Services and Minecraft exceptions still open their existing read-only sheets directly; healthy groups remain hidden, without replacement menu controls. The card now uses the same `jarvisGlassSurface(surface, ...)` appearance as neighboring cards, including light/dark, contrast and Reduce Transparency behavior, rather than a hard-coded blue background or status-tinted wash. These corrections are included in installed build 264; the original 263 archive is retained unchanged as rollback.

## Presentation

- Thin categorical health trace, restrained glow/gradient fill, quiet precision grid and recorded-time labels. No invented health percentage, heartbeat, group counter or healthy-component checkmarks.
- Current exceptions only: warning triangle for issues, question mark for unverified data, clock for checking, pause for inactive. Backend-only problems and connection/history notices remain visible. Exception lists never silently truncate.
- A restrained status border is cyan for healthy, amber for issues, neutral for unknown/offline. Light appearance uses higher-contrast dark cyan/amber. High-contrast mode strengthens traces; dimmed Watch removes the glow.
- A source-evidence beacon pulses briefly only for a newer represented source timestamp. First appearance, repeated cached responses, clock ticks, stale/mixed/partial/unverified history and hidden/reduced-motion/dimmed presentations do not claim fresh activity.
- iPhone inspection uses a short hold followed by dragging so ordinary vertical scrolling remains available. The tooltip labels the selected minute interval, including mixed/partial evidence. VoiceOver adjustment provides a non-drag inspection alternative. Watch receives no new touch-drag or Crown recognizer.
- Build 263 provided an ellipsis chooser for healthy Services/Minecraft detail access. The owner requested its removal in the follow-up above. Direct exception-row routes retain platform-owned read-only sheets, covered-state polling/motion gates and separate service scopes.

## Recovery and evidence

`SystemTelemetrySession` is presentation-only, endpoint-scoped memory in the existing history model. A newer, trusted cached observation changing from a problem to healthy sets a conservative recovery boundary. Repeated, older, future-dated or disconnected observations cannot reset it. Endpoint changes clear this memory.

For a currently verified healthy system, only the trailing wholly healthy recorded buckets are shown. Their start becomes a monotonic display fence, so offline/unknown transitions cannot resurrect already-hidden incidents. Buckets crossing the fence are omitted whole, not split or recoloured. A latest mixed/partial/problem bucket can therefore produce **Waiting for verified healthy history** until the recorder catches up. No green line is backfilled instantly after recovery and no exact physical recovery time is inferred inside an aggregate bucket.

During a current incident, display the recent affected range plus a preceding healthy context bucket. If the current state reports an issue before history records it, say **Waiting for current history**, not a misleading healthy endpoint. Stale/paused traces are muted and labelled cached. Initial all-healthy history says **Healthy observations**, not an invented recovery time.

Each point is a cached observation bucket, not uptime or exact failure duration. Full homogeneous buckets may connect with categorical steps. Gaps and mixed/partial buckets break the trace and retain hatching/observed-state caps. Unavailable, inactive and unknown remain distinct. Inspection exposes covered/missing seconds and reason codes.

**Stored history/events, freshness rules, credentials, backend and provider polling are unchanged.** History still polls at its existing 60-second presentation cadence. No extra refreshes, model probes, physical actions or backend writes are introduced. Neural Core sources and behavior are untouched.

## Layout and validation

The previous fixed-height ring/chip overview is replaced by a graph and a variable-length exception list. Normal healthy cards remain compact. Larger text and many exceptions use the existing iPhone parent scroll view and Watch Crown viewport; the shared card owns neither and must not clip or discard rows to force a one-screen fit.

Shared tests cover recovery ranges, late history, mixed/gap handling, stale/offline behavior, monotonic source/fence rules, beacon admission, endpoint reset and accessible inspection evidence. Native fixtures cover healthy/issue/offline, phone/compact Watch widths, light/dark appearances, accessibility text and read-only detail routes. A watchOS simulator build is required separately; rendering compact content on iOS alone does not prove Watch compilation. Physical display/gesture/VoiceOver acceptance is separate from these tests.
