# JARVIS widget catalogue, deployment, and physical validation

**Prepared:** 2026-08-20
**Candidate:** JARVIS `0.2.0 (12)`
**Physical status:** build 11 installed; build-12 interaction-feedback correction pending deployment

## 1. Replacement boundary

Build 11 removes the previous `JARVIS Plugs` and `JARVIS First Plug` widget
kinds. Each platform's existing WidgetKit extension now publishes exactly four
new widget kinds:

1. Open JARVIS
2. JARVIS Plug
3. JARVIS Plug Grid
4. Air Purifier

No service, scheduled-job, event, weather, or Pi widget is retained or added in
this build.

## 2. iPhone catalogue

| Widget | Families | Behavior |
|---|---|---|
| Open JARVIS | system small; accessory circular, rectangular, inline | Network-independent `jarvis://home` deep link. No command or state request is required to launch the app. |
| JARVIS Plug | system small; accessory circular, rectangular, inline | App-Intent-configurable approved plug. Shows explicit ON/OFF/STALE state and sends an idempotent desired-state `plug-on` or `plug-off` command. |
| JARVIS Plug Grid | system medium and large | Medium shows up to four plugs; large shows up to eight. Each item has a separate desired-state button. |
| Air Purifier | system small and medium; accessory circular, rectangular, inline | Read-only PM2.5, quality, power, mode, fan, filter, and stale status as space permits. |

## 3. Apple Watch catalogue

| Widget | Families | Behavior |
|---|---|---|
| Open JARVIS | accessory circular, corner, rectangular, inline | Opens the JARVIS Watch app. |
| JARVIS Plug | accessory circular, corner, rectangular, inline | Configurable approved plug with explicit desired-state control. |
| JARVIS Plug Grid | accessory rectangular | Two large, separated plug targets suitable for a rectangular complication or Smart Stack widget. |
| Air Purifier | accessory circular, corner, rectangular, inline | Read-only glanceable PM2.5, quality, power/mode summary, and stale status. |

## 4. Data, refresh, and safety contract

- The launcher is static and uses a `.never` timeline policy.
- State widgets request a timeline refresh every 15 minutes. WidgetKit retains
  final scheduling authority.
- Concurrent timeline requests share only the currently in-flight request inside
  each extension process, avoiding duplicate `jarvisd` reads without replaying
  a completed pre-command snapshot.
- A plug intent marks the selected plug Updating and disables it while running,
  applies the confirmed result to target-local state, then selectively reloads
  both plug timelines.
- Repeated taps for the same desired state are suppressed for ten seconds.
- State older than 15 minutes, or state marked stale by the daemon, is visibly
  marked stale.
- Plug controls are disabled for stale or unknown state.
- Plug interactions carry an explicit desired state; they never call
  `plug-toggle`.
- Air-purifier widgets are read-only. They cannot issue purifier commands.
- Every non-button area deep-links to the relevant JARVIS Home screen.
- Personal Team builds still lack App Groups and shared cross-target Keychain
  access. Each extension has a target-local cache and direct trusted-network
  `jarvisd` discovery fallback. Token-mode credentials are not inherited.

## 5. Build-11 physical finding and build-12 correction

The signed build-11 iPhone gallery listed all four replacement widgets, and Open
JARVIS launched Home correctly. During the first plug interaction, however, the
30-second completed-result cache replayed the pre-command snapshot after
`WidgetCenter` reload. The lamp turned on, but the widget still appeared off;
four taps therefore generated four idempotent `plug-on` requests. The initial
off state was restored with one approved `plug-off` and verified.

Build 12 removes completed-result retention while preserving true concurrent
single-flight behavior. It also invalidates older in-flight reads, writes the
confirmed command result to the extension-local snapshot, exposes an
Updating/disabled presentation during execution, reloads only plug timelines,
and suppresses rapid duplicate same-state intents. Automated coverage verifies
confirmed-state cache updates plus pending and duplicate-control behavior.

## 6. Apple design-guideline alignment

The implementation follows the current Apple widget guidance:

- one focused purpose per widget;
- larger families add useful information rather than stretching a small layout;
- standard WidgetKit content margins and `containerBackground(for: .widget)`;
- system text styles and SF Symbols;
- semantic colors plus text/icon labels, so color is never the only status cue;
- `widgetAccentable()` on important accessory glyphs for tinted Watch faces and
  Home Screen appearances;
- dedicated compact layouts for every accessory family rather than scaling down
  a Home Screen layout;
- realistic gallery placeholders and succinct action-led descriptions;
- VoiceOver labels and hints for controls;
- limited, well-separated interactive targets; and
- deep links for taps outside interactive buttons.

References:

- [Widgets — Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/widgets/)
- [Making a configurable widget](https://developer.apple.com/documentation/widgetkit/making-a-configurable-widget)
- [Creating accessory widgets and watch complications](https://developer.apple.com/documentation/widgetkit/creating-accessory-widgets-and-watch-complications)

## 7. Simulator validation

Required before physical installation:

- JARVISKit and AppState tests pass.
- Generic iOS and watchOS simulator builds pass.
- The iPhone widget gallery lists six Home Screen previews: launcher small,
  selected-plug small, grid medium/large, and purifier small/medium.
- Launcher, grid, and purifier previews are inspected in light and dark
  appearances; layout remains legible at increased contrast.
- The launcher is added to the Home Screen and opens `jarvis://home`.
- No widget source contains the retired widget kind names.
- Both extension bundles contain App Intents metadata for the configurable
  selection and desired-state action.

`simctl` installs of unsigned/ad-hoc simulator products cannot complete App
Intent execution on the current Xcode 26 runtime: `linkd` rejects the extension
because no development-team identity is attached. Static rendering and deep
links remain testable there. App-Intent configuration and button execution must
therefore be closed using the signed physical archive, not by treating the
unsigned simulator rejection as an application failure.

## 8. Signed physical gate

When the iPhone is connected:

1. Build one signed archive with all four products on build 12.
2. Deep-verify the iPhone app, iPhone widget, Watch app, and Watch widget.
3. Install the exported parent IPA through `ideviceinstaller` on the allowlisted
   iPhone.
4. Install the exact archived Watch app through CoreDevice developer services.
5. Confirm both inventories report `0.2.0 (12)` and both widget extensions are
   present.
6. Add and launch Open JARVIS on iPhone and Watch.
7. Add JARVIS Plug, verify all four approved configuration choices, and confirm
   stale/unknown state blocks interaction.
8. Add both Plug Grid sizes on iPhone and the rectangular Watch grid; inspect
   target spacing before issuing any command.
9. Add every purifier family and confirm they remain read-only.
10. After a separate hardware-change warning and explicit approval, exercise one
    representative desired-state plug command. Confirm immediate feedback, the
    final displayed state, and duplicate suppression before restoring its
    starting state.
11. Confirm exactly one event pair per changed desired state and no purifier or
    service command.

Never test by unpairing or erasing the Watch. Never install on a non-allowlisted
device.
