# Native app build and operations

[App overview](../README.md) · [Architecture](architecture.md) · [Documentation index](README.md)

This guide is an entry point and safety checklist. It does not authorize deployment or establish which build is installed. Historical commands are retained in the linked archives; revalidate their versions, device selectors, and signing assumptions before use.

## Prerequisites

- A compatible Mac/Xcode toolchain, XcodeGen, Python, Node, and the project's resolved dependencies.
- Xcode's optional Metal toolchain for the SwiftTerm renderer, if not already installed.
- Configured Pi and host services for live integration. Reading source and running isolated tests do not require permission to control the live system.
- Appropriate Apple signing and explicitly approved physical devices for installation.

Start with the repository's [runtime guide](../../../../docs/runtime-guide.md) and [rebuild instructions](../../../../.pi/docs/REBUILD_FROM_SCRATCH.md). Prefer an isolated development checkout so project generation and test artifacts cannot disrupt the live workspace.

## Verification

From `projects/operation-jarvis/jarvis-app/` in the isolated checkout:

```bash
./scripts/verify-jarvis-app.sh
```

The verifier regenerates the Xcode project, checks the locked package resolution, runs Python/Node/Swift tests and source/asset contracts, and builds iOS/watchOS simulator products. It writes build artifacts and may need configured simulator destinations. It is not a read-only health command and was not run as part of this documentation reorganization.

The `JARVIS_RUN_IOS_TESTS=1` flag enables additional iOS testing; `JARVIS_IOS_TEST_DESTINATION` can select the intended isolated simulator. Live integration uses a separate `JARVIS_LIVE_TESTS=1` opt-in and requires explicit permission to access the configured host. Do not enable live tests merely to review documentation.

Useful review-only checks from the repository root:

```bash
git diff --check
git status --short
```

These check formatting and scope, not runtime correctness. Simulator verification, signed archive auditing, and physical acceptance are separate gates.

## Signing and deployment

1. Record the exact source commit, dependency locks, owner-approved feature flags, and intended version. Do not infer an installed version from `project.yml` or a historical README heading.
2. Verify in isolation. Preserve existing conversations, session identities, private configuration, credentials, and rollback evidence.
3. Obtain separate authorization for portal changes, signing, service rollout, or installation on allowlisted devices.
4. Produce and audit the exact archive: bundle hierarchy, signatures, entitlements, provisioning profiles, embedded Watch product, and exclusion of private files.
5. Freeze the audited products. Do not rebuild between audit and installation.
6. Install only those products on the explicitly approved devices, then perform bounded physical acceptance. A build command or launch success does not establish gesture, Siri, attachment, or notification acceptance.
7. Keep an exact rollback artifact and record what was actually deployed in private operational evidence.

Older documents mix Personal Team/free provisioning and paid-program signing. Do not run the retained free-signing helper by default or assume an old Team ID, device identity, or profile applies today.

Detailed retained procedures:

- [Packaging and signing history](development-history.md#7-companion-identity-embedding-and-signing)
- [Archive, verification, and export history](development-history.md#8-verification-archive-and-export)
- [Free-profile deployment history](development-history.md#9-canonical-free-profile-deployment)
- [Script descriptions](../scripts/README.md)

## Protect the live terminal and services

- Do not kill, resize, replace, or select a different tmux/Pi session as a side effect of documentation, app builds, or unrelated service work.
- Do not reload Pi extensions, start new slots, install LaunchAgents, or restart `jarvisd`, `terminald`, room audio, or the scheduler without the corresponding owner-approved plan.
- Use exact current session identities and fresh authoritative evidence, not historical PIDs or whichever conversation was most recently used.
- Never replay uncertain terminal input or hardware commands. Check state through the intended read-only path and leave uncertain delivery explicit.
- Preserve conversations and new slots during rollback; rolling back an app is not permission to delete runtime history.

## Notifications

Changing app code is not permission to request device consent, read provider keys, activate dispatch, or send a test alert. Verify signing capabilities, per-device opt-in, registrations, provider configuration, payload privacy, and the host activation gate separately. Do not backfill historical notifications or retry ambiguous delivery as though it had definitely failed.

Notification privacy contracts changed across historical builds. Read the [architecture summary](architecture.md#notifications-and-privacy) and the [implementation record](implementation-history.md#native-iphone-and-apple-watch-apns-scheduled-job-notifications), including later addenda, rather than adopting the earliest plan.

## Diagnostics and recovery

Begin with read-only state and the exact failed boundary: connection trust, endpoint availability, source/build compatibility, signing, companion registration, or application behavior. Do not weaken host-key/certificate checks or broaden network trust as a shortcut.

Retained references:

- [Diagnostics and non-destructive recovery](development-history.md#10-device-diagnostics-and-non-destructive-recovery)
- [Physical validation and release procedure](development-history.md#11-physical-validation-and-release-procedure)
- [Attachment rollback and compatibility](implementation-history.md#compatibility-and-rollback)

Never erase, unpair, uninstall, reboot, or target a device outside the approved allowlist as an automatic recovery action. Keep device logs, provisioning output, setup codes, archives, private paths, and unreviewed screenshots out of public commits.
