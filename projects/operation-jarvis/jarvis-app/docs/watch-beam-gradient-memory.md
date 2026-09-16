# Watch beam-pulse gradient candidate

Controlled physical A/B on 2026-09-12: Build164 restores animation with old design. Build165 shows C2 and owner confirms the core animates, without later beam pulses. Build166 and Build168 are killed at20MiB when rendering the pulse addition. Build168 static-glow batching was insufficient; this candidate starts from main/166, not168. Rejected167 reduced-FPS candidate was never installed.

Keep48scenes, nominal24FPS and2second loop, all12pulses,6segment tails,heads,glints, static C2, geometry, brightness, accessibility/lifecycle guards, telemetry and destinations. On Watch only, normalize each gradient-tail path into a shared unit-chord shading, using draw-time opacity rather than a distinct gradient ramp with baked-in envelope alpha for each pulse/frame. Transform back to the exact original geometry and stroke width. iPhone retains its original draw path. No new timers, reloads, dependencies or backend/session changes.

All48frames are compared against the original pulse rendering at both rendering modes and four surface sizes. Source/render tests cannot prove WidgetKit memory headroom; installation plus awake physical motion and newJetsam checks remain required. This is still a candidate, not a claim of repaired memory.
