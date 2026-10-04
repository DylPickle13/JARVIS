# Native app build and operations

[App overview](../README.md) · [Architecture](architecture.md) · [Documentation index](README.md)

Use this guide to build, test, and prepare the app for installation. Installing on a device still needs owner approval. Before using an archived command, check its version, device target, and signing setup.

## Grey compaction palette — build 245

Owner-approved build **245** was installed once on each allowlisted iPhone and
Watch and independently version/launch/process verified on **2026-10-04 at
09:43 EDT**. Compacting uses exact neutral grey `#8A8A8A`, shared by Home cards
and phone/Watch terminal indicators and mirrored by Pi Desk. Native app motion,
Reduce Motion, other lifecycle colours, routing, freshness and network cadence
are unchanged. Only eight frozen colour/test/version/documentation inputs differ
from deployed 244; no other feature, capability, dependency or credential changed.

**163 iPhone tests, 290 shared tests (3 expected skips), 37 terminal tests and both
simulator builds passed from frozen source.** The sole excluded assertion is the
previously documented plain-Paste pixel test. Candidate and exact build-244 rollback
passed four-bundle signature/profile/unchanged-entitlement audits and payload seals.
The existing paid-team identity/profiles and pinned dependencies were reused;
no portal/provisioning changes or rebuild between audit and installation.

A transient Watch developer-transport disconnect stopped the first read-only
preflight before any physical write; one fresh read-only preflight passed.
Immediately before installation, both targets again passed allowlist/identity,
pairing, usable developer-services, unlock and installed-baseline-244 checks.
Each then received exactly one install. Both versions and running processes were
independently verified, including final-version readbacks. No install retry.

All **18 protected service records** and existing Pi pane/window/process identities
were preserved. No backend/Pi restart, uninstallation, unpairing, reboot, app-data
removal or credential change. The dedicated validation simulator was restored to
its original shutdown state. Physical palette acceptance awaits owner review.

Private evidence: `20261004T132854Z-build245-session-grey`, including frozen
247-file source/hash manifest, exact signed/sealed archive, tests, four-bundle
audit, one-shot installer and `deployment/result.json`. Exact signed build 244
is the rollback for both devices. Session-created simulator/archive build caches
and Swift package scratch output were removed after verification (2.82 GiB).

Subsequent owner-requested cleanup removed **11 superseded signed archive trees**
from builds 231–243, freeing another **1.20 GiB**. Only deployed build **245** and
immediate rollback **244** retain signed archives; both payload seals and all four
bundle signatures were reverified after cleanup. Every historical frozen source,
audit, payload manifest/seal, deployment record, test log and result bundle remains,
with private per-release pruning records. Active signing status/config had no
references to the removed payloads. Historical entries below describe recovery
retention at their original deployment time, not current archive availability.
See [shared session colours](session-status-indicators.md).

## Orange compaction palette — build 244

Owner-approved build **244** was installed once on each allowlisted iPhone and
Watch and independently version/launch/process verified on **2026-10-03 at
23:32 EDT**. That release uses exact orange `#FF7A00` for Compacting, matching
Pi Desk at deployment time and separating it from New cyan. Build 245 now replaces
that palette with neutral grey `#8A8A8A`; see the verified deployment above. Native app motion,
other lifecycle colours, layout, routing, freshness and polling are unchanged.
Previously checked-in notification copy/comment clarifications accompany the
release; no additional notification-routing behavior or capability was added.

**163 iPhone tests, 290 shared tests (3 expected skips), 37 terminal tests and both
simulator builds passed from frozen source.** Only the previously documented plain
Paste pixel test was excluded. The exact signed archive and exact build-243
rollback passed all four bundle/signature/profile/entitlement/dependency audits.
Existing paid-team identity/profiles and feature flags were retained; dependencies,
credentials and entitlements were not changed. The audited archive was not rebuilt
between audit and installation.

Fresh device allowlist/identity, pairing, developer-service, lock-state and
installed-baseline-243 checks passed before the first physical write. The Watch's
initial connecting transport reported unknown developer mode; bounded read-only
checks subsequently verified enabled mode and a compatible DDI. No device writes
occurred during that connection check. Each device later received exactly one
installation and its installed version and running process were read back
independently, including final-version checks.

All **16 active PIDs across 17 protected service records** and existing Pi
pane/window/process identities were preserved. No backend service or Pi restart, uninstallation, unpairing, reboot,
app-data removal or credential change. The isolated validation simulator was
returned to its previous shutdown state. Physical palette acceptance awaits owner
review; an installed-version/launch check does not itself prove perceived colour.

Private evidence: `20261004T032028Z-build244-session-orange`, including frozen
source/hash manifest, test results, exact signed archive, payload seal, four-bundle
audit, one-shot deployment helper and `deployment/result.json`. Exact signed build
243 remains retained as rollback for both devices. Owner-requested cleanup removed
approximately 3.1 GiB of session-created build caches, temporary palette/test
checkouts and local/remote Pi Desk staging. Exact deployed/rollback archives,
frozen source/manifests, audits, test results and Pi Desk rollback backups remain;
both archive seals/signatures and frozen inputs verify after cleanup. See
[shared session colours](session-status-indicators.md).

## Balanced Settings grid — build 243

Owner-approved build **243** was installed once on the allowlisted iPhone and
independently version/launch/process verified on **2026-10-02 at 16:06 EDT**.
It replaces build 242's uneven inline Settings cards with four equal Liquid Glass
summary cards, one full-width Diagnostics & Maintenance card, and separate glass
editors. The overview retains the Alerts toggle; passwords load into editing state
only on the iPhone Terminal detail page. Existing safety confirmations remain.

**163 iPhone tests passed from frozen release source**, excluding only the previously
documented plain-Paste pixel test. The populated native fixture measured 685.5 pt
within its 765 pt tab viewport. Equal card bounds, accessibility expansion,
editor navigation/back, invalid-save publication and toggle-without-navigation passed.
Candidate and exact build-242 rollback archives passed four-bundle signature,
profile, entitlement and pinned-dependency audits. Shared/backend evidence remains
retained from previous releases and is not claimed as a new run.

Fresh identity, pairing, developer-services, lock-state and baseline-242 checks
passed before the single install. Final readbacks verified build 243 and its running
process; launch requested Settings. All 18 protected service PIDs and existing Pi
pane identities were preserved. No backend/Pi restart or direct Watch install was
issued. iOS may sync the embedded unchanged-source Watch companion; Watch's last
independent version verification remains build 241. Physical layout, keyboard and
VoiceOver acceptance awaits owner review.

Private evidence: `20261002T200255Z-build243-balanced-settings`, including
`deployment/result.json`. The exact signed build-242 rollback, frozen source,
manifests, test results and deployment evidence are retained.

## Inline iPhone Settings — build 242

Owner-approved build **242** was installed once on the allowlisted iPhone and
independently version/launch/process verified on **2026-10-02 at 15:40 EDT**.
Six inline Liquid Glass cards replace the four Settings destinations: Connection,
Diagnostics, iPhone Terminal, Watch Terminal, Maintenance and Notifications.
Options and technical information remain visible without opening cards; no card
scrolls internally. Compact portrait fixtures fit above the tab bar; larger text,
long errors and the keyboard may use page overflow. Safety confirmations remain.

**160 iPhone tests passed from frozen release source**, with the previously
recorded plain-Paste pixel test excluded. The native-control fixture measured
726.5 pt of populated content in the actual 765 pt tab viewport and mounted all
six text fields. Accessibility expansion, long values and failed-save error
publication also passed. The signed archive and exact build-241 rollback passed
four-bundle signature/profile/entitlement/dependency audits; sealed artifacts were
rechecked before and after installation. Shared (289, 3 expected skips) and backend
(37) evidence is retained from previous releases, not represented as new test runs.

Fresh identity, pairing, developer-services, lock-state and installed-baseline
checks passed before the sole iPhone install. Launch requested Settings. All
18 protected service PIDs and existing Pi panes were preserved; no backend service
or Pi session restarted. Credentials, app data, entitlements and dependency locks
were not changed. No direct Watch installation was issued; the iPhone package
contains the unchanged-source companion, which iOS may transfer automatically.
Watch's last independent device version verification remains build 241.
Owner review subsequently rejected the uneven card sizes. Build 243 now supplies
a balanced four-card summary grid with separate editors;
see [the replacement layout](navigation-and-home.md#balanced-settings-grid--build-243).
Keyboard and VoiceOver acceptance remain unconfirmed.

Private evidence: `20261002T193649Z-build242-inline-settings`, including
`deployment/result.json`. Exact signed build 241 and older recovery evidence remain
retained. Frozen source manifests record the release inputs independently of git HEAD.

## Matching swipe animation — build 241

Build 241, installed and independently version/launch/process verified on both
physical devices at **2026-10-02 13:23 EDT**, adds a shared 300 ms directional slide/fade:
horizontal phone tab swipes and vertical Watch page swipes. Page order, device-card
locations, Terminal session gestures and notification/TLS fixes are preserved.
Reduce Motion disables the transition; backgrounding and interrupted routes do
not strand a phone overlay. The native tab bar, tab controllers and delegates
are retained, with memory-only snapshots shielding moving content taps. Watch
also shields controls until its page animation completes.

155 iPhone tests passed, including six real-window animation/lifecycle tests;
289 shared tests completed with 3 expected skips. Both simulator builds and the
four-bundle signing/profile/entitlement/dependency audit passed. The existing plain
Paste pixel test exclusion remains. Terminal code is unchanged; its build-240
test evidence is retained, not represented as a new backend test run.

**Installation completed:** the first Watch preflight disconnected before any
device write. After the owner woke/unlocked the devices, fresh identity, developer
service, lock-state and baseline checks passed. Each device received exactly one
installation, with independent final version and running-process verification.
All 18 protected service PIDs and existing Pi pane identities were preserved.
Build 240 is the exact retained rollback. No backend service or Pi session restarted.
Physical swipe feel and accessibility acceptance remain pending owner review.

Private evidence: `20261002T171632Z-build241-page-motion`.

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
