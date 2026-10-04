# Shared Pi session colours

Pi Desk and the app now use **neutral grey `#8A8A8A` for Compacting**,
matching Pi Desk's existing neutral grey. Pi's indicator colours are theme-dependent;
this is a deliberate neutral-grey choice, not a universal Pi theme RGB claim.
`PiSessionLifecycle.statusColor` is the shared app authority for Home cards and the
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
The app's existing native busy animations, Reduce Motion behaviour, status labels,
accessibility, freshness and network cadence are unchanged. Only Pi Desk adopts
new single-cell rotating indicators and stronger navigation/group badges.

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
