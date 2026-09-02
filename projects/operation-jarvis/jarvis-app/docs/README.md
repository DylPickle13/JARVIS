# JARVIS app implementation documentation

This is the canonical documentation index under `jarvis-app/docs`. It consolidates the native APNs notification plan, iPhone terminal keyboard-avoidance plan, and native Photos/Files attachment plans into one navigable document. The broader app architecture, operations, deployment, recovery, and historical plans remain in the [app README](../README.md).

The dated status lines and checklists below are retained as implementation history; consult the app README and owner-only acceptance records for the currently deployed build state. Non-Markdown third-party license material remains separate under [`third-party/`](third-party/AnimationLimitBreaker-LICENSE.txt).

## Contents

- [Native iPhone and Apple Watch APNs notifications](#native-iphone-and-apple-watch-apns-scheduled-job-notifications)
- [Six fixed mobile Pi conversations](#six-fixed-mobile-pi-conversations)
- [iPhone terminal keyboard avoidance and native attachments](#iphone-terminal-keyboard-avoidance-and-native-attach-implementation-plan)
- [Pi attachment product contract](#jarvis-app-pi-attachment-integration-plan)

---

# Six Fixed Mobile Pi Conversations

Status: **Build 141 is owner-accepted; the next isolated candidate additively expands its protected three-session runtime to six fixed conversations**

Prepared: **2026-08-30 EDT**

## Fixed topology

| Slot | tmux session | UI label |
|---|---|---|
| 1 | `jarvis-ios` | `1` |
| 2 | `jarvis-ios-2` | `2` |
| 3 | `jarvis-ios-3` | `3` |
| 4 | `jarvis-ios-4` | `4` |
| 5 | `jarvis-ios-5` | `5` |
| 6 | `jarvis-ios-6` | `6` |

All six sessions use socket `jarvis-mobile` and working directory `/Users/dylanrapanan/JARVIS`. The mapping is compiled/host-allowlisted; no client-supplied tmux target is accepted. The surviving Slots 1–3 panes and Pi processes must not be replaced during rollout. Missing Slots 4–6 are created detached and continue running when no phone PTY or Watch poll is active. `window-size latest` remains the only sizing policy; no rollout or switch may call `resize-window`, `resize-pane`, `kill-session`, or `kill-server`.

Local VS Code presents exactly two terminal groups selected from the terminal-tabs picker on the right: Slots **1 | 2 | 3** in the first group and Slots **4 | 5 | 6** in the second. Every task client attaches with `-f ignore-size`. Because VS Code inserts each later split beside the first pane, deterministic task creation order is `1, 3, 2` and `4, 6, 5`; the visual order is still ascending. Closing a task terminal detaches only that client and never stops a tmux session or Pi.

The protected-runtime baseline for this candidate is Slot 1 pane `%0` / Pi PID `26167`, Slot 2 pane `%1` / Pi PID `24108`, and Slot 3 pane `%3` / Pi PID `96273`. Older acceptance history below records PID `99571`; that PID is historical and had transitioned to `26167` before this isolated feature began. The transition does not authorize another replacement: rollout must preserve all three current pane/PID identities unless an owner-approved recovery is separately recorded.

## Device behavior

- iPhone and Watch each persist `JARVISTerminalSlot` in their own `UserDefaults.standard` container. Their selections are intentionally independent.
- A horizontal left/right terminal swipe moves one slot without wrapping. Existing iPhone vertical touch scrolling, Watch vertical Terminal → Plugs → System paging, and Digital Crown history remain axis-separated.
- iPhone owns one SSH parent and at most one attached PTY child. A switch closes the previous child before opening the fixed command for the new slot. Generation checks reject stale output/readiness callbacks, and input is never queued or replayed while switching. Keyboard and key-deck input remain disabled during replacement; if the software keyboard was focused, its isolated proxy resigns and resets, then rearms only after readiness from the exact fresh generation. No Escape or other terminal byte is synthesized.
- Watch polls only the selected slot. Frame, history, input acknowledgement, and speech responses carry and validate `sessionID`; a mismatched or stale response cannot enable input.
- Siri reads the invoking device's locally persisted slot, preflights that slot, and submits one non-retried input carrying the same identity.
- Deep links continue to open the terminal without changing the remembered slot.

## Additive host protocol

`jarvis-terminald` retains all `/v1/terminal/*` routes as Slot 1 for installed older builds. New apps use `/v2/terminal/*` and must supply exactly one session identity from `1...6`. The daemon owns independent `TerminalService` instances, frame sequences, histories, input-deduplication sets, samplers, speech markers, and bounded speech caches per slot. JSON input acknowledgement and WAV response headers echo the selected identity.

The launcher remains no-argument-compatible with Build 132 and additionally accepts only `--slot 1|2|3|4|5|6` plus optional `--ensure-only`. Startup eagerly ensures the six fixed sessions without attaching a hidden client.

## Slot-scoped native attachments

The iPhone paperclip always targets the active iPhone slot and switching is blocked for the life of an attachment sheet/transaction. PTY and attachment bytes remain separate typed SSH child channels. The receiver accepts only optional `--slot 1|2|3|4|5|6`; filenames and other picker data never enter its command string.

Each exact mobile Pi process publishes `pi-attach-mobile-slot-<slot>.json`. Slot 1 also publishes/accepts legacy `pi-attach-mobile.json`, including fallback to a live legacy descriptor if a scoped descriptor is stale during rollback. Every descriptor remains mode `0600` under the mode-`0700` private runtime directory and points to an owner-only process-scoped socket. Queue CAS, byte/hash verification, limits, deadlines, ambiguity handling, flat `attachments/` storage, and no-model-turn behavior are unchanged.

## Rollout boundary

1. Audit source and signed archive in isolation; do not touch production tmux or physical devices.
2. Record Slots 1–3 sessions, panes, Pi PIDs, dimensions, clients, and descriptors before host rollout.
3. Land the compatible launcher/terminald/receiver first; prove installed Build 141 still reaches Slots 1–3.
4. Eagerly create Slots 4–6, then prove every Slots 1–3 pane/PID survived exactly.
5. Install only the exact audited archive on the allowlisted iPhone and Watch after owner instruction.
6. Physically accept independent persistence, horizontal gestures, Siri routing, attachments, Watch vertical/Crown coexistence, stale-response rejection, and all isolation invariants.

---

# iPhone Terminal Keyboard Avoidance and Native Attach Implementation Plan

Status: **implemented, audited, and deployed as Build 132; native iPhone attachments, stale-state foreground convergence, and job-centric output channels are accepted on the allowlisted devices, while checked-in source remains fail-closed without the candidate-only attachment flag**

Prepared: **2026-08-30 EDT**

Physical result: **Build 128 and the first Build 129 run both appeared to hide bottom Pi rows. Reinstalling the exact accepted Build 127 reproduced the issue, proving that app source was not the cause. The protected `jarvis-ios:0` window had retained a per-window `manual` override from an earlier detached-window recovery, despite the checked-in global `latest` policy. Restoring only that option produced observed 48×42 → 48×28 → 48×42 transitions without changing pane `%0`, PID 99571, history, editor state, or terminal bytes. Exact audited keyboard-only Build 129 was then reinstalled and physically accepted by the owner. Build 128 remains rejected and neither candidate was installed on Watch while its tunnel was unavailable.**

Build 130 subsequently passed physical Files and Photos staging, cancellation, clearing, hashing, size/mode, cleanup, pane-survival, no-model-turn, and flat-directory checks. Build 131 added bounded read-only foreground stale-state convergence. Build 132 added the accepted job-centric Jobs root, Discord-style complete output channels, and bounded safe inline links. Its exact audited archive was installed on both allowlisted devices as `0.3.0 (132)` without rebuilding; Watch remains attachment-isolated and APNs remains dormant.

This plan combines two iPhone terminal improvements:

1. Make the software keyboard deterministically leave both the native key bar and Pi's rendered input editor visible.
2. Add a native paperclip workflow that stages Photos/Files selections into the live Pi process exactly like the existing parameterless `/attach` command.

The existing attachment product contract remains in [the Pi attachment product contract](#jarvis-app-pi-attachment-integration-plan). This document refines its implementation architecture, sequencing, concurrency rules, tests, and physical acceptance gates now that the desktop/local `/attach` extension and Mac SSH picker bridge exist.

## Definition of done

### Keyboard

- Opening the software keyboard never leaves Pi's input editor or the native key bar beneath the docked keyboard.
- The terminal's actual UIKit bounds shrink above the keyboard; the fix is not a visual offset over an unchanged terminal.
- SwiftTerm publishes the resulting row count through the existing SSH window-change path, and tmux/Pi redraws inside the visible viewport.
- Keyboard-hidden launch, tap-to-open, the fixed keyboard toggle, interactive downward dismissal, hardware-keyboard input, rotation, background/foreground, and reconnect behavior remain intact.
- No synthetic terminal bytes, pane resize command, process restart, delayed input, or keyboard-forcing workaround is introduced.

### Native attachments

- A paperclip beside the keyboard control opens an iPhone-native attachment sheet.
- The sheet supports Photos and Files, multi-selection, staged-item review, removal, clear, cancel, progress, and bounded failures.
- Picker interaction and upload never type `/attach`, alter Pi's current editor text, emit Return, or start a model turn.
- A successful transaction updates the same live in-memory queue and Pi attachment widget used by desktop `/attach`.
- The next normal interactive Pi submission consumes the staged set exactly once.
- Failed, cancelled, stale, disconnected, or ambiguous operations do not mutate the authoritative queue unless the host proves that the transaction committed.

## Non-negotiable invariants

- Preserve tmux socket `jarvis-mobile`, all existing Slots 1–3 sessions, panes, ordering, and persistent Pi processes except for an owner-approved recovery action; the six-session design adds only fixed `jarvis-ios-4`, `jarvis-ios-5`, and `jarvis-ios-6`.
- Preserve immediate-only terminal input. Never queue, replay, synthesize, or retry terminal bytes.
- Preserve the current Keychain password storage, exact host-key pinning, changed-key rejection, LAN/Tailscale behavior, and fixed terminal bootstrap command.
- Keep PTY bytes and attachment bytes on separate SSH child channels.
- Do not expose arbitrary SSH execution, a user-controlled remote command, filename interpolation, or a general upload endpoint.
- Do not route attachments through `jarvisd`, `jarvis-terminald`, HTTP, a browser, cloud storage, or a persistent daemon.
- Keep the Watch app, both widget catalogues, hardware controls, Jobs, scheduler, room audio, and polling boundaries unchanged.
- Add no App Group, Photos-library-wide permission, background mode, notification prompt, APNs registration, push entitlement, or other signed entitlement.
- Keep Watch attachment selection, camera capture, share extensions, drag and drop, background upload, and automatic archive extraction out of scope.
- Treat file names and bytes as untrusted data. Never execute selected files.
- Retain only loose private attachment files on the Mac. Do not persist a staged-queue manifest on either device.
- Preserve the accepted Build 127 archive and acceptance records unchanged. A later build must receive its own audit and evidence.

## Current-state findings

### Why keyboard avoidance is intermittent

`PiTerminalView.swift` currently places `PiTerminalContainer` and `PiTerminalKeyBar` in a plain SwiftUI `VStack`. It relies on implicit SwiftUI keyboard-safe-area propagation. The keyboard's actual first responder, however, is `PiTerminalKeyboardResponder`, a transparent 1×1 `UITextView` embedded inside the `UIViewRepresentable`-hosted `PiTerminalHostView`.

The existing path correctly retains valid SwiftTerm dimensions and sends SSH window-change events, but it can only do that after UIKit gives the terminal a smaller frame. If SwiftUI does not settle the representable's keyboard-safe frame during a presentation transition, the terminal keeps its full-height bounds and Pi's bottom editor remains behind the keyboard.

The implementation should therefore make keyboard geometry an explicit UIKit constraint instead of adding timing delays, guessed keyboard heights, scroll offsets, or extra responder toggles.

### Why the existing SSH `/attach` path cannot simply be reused

The current project-local attachment implementation has two selection paths:

- Direct Mac use invokes the native AppKit picker.
- `.pi/scripts/jarvis-pi-ssh` starts a temporary picker bridge on the SSH **client** and reverse-forwards a random Unix socket into the remote shell.

The iPhone's persistent Pi process lives inside tmux and outlives individual SSH clients. It does not inherit a fresh reverse-forward socket or token whenever the app reconnects. Injecting bridge environment variables into a newly attached shell would not update the already-running Pi process.

The iPhone path therefore needs an extension-owned, process-scoped Unix socket on the Mac and a fixed receiver command reached through a second SSH child session. The existing `AttachmentStore`, image preparation, widget, and next-message transform remain authoritative.

## Architecture decisions

### 1. Deterministic keyboard layout — withdrawn in favor of the accepted composition

The initial implementation introduced an iPhone-only UIKit layout controller hosted by `UIViewControllerRepresentable`, using UIKit's public `UIKeyboardLayoutGuide` as the obstruction authority. Its first signed run occurred while tmux was unknowingly pinned to `window-size manual`, so that run could not isolate the container. Exact Build 127 subsequently reproduced the issue and proved the host override was causal. The controller and its synthetic geometry test remain removed because the accepted Build 127 SwiftUI `VStack` plus `UIViewRepresentable` composition physically works once `window-size latest` is restored, avoiding an unnecessary presentation rewrite. The bootstrap now reasserts that policy for the existing exact window without a resize command. The following text records the withdrawn design rather than an active production decision.

Production constraints:

- Terminal top/leading/trailing = container top/leading/trailing.
- Native key bar top = terminal bottom.
- Native key bar height = the accepted 46 points.
- Native key bar bottom = `view.keyboardLayoutGuide.topAnchor`.
- When the keyboard is hidden, the keyboard layout guide naturally resolves to the container safe-area bottom.
- Keep `followsUndockedKeyboard` disabled for this iPhone-only app so a floating/undocked keyboard does not collapse the whole terminal around a small floating rectangle.

Host the existing SwiftUI `PiTerminalKeyBar` in a child `UIHostingController`; do not duplicate the controls in UIKit. The terminal and key bar then share one authoritative layout tree. If SwiftUI has already reduced the outer representable, the guide resolves at that reduced bottom and does not add a second inset. If SwiftUI has not reduced it, the guide still tracks the keyboard.

The terminal must receive a genuinely smaller frame. `PiTerminalHostView` then follows its existing path:

1. SwiftTerm recalculates rows and columns.
2. `sizeChanged` calls `PiSSHConnection.resize`.
3. `PiTerminalWindowState` retains the latest valid dimensions.
4. The live child channel receives a normal SSH window-change request.

Do not use keyboard notifications as the source of truth, hard-coded keyboard heights, `safeAreaPadding` guesses, content-offset writes, tmux `resize-pane`, or delayed `becomeFirstResponder` calls.

### Keyboard diagnostic boundary

Before changing layout, add a DEBUG/test-only content-free geometry probe recording only:

- container, terminal, key-bar, safe-area, and keyboard-layout-guide frames;
- SwiftTerm columns/rows and latest retained PTY dimensions;
- focus state and orientation.

It must never record terminal text, input bytes, credentials, host addresses, or screenshots automatically. Remove or compile out the probe before the release archive after the physical issue is reproduced and the fix is proven.

### 2. Native attachment flow

The data path will be:

```text
PhotosPicker / fileImporter
        ↓
iPhone private temporary file(s)
        ↓
second SSH session child on the existing pinned parent connection
        ↓
fixed absolute receiver command (no arguments from the selection)
        ↓
owner-only live Unix socket under .pi/runtime
        ↓
AttachmentCoordinator + AttachmentStore in the exact live mobile Pi process
        ↓
existing Pi attachment widget and next interactive input transform
```

The first implementation should use another `.session` child from the existing `NIOSSHHandler`. SwiftNIO SSH is designed to multiplex child channels over one authenticated parent. A disposable concurrency test must prove that PTY output/input and an upload can proceed without cross-channel bytes or lifecycle coupling.

Only if that test demonstrates an upstream limitation may the implementation use one short-lived second SSH connection. Such a fallback must reuse the same configuration, Keychain credential, pinned host key, and changed-key rejection; it must not introduce another trust path.

### Fixed receiver boundary

Add a fixed host command, for example:

```text
/opt/homebrew/bin/node /Users/dylanrapanan/JARVIS/.pi/scripts/pi-attach-mobile-receiver.mjs
```

The app stores this as a constant. It never appends a filename, path, request ID, shell fragment, or user-controlled value. The process is a bounded stdin/stdout proxy to the extension-owned Unix socket and exits after one operation. It is not a daemon and does not inspect or execute attachment content.

The extension publishes its mobile endpoint only when it proves it is running in the exact `jarvis-mobile` tmux socket and one of the six fixed sessions. Slot 1 must remain `jarvis-ios` pane `%0`; Slots 2–6 must be window/pane index `0` in their exact allowlisted sessions. Use the inherited `TMUX`/`TMUX_PANE` identity plus a fixed, read-only tmux identity query; fail closed if any value is absent or mismatched.

Runtime files:

- `.pi/runtime/pi-attach-mobile-slot-<slot>.json`: atomic mode-`0600` descriptor containing protocol version, fixed session identity, live Pi PID, random instance nonce, and socket path.
- `.pi/runtime/pi-attach-mobile.json`: Slot 1 compatibility descriptor for Build 132.
- `.pi/runtime/pi-attach-mobile-<pid>-<nonce>.sock`: owner-only socket under the existing mode-`0700` runtime directory.

On `session_shutdown` or `/reload`, close the listener and remove every descriptor owned by that instance plus its socket. A new extension instance uses a new nonce. The receiver rejects a symlink, wrong owner/mode, dead PID, mismatched slot, stale descriptor, unsupported version, or unavailable socket.

### Shared attachment coordinator

Refactor the current extension-local `store`, `staged`, and `pickerBusy` state behind one `AttachmentCoordinator` used by:

- desktop/local `/attach`;
- the existing Mac SSH picker bridge;
- the mobile socket;
- the interactive-input consumption hook.

The coordinator owns:

- the current memory-only staged records;
- a monotonic in-memory revision;
- one current Pi-instance generation/nonce;
- bounded recent request outcomes for ambiguous-delivery queries;
- atomic widget refresh;
- mutation serialization at the final commit point.

A mobile picker first reads a snapshot containing generation, revision, limits, and staged metadata. Its eventual reconcile request includes the expected generation and revision. If the user submits a Pi message, invokes desktop `/attach`, reloads Pi, or otherwise changes the queue while the iPhone sheet is open, the mobile commit fails as stale and returns the new snapshot. It must not overwrite the newer state.

Remote transfer must not block ordinary terminal input for the duration of a large upload. Stream new files into owner-only `.incoming-*.part` files first. At final commit:

1. Recheck generation and expected revision.
2. Verify every exact byte count and SHA-256.
3. Allocate collision-safe loose filenames without overwrite.
4. Apply kept IDs plus new records as one logical queue mutation.
5. Delete removed unsent files.
6. Increment revision and update the Pi widget.
7. Record the bounded request outcome and acknowledge the committed revision.

If the revision changed, delete only the transaction's temporary files and leave the authoritative queue and existing loose files untouched.

### Versioned bounded framing

Use one documented binary protocol shared by TypeScript and Swift tests:

- 4-byte unsigned big-endian JSON-header length;
- UTF-8 JSON header, maximum 64 KiB;
- exact raw file bodies in header order, each with a declared 64-bit size;
- one bounded framed JSON response, maximum 64 KiB;
- no path values from the iPhone.

Version 1 operations:

- `snapshot` — returns generation, revision, limits, and staged metadata.
- `reconcile` — keeps selected staged IDs and adds zero or more streamed files.
- `requestStatus` — reports a bounded in-memory outcome for one request ID after an ambiguous disconnect.

Each reconcile includes:

- protocol version;
- UUID request ID;
- expected generation and revision;
- retained host attachment IDs;
- sanitized display name, exact size, and SHA-256 for each new file.

The host enforces the existing defaults and configured bounds: 10 files, 50 MiB per file, and 100 MiB aggregate unless the live extension reports lower valid values. Both ends enforce count, per-file, aggregate, header, name, timeout, and response bounds. The host remains authoritative.

A lost acknowledgement is ambiguous. The app may reconnect and perform the read-only `requestStatus` operation, but it must never retransmit automatically. If the exact live process proves the request committed, refresh and show success. If it proves the request did not commit, offer an explicit user retry. If the generation changed or the outcome is unknown, require a fresh snapshot/review rather than guessing.

### 3. iPhone picker and staging UI

The paperclip is a new trailing 44×46-point control next to the existing keyboard control. Preserve Escape, Ctrl, Tab, slash, Up, Down, and the keyboard toggle. Rebalance spacing only as needed to fit supported iPhone widths; do not remove or hide an accepted control.

Paperclip behavior:

1. Require a connected, host-key-validated terminal parent connection.
2. Resign the terminal keyboard without sending bytes.
3. Open an attachment sheet and fetch the authoritative host snapshot.
4. Offer **Photos** and **Files**.
5. Let the user build a draft selection containing retained host items and new local items.
6. Display name, size, preparation/upload progress, removal, clear, and bounded errors.
7. **Done** performs one reconcile transaction. **Cancel** leaves host state unchanged.
8. After a verified acknowledgement, dismiss or refresh the sheet; Pi's existing widget is the authoritative terminal presentation.

Do not maintain a persistent paperclip badge from cached state because it could become stale after desktop changes or prompt consumption.

### Files source

Use SwiftUI `fileImporter(allowsMultipleSelection: true)`. For each returned security-scoped URL:

- balance `startAccessingSecurityScopedResource()` and `stopAccessingSecurityScopedResource()`;
- coordinate File Provider access where needed;
- reject directories, packages presented as directories, symlinks, unavailable placeholders, and files beyond live limits;
- stream-copy to an app-private temporary regular file;
- avoid logging the source URL or provider path.

### Photos source

Use `PhotosPicker` with image selection and the live remaining file-count limit. Use a custom `Transferable` `FileRepresentation` so the result is copied from a temporary file representation. Do not use an unbounded `Data` load fallback. The system picker must not request broad photo-library authorization.

Preserve the selected representation's safe extension where available, sanitize its display name, and apply the same limits as Files.

### Device temporary storage

Use a per-operation directory below the app's temporary container:

- random non-user-derived directory and filenames;
- complete file protection while at rest;
- excluded from backup;
- no manifest retained across app launches;
- streamed 64 KiB chunks rather than whole-file memory loads.

Delete temporary copies on picker cancellation, explicit removal, clear, verified success, definitive failure, leaving the terminal tab, app backgrounding, or app termination cleanup. During an ambiguous disconnect, keep only the current foreground operation long enough to query status; never create a durable retry queue.

The app becoming merely `.inactive` for a system picker must not cancel selection. Actual `.background`, terminal-tab departure, connection loss, or host-key failure cancels the child channel and moves the state to failure/ambiguous as appropriate.

## Source touchpoints

### Keyboard

- `JARVIS/Terminal/PiTerminalView.swift`
  - Replace the implicit `VStack` terminal/key-bar composition with the UIKit-backed viewport container.
  - Keep setup and status overlays behaviorally unchanged.
- New `JARVIS/Terminal/PiTerminalLayoutController.swift`
  - Own terminal, hosted key bar, keyboard layout guide constraints, and test-only guide injection.
- `JARVIS/Terminal/PiSSHTransport.swift`
  - Preserve the keyboard proxy and resize path; expose only minimal content-free geometry/test hooks if needed.
- `JARVISTests/AppStateTests.swift`
  - Add deterministic layout and resize regression tests.

### Host attachment endpoint

- `.pi/extensions/05-attach.ts`
  - Use the shared coordinator and start/stop the exact mobile endpoint with session lifecycle.
- `.pi/extensions/lib/attach/core.ts`
  - Refactor transactional preparation/commit while preserving current local and SSH behavior.
- New `.pi/extensions/lib/attach/mobile-server.ts`
  - Exact tmux identity gate, socket lifecycle, protocol parser, revision checks, request outcomes, and bounded responses.
- New `.pi/scripts/pi-attach-mobile-receiver.mjs`
  - Fixed no-argument stdin/stdout-to-Unix-socket proxy.
- New focused `.pi/scripts/tests/pi-attach-mobile-*.test.mjs`
  - Protocol, socket, transaction, ambiguity, permissions, and cleanup tests.
- `.pi/smoke-test.sh` and `.pi/docs/PI_EXTENSIONS.md`
  - Inventory and document the fixed private mobile receiver without adding a command/tool surface.

### iPhone attachments

- `JARVIS/Terminal/PiTerminalController.swift`
  - Publish the attachment sheet/state machine, coordinate lifecycle cancellation, and expose no arbitrary command API.
- `JARVIS/Terminal/PiSSHTransport.swift`
  - Add a separately typed attachment child-channel operation on the authenticated parent.
- New `JARVIS/Terminal/Attachments/`
  - `PiAttachmentModels.swift`
  - `PiAttachmentProtocol.swift`
  - `PiAttachmentTemporaryStore.swift`
  - `PiAttachmentPickerView.swift`
  - `PiAttachmentUploader.swift`
- `JARVIS/Terminal/PiTerminalView.swift`
  - Add the paperclip and sheet presentation.
- `JARVIS/JARVISApp.swift`
  - Route actual background lifecycle cancellation through the controller if the existing controller hook is insufficient.
- `JARVISTests/`
  - Add codec, limits, picker-state, cleanup, concurrency, and transport tests.
- `scripts/verify-jarvis-app.sh`
  - Preserve the accepted terminal-control contracts while explicitly allowing the paperclip and rejecting text injection/arbitrary exec.
- `project.yml`
  - No capability change; only the normal final build-number bump. Regenerate `JARVIS.xcodeproj` rather than hand-editing it.

## Implementation sequence

### Phase 0 — isolate the work

1. Finish or separately preserve any unrelated working-tree changes before implementation.
2. Start from a clean branch/worktree containing the accepted terminal behavior and current host `/attach` implementation.
3. Capture baseline simulator/physical keyboard-hidden and keyboard-open geometry without changing the protected pane.
4. Confirm existing `/attach`, smoke, JARVISKit, iPhone, jarvisd, and terminald tests pass.

Exit gate: clean baseline and reproducible keyboard-obscuration evidence or geometry proving the unsafe layout transition.

### Phase 1 — keyboard fix only

1. Add the UIKit layout controller with injectable bottom layout guide for tests.
2. Move the existing terminal and unchanged key bar into that controller.
3. Keep all focus, gesture, byte, and resize behavior unchanged.
4. Add automated hidden/open/repeated-transition/landscape constraint tests.
5. Run a simulator keyboard-toggle loop and inspect final frame/row assertions.
6. Produce a keyboard-only physical candidate before adding the paperclip.

Exit gate: repeated physical keyboard transitions cannot cover the Pi editor or key bar, and terminal/tmux identity and byte behavior remain unchanged.

### Phase 2 — host mobile attachment endpoint

1. Refactor attachment state behind `AttachmentCoordinator` with revisioned transactional commits.
2. Add protocol parser/encoder tests before opening a real socket.
3. Add the exact mobile-process identity gate and owner-only socket lifecycle.
4. Add the fixed receiver proxy.
5. Test `/reload` teardown/rebind in a disposable Pi session.
6. Re-run every existing native attachment test to prove local Mac and `jarvis-pi-ssh` behavior is unchanged.

Exit gate: a disposable receiver can snapshot/reconcile/query status against the exact fixture Pi process, with no production pane or service touched.

### Phase 3 — iPhone local selection and state machine

1. Add models, temporary storage, Files ingestion, and Photos file-representation ingestion behind injected protocols.
2. Add the attachment sheet and draft-selection behavior.
3. Add the paperclip to the already accepted keyboard-safe key bar.
4. Test cancel/remove/clear/stale snapshot/background cleanup without SSH.

Exit gate: UI and local-file tests pass with no terminal text/byte mutation and no broad Photos permission.

### Phase 4 — multiplexed SSH upload

1. Add the no-PTY attachment child handler and strict framed codec.
2. Stream with bounded chunks and channel backpressure.
3. Keep upload errors scoped to the child; never mark a healthy PTY failed because an attachment operation failed.
4. Cancel all child work on parent disconnect/tab departure/background.
5. Add concurrent PTY/upload disposable integration tests.
6. Add ambiguous-acknowledgement and request-status tests.

Exit gate: exact files stage through the fixture while simultaneous terminal bytes remain ordered and uncontaminated.

### Phase 5 — controlled live integration

1. Verify the production staged queue is empty.
2. Record tmux socket/session/pane/Pi PID and terminald/jarvisd identities.
3. Load the host extension with one owner-approved Pi `/reload`; this should replace extension state without restarting Pi or tmux.
4. Verify endpoint mode, PID binding, and socket cleanup/rebind without uploading a file.
5. Install only the exact audited iPhone candidate on the allowlisted phone.
6. Perform harmless owner-driven attachment tests.
7. Reconfirm pane `%0`, session `jarvis-ios`, Pi PID, terminald, jarvisd, scheduler, and room-audio isolation.

If `/reload` cannot establish or cleanly remove the endpoint, stop and roll back the host extension. Do not restart or recreate the protected pane as an automatic recovery.

## Automated test matrix

### Keyboard

- Hidden guide resolves to safe-area bottom.
- Docked guide places the 46-point key bar immediately above the keyboard.
- Terminal bottom always equals key-bar top.
- Repeating hidden/open layout at least 25 times produces no cumulative inset or stale frame.
- Portrait and both supported landscape orientations.
- Hardware keyboard/zero software-keyboard obstruction.
- Interactive dismissal updates continuously and returns to the exact hidden layout.
- Every generated terminal dimension is positive; the final open size has fewer rows than hidden and restores afterward.
- No keyboard transition invokes terminal send callbacks.
- Existing backspace-repeat proxy, Ctrl latch, slash, arrows, touch scroll, and fresh-connection resize tests continue to pass.

### Host protocol and storage

- Fragmented/coalesced headers and file chunks.
- Empty files, maximum accepted boundaries, one-byte overflow, count overflow, aggregate overflow, header overflow, timeout, and truncated bodies.
- Invalid UTF-8/JSON, unsupported versions/operations, duplicate IDs, traversal names, separators, control characters, symlinks, and changed files.
- SHA-256 mismatch and declared-size mismatch clean up `.incoming` files.
- Collision-safe names never overwrite an existing loose file.
- Socket/descriptor modes, owner, atomic publication, stale PID, wrong tmux identity, stale nonce, reload, and shutdown cleanup.
- Revision conflict after desktop selection or prompt consumption leaves both old and new authoritative state untouched.
- Duplicate request ID returns the recorded outcome without importing bytes twice.
- Outcome retention is bounded and memory-only.
- Pi restart/reload clears unsent queue metadata while preserving already retained loose files according to the existing contract.
- Existing Mac picker and `jarvis-pi-ssh` suites remain green.

### iPhone

- Files and Photos cancellation preserve host state.
- Security-scope access is balanced on success, failure, and cancellation.
- File representations are streamed to protected temporary files; no whole-file `Data` path exists.
- Draft add/remove/clear and host retained-ID ordering.
- Host limits override local defaults.
- Strict frame encoding/decoding and bounded error text.
- Upload progress never marks an item staged before the verified host acknowledgement.
- Child cancellation does not close the parent PTY.
- Changed host key, disconnected terminal, dead Pi socket, stale generation/revision, app background, and tab departure fail closed.
- Lost acknowledgement performs only a read-only status query; there is no automatic upload retry.
- No filename/path enters the SSH command string, logs, preferences, Keychain, analytics, or terminal byte stream.
- No App Group, Photos usage string, background mode, APNs call, notification key, or new entitlement appears.

## Physical acceptance matrix

### Keyboard-first candidate

- Launch with keyboard hidden.
- Open by tapping the terminal and by the fixed keyboard button.
- Hide by the button and downward swipe.
- Repeat open/hide at least 20 times while output is idle and while harmless output is streaming.
- Rotate with keyboard hidden and shown through both landscape orientations and back to portrait.
- Switch tabs, foreground/background, reconnect LAN, and reconnect Tailscale.
- If available, connect/disconnect a hardware keyboard.
- At every step, Pi's input editor and the entire native key bar remain above the keyboard.
- Confirm no terminal bytes were generated by layout transitions and the protected pane/session were not recreated.

### Attachment candidate

Use only harmless, non-secret fixtures:

- one small text file from Files;
- one image from Photos;
- multi-select text plus image;
- picker cancellation;
- remove one retained item;
- clear all staged items;
- duplicate filename collision;
- a safely generated over-limit fixture rejected before transfer;
- background during a disposable transfer;
- connection loss after send/before acknowledgement in a fixture, followed by status resolution;
- LAN and Tailscale transfer.

For successful cases verify:

- exact host byte count and SHA-256;
- mode `0600` loose file under `attachments/`;
- correct Pi widget names/count;
- no automatic Return or model turn;
- next normal message consumes the set once;
- image reaches the existing native-image path and text reaches the existing local-path metadata path;
- the same Pi PID and tmux pane survive;
- no jarvisd lifecycle/control event, hardware write, scheduler mutation, notification registration, or Watch behavior change occurs.

## Build, audit, and rollout gates

1. Keep keyboard, host protocol, and iPhone attachment changes in reviewable commits so each layer can be reverted independently.
2. Run root smoke and all native attachment tests.
3. Run jarvisd, terminald, JARVISKit, and JARVISTests.
4. Regenerate the Xcode project and prove no unexplained generated diff.
5. Run target-scoped Swift 6 complete-concurrency and warnings-as-errors validation for `JARVIS` and `JARVISWatch`; do not force those flags onto SwiftTerm or C dependencies.
6. Run normal warning-free iOS/embedded-Watch and standalone Watch builds.
7. Audit Info.plists, privacy manifest, background modes, provisioning profiles, and signed entitlements. They must remain push-free and capability-identical to the accepted pre-membership scope.
8. Bump the build number only for the final candidate.
9. Create the archive from a clean exact source commit, checksum it, and install only its products on the two allowlisted devices.
10. Record keyboard and attachment physical evidence plus exact source/archive hashes in a new owner-only acceptance record.

### Automated implementation checkpoint

Before physical deployment, Gates 2–6 passed in the isolated source candidate: root smoke was `PASS=124 WARN=1 FAIL=0` (the warning was the temporary worktree's intentionally absent Pi session-history directory), attachment Node tests were 9/9 and 13/13, JARVISKit was 83 tests with three live-only skips, JARVISTests was 36/36, generated-project output was reproducible, and normal plus target-scoped Swift 6 warnings-as-errors builds passed for iOS and Watch. After retaining the accepted composition and removing the unnecessary synthetic layout test, the complete verifier passes JARVISKit 83 tests with three live-only skips and JARVISTests 35/35 with zero compiler diagnostics. Physical A/B testing identified and corrected the host `manual` sizing override, then accepted exact audited keyboard-only Build 129. The source still defaults to keyboard-only: the paperclip and programmatic sheet entry remain fail-closed unless `JARVIS_NATIVE_ATTACHMENTS` is enabled on the iPhone target for the later attachment candidate. The owner-only Build 128 artifact remains marked `REJECTED`. After the keyboard gate, the four reviewed host runtime files were copied with owner-only rollback backups and one controlled `/reload` preserved pane `%0` and Pi PID 99571. The resulting mode-0600 socket/descriptor passed a read-only fixed-receiver snapshot at revision 0 with no staged files; production root smoke passed `PASS=129 WARN=0 FAIL=0`. No Watch product was installed while its tunnel was unavailable. iPhone attachment and final cross-platform gates remain open.

## Compatibility and rollback

- Old iPhone builds ignore the new host endpoint.
- A new iPhone build connected to a host without the endpoint keeps the terminal fully functional and reports attachments unavailable; it never falls back to typing `/attach`.
- Desktop/local `/attach` and `.pi/scripts/jarvis-pi-ssh` retain their current behavior.
- Reverting the paperclip leaves the keyboard fix independent.
- Reverting the host endpoint removes its descriptor/socket during extension shutdown and leaves existing loose attachment files untouched.
- Reverting the keyboard container restores only presentation composition; it must not require tmux/Pi changes.
- Any host/app protocol mismatch fails closed before file bytes or queue mutation.

## Final acceptance checklist

- [ ] Keyboard issue reproduced or unsafe geometry captured without content.
- [x] Build 128's inconclusive keyboard-layout-guide candidate was removed in favor of the accepted composition.
- [x] Restored accepted terminal composition passes repeated physical transitions under `window-size latest`.
- [ ] No terminal input or protected-runtime regression.
- [ ] Host coordinator and mobile socket are exact-process-bound, private, transactional, and memory-only.
- [ ] iPhone Photos/Files selection is private, bounded, streamed, and cancellable.
- [ ] Paperclip never injects `/attach` or Return.
- [ ] Concurrent PTY and upload channels are isolated.
- [ ] Ambiguous delivery is queried, never automatically retried.
- [ ] Existing desktop `/attach` behavior remains accepted.
- [ ] Watch, widgets, Jobs, controls, scheduler, room audio, and APNs-dormant state remain unchanged.
- [ ] Exact signed archive passes audit and allowlisted-device physical validation.

---

# JARVIS App Pi Attachment Integration Plan

Status: **planned only — not implemented**

The combined execution sequence, keyboard-avoidance prerequisite, transaction model, and release gates are defined in [the combined iPhone terminal implementation plan](#iphone-terminal-keyboard-avoidance-and-native-attach-implementation-plan).

This document describes the deferred iPhone integration for the project-local Pi `/attach` extension. The desktop/local extension and SSH client bridge may ship independently. No JARVIS app source, Xcode project, `jarvisd`, or `jarvis-terminald` change is part of the current implementation.

## Product contract

- Pi continues to register exactly one parameterless attachment command: `/attach`.
- The iPhone app adds no Pi command, command alias, or text protocol exposed to the user.
- A paperclip control in the iPhone Pi terminal is the native app equivalent of invoking `/attach`.
- The app opens native `PhotosPicker` and `fileImporter` interfaces instead of a macOS file dialog.
- Selecting files stages them in the live Pi process for the next normal Pi message; selection never submits the editor or starts a model turn.
- The staging UI permits adding, removing, and clearing files without introducing additional slash commands.
- Only attachment files persist on disk. Restarting Pi clears the unsent queue; no manifest or other attachment metadata is saved.
- Watch attachment selection is out of scope.

## Proposed user experience

1. The user taps a paperclip beside the existing terminal keyboard control.
2. A native sheet offers **Photos** and **Files**.
3. The user selects one or more items and sees a staged-attachment tray with name, size, progress, and failures.
4. Successfully uploaded files appear in Pi's existing attachment widget above the editor.
5. The user's next normal terminal submission consumes the staged set.
6. Cancelling a picker or failed upload leaves the previously staged set unchanged.

The paperclip must not type `/attach` into SwiftTerm. Injecting command text could overwrite or combine with a partially edited prompt and would couple file transfer to terminal cursor state.

## Transport design

Use a separate one-shot SSH child session on the app's existing host-key-pinned SSH connection:

1. The live `jarvis-ios` Pi extension binds a fixed owner-only Unix socket under `.pi/runtime`; the socket is removed on shutdown and contains no persisted queue metadata.
2. The app opens a second SSH child channel and executes one fixed absolute receiver command. No user filename or local path is interpolated into the SSH command string.
3. The receiver connects to the live extension socket and the app sends a bounded framed stream: protocol version, request ID, sanitized display name, declared size, and then exact file bytes.
4. The extension streams to a mode-`0600` temporary file, verifies byte count and SHA-256, commits it directly under `attachments/` with a readable collision suffix, and adds the resulting record to its in-memory queue.
5. The extension refreshes the same Pi attachment widget used by desktop `/attach`; if the target Pi process is not live, the upload fails closed.

The transfer must not be routed through `jarvisd` or `jarvis-terminald`. Those services retain their current hardware/status and Watch-terminal boundaries respectively. There is no browser upload route, public listener, cloud storage, or persistent attachment daemon.

If SwiftNIO SSH cannot safely share the current parent connection for a second child session, use one short-lived second SSH connection with the same saved credentials and host-key validation. Do not weaken pinning or add a fallback trust path.

## Native APIs and source touchpoints

Expected app files:

- `JARVIS/Terminal/PiTerminalView.swift`
  - Add the paperclip control without changing terminal input semantics.
  - Present the source picker and staged-attachment tray.
- `JARVIS/Terminal/PiTerminalController.swift`
  - Own picker presentation state, upload progress, cancellation, and authoritative refresh.
- `JARVIS/Terminal/PiSSHTransport.swift`
  - Add the bounded one-shot upload child channel or short-lived upload connection.
  - Keep terminal PTY bytes and upload bytes on separate channels.
- New focused types under `JARVIS/Terminal/Attachments/`
  - Security-scoped file access.
  - Photo/file selection normalization.
  - Framing and upload state machine.

Use `PhotosPicker` for photo-library assets and SwiftUI `fileImporter` for Files. Copy security-scoped selections to one private temporary URL before upload, stream from disk rather than loading an entire file into memory, and delete temporary copies after a verified terminal-side acknowledgement.

## Reliability and safety requirements

- Enforce the same file-count, per-file, and aggregate byte limits as the Pi extension.
- Treat every selected file as untrusted data; never execute or automatically extract it.
- Sanitize display names on both app and host, while allocating collision-safe loose filenames.
- Use request IDs for receiver-side deduplication.
- A timeout or disconnected acknowledgement is ambiguous: do not retry automatically. Query the live in-memory queue before offering a manual retry.
- Cancel uploads when the app backgrounds unless the exact transfer has already received a verified acknowledgement.
- Never place file contents, host paths, mailbox nonces, credentials, or bearer material in logs or analytics.
- Reject an absent or stale live socket, dead Pi processes, changed SSH host keys, truncated streams, oversized bodies, traversal names, symlinks, and duplicate request IDs.
- Preserve uploaded files after their prompt is accepted because session history may refer to their local paths later.

## Test plan

### Unit tests

- Picker cancellation and multi-selection.
- Security-scoped URL acquisition/release.
- Size/count limits before transfer.
- Frame encoding and malformed acknowledgement rejection.
- Upload state transitions, duplicate request handling, ambiguous timeout behavior, and no automatic retry.
- Staged tray add/remove/clear behavior without terminal text injection.

### Disposable integration tests

- Use a disposable SSH server, receiver directory, Unix socket, and tmux/Pi fixture.
- Verify exact bytes, size, SHA-256, mode `0600`, collision-safe flat filename, and in-memory queue update.
- Verify a selected image appears as a native image on the next fixture prompt and a non-image appears as a readable local path.
- Verify cancellation, disconnect, changed host key, stale nonce, dead PID, oversize, duplicate request ID, and app backgrounding fail closed.
- Confirm that no fixture writes to the production `jarvis-ios` pane or touches `jarvisd`, `jarvis-terminald`, plugs, purifier, services, or schedulers.

## Rollout gates

1. Complete implementation behind the iPhone paperclip UI with no Watch changes.
2. Pass JARVISKit and iPhone tests plus disposable SSH integration tests.
3. Run warning-free iOS/watchOS builds and the repository verifier.
4. Archive and audit the exact signed product before physical installation.
5. Perform owner-driven physical validation with harmless files only: one photo, one text file, cancellation, background/foreground, LAN, and Tailscale.
6. Confirm the production tmux pane identity and Pi PID are unchanged throughout validation.

---

# Native iPhone and Apple Watch APNs Scheduled-Job Notifications

Status: **Build 144 implementation candidate; Build 143 remains immutable; provider and host dispatch remain dormant**

Prepared: **2026-09-01 EDT**

Implementation authorized: **2026-09-01 EDT**

## Candidate implementation status

The isolated `feat/native-apns-notifications` candidate implements the dormant
host provider/data model, strict registration helper, native iPhone/Watch
coordinators, explicit two-device authorization flow, fixed-command pinned-SSH
token upload, Jobs routing, Watch result sheet, sanitized Settings status, and
app-only push entitlements. The iPhone **Developer Signing** Settings destination
has been removed; the historical manual recovery script remains available.

Implementation does **not** itself enable delivery. `JARVIS_APNS_ENABLED` still
defaults to `0`, scheduler dispatch still defaults off in private SQLite config,
no authentication key is checked in, and no historical result is backfilled.
Apple capability/profile/key creation, exact signed archive audit, approved-device
registration, physical APNs validation, and final host-dispatch activation remain
separate gated rollout work.

## Decision summary

The first notification release will send the same generic scheduled-result alert to the JARVIS iPhone app and directly to the JARVIS Watch app, using each app's own APNs device token and bundle-ID topic:

- iPhone: `com.operation-jarvis.jarvis`
- Watch: `com.operation-jarvis.jarvis.watchkitapp`

The Watch app is currently a dependent companion app. Apple permits sending only to iPhone or to both devices for this app type, and states that when the provider sends to both, the system presents one notification at the best destination. JARVIS will choose both because direct Watch delivery is an explicit product goal and iPhone delivery remains the supported fallback. The provider must not attempt its own cross-device presentation or deduplication.

This is a new future build, not an in-place activation of Build 143. No portal capability, entitlement, profile, prompt, device registration, provider credential, network traffic, scheduler enqueue, daemon, port, or installed app changes are authorized by this plan alone.

## Product contract

### In scope

- Notify only when the scheduler persists a new non-silent result or error in its durable Jobs history.
- Retain the existing Jobs database as the source of truth. APNs is a lossy alert carrier, never the result store.
- Keep the lock-screen and Watch alert generic: `JARVIS Jobs` / `A scheduled job result is ready.`
- Include only a versioned route and positive retained `resultSequence` in custom payload data.
- Register the iPhone and Watch apps independently with APNs and retain one active approved-device registration for each topic and environment.
- On an iPhone notification tap, open the existing Jobs tab and exact result thread.
- On a Watch notification tap, present a bounded read-only result sheet over the existing app; do not add a fourth dashboard page or disturb Terminal → Plugs → System navigation.
- Add accurate notification health in Settings without exposing tokens, credentials, output, job names, or result contents.
- Preserve Build 143's six Pi sessions, attachments, exact-generation input behavior, Neural Core motion, controls, widgets, scheduler semantics, terminald, jarvisd, room audio, and ports `8790–8792`.

### Explicitly out of scope

- Discord, Web Push, email, SMS, third-party notification relays, or cloud result storage.
- Silent/background pushes, `content-available`, background fetch, background processing, PushKit, Live Activities, complication pushes, or notification service/content extensions.
- Job output, prompt, job name, status, links, host paths, tokens, or credentials in an APNs payload.
- Notification actions that execute commands or mutate Jobs. Jobs remains read-only.
- A new daemon, listener, public endpoint, or port.
- Automatic enrollment, launch-time permission surprises, profile mutation outside the audited candidate, or historical-result backfill.

## Existing foundation

The accepted tree already provides:

- `.pi/scheduler/apns_provider.py`: a dormant, fail-closed token-authenticated HTTP/2 provider with generic payloads, bounded JWT age, strict key permissions, and APNs response classification.
- `.pi/scheduler/runner.py`: a private mode-`0600` SQLite database with durable `results` and a dormant `notification_outbox`; current tests prove that the outbox stays empty before activation.
- `JARVISKit/Sources/JARVISKit/ScheduledJobNotificationRoute.swift`: pure validation of a positive `resultSequence` with no authorization, registration, token, traffic, or notification side effects.
- Existing iPhone Jobs deep-link routing and exact-result fetching.
- Existing WatchConnectivity, iPhone host-key-pinned SSH, and a private scheduler process that runs once per minute.

The provider's current Watch-only topic assumption is scaffolding, not the final architecture. It must be generalized to a strict two-topic allowlist before activation.

## End-to-end architecture

```text
Scheduler persists a bounded local result
            │
            ├── durable Jobs history remains authoritative
            │
            └── if and only if host dispatch is explicitly enabled:
                  create one notification event
                          │
                          ├── iPhone topic + active iPhone token
                          └── Watch topic + active Watch token
                                   │
                             Apple Push Notification service
                                   │
                          system chooses best presentation

Notification tap
      ├── iPhone → existing Jobs tab → exact retained result
      └── Watch  → bounded read-only result sheet → existing jarvisd result API
```

APNs acceptance does not mean display, and APNs delivery is not guaranteed. The UI must never infer that a result does not exist because no alert appeared. Conversely, an alert must never carry the result itself.

## Apple account, capability, and signing plan

Apple Developer Program enrollment is active as an Individual account under Team ID `5GB5BU49Q8`. The developer account already contains explicit App IDs for both required bundle identifiers and currently contains no APNs authentication key.

Portal and signing changes require a separate owner checkpoint and occur only after source and unsigned tests are ready:

1. Enable **Push Notifications** only on these two explicit App IDs:
   - `com.operation-jarvis.jarvis`
   - `com.operation-jarvis.jarvis.watchkitapp`
2. Do not enable Push Notifications on either widget identifier or any legacy Watch identifier.
3. Regenerate the affected paid-team development provisioning profiles. Apple invalidates profiles associated with a modified App ID, so no candidate may reuse the old profiles.
4. Add checked-in iPhone and Watch entitlements files and set `CODE_SIGN_ENTITLEMENTS` only on the two app targets. The final signed products must contain the profile-matched `aps-environment` value.
5. Keep `JARVISWatch/Info.plist` background modes exactly `audio`. Visible APNs alerts do not require `remote-notification`; `fetch` and `processing` remain forbidden.
6. Create a dedicated, least-privileged APNs authentication key matching the candidate environment. Prefer a topic-specific key covering only the two JARVIS app topics when the portal offers that option; keep sandbox and production credentials separate if the selected key type is environment-scoped.
7. Store the downloaded `.p8` outside Git under `~/Library/Application Support/JARVIS/apns/`, with directory mode `0700` and file mode `0600`. Add repository guards for `.p8`/`AuthKey_*`; never put key bytes in `.env`, source, logs, artifacts, tests, durable project memory, or documentation.
8. Record only non-secret evidence: Team ID, Key ID, allowed topics, environment, file permission check, and a local SHA-256 fingerprint. The `.p8` contents and APNs device tokens are excluded from every manifest and acceptance record.

The candidate audit must extract both the signed executable entitlements and embedded provisioning profiles. It must prove exact topic/profile alignment, the expected `aps-environment`, unchanged bundle identifiers, no push entitlement on widgets, and no new Watch background mode.

## Explicit authorization and app lifecycle

Notification support has three independent gates:

1. **Compiled support** — the future signed build has the exact capability and entitlement.
2. **Owner opt-in** — the owner explicitly enables scheduled-job notifications in JARVIS Settings and grants system authorization on both devices.
3. **Host dispatch** — the private scheduler configuration is explicitly activated after both registrations and provider credentials validate.

All three must be true before a real scheduled result can generate APNs traffic.

### iPhone

- Add an iPhone `UIApplicationDelegate` through `@UIApplicationDelegateAdaptor`.
- Install the `UNUserNotificationCenterDelegate` during app launch, but do not request permission or call `registerForRemoteNotifications()` merely because the app launched.
- Add a Settings-only **Scheduled job notifications** flow with explanatory copy and an explicit Enable button.
- After that action, request alert, sound, and badge authorization. If granted, call `registerForRemoteNotifications()` and do so again on later launches while the feature remains enabled, as Apple recommends.
- If authorization is denied, show a non-blocking Settings link; never loop or synthesize another prompt.
- Disabling JARVIS notifications unregisters the app locally and sends an idempotent deactivation to the host when the secure route is available. System permission remains owner-controlled in Settings.

### Watch

- Add a Watch application delegate through the SwiftUI Watch delegate adaptor and configure its notification-center delegate at launch.
- The iPhone opt-in sends only a non-secret desired-state signal through WatchConnectivity.
- On the next explicit Watch app use, show a JARVIS explanation screen with **Allow Notifications** and **Not Now**. The system authorization prompt appears only after the owner taps Allow Notifications.
- Once authorized, call the current WatchKit remote-notification registration API on every subsequent launch while enabled.
- Never add a notification toggle to the tight three-page dashboard. Permission setup is a temporary onboarding overlay; notification state can be summarized in the System page only if it fits without displacing accepted controls.

Authorization and APNs registration are different states. The Settings status must distinguish Off, Needs Permission, Registering, Pending Secure Upload, Active, Denied, and Error instead of collapsing them into a generic enabled flag.

## Secure device-token registration

Every app/device combination receives a different APNs token. The token can change, and neither app may rely on a locally cached old value. Each launch asks APNs for the current token, then forwards the callback value to the host.

JARVIS will not upload APNs tokens through plain jarvisd HTTP. It will reuse the accepted authenticated channels:

1. The iPhone receives its own token directly.
2. The Watch receives its own token and relays it to the paired iPhone through an immediate WatchConnectivity message. The message contains a strict versioned registration envelope; it is never placed in the shared state snapshot or latest-value application context.
3. If the phone is unreachable, the Watch retains the token only in process memory. A later explicit iPhone Retry preference can resend it, and the Watch asks APNs to register again on a later launch. It does not write the token to `UserDefaults`, cache files, widget stores, or logs, and it creates no background retry queue.
4. The iPhone submits each token over a separate one-shot, host-key-pinned SSH channel. It reuses the saved SSH credential and exact changed-host-key rejection. It never opens or writes to a tmux PTY.
5. The SSH child executes one fixed absolute command with no token, topic, path, or user value in the command string, for example:

   ```text
   /Users/dylanrapanan/JARVIS/.venv/bin/python /Users/dylanrapanan/JARVIS/.pi/scheduler/apns_registration.py
   ```

6. The helper accepts one bounded JSON object on stdin and emits one bounded acknowledgement. It derives the topic from the fixed platform value, validates `development|production`, validates a 64–200 hexadecimal token, and rejects unknown keys, oversized input, malformed installation IDs, mixed environments, symlinks, and unsafe database permissions.
7. The app supplies a random installation identifier stored as `ThisDeviceOnly` Keychain data. It supplies no CoreDevice UDID, user name, host path, job data, or terminal session identity.
8. The host upsert is idempotent. Retrying an unconfirmed registration is safe and never enqueues or sends a notification. Diagnostics contain only a short token SHA-256 prefix, never the token.

The registration transport may multiplex a separate child on an existing authenticated SSH parent. If no parent exists, it may create one short-lived connection with the same pinned-host configuration. It must not weaken trust, ask for new trust in the background, affect terminal readiness, stage attachment bytes, or touch any Pi process.

## Private registration and delivery state

Extend the existing private scheduler database rather than introducing another service or public store.

### Device registrations

Add a bounded table representing exactly the approved iPhone and Watch registration slots. Suggested fields:

- random installation ID;
- fixed platform (`iphone` or `watch`);
- fixed topic derived by the host;
- APNs environment;
- current token and full token SHA-256 for equality checks;
- current-registration state and registration/update timestamps;
- last accepted delivery timestamp.

The database remains mode `0600` under a mode-`0700` directory. Tokens are needed for sending and are therefore stored only in this owner-only database. They never appear in public scheduler output, jarvisd payloads, SQLite error strings, backups intended for source artifacts, or logs.

A new registration for the same installation replaces its token atomically. Because this deployment has exactly one approved iPhone and one approved Watch, a separately authorized replacement installation supersedes the older active slot for that platform/environment instead of accumulating stale targets. Installation-scoped owner deactivation deletes the current row and token; a stale installation cannot delete its replacement. APNs invalidation likewise removes the unusable token, but an invalidation timestamp older than a newer registration is ignored.

### Notification events and deliveries

Keep `notification_outbox` as one row per persisted result and add per-device delivery rows keyed by outbox event and registration slot. Per-delivery state is required because iPhone acceptance, Watch acceptance, retry, and invalidation can differ.

- When host dispatch is disabled, completion behavior is unchanged and the outbox remains empty. This preserves the existing preactivation invariant.
- Activation never backfills existing results.
- After activation, result insertion and outbox insertion occur in one SQLite transaction.
- Silent successful checks that do not create a Jobs result do not create an alert.
- If no active target exists at completion time, record the event as suppressed; do not alert later when a device registers.
- Deleting an old bounded result cascades its old notification event and delivery rows.

## Provider and dispatch behavior

Generalize `.pi/scheduler/apns_provider.py` from one Watch topic to a strict configuration selected per delivery:

- only the two exact JARVIS topics;
- sandbox host for `development`, production host for `production`;
- `apns-push-type: alert`;
- `apns-priority: 10`;
- short expiration, initially five minutes;
- a stable per-delivery `apns-id` for correlation without token exposure;
- a per-job hashed `apns-collapse-id` so disconnected devices do not receive a burst of stale alerts for repeated runs of one job;
- one JWT reused for the iPhone and Watch requests in the same dispatcher invocation;
- no import-time credential read or network side effect.

The scheduler's existing once-per-minute launchd job drains due notification deliveries after running due jobs. Use the existing SQLite lock mechanism for one dispatcher at a time; add no resident process.

Delivery policy:

- `200`: accepted by APNs; mark that target accepted. Do not claim that the user saw it.
- `400` token/topic errors or `410 Unregistered`: invalidate only the affected registration. Honor APNs's invalidation timestamp so a response for an old token cannot invalidate a newer registration.
- `403` authentication/topic configuration failures: fail closed globally for that drain, retain bounded diagnostic reason, and send nothing else until corrected.
- `429`, `500`, or `503` with a definite APNs response: retry with `Retry-After` or capped exponential backoff, within the five-minute expiry and a small maximum attempt count.
- Transport failure after request transmission is **ambiguous**. Do not automatically retry it because a second request could create a duplicate visible alert. Durable Jobs history remains available.
- Never retry a delivery against the other topic or token. iPhone and Watch are independent targets for the same event.

Host activation lives in one owner-only configuration outside Git and defaults to false. Startup or drain must fail before transport if the key is absent, permissions are unsafe, Team ID/Key ID/topic/environment is invalid, active registrations are mixed-environment, or credentials do not cover both topics.

## Payload, privacy, and routing

Use the same payload body for both device targets:

```json
{
  "aps": {
    "alert": {
      "title": "JARVIS Jobs",
      "body": "A scheduled job result is ready."
    },
    "sound": "default",
    "thread-id": "jarvis-jobs"
  },
  "route": "scheduled-job-result",
  "routeVersion": 1,
  "resultSequence": "41"
}
```

The payload must remain below a small internal bound far under APNs's maximum. Extend `ScheduledJobNotificationRoute` to require the exact route name, exact supported version, and positive integer sequence while ignoring no malformed alternative. Tests must prove that job names, prompts, output, error text, URLs, local paths, identifiers, API tokens, APNs tokens, and provider credentials never serialize into the request.

No `content-available`, `mutable-content`, command action, or result body is permitted.

### Foreground and tap handling

- Both notification delegates implement `willPresent`; otherwise foreground Watch notifications can be silently discarded. Return only the intended alert/list/banner and sound presentation options for a valid JARVIS payload.
- Both delegates always call completion handlers exactly once.
- An invalid payload may open the app normally but cannot select a result or mutate state.
- iPhone default-action taps post a process-local route consumed by `RootTabView`; it selects Jobs and sets the existing `requestedJobResultSequence` binding.
- Watch default-action taps set a bounded pending route consumed by `WatchConnectView`. Present a read-only sheet without changing the accepted dashboard pager. Fetch only the exact sequence through the existing authenticated scheduled-results API. If it was pruned or the Mac is unavailable, show `Result unavailable — check Jobs on iPhone` and a manual Retry button.
- The Watch sheet shows bounded sanitized title/summary and a short output prefix; the complete durable result remains in iPhone Jobs. It performs no background fetch before a tap.

## Accurate owner-visible status

Add a compact Notifications section in iPhone Settings. Combine local system authorization with a new sanitized read-only status from the existing jarvisd port. Expose only:

- global host dispatch enabled/disabled;
- configured environment;
- iPhone registered yes/no and last registration time;
- Watch registered yes/no and last registration time;
- last aggregate APNs outcome/time;
- pending, failed, and ambiguous counts.

Do not return device tokens, token hashes, installation IDs, Key IDs, key paths, job names, result sequences, or APNs response bodies. This status is informational and must never disable unrelated controls. It belongs in Settings, not Build 143's two-row Home interface.

## Implementation phases and gates

### Phase 0 — preserve the accepted baseline

- Branch from exact `acfe26edbdb8eef1a28771cde31a0eab4563db94` with a clean worktree.
- Record Build 143 artifact/evidence hashes and treat them as read-only rollback material.
- Make no portal or device changes.

### Phase 1 — host data model and provider, still dormant

- Add registration validation/upsert/deactivation and private tables.
- Add outbox/delivery state, strict payload builder, two-topic provider configuration, retry/invalidation handling, and sanitized status.
- Keep dispatch disabled by default; prove no credentials are read, no outbox rows are created, and no network call occurs while disabled.
- Test only with fakes and a disposable SQLite database.

### Phase 2 — app code, still no portal mutation

- Add pure notification state machines, delegates, explicit permission UI, secure registration transport, Watch token relay, tap routing, Watch result sheet, and Settings telemetry.
- Simulator tests use injected authorization/token providers and never pretend to validate APNs.
- Preserve checked-in `CURRENT_PROJECT_VERSION: 127`; build number and native-attachment condition remain candidate-export-only inputs.

### Phase 3 — explicit Apple account checkpoint

- Obtain owner approval for portal mutation.
- Enable the two App IDs, create the least-privileged APNs key, and regenerate paid-team profiles.
- Add exact signed entitlements and regenerate the Xcode project deterministically.
- Keep the provider disabled and do not request device permission yet.

### Phase 4 — exact candidate verification and freeze

- Run all scheduler, provider, jarvisd, terminald, JARVISKit, iPhone, Watch, attachment, lifecycle, and smoke tests.
- Build iOS and watchOS Release products without warnings.
- Archive from one exact commit with the accepted package lock and no overlays.
- Audit source, package lock, capabilities, entitlements, profiles, topics, background modes, bundle identifiers, credentials exclusion, and frozen archive hashes.

### Phase 5 — owner-driven device registration

- Install only the exact frozen archive on the approved iPhone and approved Watch. Never target the forbidden Watch CoreDevice.
- Launch both apps, inspect the permission explanations, and let the owner decide whether to continue.
- Grant iPhone permission, then explicitly complete the Watch permission overlay.
- Confirm current tokens reached the host using only registration status and token-digest equality checks.
- Keep scheduler dispatch disabled throughout this phase.

### Phase 6 — bounded physical APNs validation

Use a deliberate harmless test result; do not run `projects-drive-backup`.

1. Send an explicit iPhone-only test delivery and verify generic content plus exact Jobs routing.
2. Send an explicit Watch-only test delivery and verify direct Watch presentation plus the bounded result sheet.
3. Send the same test event to both active tokens and verify the system presents one notification at the best destination.
4. Validate phone locked/watch worn, phone foreground, Watch app foreground, Watch temporarily unreachable, denial/re-enable, token re-registration, and a pruned/unavailable result route.
5. Confirm no payload or logs contain private result data or tokens.
6. Confirm all six tmux panes/PIDs, ports `8790–8792`, terminal input readiness, attachments, Jobs history, controls, audio, widgets, and Watch `audio` background mode remain unchanged.

Only after those gates and explicit owner approval may host dispatch be enabled for future scheduler results. Enabling must not send old outbox/history.

### Phase 7 — acceptance and rollback readiness

- Seal a new build artifact, signed-capability audit, redacted registration/provider status, physical acceptance record, and deployment manifest.
- Record the APNs Key ID and key-file fingerprint, never the private key or device tokens.
- Document the one-command host dispatch disable path.
- To roll back, disable host dispatch first, then reinstall an accepted frozen build. Build 143 does not register for APNs and remains a valid behavioral rollback; any still-current registrations stay private and inert while dispatch is disabled.
- Revoke an APNs key only if compromised or deliberately retired, not as a normal app rollback step.

## Test matrix

### Python/provider and scheduler

- Disabled configuration has zero credential reads, zero enqueue, and zero transport.
- Exact topic/environment allowlist; mixed or unknown values fail before signing.
- Generic payload privacy and size; equal payloads for iPhone and Watch.
- JWT claims/signature, bounded reuse, key owner/mode, and missing-tool failures.
- Registration body bounds, action-specific fields, token syntax, platform-derived topic, installation rotation, deactivation/invalidation token removal, and no token logging.
- Atomic result/outbox insertion, no silent-result alert, no historical backfill, bounded cascade, and one delivery per active slot.
- Accepted, permanent failure, invalidation timestamp, definite retry, attempt cap, expiry, and ambiguous no-retry behavior.
- Concurrent scheduler invocations cannot double-dispatch.
- Sanitized status never exposes secret fields.

### Swift/JARVISKit and apps

- No permission request or APNs registration before explicit opt-in.
- Authorization transitions for not-determined, granted, provisional, denied, and settings-changed states.
- Current entitlement environment extraction and fail-closed mismatch handling.
- Token callbacks normalize only valid bytes and never persist/log token text.
- Watch-to-phone registration envelope validation, unreachable behavior, and no token in application context/state caches.
- Host-key change, unavailable credentials, backgrounding, timeout, malformed acknowledgement, and idempotent registration retry.
- Foreground presentation completion exactly once.
- Exact payload route validation and rejection of missing, zero, fractional, overflow, wrong-version, wrong-route, or output-bearing payloads.
- iPhone Jobs routing, Watch sheet routing, unavailable result fallback, and unchanged dashboard gestures.
- Settings status distinguishes local authorization from host registration and provider activation.

### Signed artifact and physical devices

- `aps-environment` exists only on iPhone and Watch app executables and matches each profile.
- Both exact topics are allowed by provider configuration and key scope.
- Widgets have no push entitlement.
- Watch `UIBackgroundModes` remains exactly `audio`.
- No `.p8`, APNs token, provider JWT, Key ID-bearing config, or private database is included in source/archive manifests.
- Sandbox and production are never mixed.
- Real APNs acceptance, system best-destination behavior, foreground behavior, and token rotation are physical-device-only acceptance gates.

## Expected source touchpoints

Host:

- `.pi/scheduler/apns_provider.py`
- `.pi/scheduler/runner.py`
- new `.pi/scheduler/apns_registration.py`
- `.pi/scheduler/tests/test_apns_provider.py`
- `.pi/scheduler/tests/test_runner.py`
- `jarvisd/jarvisd.py` and tests for sanitized read-only status
- `.pi/smoke-test.sh`, `.gitignore`, and scheduler/rebuild documentation

Shared/app:

- `JARVISKit/Sources/JARVISKit/ScheduledJobNotificationRoute.swift`
- new pure registration/status models under `JARVISKit`
- `JARVIS/JARVISApp.swift`, notification coordinator/delegate, Settings, `AppState`, and tests
- `JARVISWatch/JARVISWatchApp.swift`, notification coordinator/delegate, `WatchConnectView`, bounded result sheet, and tests
- `JARVISKit/Sources/JARVISKit/WatchBridge.swift`
- iPhone host-key-pinned SSH transport refactored only enough to support the fixed one-shot registration command
- `project.yml`, generated `JARVIS.xcodeproj`, iPhone/Watch entitlements, verifier, app README, and this canonical documentation

No terminald, room-audio, widget implementation, Pi lifecycle extension, tmux configuration, attachment protocol, or new network listener should need behavioral changes.

## Definition of done

- Build 143 and its evidence are unchanged.
- A new exact signed build contains paid-team push capability only for the iPhone and Watch apps.
- Permission and registration occur only after explicit owner actions.
- Exactly one approved iPhone token and one approved Watch token are securely registered for one matching environment.
- Every future persisted non-silent result creates at most one event with independent iPhone/Watch delivery state; no old result is backfilled.
- The APNs payload is generic, private, bounded, and identical across both topics.
- Apple, not JARVIS, selects the best presentation when both targets receive the event.
- iPhone and Watch taps reach the intended retained result without adding write actions.
- Definite transient failures retry within bounds; ambiguous sends do not retry; invalid tokens are retired safely.
- Provider disable is immediate, fail-closed, and leaves durable Jobs history intact.
- All automated, signed-artifact, and owner-driven physical gates pass on only the approved devices.

## Build 145 privacy-contract addendum

The Build 144 definition above remains the historical contract for its sealed artifact.
Build 145 intentionally proposes a different owner-visible alert contract: the APNs
`aps.alert` title contains the immutable result job name, and the body contains
`Completed — …` or `Failed — …` followed by an approximately 240-character excerpt
from the already-sanitized immutable result summary. Custom routing data remains only
the fixed route, route version, and positive retained result sequence. Full output,
prompts, model configuration, credentials, tokens, local paths, and raw URLs are not
sent. Any preview that still resembles sensitive context fails closed to generic text.
The iPhone and Watch permission copy warns that Apple may display this content on the
Lock Screen and points the owner to the system **Show Previews** control.

Build 145 also removes only the iPhone Home System/Services presentation and polling;
jarvisd APIs and services remain intact. Opening the Jobs root does not clear unread
state. Protected per-job sequence watermarks mark only the opened/deep-linked thread
read, and the Jobs tab badge counts unread job threads rather than retained results.
Build 144 cache history is baselined as read during migration, so rollout does not
surface old results. This addendum is not deployment or physical acceptance evidence.

## Apple references

- [Enabling and receiving notifications on watchOS](https://developer.apple.com/documentation/watchos-apps/enabling-and-receiving-notifications)
- [Registering your app with APNs](https://developer.apple.com/documentation/usernotifications/registering-your-app-with-apns)
- [Handling notifications and notification-related actions](https://developer.apple.com/documentation/usernotifications/handling-notifications-and-notification-related-actions)
- [Setting up a remote notification server](https://developer.apple.com/documentation/usernotifications/setting-up-a-remote-notification-server)
- [Establishing a token-based connection to APNs](https://developer.apple.com/documentation/usernotifications/establishing-a-token-based-connection-to-apns)
- [Communicating with APNs using authentication tokens](https://developer.apple.com/help/account/capabilities/communicate-with-apns-using-authentication-tokens/)
- [Enabling App ID capabilities and regenerating affected profiles](https://developer.apple.com/help/account/identifiers/enable-app-capabilities/)
