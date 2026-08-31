# JARVIS app implementation documentation

This is the canonical documentation index under `jarvis-app/docs`. It consolidates the iPhone terminal keyboard-avoidance and native Photos/Files attachment plans into one navigable document. The broader app architecture, operations, deployment, recovery, and historical plans remain in the [app README](../README.md).

The dated status lines and checklists below are retained as implementation history; consult the app README and owner-only acceptance records for the currently deployed build state. Non-Markdown third-party license material remains separate under [`third-party/`](third-party/AnimationLimitBreaker-LICENSE.txt).

## Contents

- [iPhone terminal keyboard avoidance and native attachments](#iphone-terminal-keyboard-avoidance-and-native-attach-implementation-plan)
- [Pi attachment product contract](#jarvis-app-pi-attachment-integration-plan)

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

- Preserve tmux socket `jarvis-mobile`, session `jarvis-ios`, pane `%0`, current pane ordering, and the persistent Pi process except for an owner-approved recovery action.
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

The extension publishes its mobile endpoint only when it proves it is running in the exact `jarvis-mobile` tmux socket, `jarvis-ios` session, and pane `%0`. Use the inherited `TMUX`/`TMUX_PANE` identity plus a fixed, read-only tmux identity query; fail closed if any value is absent or mismatched.

Runtime files:

- `.pi/runtime/pi-attach-mobile.json`: atomic mode-`0600` descriptor containing protocol version, live Pi PID, random instance nonce, and socket path.
- `.pi/runtime/pi-attach-mobile-<pid>-<nonce>.sock`: owner-only socket under the existing mode-`0700` runtime directory.

On `session_shutdown` or `/reload`, close the listener and remove both files. A new extension instance uses a new nonce. The receiver rejects a symlink, wrong owner/mode, dead PID, stale descriptor, unsupported version, or unavailable socket.

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
