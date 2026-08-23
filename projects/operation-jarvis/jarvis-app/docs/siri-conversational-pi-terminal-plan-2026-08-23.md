# Siri conversational prompt-to-Pi plan

**Date:** 2026-08-23 EDT

**Proposed release:** `0.3.0 (39)`
**Status:** Implemented in build 39; physical Siri routing acceptance pending

## Implementation result

Build 39 implements the approved architecture in host-only App Intents on both
iPhone and Watch. `SendPromptToJARVISIntent` advertises exactly bare
**“Hey JARVIS”**, uses the prompted required `String`, reads only target-local
Keychain configuration, normalizes one logical line with a 3,500-byte UTF-8
cap, performs an authenticated pinned frame preflight, and then attempts exactly
one `appendReturn=true` POST. The foreground Watch terminal now consumes the
same extracted `WatchTerminalClient`.

Xcode accepted and trained the exact bare phrase in both host metadata products.
Unit tests cover normalization, controls, bounds, preflight, atomic payload,
ambiguous POST non-retry, and dialog outcome mapping. A disposable TLS server
and isolated tmux socket verified one prompt plus one Return with duplicate
request suppression; no automated test writes to the production Pi pane.
Physical iPhone/Watch Siri routing, lock-state, and cellular acceptance remain
pending because the devices were intentionally disconnected during implementation.

## 1. Objective

After Siri is already listening, support this public-API flow on iPhone and Apple Watch:

1. Owner: **“Hey JARVIS.”**
2. Siri: **“What would you like me to send to JARVIS?”**
3. Owner speaks an arbitrary prompt.
4. JARVIS inserts that resolved text into the existing `jarvis-ios` Pi/tmux editor and emits one Return.
5. Siri: **“Sent to JARVIS.”**

This is a parameter-prompting App Intent, not a custom wake word. The system wake remains “Hey Siri” or a hardware gesture; JARVIS never runs an always-listening microphone.

## 2. Feasibility and platform boundary

The existing public App Intents stack already supports the required conversation:

- An `AppShortcut` can advertise the literal phrase `"Hey \(.applicationName)"`.
- A missing `String` `@Parameter` can use `requestValueDialog` so Siri asks for the prompt.
- `perform()` can submit the resolved text and return a spoken `IntentDialog` acknowledgement.
- `openAppWhenRun` can remain `false`.

The exact bare phrase must still pass Xcode metadata validation and physical Siri routing. If Siri reserves or misroutes it, retain **“Hey JARVIS”** as the acceptance target and test **“Ask JARVIS”** only as a diagnostic fallback—not as a silent product substitution.

## 3. MVP behavior decisions

- **Two-turn requested flow:** no extra Yes/No confirmation in the MVP. The deliberate answer to Siri’s prompt authorizes submission.
- **One logical terminal line:** normalize CR/LF and disallowed control characters so speech cannot create multiple terminal submissions.
- **Atomic execution:** send UTF-8 prompt bytes plus one server-appended Return in one authenticated request.
- **Current cursor:** input goes to the same Pi editor/cursor used by iPhone and Watch terminal controls.
- **No queue:** if the bridge is unavailable, nothing is saved for later.
- **No replay:** do not fail over or retry after a POST begins. An ambiguous timeout returns “Send was not confirmed; check JARVIS.”
- **No Pi-answer speech in MVP:** Siri acknowledges delivery only. Capturing and speaking the asynchronous Pi response is a separate feature.
- **Idle-editor precondition:** MVP acceptance assumes no other client has unsent text at the Pi cursor. The current tmux frame does not expose a reliable semantic “editor empty” flag; silently clearing or replacing another client’s draft is prohibited.

## 4. Architecture

```text
Siri on iPhone or Watch
        │
        ▼
SendPromptToJARVISIntent
  @Parameter prompt: String
        │
        ├─ target-local terminal configuration
        │  (endpoint + pinned certificate + Keychain token)
        │
        ▼
Shared pinned TerminalBridgeClient
  1. authenticated frame preflight
  2. exactly one POST /v1/terminal/input
        │
        ▼
jarvis-terminald :8792
  bounded bytes + request-ID dedupe
        │
        ▼
jarvis-mobile / jarvis-ios tmux pane
        │
        ▼
Pi fixed editor receives prompt + Return
```

`jarvisd` remains the hardware/status/service control plane and receives no terminal prompt route. `jarvis-terminald` remains unable to call plugs, purifier, services, or scheduler logic.

## 5. Implementation workstreams

### A. Add the conversational App Intent

Implemented as a host-only intent beside the existing plug intents:

```swift
struct SendPromptToJARVISIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to JARVIS"
    static let description = IntentDescription("Send a spoken prompt to the active JARVIS Pi session.")
    static var openAppWhenRun: Bool { false }

    @Parameter(
        title: "Prompt",
        requestValueDialog: IntentDialog("What would you like me to send to JARVIS?")
    )
    var prompt: String
}
```

Add a third `AppShortcut`:

```swift
AppShortcut(
    intent: SendPromptToJARVISIntent(),
    phrases: ["Hey \(.applicationName)"],
    shortTitle: "Talk to JARVIS",
    systemImageName: "waveform"
)
```

Bump `JARVISSiriParameterRegistrar`’s phrase schema version so upgrade-time shortcut metadata republishes even when the plug catalogue is unchanged.

### B. Extract a shared pinned terminal bridge client

Implemented by moving the reusable HTTPS behavior out of the private Watch view implementation into a JARVISKit client that:

- accepts a `WatchTerminalConfiguration` but never persists or logs it;
- preserves SHA-256 leaf-certificate pinning;
- uses bearer authentication;
- probes saved endpoint, LAN, MagicDNS, and current Tailscale candidates with an authenticated frame GET;
- selects one confirmed route before enabling submission;
- performs one `WatchTerminalInput` POST with a fresh request ID;
- has bounded preflight and submit timeouts;
- never retries an input POST on another route;
- exposes no SwiftTerm, SwiftNIO, or SSH dependency.

The foreground Watch terminal should consume this same client after extraction so Siri and UI networking cannot drift.

### C. Read target-local credentials safely

Because free provisioning prevents a shared Keychain/App Group:

- **iPhone intent:** read the existing iPhone terminal provisioning token, endpoint, and fingerprint from `WatchTerminalProvisioningSettings` storage.
- **Watch intent:** read the existing Watch-local token, endpoint, and fingerprint from the Watch terminal settings storage.
- Keep `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`.
- If Keychain is unavailable while locked, Siri says **“Unlock this device and try again.”** Nothing is sent.
- Do not copy credentials into App Intent parameters, defaults, widgets, logs, or WatchConnectivity messages.

### D. Normalize and bound the spoken prompt

Before network access:

1. Trim surrounding whitespace.
2. Replace CR/LF runs with a single space.
3. Reject NUL, escape, and remaining C0/C1 control characters.
4. Preserve ordinary Unicode and punctuation.
5. Reject empty text.
6. Cap normalized UTF-8 to at most 3,500 bytes, below the bridge’s 4,096-byte limit.

Submit:

```swift
WatchTerminalInput(data: Data(normalized.utf8), appendReturn: true)
```

This uses terminald’s byte-safe tmux paste path and appends exactly one Return without shell interpolation.

### E. Define Siri dialogs and failures

| Condition | Siri response | Terminal effect |
|---|---|---|
| Success | “Sent to JARVIS.” | Prompt + one Return |
| Empty prompt | “I didn’t hear a prompt.” | None |
| Too long | “That prompt is too long for JARVIS.” | None |
| Not provisioned | “Open JARVIS Settings and set up the terminal first.” | None |
| Device locked / Keychain denied | “Unlock this device and try again.” | None |
| No authenticated frame route | “The JARVIS terminal is offline.” | None |
| Certificate mismatch | “The JARVIS terminal identity could not be verified.” | None |
| POST rejected | “JARVIS did not accept the prompt.” | None or server-confirmed rejection |
| POST timeout after transmission begins | “Send was not confirmed; check JARVIS.” | Never retried automatically |

Do not include the prompt, token, endpoint, certificate details, or local paths in dialogs or logs.

### F. Keep target and control-plane isolation

- Compile the new intent only into iPhone and Watch host apps, not either widget.
- Continue verifying that Watch and Watch widget binaries have no SwiftTerm/NIO/SSH linkage.
- Do not add a prompt endpoint to `jarvisd`.
- Do not use WatchConnectivity as a delayed queue.
- Do not add background microphone capture, Speech framework recording, or a custom wake-word engine.

## 6. Test plan

### Unit and protocol tests

- Phrase metadata contains exactly the new parameterless **“Hey JARVIS”** shortcut plus the two existing plug shortcuts.
- Upgrade schema republishes shortcut parameters once.
- Prompt normalization preserves Unicode and punctuation.
- Newline/control-character input cannot create a second command.
- Empty and oversized prompts fail before network access.
- Successful payload has prompt bytes and `appendReturn=true`.
- Request IDs are unique and duplicate server receipt produces only one tmux write.
- Disconnected, unprovisioned, locked-Keychain, certificate-mismatch, and timeout paths never queue or replay.
- No test writes to the production tmux pane; use a disposable terminald/tmux fixture.

### Build and static checks

- iOS and watchOS Debug/Release builds are warning-free.
- App Intents metadata extraction accepts the bare phrase.
- Release binaries contain the new intent metadata.
- Watch dependency isolation remains clean.
- Existing plug-only Siri intent behavior remains unchanged.
- Repository smoke remains `WARN=0 FAIL=0`.

### Physical iPhone acceptance

1. With iPhone unlocked and JARVIS terminal provisioned, activate Siri.
2. Say **“Hey JARVIS.”**
3. Confirm Siri asks the configured prompt question.
4. Speak a unique harmless fixture prompt against a disposable tmux session.
5. Confirm exactly one normalized prompt and one Return arrive.
6. Repeat over LAN and cellular/Tailscale.
7. Verify offline, certificate-mismatch fixture, locked-device, and force-quit behavior produce no delayed input.

### Physical Watch acceptance

Repeat the same flow with Siri initiated on the Watch:

- foreground and wrist-raised;
- iPhone nearby and then unavailable where practical;
- Wi-Fi/LAN and supported off-LAN path;
- no duplicate send if Siri dismisses or the wrist drops;
- simultaneous iPhone terminal attachment still targets one tmux pane.

### Regression acceptance

- “Hey JARVIS, turn on/off …” continues routing only to plug intents.
- Bare “Hey JARVIS” routes only to the prompt intent.
- No contact-directed “Tell JARVIS” phrasing returns.
- Watch Keys/Input/Send behavior remains unchanged.
- No plug, purifier, service, scheduler, or production terminal mutation occurs during automated tests.

## 7. Rollout sequence

1. **Done:** implement as build 39 behind the existing Personal Team configuration.
2. **Done:** validate with disposable HTTPS/tmux fixtures and simulator Siri metadata.
3. **Done:** archive/export and audit the exact signed build-39 artifacts.
4. Install on the allowlisted iPhone and Watch only after the owner reconnects them.
5. Perform owner-driven physical Siri routing with a harmless disposable prompt.
6. Keep build 38 available for rollback.
7. Do not restart the persistent Pi pane unless separately approved.

## 8. Explicit non-goals

- No independently always-listening “Hey JARVIS” wake word.
- No replacement for Siri’s system speech recognition.
- No automatic reading of Pi’s eventual response.
- No prompt history, cloud sync, widget action, or offline queue.
- No terminal access through `jarvisd`.
- No automatic clearing or replacement of another client’s staged editor text.
