# Native app build and operations

[App overview](../README.md) · [Architecture](architecture.md) · [Documentation index](README.md)

Use this guide to build, test, and prepare the app for installation. Installing on a device still needs owner approval. Before using an archived command, check its version, device target, and signing setup.

## Watch layout restoration — build 240

Owner-approved build **240** was installed once on both devices and independently
version/launch/process verified on **2026-10-02 at 12:39 EDT**. Watch restores
**Home → Terminal → Plugs → JARVIS → Jobs**. Home is health-only; Plugs has its own
grid; purifier returns above Codex/oMLX, with its entry refresh on JARVIS.
The iPhone UI and build-239 notification/TLS fixes are unchanged.

149 iPhone tests passed, 285 shared tests completed with 3 expected skips, both
simulator builds passed, and all 37 terminal tests passed from frozen release
source. The existing plain Paste pixel exclusion remains. Earlier reused-workspace
backend runs hit a sampler timing assertion; no backend code was changed.
Signed candidate and exact build-239 rollback archives passed four-bundle audits
with unchanged entitlements and dependency lock.

**Post-check caveat:** all 18 protected service PIDs were unchanged, but Pi 4's
process changed during the install window (12:39:31 EDT), retaining tmux window
and pane IDs. The other nine pane processes were unchanged; all ten slots remain.
The installer stopped at its preservation assertion after both installs and final
version readbacks had succeeded. No install was retried and no backend restart was
issued by this deployment. The owner subsequently acknowledged that they might
have restarted Pi 4 and requested no further investigation. This closes the
follow-up without claiming the original pane-process preservation check passed.
Physical Watch swipe/Crown acceptance remains pending.

Private evidence: `20261002T163716Z-build240-watch-layout`, including the original
`deployment/result.json` exception and the follow-up review. Build 239 remains the
exact rollback; the older rollback artifacts were not modified.

## Navigation and terminal recovery — build 239

Build **239** was installed once on each allowlisted iPhone and Watch and
independently version/launch/process verified on **2026-10-02 at 12:15 EDT**.
It includes the new JARVIS/Home/Terminal grouping, phone tab swipes and a shared
completion-notification repeat-tap fix. A separately owner-approved terminald
update moves TLS handshakes off the listener and adds a five-second deadline.

The signed four-bundle archive passed its audit; 149 iOS tests, 285 package tests
(3 expected skips), and 37 backend tests passed. The previously documented plain
Paste pixel test was excluded. Both simulator builds passed. No credential,
entitlement, dependency-lock or Pi session identity changes. Readback confirms
both devices run 239; physical gesture/notification acceptance remains pending.

The previous installed version was development build 127. Its original binaries
had been cleaned up, so its rollback was reconstructed from pre-change source and
labelled accordingly; archived build 237 also remains intact. Build 238 was prepared
but never installed. See [full recovery and deployment record](terminal-recovery-and-notification-taps.md).
Private evidence: `20261002T160824Z-build239-navigation-recovery`.

## History cadence compatibility — build 237

Owner-approved build **237** was installed and version/process verified on both
iPhone and Watch on 2026-09-30 EDT. It accepts both 10-second and legacy 60-second
history sampling while preserving all bucket, freshness, coverage and schema
validation. Build 236's strict 60-second check rejected the new backend response
as unavailable; backend-only validation had missed this client contract.

The isolated candidate passed **266 package tests** (3 skipped, zero failures)
and **62 iOS tests**. Its exact Swift validator also accepted live `1h`/`24h`/`7d`
responses for both phone and Watch series. Home and the System layout are unchanged;
only validation and cadence-neutral explanatory text changed. Signed payload,
profiles, entitlements and source were audited; build 236 is retained as rollback
but cannot display history from a 10-second backend. The owner subsequently
confirmed the updated UI looks good. No backend/services were restarted by this app deployment.

Evidence: private signing-renewal artifact
`20261001T033129Z-build237-history-compat`, including `deployment/result.json`
and `live-contract-check.log`. Future history API changes must be validated through
the shipping native decoder, not only backend tests.

## Prerequisites

- A compatible Mac/Xcode toolchain, XcodeGen, Python, Node, and the project's resolved dependencies.
- Xcode's optional Metal toolchain for the SwiftTerm renderer, if not already installed.
- Configured Pi and host services for live integration. You can read source and run isolated tests without controlling the live system.
- Apple signing configured for the intended build, and owner-approved devices for installation.

Start with the repository's [runtime guide](../../docs/runtime-guide.md) and [rebuild instructions](../../../../.pi/docs/REBUILD_FROM_SCRATCH.md). Prefer an isolated development checkout so project generation and test artifacts cannot disrupt the live workspace.

## Verification

For backend-only changes, use `../jarvisd/verify.sh` from the app directory.
It isolates daemon configuration and event/log storage without building or
installing the apps. See [shared backend operations](../../jarvisd/README.md).

From `projects/operation-jarvis/jarvis-app/` in the isolated checkout:

```bash
./scripts/verify-jarvis-app.sh
```

The verifier regenerates the Xcode project, checks locked dependencies, runs Python/Node/Swift tests and source/asset checks, and builds iOS/watchOS simulator apps. It writes build artifacts and may need configured simulator destinations. It is not a read-only health check; the documentation review did not run it.

The `JARVIS_RUN_IOS_TESTS=1` flag enables additional iOS testing; `JARVIS_IOS_TEST_DESTINATION` can select the intended isolated simulator. Live integration uses a separate `JARVIS_LIVE_TESTS=1` opt-in and requires explicit permission to access the configured host. Do not enable live tests merely to review documentation.

Useful review-only checks from the repository root:

```bash
git diff --check
git status --short
```

These check formatting and changed files, not runtime behavior. Test the simulator build, audit the signed archive, and check the app on its intended devices separately.

## Signing and deployment

1. Record the source commit, dependency locks, approved feature flags, and intended version. Check the installed app directly rather than guessing from `project.yml` or an old README.
2. Test in isolation. Preserve existing conversations, session identities, private configuration, credentials, and rollback records.
3. Obtain approval for Apple portal changes, signing, service updates, and installation on the allowlisted devices.
4. Audit the archive's bundle layout, signatures, entitlements, provisioning profiles, embedded Watch app, and exclusion of private files.
5. Keep that exact archive. Do not rebuild between audit and installation.
6. Install only the audited products on the approved devices. Check gestures, Siri, attachments, and notifications on the devices; a successful build or launch does not test those behaviors.
7. Keep the exact rollback build and a private record of what was installed.

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

Before enabling or testing notifications, obtain approval to request device consent, access provider keys, and send alerts. Check signing capabilities, each device's opt-in and registration, provider settings, payload privacy, and host activation. Do not send old notifications as a backfill or retry a delivery whose outcome is unknown.

Notification privacy contracts changed across historical builds. Read the [architecture summary](architecture.md#notifications-and-privacy) and the [implementation record](implementation-history.md#native-iphone-and-apple-watch-apns-scheduled-job-notifications), including later addenda, rather than adopting the earliest plan.

## Siri phrase troubleshooting

The app advertises **“Hey JARVIS”** through its built-in App Shortcut, **Talk to JARVIS**. A personal shortcut is not required. Activate Siri first (for example, hold the iPhone side button or Watch Digital Crown), then say the phrase; JARVIS does not replace Apple's Siri wake phrase.

If Siri answers with its built-in “Mr Stark” joke rather than asking for a prompt:

1. On iPhone, open **Shortcuts**, find **JARVIS** in the app shortcuts, tap its heading, then the **ⓘ** information button.
2. Check **Siri / Use in Siri**. Enable it if disabled. Its exact label can vary with the OS version. An app's packaged phrase metadata does not prove this user-controlled setting is enabled.
3. Activate Siri and say **“Hey JARVIS.”** For a routing-only test, cancel after the prompt question; do not supply a test prompt that would consume an unused New session.
4. Test Watch separately when it is available. An iPhone success does not establish Watch registration or end-to-end prompt delivery.

On 2026-09-12, the owner found this Siri toggle disabled and confirmed that enabling it restored the iPhone phrase. No source fix, rebuild, personal shortcut or Siri reset was needed. Watch recovery was not confirmed. If the setting is already enabled or JARVIS is missing from the catalogue, investigate that device's registration and permissions before changing code or resetting Siri.

Phrase recognition and terminal admission are separate checks. The existing prompt action still submits at most once to an eligible unused New session, or refuses when none is available. Never reload/reset a Pi session or retry an uncertain submission merely to troubleshoot phrase recognition.

## Diagnostics and recovery

Start with read-only checks to narrow down the problem: connection trust, endpoint availability, compatible versions, signing, Watch registration, or app behavior. Do not bypass host-key or certificate checks, or broaden network access, to get past an error.

Retained references:

- [Diagnostics and non-destructive recovery](development-history.md#10-device-diagnostics-and-non-destructive-recovery)
- [Physical validation and release procedure](development-history.md#11-physical-validation-and-release-procedure)
- [Attachment rollback and compatibility](implementation-history.md#compatibility-and-rollback)

Never erase, unpair, uninstall, reboot, or target a device outside the approved allowlist as an automatic recovery action. Keep device logs, provisioning output, setup codes, archives, private paths, and unreviewed screenshots out of public commits.
