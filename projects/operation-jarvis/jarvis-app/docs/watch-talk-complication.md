# Native Watch “Talk to JARVIS” complication

## Behavior

- Add **JARVIS → Talk to JARVIS** to a supported watch-face complication slot.
- Circular/corner slots use the existing JARVIS icon assets, including accented rendering. Rectangular/inline slots include a label.
- Tapping opens `jarvis://talk` and automatically presents watchOS native text input. Finishing native input (usually **Done**) submits immediately; there is no extra Prompt-field tap or JARVIS Send button. watchOS controls which input method appears; dictation is not forcibly selected.
- Opening, partial input, cancelling, or repeatedly tapping the complication does not send a prompt. A nonempty native completion authorizes at most one submission.
- Native completion uses the existing guarded first-available New-session admission path (slots 1–9, independent of the Watch selection). It must not reset or paste into an existing conversation. Confirmed delivery opens the allocated terminal slot.
- Duplicate completion callbacks are ignored. Cancellation and blank input consume the completion without submission. No automatic retries occur. An unconfirmed result offers Close, never resubmission and tells the user to inspect Pi sessions first.
- Existing **Open JARVIS** and Neural Core widgets retain their kinds and destinations.

## Siri retirement

Both host apps no longer register `Hey JARVIS`, `SendPromptToJARVISIntent`, or the Siri-only `OpenJARVISTerminalIntent`. The App Shortcuts provider and startup registration calls are removed. Existing personal shortcuts using the removed action will no longer work after upgrading.

Shared delivery and terminal navigation are retained as `JARVISPromptRuntime` and `JARVISPromptNavigation`. Legacy persistence keys and backend admission protocol names remain intentionally compatible; they are not Siri command registrations. No backend, Pi session, purifier, or terminal protocol changes are required.

## Verification / acceptance

Source contracts: `python3 scripts/tests/verify-watch-talk.py`.
Injected host-runtime tests: `python3 scripts/tests/test-prompt-runtime.py` (no devices, Keychain access, or live submissions).
The main verifier now rejects retired Siri actions and checks that built host metadata has no actions or automatic shortcuts (metadata may be absent).

Physical acceptance is separate from compilation:

1. Install a newly signed, verified iPhone + Watch build; do not reuse a closed deployment driver.
2. Confirm existing launcher and Neural Core destinations still work.
3. Add Talk to JARVIS to circular/corner/rectangular slots as available; check accented appearance.
4. Test face tap from terminated/background/foreground app states.
5. Verify input opens without a Prompt-field tap; dictate, cancel, and verify no submission.
6. Finish native input with a deliberate test prompt once; verify no JARVIS Send tap is needed and exactly the first eligible New slot receives it and opens, regardless of the previously selected slot.
7. Check unavailable capacity, offline, locked credentials, identity failure, and unconfirmed-result UI using isolated fixtures where possible.
8. Verify no changes to nine session identities, configuration, backend listeners, purifier controls, or iPhone terminal behavior.

No physical acceptance or device installation is implied by source checks or an unsigned build.

## Automatic-input revision

Native input uses `WKInterfaceController.presentTextInputController` from the visible controller after the SwiftUI sheet appears. Physical cold/warm-launch presentation, input method choice, cancellation, and end-to-end delivery require owner acceptance. Native Done is the authorization boundary; speech silence is not used to trigger submission.

## Build186 physical rejection and root-host correction

The owner reported that Build186 displayed its waiting text without opening native input. Compilation and deployment did not establish successful input presentation.

The correction removes the Talk SwiftUI sheet and nested NavigationStack. A root overlay keeps the dashboard mounted while native WatchKit input is requested from the root host. Done-to-send, cancellation, duplicate suppression, and first-available-New-slot routing remain unchanged. A native TextFieldLink provides explicit manual recovery if automatic presentation still fails; that fallback is not acceptance of the requested zero-extra-tap flow. Public logs record only presentation/completion events, never prompt text.

Physical cold/warm-launch tests must demonstrate automatic native input presentation. If only Open input appears, automatic presentation remains unresolved. Cancel once to verify no submission, then deliberately complete input for the end-to-end test.
