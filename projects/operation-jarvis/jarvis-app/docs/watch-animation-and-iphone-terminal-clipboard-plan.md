# Watch animation reliability and iPhone terminal clipboard plan

Status: implementation candidate in `/tmp/JARVIS-watch-clipboard`, branch `fix/watch-reliability-terminal-clipboard`; not installed or physically accepted.

## Implementation notes

- Watch uses 40 evenly spaced scenes / nominal20FPS over the original2s loop; phone remains48 / nominal24FPS. This is a resource-reduction experiment, not a proven fix for intermittent stalls. Current Watch crash-list retrieval timed out; no new causal evidence was obtained.
- Seven alternating hostMacImageRenderer runs: median incremental footprint48frames=19,087,528bytes versus40frames=17,236,136bytes (about1.77MiB less). Not actualWatchWidgetKit peak or energy evidence.
- Inline long-press uses the terminal's selection highlighting/handles and a native Copy menu. To keep selected cells stable under alternate-screen redraws, a bounded, noninteractive cell-rendering layer holds the exact visible viewport in place. No sheet, navigation or reflow; the original terminal and SSH parsing continue underneath. Dismissal removes the layer and shows current output. Only viewport cells are held, scrollback is disabled in that layer, and its display resources are closed on dismissal. Visual equivalence and VoiceOver still need physical acceptance.
- The keyboard proxy forwards Copy/Paste rather than copying its hidden sentinel. Native Paste control starts asynchronous provider loading with captured request/connection/generation identities. Text is limited to64KiB, terminal control characters are rejected, and multiline/tab paste requires review. Without bracketed paste, only the explicit single-line conversion is allowed. No Return is appended; confirmation is consumed before sending, and stale completions are discarded.
- Isolated simulator fixtures cover no-byte selection/copy, live parsing during selection, Unicode handle extension, scroll suppression/resumption, resize/transition cleanup, paste policy, review confirmation, cancellation and keyboard-proxy routing. Physical gesture/clipboard-permission/Watch reliability acceptance remains outstanding.
- No backend, livePi-session or device deployment changes. Tests/results are under `/tmp/JARVIS-watch-clipboard-checks` pending final artifact retention.

## Baselines and scope

- Owner now reports two intermittent Watch animation stalls after initially accepting Build170. Initial acceptance is retained; sustained reliability is not established.
- Owner now permits evaluating 20 FPS on Watch. This supersedes the earlier no-FPS-change constraint for this new experiment only; rejected Build167 (12 frames / 6 FPS) remains rejected.
- Starting Watch implementation is accepted Build170: `fix/watch-frame-wrapper-memory`, executable commit `f81ce02`, verifier-only follow-up `8a78455`. Main predates this fix; do not rebuild/regress Watch from main accidentally.
- iPhone remains Build166. Its shared-gradient experiment showed no host benchmark benefit and was rejected; retain its original gradient path.
- Preserve all nine pane/PID/attachment-generation/socket/history identities, existing scrolling, routing, attachment handling, configuration, Siri, notifications and backends. No live-session test submissions, resets or service restarts.

## 1. Diagnose and reduce Watch animation stalls

1. Correlate a recurrence with awake versus Always-On, Reduce Motion, elapsed time and whether both core and pulses freeze. Capture installed widget identity, current crash reports, process lifecycle, reload-request preferences and bounded memory samples where connectivity allows. A reload request is not proof of timeline delivery; sampled footprint is not true peak memory.
2. Separate expected frozen states from failure to resume on wake. Investigate timer-selector/timeline replacement as well as memory pressure; do not assume every stall is a Jetsam kill.
3. Build an isolated Watch-only 40-frame / two-second-loop candidate, nominal 20 FPS. Generate 40 evenly spaced phases across the complete loop, not the first 40 of the old 48. Preserve all geometry, luminance, twelve pulses, speed, tails/glints, masks, accessibility and existing reload limits. iPhone stays at 48 frames / nominal 24 FPS. This reduces scene count by 16.7%, not necessarily memory or energy by 16.7%; watchOS still controls actual display cadence.
4. Compare full-tree resource usage against170 and test frame-count/phase/font-selector contracts, wrap continuity, frozen fallback and rendering in both color modes and supported sizes. Do not blindly lower a shared constant or introduce reload polling.
5. Deploy Watch-only after archive/signature/capability and fresh preservation checks. Retain signed170 and known-working core-only165 rollback options. Check awake core and beam motion, repeated sleep/wake, app/face transitions, guarded timeline replacement and extended normal wear. Confirm physical AOD/Reduce Motion behavior separately.
6. If stalls persist without resource-failure evidence, address the demonstrated selector/resume or delivery issue rather than repeatedly reinstalling or reducing FPS further. Any recovery change needs its own scoped tests.

## 2. iPhone terminal text selection and copying

Source findings: `PiSSHTransport.swift` explicitly disables long-press and multi-tap SwiftTerm selection gestures to preserve fixed-step remote scrolling. Re-enabling all gestures risks the previously rejected scrolling regressions.

Revised owner requirement: select text **directly in the existing terminal**, without opening a sheet, a separate snapshot view, or replacing/reflowing the terminal. Inline selection is the primary implementation, not a later enhancement.

- Long-press a word to select it in place; show selection highlights, draggable handles and the native Copy menu. Tapping outside dismisses selection without sending terminal input. Provide an equivalent accessible selection action without navigation or opening the keyboard.
- Audit the pinned SwiftTerm selection implementation and keyboard proxy, then selectively restore or adapt inline selection. Do not broadly enable all disabled recognizers or restore native scroll momentum.
- Arbitrate gestures explicitly: ordinary vertical drags retain existing fixed-step remote scrolling; a recognized long-press or selection-handle drag selects text and must not emit remote mouse/wheel/input bytes. Movement before the long-press threshold should remain a normal scroll. Test gesture cancellation and recognizer precedence.
- Copy readable terminal buffer text, preserving meaningful whitespace, logical wraps and Unicode without ANSI control sequences. Initially guarantee selection within the visible viewport; do not claim full session history or automatically scroll the remote terminal while extending selection.
- Keep the selected text tied to the highlighted content while live output arrives. First evaluate stable buffer anchors. If alternate-screen redraws overwrite selected cells, evaluate briefly holding local presentation at its exact current appearance while selection is active, continuing to receive and parse output, then rendering the latest state on dismissal. This must not create a separate view, stop the remote process, accumulate an unbounded update queue, or let Copy silently return text different from the highlight. Treat this as a prototype behavior to validate, not an assumed SwiftTerm capability.
- Clear selection safely on session/connection-generation changes, backgrounding and incompatible resize/reflow. Never carry selection across sessions, persist/log selected content, or send bytes merely to dismiss selection.
- Validate inline selection under ongoing output and existing scrolling in an isolated fixture before deployment. If the library cannot support these requirements reliably, report the specific limitation and revise the inline approach with the owner; do not substitute the rejected separate-view design.

## 3. iPhone terminal pasting

Source findings: `PiTerminalController.pasteIntoTerminal()` exists, but the reviewed app has no caller. `clipboardRead` deliberately returns nil; do not infer that enabling this delegate is the appropriate fix without tracing the pinned SwiftTerm implementation and keyboard proxy.

- Add a visible **Paste** control near keyboard/attachment controls, using the native user-authorized paste mechanism (`UIPasteControl` where appropriate).
- Trace hardware Cmd-V, keyboard edit-menu paste, the proxy responder, SwiftTerm paste encoding and the SSH send gate. Route supported user paste entry points through one session-bound operation.
- Read the clipboard only after explicit user action. Keep terminal-program clipboard reads blocked; do not enable remote OSC52 clipboard access to fix local paste.
- Paste plain text into the active verified session only. Capture the session/connection generation at initiation and reject stale completion after switching, backgrounding or reconnecting. Never queue/replay paste across sessions.
- Honor bracketed paste where negotiated. Preview multiline/control-containing text and provide a safe fallback where bracketed paste is unavailable; multiline paste must not silently become command execution. Never append Return or automatically submit a prompt.
- Establish bounded size and control-character handling, clear user feedback for empty/non-text clipboard or unavailable input, and cancellation. Image/file clipboard content belongs to the existing attachment workflow, not raw terminal bytes.

## 4. Verification and rollout

- Test inline selection using a synthetic terminal fixture: long-press/scroll arbitration, handle dragging, exact copied text, wraps, whitespace, Unicode/emoji, ongoing redraws, accessibility, outside-tap dismissal, resize and session changes. Verify the terminal stays in place without navigation/reflow and ordinary scrolling is unchanged. Assert zero outgoing terminal bytes from selection, copying or dismissal; if local presentation is held, assert output parsing continues, memory stays bounded and dismissal shows the latest state.
- Test paste with synthetic clipboard/input and a recording transport: exact encoding, bracketed delimiters, empty/oversized/control-containing input, no appended Return, one delivery only, permission failures, connection readiness and rapid session switches.
- Exercise touch scrolling, keyboard open/close, hardware keyboard, nine-session routing and attachments without sending probes to real Pi sessions.
- Run relevant native tests, app regression suite, simulator builds and source/signature/capability checks before separate device candidates. Establish fresh preservation baselines for each deployment.
- Keep Watch reliability and phone clipboard changes in separate commits/candidates. Inspect companion packaging/automatic synchronization when installing the iPhone app; do not silently replace the validated Watch implementation.
- Physical acceptance: owner observes sustained Watch recovery and can select/copy intended text and safely paste into the intended iPhone session. Installation, passing tests and refresh requests alone are not acceptance.
