# Shared Pi session indicators

## Larger dashboard glyphs — build 247

Build **247** raises the dashboard glyph base size to **22 pt**, up from build
246's 18 pt (22% larger). One shared `PiSessionGlyphs.dashboardSize` supplies both the
nine Pi cards and Room Audio, with their existing Dynamic Type scaling. The
80 ms cadence, colours, status labels, card spacing, routes and phone/Watch
Terminal capsules are unchanged. Owner-approved build 247 was installed once on
the allowlisted iPhone and independently version/launch/process verified on
**2026-10-04 at 11:17 EDT**; launch selected the JARVIS dashboard.

**Frozen release validation:** 169 iPhone tests passed, including enlarged glyph rendering,
real busy animation/off-page stopping and unchanged normal card footprints
(58 pt per card; 190 pt for the nine-card grid). All 296 shared tests completed
with 3 expected live-test skips and no failures; all 37 terminal tests passed.
The indicator source contract,
combined iPhone/embedded-Watch and standalone Watch simulator builds passed;
the pre-existing plain-Paste pixel assertion remains excluded. The dedicated
simulator returned to its original shutdown state.

The exact signed candidate and exact rollback **246** each passed all four bundle
signature/profile/unchanged-entitlement audits. Existing paid-team signing identity
was reused; all four cached profiles are byte-identical to rollback. Pinned dependencies,
capabilities and credentials are unchanged. There was no rebuild between audit
and installation. Fresh allowlist/identity, pairing, developer services, unlock
and baseline-246 checks passed before the one-shot iPhone install; final version
and independently observed running-process checks passed. All **18 protected
service records** and existing Pi pane/window/process identities were preserved.
No backend/Pi restart, direct Watch install/launch, install retry, uninstallation,
reboot or app-data removal occurred.

Watch's last independent device version/launch/process verification remains
**245**; iOS may sync the unchanged-source embedded companion, and no new Watch
version is claimed. Physical 22-point appearance and VoiceOver acceptance await
owner review. Private evidence is retained in `20261004T150607Z-build247-larger-glyphs`,
including 248 frozen source inputs, tests/audit, signed/sealed archive and
`deployment/result.json`. Exact signed iPhone recovery builds 247/246 and Watch
recovery builds 245/244 remain retained; superseded secondary archives/build
scratch were pruned with source/audit/test evidence preserved. See
[current retention](operations.md#current-recovery-retention-and-cleanup).

## Dashboard braille — build 246

The iPhone **JARVIS** dashboard now replaces its SF Symbol session icons with
Pi-style glyphs, including Room Audio/session 10. The nine glass cards, session
numbers, written status labels, whole-card terminal routes and VoiceOver labels
are unchanged. Terminal's phone/Watch capsule indicators and their native motion
are deliberately unchanged.

| Lifecycle | Dashboard glyph | Colour / motion |
|---|---|---|
| Running | `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` | Existing green, forward at 80 ms/frame |
| Compacting | Same ten frames | `#8A8A8A`, identical direction and cadence |
| Idle | `●` | Existing purple, static |
| New | `○` | Existing cyan, static |
| Offline | `×` | Existing grey, static |
| Unknown | `?` | Existing amber, static |

[`PiSessionGlyph.swift`](../JARVISKit/Sources/JARVISKit/PiSessionGlyph.swift) owns
the sequence, glyph mapping, policy gate and fixed-size monospaced renderer. A
common reference-date epoch keeps busy glyphs in phase. Only eligible busy glyphs create an 80 ms periodic display timeline;
idle/unknown/off-page/inactive/dimmed/Reduce Motion surfaces create none. Busy
states retain the first braille frame when motion is disabled, remaining distinct
from the Idle dot. The box scales with Dynamic Type without changing frame-to-frame
layout. Glyphs are decorative and hidden from accessibility; the enclosing card
continues to announce its session and lifecycle.

Existing stale→Unknown handling, speaker freshness, backend refresh cadence,
credentials, signing, dependencies and device controls are unchanged. No animation
frame requests network data. Source contracts compare sequence/cadence/static
shapes with Pi Desk; unit and rendered-view tests cover policy gates, wrapping,
font coverage and unchanged card footprints.

**Deployed:** owner-approved build **246** was installed once on the allowlisted
iPhone and independently version/launch/process verified on **2026-10-04 at
10:42 EDT**. Exact signed build **245** is retained for rollback. No direct Watch
installation or launch was issued; iOS may sync the unchanged-source companion.
Watch's last independent version/launch/process verification remains build 245.
A post-install read-only Watch inventory was unavailable and is not evidence of
an updated or removed Watch app. The owner accepted build 246's indicator
appearance; VoiceOver acceptance remains unconfirmed.

**Frozen release validation:** 168 iPhone tests passed, including real hosted
busy animation/off-page stopping and fixed-size light/dark glyph rendering. All
296 shared tests completed with 3 expected live-test skips and no failures; 37
terminal tests and both simulator builds passed. The pre-existing plain-Paste
pixel assertion remains excluded. The full source/unit verifier also passed for
the pre-version candidate. Font coverage and all ten braille frames were checked;
normal cards retain their 58-point height and the nine-card grid its 190-point
height. The dedicated simulator was returned to its initial shutdown state.

The exact signed candidate and rollback 245 passed all four bundle signatures,
profiles and unchanged-entitlement audits, with pinned dependencies and frozen
inputs verified. All 18 protected service records and existing Pi pane identities
were preserved; no backend/Pi restart, app-data removal or credential change.
Private evidence: `20261004T143234Z-build246-dashboard-braille`, including sealed
archive, frozen source manifests, tests/audits and `deployment/result.json`. See
[deployment checks](operations.md#dashboard-braille--build-246).

SwiftUI ImageRenderer previews are useful for glyphs and dimensions, not physical
Liquid Glass acceptance; large-text glass effects may render inaccurately offscreen.

## Deployed palette — build 245

Pi Desk and the app now use **neutral grey `#8A8A8A` for Compacting**,
matching Pi Desk's existing neutral grey. Pi's indicator colours are theme-dependent;
this is a deliberate neutral-grey choice, not a universal Pi theme RGB claim.
`PiSessionLifecycle.statusColor` is the shared app authority for JARVIS cards and the
phone/Watch terminal indicators. The exact sRGB value is
`Color(red: 138.0 / 255, green: 138.0 / 255, blue: 138.0 / 255)`.

Pi Desk's running and compacting braille spinners both advance forwards every
80 ms (0.8-second cycle), matching Pi TUI's default loader cadence. Metadata polling
remains 500 ms; frame deadlines stay independent of those refreshes.

**Deployed:** build 245 was installed once on each allowlisted iPhone and Watch
and independently version/launch/process verified on **2026-10-04 at 09:43 EDT**.
Exact signed build 244 is retained for rollback. Physical colour acceptance awaits
owner review; installed-version and process checks do not prove perceived colour.

Running green, Idle purple, New cyan, Offline grey and Unknown amber are unchanged.
In deployed build 245, the app's native busy animations, Reduce Motion behaviour,
status labels, accessibility, freshness and network cadence were unchanged. Only
Pi Desk adopted single-cell rotating indicators and stronger navigation/group
badges in that release; the dashboard source candidate above is a later change.

The shared colour test and verification-script assertion cover this mapping;
Pi Desk also checks the exact cross-project RGB contract.

## Grey palette deployment — build 245

Frozen build 245 passed 163 iPhone tests, 290 shared tests (3 expected skips),
37 terminal tests, the combined iPhone/embedded-Watch simulator verification and
the standalone Watch simulator build. Only the previously documented plain-Paste
pixel assertion remains excluded. Candidate and exact rollback 244 passed all
four app/widget signature/profile/unchanged-entitlement audits; pinned dependencies,
capabilities, signing identity and feature flags are unchanged.

Both devices passed fresh identity/allowlist, pairing, developer-service, unlock
and baseline-244 checks before the first physical write. Each received exactly
one install, followed by independent version/launch/process and final-version
readbacks. All 18 protected service records and existing Pi pane/window/process
identities were preserved; no backend/Pi restart, unpairing, reboot, uninstallation,
app-data removal or credential change. The isolated validation simulator was
returned to its initial shutdown state.

Private evidence: `20261004T132854Z-build245-session-grey`, including frozen
source/hash manifest, exact sealed signed archive, test/audit logs and
`deployment/result.json`. See
[deployment checks](operations.md#grey-compaction-palette--build-245).

## Previous orange palette deployment — build 244

Owner-approved build **244** was installed once on each physical iPhone and Watch
and independently version/launch/process verified on **2026-10-03 at 23:32 EDT**.
All four signed app/widget bundles passed signature/profile/unchanged-entitlement
checks; dependencies and capabilities are unchanged. Frozen verification passed
163 iPhone tests, 290 shared tests (3 expected skips), 37 terminal tests and both
simulator builds. The known plain-Paste pixel assertion remains excluded.

Exact signed build 243 is retained for rollback. Protected service PIDs and
existing Pi identities were preserved; no backend/Pi restart or app-data removal.
Physical palette acceptance is pending owner review. Private release evidence:
`20261004T032028Z-build244-session-orange`. See
[deployment checks](operations.md#orange-compaction-palette--build-244).
