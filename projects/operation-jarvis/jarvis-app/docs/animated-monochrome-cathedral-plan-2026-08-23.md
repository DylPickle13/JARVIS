# Animated Monochrome Cathedral Plan

Date: 2026-08-23 EDT
Status: Implemented, audited, and physically deployed as JARVIS 0.3.0 (47); visual motion acceptance remains pending

## Decision summary

The Monochrome Cathedral can be recreated entirely as native SwiftUI vector/procedural artwork. It does not need to be a PNG, GIF, video, or other static asset.

A continuously animated third-party iPhone Home Screen widget or Apple Watch complication is **not possible with WidgetKit**. Widget views are archived and rendered by the system; the extension's view code is not continuously running while the widget is visible. WidgetKit supports animations when transitioning between timeline entries or other system-driven content changes, not an indefinite display-link animation loop.

Apple also explicitly disables widget and complication animations on Always-On displays to preserve battery life.

The recommended product is therefore:

1. A native-vector Monochrome Cathedral widget and complication with **short, system-supported motion when a real timeline entry changes**.
2. A balanced hero frame that remains attractive when WidgetKit freezes it between updates and in Always On.
3. Optionally, the same rendering engine presented inside the foreground iPhone and Watch apps, where it can animate continuously while active. In Always On, motion stops but the artwork does not apply an additional authored luminance reduction; the system remains responsible for actual display luminance.

## Feasibility matrix

| Surface | Procedural/vector artwork | Continuous animation | Short update transition | Always On |
| --- | --- | --- | --- | --- |
| iPhone Home Screen widget | Yes | No | Yes, when WidgetKit changes entries | System suppresses animation on AOD-capable devices |
| Watch complication / accessory widget | Yes | No, even while the face is active | Yes, when WidgetKit changes entries | Static; animation is system-disabled |
| Foreground iPhone app | Yes | Yes | Yes | Not applicable to Dylan's iPhone 11 |
| Foreground Watch app | Yes | Yes while active | Yes | Static with no additional authored dimming; the system controls display luminance |

Smart Stack widgets and Live Activities do not remove the continuous-animation restriction. A custom Watch face is also not available to third-party apps.

## Apple platform basis

- WidgetKit archives timeline-entry views and the system renders those archived representations. The widget extension's view code is not running continuously on screen.
- Widget animations communicate changes between timeline entries. They are not a persistent render loop, and Apple limits widget/Live Activity animations to a maximum duration of two seconds.
- Widgets do not support continuous, real-time updates, and timeline reloads are system-budgeted.
- On Always-On displays, the system does not perform widget animations.
- A foreground watchOS app is different: `TimelineView(.animation)` can drive high-frequency rendering while active. Its cadence drops when the app becomes inactive or enters Always On.

References:

- [Animating data updates in widgets and Live Activities](https://developer.apple.com/documentation/widgetkit/animating-data-updates-in-widgets-and-live-activities)
- [Bring widgets to life — WWDC23](https://developer.apple.com/videos/play/wwdc2023/10028/)
- [Widgets — Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/widgets)
- [Updating watchOS apps with timelines](https://developer.apple.com/documentation/watchos-apps/updating-watchos-apps-with-timelines)
- [WidgetKit foundations — WWDC26](https://developer.apple.com/videos/play/wwdc2026/277/)

## Visual contract

The production design retains only the `JARVIS` wordmark. There are no visible metric labels, status sentences, or explanatory text.

The cathedral remains state-reactive through geometry rather than copy:

- Pi sessions control illuminated filament channels and radial density.
- The four approved plugs control four architectural anchor nodes.
- Codex remaining controls the outer orbital arc while preserving the strict critical threshold: below 30% is critical; exactly 30% is not critical.
- PM2.5 controls central-core intensity.
- Fresh connectivity permits the energized composition.
- Missing or stale telemetry freezes, dims, and fractures the projection instead of inventing activity.
- Gallery placeholders are the only state allowed to use illustrative values.

Accessibility continues to expose a useful spoken state even though the visual presentation contains no metric text.

## Procedural animation design

Build the image as deterministic vector layers, not a raster sequence:

1. **Core reactor** — pronounced rhythmic breathing and concentric discharge waves.
2. **Inner filament sphere** — deterministic curved links carrying bright synaptic impulses, visible tails, and destination-node flashes.
3. **Particle crown** — seeded particles that brighten, orbit, and drift along constrained paths; no random jitter between renders.
4. **Cathedral arches** — symmetric upper and lower structures with very slow counter-rotation or phase offset.
5. **Orbital equator** — a restrained white/silver sweep around the center.
6. **Telemetry anchors** — four fixed nodes whose intensity reflects real plug state.
7. **Wordmark** — stable `JARVIS` text; it does not orbit, pulse, or compete with the image.

Motion must be energetic but ordered and architectural. Frequent neuron-like firings should make the projection feel alive without turning it into random noise or a loading spinner.

### Motion modes

- `liveApp`: continuous time-driven animation for a foreground app.
- `widgetTransition`: a restrained morph between two equally valid hero frames when WidgetKit presents a new entry.
- `reducedMotion`: no rotation or travel; at most a subtle opacity transition on a real update.
- `alwaysOn`: static full-designed-luminance hero frame; the system may apply its own display treatment.
- `stale`: static fractured frame with no energized motion.

Every endpoint must be a finished composition because WidgetKit may stop showing motion at any time.

## Proposed architecture

### Shared rendering engine

Create a shared source group compiled into the iPhone app, Watch app, iPhone widget, and Watch widget without adding SwiftTerm, NIO, or SSH to widget targets.

Suggested types:

- `MonochromeCathedralArtwork`: public SwiftUI composition.
- `MonochromeCathedralCanvas`: procedural `Canvas` renderer.
- `MonochromeCathedralGeometry`: deterministic points, arcs, filaments, and seeded particles.
- `MonochromeCathedralPhase`: normalized phase values for core, orbit, crown, and highlights.
- `MonochromeCathedralMotionMode`: live app, widget transition, reduced motion, Always On, or stale.
- `MonochromeCathedralStyle`: phone/watch density and rendering-mode adaptations.

Inputs remain explicit: telemetry, layout, motion mode, phase, rendering mode, and luminance state. Rendering must never perform networking or generate fake telemetry.

### Widget behavior

The current providers request a reload every 15 minutes, but WidgetKit controls actual timing. Do not increase reload frequency to simulate animation.

When a fresh entry replaces an old entry:

- Alternate between two compositionally balanced deterministic phases.
- Animate small layer transforms and opacity changes for approximately 1–2 seconds.
- Let the resulting frame remain static until the next real update.
- Suppress motion under Reduce Motion, stale telemetry, nonanimated system contexts, or reduced luminance, without intentionally dimming the static hero frame.

This produces occasional "awakening" motion, not continuous animation. It must be described honestly in the widget description and acceptance criteria.

Preserve existing deep links:

- iPhone Neural Core opens Home.
- Watch Neural Core opens Terminal.

### Optional foreground app behavior

Use `TimelineView(.animation)` to derive phase from the supplied timeline date rather than timers or mutable random state.

- iPhone: animate while the relevant JARVIS view is visible.
- Watch: animate only when the app is active and cadence is live.
- Watch Always On: immediately freeze on the full-designed-luminance static hero phase and rely on the system for actual display luminance.
- Respect Reduce Motion on both platforms.

This is the only supported route to genuinely continuous Monochrome Cathedral motion.

## Performance boundaries

- Keep a single primary `Canvas` and a small number of independently transformed SwiftUI layers.
- Use deterministic seeded geometry so entry updates do not scramble the sphere.
- Reduce filament and particle counts on Watch.
- Keep Always-On artwork at the designed luminance; simplify only effects the system cannot render legibly or efficiently.
- Avoid Metal, video, animated GIF/APNG, timers, display-link workarounds, timer/custom-font frame encoding, and private clock-hand effects in widget extensions.
- Treat the actual `GeometryReader` size as authoritative; do not hardcode mockup pixels.

Initial density targets for physical profiling, not hard requirements:

- iPhone medium: 80–140 visible filament segments and 40–64 particles.
- Watch rectangular: 36–72 visible filament segments and 18–32 particles.
- Always On: no animation and no intentional luminance reduction; detail may change only if physical legibility or performance requires it.

## Implementation gates

### Gate 0 — motion study (complete)

Produce a short native-vector motion study at the exact iPhone medium and Watch rectangular aspect ratios. Show:

- normal active loop,
- WidgetKit-compatible one-shot transition,
- Watch Always-On frame,
- stale/frozen frame,
- Reduce Motion frame.

Approval here prevents committing to unsuitable motion language.

Neural-firing revision 2 motion-study artifacts:

- `/tmp/JARVIS-monochrome-cathedral-neural-firing-study.mp4`
- `/tmp/JARVIS-monochrome-cathedral-neural-firing-iphone.mp4`
- `/tmp/JARVIS-monochrome-cathedral-neural-firing-watch.mp4`
- `/tmp/JARVIS-monochrome-cathedral-full-luminance-static.png`
- [Discord delivery](https://discord.com/channels/1474183230541529260/1505957511704871114/1541283895012622397)

### Gate 1 — renderer replacement (complete)

Replace the current Neural Core ring/trace with the static Monochrome Cathedral renderer while preserving telemetry semantics, `JARVIS`, accessibility, rendering modes, and deep links.

### Gate 2 — physical WidgetKit transition proof (installed; visual acceptance pending)

Before building the entire animation system, prove on both allowlisted physical devices that the chosen layer transforms interpolate acceptably between timeline entries. If `Canvas` contents crossfade rather than interpolate cleanly, keep geometry inside Canvas and animate only stable containing layers such as orbit rotation, scale, and opacity.

This gate is important because widget animation behavior is system-rendered and physical evidence is authoritative.

### Gate 3 — optional live app renderer (not implemented)

Add date-driven continuous motion to an approved app destination without changing the iPhone Home or Watch Terminal deep-link contracts.

### Gate 4 — hardening and deployment (complete for widget scope)

- Unit-test deterministic geometry and phase generation.
- Preserve stale/fail-closed telemetry tests.
- Preserve the exactly-30%-noncritical Codex test.
- Snapshot live, stale, placeholder, full-color, accented, reduced-motion, and Always-On states for both layouts.
- Profile CPU/GPU and memory on the physical iPhone and Watch.
- Build and audit all four products; verify widgets remain free of SwiftTerm/NIO/SSH.
- Archive and deploy only after explicit approval, using the exact audited iPhone IPA and archived Watch product.

## Acceptance criteria

1. No raster cathedral image is used in production artwork.
2. The `JARVIS` wordmark is the only visible text.
3. The artwork dominates both widget footprints and stays ordered at Watch size.
4. Widget motion occurs only on genuine WidgetKit entry changes and is never advertised as continuous.
5. The foreground app version, if approved, animates smoothly while active.
6. Watch Always On is static, legible, accent-aware, and not intentionally dimmed by JARVIS; system luminance treatment is accepted.
7. Reduce Motion removes rotation, travel, and pulsing.
8. Stale or unavailable telemetry cannot illuminate activity.
9. Existing platform-specific deep links remain unchanged.
10. No hardware control, daemon mutation, terminal input, or persistent pane restart is involved.

## Build 47 implementation record

Production implementation:

- `WidgetShared/NeuralCoreArtwork.swift` — shared procedural Cathedral, neural impulses, reactor waves, accent/AOD/Reduce Motion handling, stale-state fracture, and accessibility.
- `JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift` — deterministic timeline-entry phase and 1.8-second transition duration.
- `JARVISWidget/NeuralCoreWidget.swift` — iPhone medium phase input, near-black background, and Home deep link.
- `JARVISWatchWidget/NeuralCoreWidget.swift` — Watch rectangular phase input, transparent background, and Terminal deep link.

Verification completed:

- 26 `jarvisd` tests.
- 9 `terminald` tests.
- 48 JARVISKit tests with 3 expected live-test skips.
- 19 iPhone host tests.
- Warning-free iOS and watchOS simulator builds.
- Warning-free signed archive and export.
- All four products report `0.3.0 (47)`, team `5GB5BU49Q8`, valid signatures, and the required bundle hierarchy.
- Watch host and widget remain free of SwiftTerm, NIO, and SSH linkage.

Artifacts:

- Archive: `/tmp/JARVIS-build47-monochrome-cathedral.xcarchive`
- IPA: `/tmp/JARVIS-build47-monochrome-cathedral-export/JARVIS.ipa`
- IPA SHA-256: `2602cc2b4955002c77b84823fcbcf9461690534dd591fd3759fbbb9cfb165ebd`
- Archive log: `/tmp/JARVIS-build47-archive.log`
- Export log: `/tmp/JARVIS-build47-export.log`
- iPhone install log: `/tmp/JARVIS-build47-iphone-install.log`
- Watch install log: `/tmp/JARVIS-build47-watch-install.log`

Deployment:

- Exact exported IPA installed with explicit `ideviceinstaller -w upgrade` on Dylan's allowlisted iPhone only.
- Exact archived `JARVISWatch.app` installed through CoreDevice on Dylan's allowlisted Apple Watch only.
- Both device inventories report `0.3.0 (47)`.
- Both host apps launched and both widget extension processes remained active after installation.
- No plug, purifier, daemon, scheduler, service, terminal-input, or persistent-pane mutation occurred.

## Next acceptance step

Confirm the Cathedral's physical static appearance on both surfaces and observe a real timeline-entry transition. WidgetKit timing remains system-controlled, and Always On remains static. The optional continuously animated foreground app renderer is still out of scope unless separately approved.
