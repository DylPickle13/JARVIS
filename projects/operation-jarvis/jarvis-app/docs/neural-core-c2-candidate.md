# Neural Core C2 and beam motion

## Deployment and acceptance record

On 2026-09-12, Build165 installed C2 on the approved iPhone, followed by Build166 (`b19809c`) with beam motion. Both iPhone installations were inventory/process-verified against their signed products, with fresh checks preserving all nine session identities and backend/configuration state. The owner accepted Build166's appearance and visible animation. This is not an energy, memory, VoiceOver, accented-mode or AOD acceptance claim.

The Watch was unavailable during the Build165 reachability check and was outside the iPhone-only Build166 rollout. No Watch installation was attempted in either rollout; its last verified Build164 inventory is historical, not a fresh current-device check. The source changes are being integrated separately from deployment, preserving newer documentation and unrelated main-branch changes.

## Beam-motion follow-up

Build165 installed the C2 visual design on iPhone; Watch deployment remained pending connectivity. The owner then requested movement on the side branches. The follow-up adds **12 short outward-travelling silver pulses** (six per side), with fading tails and brief glints at actual branch junctions. Their geometry is shared with the static dendrites so the light cannot drift off its path. They consume the existing 48 selected phases over the same two-second loop, with no new clocks, reloads, per-frame blur filters or changes to the core's motion. Existing static/Reduce Motion/AOD fallback freezes them at the authored static phase. Static beam brightness, shell highlights and palette remain unchanged. This follow-up shipped on iPhone in Build166; Watch installation remains pending.

Owner-selected **C2 / Dendrites** adds fine organic side branches, secondary forks and tiny synapse points to the existing iPhone/Watch Cathedral artwork. The denser central shell remains the focus. The follow-up vibrancy refinement increases only shell stroke contrast, silver-node highlights and local glow; the approved side-beam opacity and silver-white RGB palette are unchanged.

## Scope and preserved behaviour

- Identical design on the phone medium widget and Watch rectangular complication; existing radius, wordmark, widget families, margins, transparent Watch background and tap destinations are unchanged.
- Existing 48-frame, nominal-24-FPS timer-mask selector paths and animated core layers are unchanged. The static C2 beams and shell remain hoisted once outside the selector stack; only the small pulse overlay is phase-driven. Beams precede the halo, pulses precede the original moving layers, and the shell follows the core.
- Complete static/fallback artwork uses the same layer order and full authored luminance. Existing Reduce Motion, reduced-luminance/AOD and unavailable-font policy continues to choose static artwork. No intentional AOD dimming was added.
- No changes to live telemetry, refresh, Siri, notifications, Jobs, terminal sessions, Room Audio, signing identities or entitlements. No new polling, service calls, animation clocks, media or private APIs.
- Implementation was isolated on `feat/neural-core-beam-motion`, based on the exact Build165 app source `541a477`. That source descends from `1888cdd`. Later main-branch changes are retained during source integration; no backend rollout, Pi reload or device redeployment is implied by the merge.

## Verification

`bash scripts/verify-neural-core-artwork.sh` compiles the actual shared artwork in an isolated temporary macOS Swift package and checks representative phone/Watch sizes, complete versus split layers, phase-independent static fallback, phase/freshness-independent hoisted decoration, monochrome colours and central dominance. `JARVIS_NEURAL_RENDER_OUTPUT=/path` optionally retains PNGs. The full app verifier runs this check plus existing tests and simulator builds.

Build165 baseline verification passed: 148 JARVISKit tests (3 expected live-test skips), 79 iOS tests, 95 daemon tests, 32 terminal tests, 43 scheduler tests, guarded Siri Node checks, 176 artwork-render assertions, source contracts and both simulator builds. The isolated test simulator was deleted. The app verifier's stale 240-character notification-preview assertion was aligned with the existing 140-character backend cap from base commit `a810484`; no backend code was changed. Earlier render-harness/compiler and assertion failures were retained in development evidence, not counted as successful verification.

The beam-motion follow-up passed the full verifier on its first run: 148 Kit tests (3 expected skips), 79 iOS tests, 95 daemon tests, 32 terminal tests, 43 scheduler tests, guarded Siri Node checks, source contracts and both simulator builds. Its 204 artwork assertions include visible phase differences on both outer sides and seamless phase wrapping. Complete versus split rendering and phase-independent static fallback remain covered. The isolated simulator was deleted. The 48-frame, two-second preview is rendered from actual source at the existing nominal cadence; it is not a device capture or guarantee of native WidgetKit frame delivery.

The render checks use explicit palette branches, not writes to read-only WidgetKit accessibility/rendering environments. Small colour-conversion rounding is tolerated in 8-bit grayscale measurements. Enlarged static ImageRenderer pictures are not device screenshots or proof of native WidgetKit animation, accented appearance, AOD, VoiceOver, memory or energy behaviour. The owner confirmed the iPhone's appearance and visible animation after Build166; the other physical-device acceptance items remain pending.

**Implementation and deployment remain separate.** No devices are required for local verification. This source integration does not authorize another install, launch or backend rollout. A later deployment must reconcile current production/source state and take fresh preservation baselines, rather than reusing historical rollout scripts.
