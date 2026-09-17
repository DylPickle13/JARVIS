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

## Resonance artwork

The Talk complication uses the approved Resonance design: three broken outer arcs, fine inner arcs, three orbital dots, and five waveform bars. Circular/corner/rectangular slots show the vector mark; inline retains its readable waveform label. Existing widget kind and `jarvis://talk` URL remain unchanged.

Motion is decorative, not a microphone or listening indicator. The existing system timer-mask selector is shared without altering the Neural Core renderer. Twenty-four lightweight frames make a restrained two-second cycle (small bar modulation, ±2.5° dot drift, inner-arc sheen); no app timers, network polls, or rapid timeline refreshes are added. A complete permanent frame remains underneath, so unavailable or frozen masks cannot blank the icon. Reduce Motion, Always On/reduced luminance, and missing font use the static design. Accented/tinted rendering no longer disables motion. watchOS may suspend animation; on-device appearance/motion acceptance remains separate from builds.

The owner confirmed Build187 automatically opens native input. This visual-only revision preserves the accepted root-overlay input, completion gate, and first-available-New-session flow.

### Accented-mode motion permission

Owner requested removal of the full-color-only motion gate after observing that Neural Core animated while Resonance appeared static. Only that gate is removed; frame count, timer masks, fallback artwork, Always On/Reduce Motion safeguards, and input routing are unchanged. Animation on the physical face still needs confirmation. Reported battery drain remains unattributed; this change is not a power-use fix.

## Build192: static engraved Resonance

Owner requested complete removal of Talk animation while retaining a more detailed static icon. The new artwork has segmented engraved rings, inset tracks, calibration ticks, a symmetric five-bar waveform, and three socketed orbital nodes. Reduced luminance omits the fine details. Accented/tinted rendering remains supported.

Talk now renders one static Canvas, with no timer selectors, timer masks, animated frame stack, or animation-font registration. This removes its former24frames/48masks. Neural Core's implementation and accepted native Done-to-send input are unchanged. The icon is never a microphone indicator.

Battery benefit is **unmeasured**: two power-profiler attempts and an unlocked retry timed out before recording. Source simplification is not proof that animation caused the reported drain. Spotify remains removed. Physical visual acceptance and a matched normal-use battery comparison remain pending.

## Terminal Spark replacement (source candidate)

The owner selected the earlier monochrome Terminal Spark concept, replacing its right-side signal with a second chevron: `>_>`. Two rounded white chevrons flank a subdued steel-white underscore. The mark uses one static Canvas and preserves the complete glyph in reduced luminance; widget accenting remains supported. Legacy artwork type/file names are retained for integration compatibility.

This supersedes Build192's engraved artwork only. Native input, one-shot Done submission, first eligible New-session routing, widget identifiers, and Neural Core remain unchanged. Source/render checks are not physical Watch acceptance or energy measurements. Not yet deployed.

## Mini arc reactor replacement (source candidate)

Supersedes the deployed Build193 Terminal Spark icon at the owner's request. The static monochrome reactor has ten broad segmented coils, radial supports, a thin outer housing, and a bright circular emitter. At reduced luminance it omits the fine inner ring and slightly reduces the emitter and coil intensity. It retains one accentable Canvas, with no timers, blur, animation, or network work.

Only artwork and its source contracts changed. Talk input/submission and Neural Core remain untouched. This candidate is not yet deployed; rendered previews do not establish physical Watch acceptance or battery impact.

## Triangular Mark VI-inspired replacement (current source candidate)

The owner clarified the intended reactor is the inverted triangular Mark VI design, not the earlier circular reactor. This supersedes the circular candidate above: a bright clipped-tip inverted triangle sits inside two separated steel-white triangular rims. Reduced luminance omits the fine top bevel and slightly shrinks the emitter. No color, blur, animation, or additional rendering layer is introduced.

Reference: https://www.xenom0rph.com/2018/03/hot-toys-iron-man-mark-vi-16-mms378-d17.html (Mark VI replica photographs). Geometry is drawn locally, not a bundled reference photograph. Existing artwork names, widget routing, native input, and Neural Core are unchanged. Deployed as Build194; physical visual acceptance remains pending.


## Cascade Field animation (Build195 candidate)

Owner selected the animated Cascade Field preview and authorized restoring Talk motion. This supersedes the static-only requirement for Talk, not for its native input or submission behavior.

The clipped triangular emitter and layered rims remain fixed. Six expanding triangular fields, three counter-traveling tapered energy packets, and a clipped grayscale emitter scan provide decorative movement. This is never a microphone/listening-state indicator.

Uses the existing, unchanged shared timer-font selector: **32 authored phases over its two-second cycle (nominal 16 FPS)**, rather than the offline GIF's 3.2-second/20-FPS loop. There are 32 Canvas scenes and 64 timer masks; this is a rendering-cost increase over Build194, not an energy optimization. Talk explicitly registers the already bundled font. No process timers, animation loops, networking, or timeline reloads drive the artwork. The system may throttle or suspend presentation; the nominal rate is not a measured physical result.

Always-On/reduced luminance, Reduce Motion, or an unavailable font selects one static Canvas with no timer masks. Changes to animation eligibility rebuild selector identity. The wrapper remains accentable and hidden from accessibility so the widget retains its Talk label.

Neural Core/shared selector implementation, widget identifiers/URLs, native composer, one-shot Done submission, terminal and backend remain unchanged. Build195 is not yet installed. Physical 44-point, accent, Always-On/resume, Reduce Motion, stability, and matched battery acceptance remain pending. The full legacy verifier has unrelated stale contracts and is not claimed green.


## Surge Cascade (Build196 candidate)

Owner confirmed Build195 works on Watch but found its motion too subtle, then selected **Surge Cascade** from the bold motion studies and authorized implementation/deployment. Three thick, high-contrast triangular waves move inward across a dark emitter, ending at a fixed small triangular core. The rims stay fixed. This replaces the fine expanding fields, perimeter particles, and emitter scan; it does not increase the existing 32-frame/64-mask selector budget.

The selected Surge Cascade study was adapted to the existing two-second selector cycle (nominal 16 FPS versus the study's 2.4-second/20-FPS loop). The broad wave stroke is 2.8 canonical units, approximately 1.1 points at a 44-point size. Static reduced-luminance, Reduce Motion, and unavailable-font fallbacks remain unchanged. Talk and Neural Core behavior remain unchanged.

Build196 was archived, audited, sealed, installed, and launched on both devices. All nine Pi sessions, backend, and runtime configuration were preserved. Physical motion/readability/Always-On and matched battery/energy acceptance remain pending; stronger motion does not establish battery impact.

## Reduced scene budget (Build197 candidate)

Owner reported frozen Surge Cascade and a nonresponsive Talk complication. A Watch jetsam report dated 2026-09-17 08:39:41 EDT identifies `JARVISWatchWidget` as terminated for `per-process-limit`. The report establishes widget-extension memory-limit termination, not exclusive attribution to Talk artwork. Direct `jarvis://talk` launch succeeded and the owner confirmed native input appeared.

At the owner's request, Talk uses 16 phases over the unchanged two-second cycle (nominal 8 FPS), reducing its Canvas scene count from 32 to 16 and timer masks from 64 to 32. Wave geometry, static accessibility/Always-On fallbacks, routing, submission, shared selector and Neural Core remain unchanged. This halves authored scenes/masks, not necessarily total process memory. Build/install, physical tap/motion, memory stability and energy acceptance are separate; physical acceptance remains pending.
