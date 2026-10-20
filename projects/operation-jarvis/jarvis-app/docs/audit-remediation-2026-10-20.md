# Audit remediation — 2026-10-20

Follow-up to the [code audit](code-audit-2026-10-20.md), against baseline `debb4da` (build 267). The initial source remediation made no build-number change. Signed **268** was then prepared without installation. Later authorized attempts installed and independently verified **268 on both iPhone and Watch**, with final version readbacks at **16:24 EDT, October 20**. The Watch-only completion did not reinstall or relaunch the already-updated iPhone. No terminal-server restart, live household command, credential replacement or authentication-policy change occurred. App deployment is complete; restarting terminald still requires separate approval.

## Changes

| Finding | Remediation |
| --- | --- |
| F1: API redirects could forward a token | Refuse redirects for every API request, including reads and discovery. A failed read can still recover through configured endpoint candidates; a redirect's `Location` is never adopted. |
| F2: unbounded terminal HTTP connections/read time | Admit at most 32 connections before TLS/thread creation; reject untrusted sources before TLS. Use absolute 15-second header/body deadlines, including idle keep-alive expiry, so trickled bytes cannot extend them indefinitely. Cancel read deadlines before application work; retain a separate 180-second socket-write budget for speech. |
| F3: terminal redirects could repeat POST input | Preserve certificate pinning and refuse redirects. Redirected submissions report unconfirmed delivery, without following or replaying the POST. |
| F4: settled automation receipts could revive a busy control | Share receipt reconciliation between phone and Watch. Retire receipts after a fresh, matching `verified`, `unknown` or `rejected` observation. Later peer operations cannot resurrect that retired local busy marker. Unmatched/pending receipts remain conservative; backend busy and freshness checks are unchanged. |
| F5: cancelled refresh could overwrite reset/newer state | Give connection refreshes, state requests and connection-loop cleanup generation ownership. Propagate cancellation, ignore late discovery/health/state completions and clear loading flags when retiring work. |
| F6: failed replacement could delete working credentials | Use a shared injectable update-first Keychain helper. Add only on `errSecItemNotFound`; never delete/reinsert as a replacement fallback. Commit connection/SSH settings only after persistence succeeds. Failed removal does not reset a working connection. Surface persistence errors in existing settings. |

## Safe recovery, not blind retries

The phone and direct Watch command paths may make **one passive cached-state read** after an uncertain plug/purifier result. No command, terminal input, cloud/device write or endpoint-changing write retry is added. Definite denials do not trigger reconciliation.

A read confirms success only when the desired state matches, the relevant observation is usable and timestamped at or after dispatch, and purifier verification is complete. Otherwise the outcome stays unconfirmed. Reads do not silently reinterpret a pre-command cached value as proof that the write succeeded.

Normal screens, gestures, session identity, credential names/accessibility, approved endpoints and the owner-requested trusted-network authentication posture remain unchanged. These are recovery/hardening changes, not enrollment or an authentication rollout.

## Verification

The compound verifier completed successfully with `JARVIS_SKIP_NATIVE_BUILDS=1`; native testing/builds and artwork rendering were run separately. No claim is made that the unfiltered native suite is green.

| Check | Result |
| --- | --- |
| Backend / separate scheduler pass | 1,021 / 116 tests passed (component counts, not a deduplicated total) |
| terminald | 46 tests passed, including read deadlines, TLS admission and legitimate slow processing |
| JARVISKit | 382 cases: 379 passed, three expected live-test skips |
| Real HTTP/TLS transport | Six tests passed; all five redirect statuses covered |
| Native iPhone simulator | 220 selected tests passed; the known paste-button rendering case was explicitly excluded |
| Standalone Watch simulator build | Passed |
| Prompt / copy-refresh / Node / quota checks | 12 / 12 / 10 / 13 passed |
| Neural Core native rendering | 2,316 assertions passed |

The final native run used a new isolated iPhone 11/iOS 26.5 simulator, pinned dependencies, unsigned builds and `-skip-testing:JARVISTests/PiTerminalClipboardTests/testPlainPasteButtonRendersWithoutBlackPlatter`. An earlier included run reproduced that known rendering failure and exposed reset-test reliance on simulator Keychain permissions; the reset fixtures now use injected synthetic Keychain operations and both regressions pass. The earlier result-collection stall was stopped only in the audit-owned Xcode process; the final run exited successfully.

The reviewed changes were integrated into the working checkout and byte-compared with the verified candidate. The 46 terminal tests, six real-network tests and artwork renderer also passed from the working checkout. `git diff --check` passed. No commit or deployment was performed at that source-verification stage.

Original evidence directory: `/tmp/jarvis-app-fixes.In1OWL/`. After owner-approved cleanup it is preserved as the verified private archive `owner-stale-cleanup-20261020/jarvis-app-fixes.In1OWL.tar.gz` in the 268 artifact; the temporary copy was removed. Selected logs and the final native xcresult also remain directly accessible under `prior-validation/`. Tests use isolated simulators, synthetic credentials, fake device backends and loopback HTTP/TLS fixtures. The real-transport fixture checks 301/302/303/307/308 refusal, no requests to the unapproved origin, no terminal POST replay, approved read recovery and wrong-certificate rejection.

Verification maintenance also updates the Keychain source contracts to inspect the shared helper, runs the new real-network tests, and corrects a pre-existing stale Claude interval assertion from 60 to the backend's already-existing 120 seconds. No quota timing changes are made.

## Preparation — build 268 signed without installation

After initially approving deployment, the owner changed the instruction to **“ok just prep for deployment, i have to head out now”**. At that preparation stage, the release plan explicitly denied physical deployment, with no authorized installation targets, installation-authorization file or installer attempt. No further physical-device queries were made until the owner later renewed approval.

The frozen **277-input** candidate byte-matches the verified remediation code. Fresh release checks passed: **220 selected native tests**, **382 shared cases with three expected live skips**, **46 terminal tests**, **six real-network tests**, **2,316 render assertions**, both simulator builds and the signed Release archive. The same known paste-button pixel case remains the sole native exclusion; no new exclusions were added. All eight candidate/267-rollback signatures, byte-identical provisioning profiles, unchanged entitlements/dependency lock and source/payload seals passed. Existing paid-team signing was reused without portal/provisioning updates.

Private artifact: `20261020T155300Z-build268-audit-remediation` under the signing-renewal artifacts directory. It retains the exact signed 268 archive, frozen source, logs, xcresult, render evidence and durable copies of the earlier audit verification. Exact signed **267** remains rollback. Installation must use this audited archive, not a rebuild.

Read-only preparation also found that the active backend has advanced beyond the backend reference retained with 267. The historical preservation helper is explicitly blocked: reconcile it against the then-current backend before any future installation, rather than bypassing the mismatch. No live service/configuration was changed. Fresh owner approval and both-device/immediate identity, pairing, DDI, unlock, transport and installed-version checks remain required. Physical behavior is not accepted by simulator tests. The terminal-server hardening has not been activated by this work.

These post-preparation notes do not modify the frozen candidate. No commit, app installation or service restart was performed during that preparation stage.

## Subsequent deployment attempt — stopped before writes

Fresh owner **“my devices are connected now, proceed”** authorized a guarded attempt. The backend preservation baseline was reconciled read-only against the actual autonomous-recovery service: 615 source files, 25 configuration fingerprints, and two reviewed existing-device host-address changes. Authenticated readiness, fresh service cache and ten-second history cadence passed; no backend/configuration writes occurred.

At **16:09 EDT, October 20**, the initial Watch identity query reported paired but a **disconnected developer tunnel**. CoreDevice returned best-available/cached details because a connection could not be established. The attempt stopped before Watch DDI/unlock/version queries or iPhone preflight: **zero installs and zero launches**. No reset, retry, terminal input or restart occurred. Post-stop checks preserved all 18 protected service records (17 continuous), existing Pi/Minecraft identities and source/configuration/authentication, and reverified both signed payload seals.

The attempt is closed and its authorization consumed; fresh owner readiness and all current-baseline/device gates are required for a distinct future attempt. Neither installed version was queried during this stopped attempt. Evidence: `deployment/result.json`, `deployment/watch-initial-identity.json` and `deployment/stop-review.json` in the retained 268 artifact. Do not replay the stopped helper.

A separate owner-authorized **“ready”** attempt at **16:13 EDT** hit the same initial Watch developer-tunnel gate. It also stopped before DDI/unlock/version queries or iPhone preflight, with **zero installs/launches**, no reset or automatic retry, and all source/configuration/service/Pi/Minecraft preservation checks passing. Both signed payload seals remain intact. Evidence is retained separately under `deployment-retry1/`; its authorization is consumed. Further deployment requires a working developer connection and fresh approval, not replay of either stopped helper.

## Earlier partial attempt — iPhone 268 verified; Watch 267

Owner **“just try again”** authorized a distinct third attempt. At **16:16 EDT, October 20**, both devices passed fresh preflight at 267, using wired iPhone and wireless Watch. Signed **268 installed once and launched once on iPhone**, with independent installed-version and running-process verification. Watch then reported a disconnected developer tunnel at its immediate identity gate; **no Watch install or launch was attempted**.

A single independent **read-only** inventory query confirmed Watch **267 at 16:18 EDT**, without repeating installation or resetting the connection. All 18 protected service records (17 continuous), Pi/Minecraft identities, backend source/configuration/authentication and ten-second history cadence were preserved. Both retained source/payload seals passed again. No service restart, household control or terminal input occurred.

That attempt was **partial deployment**, not both-device completion. The later authorized Watch-only completion below preserved the updated iPhone and rechecked the mixed versions and all device gates; never replay a consumed installer. Exact signed 267 remains rollback. Evidence: `deployment-retry2/result.json`, `deployment-retry2/watch-independent-version-summary.json` and `deployment-retry2/partial-deployment-review.json`. Physical UI acceptance remains owner review.

## Completed deployment — build 268 on both devices

Fresh owner **“ok try again now”** authorized Watch-only work. Read-only preflights verified iPhone 268 and Watch 267, then the immediate Watch identity/DDI/unlock/transport/version gates passed. The exact signed **268 installed once and launched once on Watch**, with independent version/process verification. Final inventory readbacks confirmed **268 on both devices at 16:24 EDT, October 20**. No iPhone installation or launch was repeated.

Across all attempts, each app was installed and launched exactly once. All 18 protected service records (17 continuous), existing Pi/Minecraft identities, backend source/configuration/authentication and ten-second history cadence were preserved. Eight candidate/267-rollback signatures and both source/payload seals were independently reverified. No connection reset, transport switch, uncertain-write retry, terminal input, household control, portal/provisioning change or service restart occurred.

Receipts: `deployment-watch-retry3/result.json` and `final-deployment-verification.json`; earlier iPhone evidence remains in `deployment-retry2/`. All earlier stops remain retained. Exact signed 267 is retained for rollback; all deployment authorizations are consumed. Physical behavior still awaits owner review. **The terminal-server hardening was not activated by this app deployment; any restart requires separate approval.** The owner subsequently acknowledged completion and approved publication and scoped stale-artifact cleanup, preserving signed 268, exact 267 rollback and audit/deployment evidence. This does not authorize further device/service actions or establish exhaustive physical UI acceptance.

## Publication and retained artifacts

The source changes were committed and pushed as **`d0db9e9`**, with GitHub's `main` ref independently checked before cleanup. Owner-approved cleanup then removed only the obsolete 266 signed archive and the two temporary workspaces after fully archiving/verifying their evidence. Net allocated artifact usage fell **259.80 MiB**; observed volume free space increased **232.63 MiB**. These measurements differ because of filesystem accounting and other activity.

Signed **268** and exact signed **267 rollback** remain, with eight signatures and both source/payload seals verified. All 4,517 retained evidence files and 7,257 compressed evidence entries passed preservation checks. Older 266 source/test/deployment records and signing metadata remain; its archive has an explicit pruning marker. All protected services, Pi/Minecraft identities and backend/configuration/authentication were preserved; no device action or restart occurred. Unrelated backups were not removed. Private receipt: `owner-stale-cleanup-20261020/cleanup.json` in the 268 artifact. Do not replay the completed cleanup.

## Deployment boundary and remaining limits

- Source verification does not establish physical iPhone/Watch, background-radio, battery, APNs or live network-exposure acceptance.
- Keep the known-good installed app/server and protected deployment artifacts intact. Installation and server restart are separate approval gates.
- Do not change the documented authentication rollback, enable token enrollment or revive deferred Watch credential cleanup as part of deployment.
- The pre-existing `PiTerminalClipboardTests.testPlainPasteButtonRendersWithoutBlackPlatter` rendering failure is not fixed by this audit work and must not be reported as passing.
