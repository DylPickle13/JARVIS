# Shared Pi session colours

Pi Desk and the app now use **vivid orange `#FF7A00` for Compacting** rather than
blue, separating it from New cyan. `PiSessionLifecycle.statusColor` is the shared
app authority for Home cards and the phone/Watch terminal indicators. The exact
sRGB value is `Color(red: 1, green: 122.0 / 255, blue: 0)`.

Running green, Idle purple, New cyan, Offline grey and Unknown amber are unchanged.
The app's existing native busy animations, Reduce Motion behaviour, status labels,
accessibility, freshness and network cadence are unchanged. Only Pi Desk adopts
new single-cell rotating indicators and stronger navigation/group badges.

The shared colour test and verification-script assertion cover this mapping;
Pi Desk also checks the exact cross-project RGB contract.

## Deployment — build 244

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
