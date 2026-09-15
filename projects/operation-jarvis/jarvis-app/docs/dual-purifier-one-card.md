# Dual-purifier release candidate

Owner-approved scope: two rows in the existing single iPhone purifier card;
no added Home height. Candidate starts from deployed build175 and includes the
reviewed multi-purifier tooling. No terminal/clipboard/artwork changes.

- Home card: 54pt total height, 22pt rows, compact fixed-size 12pt text; individual
  VoiceOver labels include full names/units. Full-size Dynamic Type readings and
  controls live in the selected device's scrolling detail sheet. The small row
  tap areas require physical acceptance; do not claim simulator render checks
  establish usability. No new inline toggles or bulk commands.
- Default legacy purifier fields/widgets remain Dylan's. `devices` adds the
  collection; stable public IDs are hashes of private VeSync CIDs. CIDs remain
  server-side. Missing selections never fall back to the default.
- One explicit batch collector; per-device age, errors and pending commands.
  Late reads cannot overwrite newer commands. Shared-session traffic stays
  serialized by the existing CLI lock. Ordinary polls never call VeSync.
- New selected-device commands require a known, fresh device ID. Older
  single-device clients retain their configured-default command path.
- Watch selection uses a native confirmation dialog (Menu is not available on
  watchOS). A distinct `purifierDeviceCommand` relay wire type prevents older
  phones from ignoring a new target and changing their default device.
- Explicit refresh on Watch System-page entry or selection/Refresh. No wrist,
  AOD, or periodic-poll cloud refresh. Immediate-only correlated read relay;
  no deferred delivery or write replay. Recovery requires a user action and is
  separately debounced to one attempt per 60 seconds.
- Automatic backoff and manual recovery remain read-only; testing must not
  change real purifier settings without asking the owner first.

Deployment gates: passing offline tests; rendered card review; signed artifact
and rollback audit; fresh before/after runtime identities. Host needs one
controlled jarvisd reload for the new collector/API. No Pi/terminald resets.
Watch installation requires confirmed finished OS update, availability/version
and fresh installed-app inventory. SDK26.5 simulator checks are not OS27 tests.
