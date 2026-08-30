# JARVIS App Pi Attachment Integration Plan

Status: **planned only — not implemented**

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
