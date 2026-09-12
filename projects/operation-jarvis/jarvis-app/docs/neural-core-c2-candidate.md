# Neural Core C2 — local implementation candidate

Owner-selected **C2 / Dendrites** adds fine organic side branches, secondary forks and tiny synapse points to the existing iPhone/Watch Cathedral artwork. The denser central shell remains the focus. The follow-up vibrancy refinement increases only shell stroke contrast, silver-node highlights and local glow; the approved side-beam opacity and silver-white RGB palette are unchanged.

## Scope and preserved behaviour

- Identical design on the phone medium widget and Watch rectangular complication; existing radius, wordmark, widget families, margins, transparent Watch background and tap destinations are unchanged.
- Existing 48-frame, nominal-24-FPS timer-mask selector paths and animated core layers are unchanged. C2's new beams and shell are **static decorative geometry**, not additional independently animated effects: beams precede the existing artwork; the shell follows it. Both are drawn once outside the selector stack rather than 48 times.
- Complete static/fallback artwork uses the same layer order and full authored luminance. Existing Reduce Motion, reduced-luminance/AOD and unavailable-font policy continues to choose static artwork. No intentional AOD dimming was added.
- No changes to live telemetry, refresh, Siri, notifications, Jobs, terminal sessions, Room Audio, signing identities or entitlements. No new polling, service calls, animation clocks, media or private APIs.
- Local work is isolated on `feat/neural-core-c2`. Its base is commit `1888cdd` (which already contains intervening notification-summary/date-context and documentation commits); it is not a declaration that those commits are deployed. Unrelated uncommitted main-worktree changes are not included.

## Verification

`bash scripts/verify-neural-core-artwork.sh` compiles the actual shared artwork in an isolated temporary macOS Swift package and checks representative phone/Watch sizes, complete versus split layers, phase-independent static fallback, phase/freshness-independent hoisted decoration, monochrome colours and central dominance. `JARVIS_NEURAL_RENDER_OUTPUT=/path` optionally retains PNGs. The full app verifier runs this check plus existing tests and simulator builds.

Local verification passed: 148 JARVISKit tests (3 expected live-test skips), 79 iOS tests, 95 daemon tests, 32 terminal tests, 43 scheduler tests, guarded Siri Node checks, 176 artwork-render assertions, source contracts and both simulator builds. The isolated test simulator was deleted. The app verifier's stale 240-character notification-preview assertion was aligned with the existing 140-character backend cap from base commit `a810484`; no backend code was changed. Earlier render-harness/compiler and assertion failures were retained in development evidence, not counted as successful verification.

The render checks use explicit palette branches, not writes to read-only WidgetKit accessibility/rendering environments. Small colour-conversion rounding is tolerated in 8-bit grayscale measurements. Enlarged static ImageRenderer pictures are not device screenshots or proof of native WidgetKit animation, accented appearance, AOD, VoiceOver, memory or energy behaviour. Those remain physical-device acceptance items.

**Implementation and deployment remain separate.** No devices are required for this local verification; no install, launch or backend rollout is authorized by this candidate. A later deployment must reconcile current production/source state and take fresh preservation baselines, rather than reusing historical rollout scripts.
