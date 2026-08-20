# scripts/

Build and deployment helpers:

- `redeploy-jarvis-app.sh` — builds and installs the free-provisioned iPhone
  app through CoreDevice. This is appropriate for iPhone-only iteration, but
  iOS records a `skip watch app install` flag for this route. Do not use it as
  evidence of companion registration or transfer.
- `redeploy-jarvis-watch.sh` — builds and directly installs the Watch product
  against the paired physical Watch. This is the permitted Personal Team
  developer-install route. A direct install is authoritative only after the
  corrected parent package is registered on the iPhone and both installed
  flags are checked.
- `patch-watch-embedding.sh` — keeps XcodeGen's `Embed Watch Content` phase at
  `JARVIS.app/Watch/` (`dstSubfolderSpec = 16`), the Xcode 26 layout accepted by
  the corrected iPhone/Watch target relationship.
- `verify-jarvis-app.sh` — runs project-contained daemon and package tests,
  plist/shell checks, opaque icon validation, combined iOS/embedded-Watch
  simulator verification, and the standalone watchOS simulator build. iOS and
  live integration tests remain opt-in.

For initial companion registration under free provisioning:

1. archive/export a signed debugging IPA with Xcode;
2. install the parent IPA through `ideviceinstaller` so CoreDevice's skip-Watch
   option is not used;
3. do **not** rely on **My Watch → Available Apps → Install** — watchOS rejects
   free-profile apps from that source with `MIInstallerErrorDomain Code=111`;
4. install the exact `JARVIS.app/Watch/JARVISWatch.app` from the same archive
   through Xcode/CoreDevice's Watch developer service;
5. verify both installed flags and then test reachability.

Follow the complete procedure, trust step, identity rules, diagnostics, and
non-destructive recovery order in:

[`../docs/watch-companion-packaging-deployment-and-recovery-2026-08-20.md`](../docs/watch-companion-packaging-deployment-and-recovery-2026-08-20.md)
