# Native Watch “Talk to JARVIS” complication

## Behavior

- Add **JARVIS → Talk to JARVIS** to a supported watch-face complication slot.
- Circular/corner slots use the existing JARVIS icon assets, including accented rendering. Rectangular/inline slots include a label.
- Tapping opens `jarvis://talk` and presents the Watch composer. Tap the Prompt field to use the watchOS keyboard/dictation UI, then tap **Send**. Dictation does not start automatically.
- Opening, editing, cancelling, or repeatedly tapping the complication does not send a prompt.
- Send uses the existing guarded New-session admission path. It must not reset or paste into an existing conversation. Confirmed delivery opens the allocated terminal slot.
- Send is disabled while a submission is pending. No automatic retries occur. An unconfirmed result disables resubmission in that composer and tells the user to inspect Pi sessions first.
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
5. Enter a prompt with native dictation, cancel, and verify no submission.
6. Send a deliberate test prompt once; verify exactly one unused New slot receives it and opens.
7. Check unavailable capacity, offline, locked credentials, identity failure, and unconfirmed-result UI using isolated fixtures where possible.
8. Verify no changes to nine session identities, configuration, backend listeners, purifier controls, or iPhone terminal behavior.

No physical acceptance or device installation is implied by source checks or an unsigned build.
