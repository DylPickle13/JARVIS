# JARVIS app code audit — 2026-10-20

**Follow-up:** see [remediation, verification and deployment status](audit-remediation-2026-10-20.md). Build 268 is installed and verified on both iPhone and Watch. No terminal-server restart was performed by this work. The assessment below records the original baseline.

## Executive assessment

**Six actionable findings: one high-priority security issue and five medium-priority security/reliability issues.** Five were reproduced against production code in isolated fixtures; credential replacement was confirmed by source inspection, without inducing failures in a real credential store. This is not a clean bill of health or evidence of an existing compromise.

The strongest existing safeguards are the fixed terminal targets, explicit SSH host trust, Watch certificate pinning, closed device-command surfaces, conservative uncertain-write handling, protected attachment staging, and substantial offline tests. The main weaknesses are inconsistent redirect policy, unbounded terminal HTTP connection lifetime, and lifecycle/receipt handling that lacks the generation discipline already used elsewhere in the app.

### Scope and method

- Baseline: Git commit **`debb4da`**, project build **267**; operational checkout initially clean.
- Scope: `jarvis-app` iPhone/Watch hosts, JARVISKit, both widget extensions, host prompt/configuration code, SSH/attachment/maintenance/push transports, terminald, build/deployment scripts, manifests and dependency configuration. Relevant backend contracts were cross-checked; the backend's offline suite was also run. This is not a separate exhaustive audit of all Operation JARVIS components.
- Repository-wide inventory covered **269 tracked app files**, including **167 Swift files**. Manual review concentrated on trust boundaries, command admission, concurrency, persistence, lifecycle and failure paths; tests/builds provided broader coverage. No claim of formal verification or exhaustive review of every visual branch.
- Testing used a Git-archive snapshot under `/tmp/jarvis-app-audit.s0cMG3`, synthetic credentials, disposable loopback servers, injected APIs and a newly created iPhone simulator. Production application source was not edited. The two additional native regression tests and network reproductions exist only in the isolated snapshot.
- No physical-device installation, live household command, service restart, credential inspection/rotation, or production load/security probe was performed. The audit-created simulator was removed after testing.
- Toolchain: Xcode **27.1**, iOS simulator **26.5**. Swift dependencies remained pinned to the checked-in resolution.

## Findings

### F1 — High / P1: API-token header follows cross-origin redirects

**Location:** [`JarvisClient.swift:203–233`](../JARVISKit/Sources/JARVISKit/JarvisClient.swift), ordinary read methods around lines 364–378.

`makeRequest` adds `x-jarvis-token`, but `perform` supplies the redirect-refusing delegate only for `deviceWrite` or explicitly `refuseRedirect` requests. Ordinary authenticated state, health, jobs and other reads use URLSession's default redirect handling. This custom header is not protected by the special handling normally associated with the standard Authorization header.

**Reproduction:** A disposable loopback server returned a 302 from `/api/v1/state` to a second origin on another port. The real `JarvisClient.state` followed the redirect, and the second origin received the synthetic `x-jarvis-token`. The resulting state response was accepted.

**Impact/preconditions:** When a nonempty API token is configured, a redirecting endpoint, misconfigured intermediary, or attacker able to alter an unencrypted HTTP response can send that credential to an unintended origin. This audit did not inspect installed tokens or establish that any real token has leaked. The documented current trusted-network/tokenless policy reduces this particular credential exposure today; it does not make the client safe for token-authenticated use.

**Fix:** Refuse redirects consistently for the API, including discovery probes, or enforce an explicit same-origin redirect policy that never forwards credentials across origins. Do not weaken the existing device-write redirect refusal. Treat authenticated transport and endpoint identity as a separate hardening decision; changing the owner's auth mode is not part of this audit.

**Required regression:** Real URLSession tests for cross-host/port and scheme-changing redirects, with a synthetic token and a receiver proving it received no credential.

### F2 — Medium / P2: Terminal HTTP connections have no post-handshake deadline or worker bound

**Location:** [`terminald/jarvis_terminald.py:794–849`](../terminald/jarvis_terminald.py), authorization at lines 892–904, request-body reads at lines 1019 and 1048.

The threaded server bounds TLS handshakes, then explicitly calls `connection.settimeout(None)`. HTTP headers, keep-alive reads and request bodies can subsequently block indefinitely. `ThreadingHTTPServer` has no application-level worker/admission cap here. CIDR and bearer checks occur only after the HTTP request has been parsed, so they do not protect against incomplete headers.

**Reproduction:** Four TLS connections to an isolated instance of the actual server completed the handshake and sent incomplete HTTP headers, without credentials. All four request workers remained blocked after the five-second handshake deadline had elapsed. The sockets were then closed; no saturation or live-server test was attempted.

**Impact/preconditions:** Any client that can reach the listener can accumulate workers/sockets without authenticating. A malicious or malfunctioning peer can exhaust resources and make the terminal relay unavailable. The source defaults to `0.0.0.0`; actual firewall/Internet reachability was not tested.

**Fix:** Add bounded connection admission and total header/body/idle deadlines; reject disallowed source addresses before expensive request handling. Preserve legitimate long-poll and speech-processing durations. A per-read activity timeout alone is insufficient against indefinitely slow trickle traffic.

**Required regression:** Unauthenticated partial headers, authenticated partial bodies, idle keep-alive connections and worker-cap tests, alongside the existing valid long-poll/speech tests. The current TLS test explicitly expects the timeout to be reset to `None`, so that contract needs revision.

### F3 — Medium / P2: Watch terminal POSTs can be redirected and transmitted twice

**Location:** [`WatchTerminal.swift:281–324`](../JARVISKit/Sources/JARVISKit/WatchTerminal.swift), `send` at lines 542–577 and `sendToNewSession` at lines 622–654.

The certificate-pinning delegate implements trust handling but not HTTP redirect refusal. The terminal client's POST methods therefore retain default URLSession behavior, despite their explicit one-attempt/no-replay contract.

**Reproduction:** Using the production pinned client, a disposable HTTPS endpoint with a matching synthetic certificate returned a 307 for `/v2/terminal/input`. The client issued a second POST to `/capture-input` with the identical input body, accepted its matching acknowledgement, and returned success.

**Impact/preconditions:** An unexpected redirect from the trusted endpoint can retransmit a prompt or terminal input outside the selected route. This is not evidence that an arbitrary unauthenticated attacker can defeat certificate pinning. Server-side deduplication may help in some cases, but is not a substitute for client-side refusal, especially across routes/services.

**Fix:** Implement task-level redirect refusal for every terminal request, particularly input and new-session POSTs. Surface an unconfirmed outcome without automatic resubmission.

**Required regression:** Real HTTPS 301/302/303/307/308 fixtures proving that no second input POST is emitted. Keep certificate-mismatch and exact session/request acknowledgement checks.

### F4 — Medium / P2: Settled Home automation receipts can permanently disable controls

**Location:** [`JARVIS/AppState.swift:659–686`](../JARVIS/AppState.swift); duplicated logic in [`WatchConnectView.swift:587–622`](../JARVISWatch/Views/WatchConnectView.swift).

`homeAutomationReceipts` retains the last locally submitted receipt indefinitely. `isHomeAutomationBusy` treats any mismatch between that saved request ID and the backend's current operation ID as busy, regardless of whether the local request already settled. There is no retirement path for these receipts.

**Reproduction:** An injected-API native test submitted a Home command, then published its matching verified operation; the control correctly became non-busy. Publishing a later verified operation with another request ID made it busy again, despite fresh authoritative state. The added regression test fails on the current code.

**Impact:** After a successful change on one device, a subsequent change from another client can leave Voice/Barn Door controls disabled in the first app for the remainder of that model's lifetime. Further refreshes cannot repair it because the retained request ID is still compared against the newer operation.

**Fix:** Track outstanding rather than historical receipts. Retire a receipt after observing its corresponding terminal outcome, and permit later authoritative operations to replace settled state. Preserve conservative handling of genuinely pending or unconfirmed changes; do not introduce automatic write retries.

**Required regression:** Own pending → own verified → peer pending → peer verified, backend restart/operation absence, rejected/unknown outcomes, and endpoint changes. Exercise both phone and Watch policies, preferably through one shared policy type.

### F5 — Medium / P2: Cancelled discovery overwrites the phone's newer connection state

**Location:** [`JARVIS/AppState.swift:423–469`](../JARVIS/AppState.swift), cancellation/reset at lines 1260–1280.

`performRefresh` does not check cancellation or an owner generation after awaiting discovery. Production discovery represents cancellation by returning `nil`; the caller interprets that as a genuine connection failure and publishes an error. The success branch also lacks a post-await ownership check before storing the endpoint and publishing health.

**Reproduction:** A native test started discovery, called `clearConnection`, and allowed the cancelled discovery to return `nil`. The app changed from the explicitly reset `.idle` state to `.failed` and displayed “Could not reach jarvisd…”. The added regression test fails on both assertions.

**Impact:** Reset, backgrounding or overlapping connection attempts can publish stale failure/status information after the owning operation has been cancelled. This differs from the already generation-protected history and oMLX models.

**Fix:** Add refresh ownership/generation checks after each suspension and before endpoint/status publication. Cancelled discovery must return without modifying state. Protect cleanup such as `isRefreshing = false` from retiring another operation's loading indicator.

**Required regression:** Cancel during discovery and health; reset during discovery; older failed attempt completing after a newer successful connection; foreground/background transitions.

### F6 — Medium / P2: Credential replacement deletes the working secret before the replacement is secured

**Locations:**

- [`PiTerminalSettings.swift:68–76,147–159`](../JARVIS/Terminal/PiTerminalSettings.swift)
- [`JARVISTerminalConfigurationStore.swift:61–74`](../HostAppIntents/JARVISTerminalConfigurationStore.swift)
- [`EndpointStore.swift:89–101`](../JARVISKit/Sources/JARVISKit/EndpointStore.swift)

All three credential writers call `SecItemDelete` followed by `SecItemAdd`. If deletion succeeds and insertion fails, the previous working credential is lost even though the save operation reports failure. The SSH settings writer additionally changes persisted host/port/username before attempting the password write, so failure can leave persisted routing different from the in-memory settings still displayed.

**Evidence:** Source-level failure-path confirmation. No real Keychain was modified to force this condition. Existing success-path tests do not establish rollback safety.

**Impact/preconditions:** Storage/security-service failures or a protection-state transition during save can turn a rejected update into lost API/SSH/terminal access. Error reporting alone does not preserve the previous configuration.

**Fix:** Use `SecItemUpdate` for existing items and add only on `errSecItemNotFound`; retain the old item on other errors. Commit associated defaults only after credential success. Propagate deletion failures rather than reporting unconditional success. The push installation-ID writer already demonstrates the update-first pattern in [`PushNotificationCoordinator.swift:355–375`](../JARVIS/PushNotificationCoordinator.swift).

**Required regression:** Injectable Keychain operations covering failed update, failed insert, failed delete and protected-data unavailability, verifying that previous secrets and associated settings remain intact.

## Verification results

| Check | Result |
|---|---|
| Shared Swift package, baseline | **374 cases: 371 passed, 3 expected live-test skips** |
| terminald, including real isolated TLS/tmux fixtures | **39 passed** |
| Host prompt runtime | **11 passed** |
| Copy-refresh script | **12 passed** |
| Siri/room Node tests | **10 passed** |
| Watch Talk source contracts | **Passed** |
| Backend offline `verify.sh` | **1,021 passed**, plus Python/LaunchAgent syntax checks |
| Neural Core offline rendering | **2,316 assertions passed** |
| iOS simulator build, including embedded Watch/widgets | **Passed** |
| Standalone Watch simulator build | **Passed** |
| Native iOS suite, including two audit-added tests | **215 cases: 212 passed, 3 failed cases** |
| Network reproductions | Cross-origin token forwarding and duplicate redirected POST reproduced; four unauthenticated workers held past handshake deadline |
| App static validation | Shell syntax; 14 Python files; 8 plist/entitlement/privacy manifests; 9 JSON files passed |

### Native failures, explicitly separated

1. **Audit-added:** `testAuditCancelledDiscoveryMustNotOverwriteClearConnection` — F5, two failed assertions.
2. **Audit-added:** `testAuditSettledHomeReceiptMustNotBlockLaterPeerOperation` — F4, one failed assertion.
3. **Existing:** `PiTerminalClipboardTests.testPlainPasteButtonRendersWithoutBlackPlatter` — already documented as excluded from earlier release runs. This audit did **not** exclude it. It failed pixel comparisons and its platter-area assertion under this simulator/toolchain. The test emits hundreds of assertion failures, but represents **one** failed test case, not hundreds of independent defects.

Thus the existing native baseline contributed **213 cases: 212 passed and one known rendering-test failure**. The two new failing cases deliberately expose previously untested behaviors. The full native test command exited nonzero; it must not be presented as a passing suite.

The first isolated Xcode build stopped at SwiftTerm build-plugin approval. The pinned plugin and its build-info generator were inspected, then the build was rerun using the repository verifier's documented `-skipPackagePluginValidation` option. That build and the standalone Watch build passed. No dependency version was changed. Build warnings included deprecated SwiftUI/WatchKit APIs, an implicit-strong-capture warning and a synchronous API advisory; no new compiler error was found.

## Other risks and maintenance observations

These are separate from the six actionable defects above:

- **Known transport/auth posture:** [`api-authentication.md`](api-authentication.md) explicitly records the owner's token-rollout reversal and trusted-network HTTP behavior. LAN HTTP does not provide application-layer encryption/server identity; Tailscale protection is route-dependent. This audit did not change that policy or establish network isolation. Any future auth/transport redesign needs explicit approval.
- **Response-size limits are post-download:** `JarvisClient.perform` checks `data.count` after `session.data` has buffered the complete response. This protects decoding, not peak memory. Consider streaming byte caps/resource deadlines, especially on Watch, and bounds for ordinary reads that currently have no response limit.
- **Test coverage gap:** Positive-path and source-text contracts are extensive, but failed credential persistence, cross-origin redirects and post-settlement cross-client behavior were missing. Add behavioral regressions rather than more grep-only guards.
- **Known rendering failure:** Repair the clipboard test's baseline/tolerance or the actual rendering issue after visual inspection. Keep any temporary exclusion explicit; do not silently treat it as passed.
- **State complexity:** `AppState` and Watch models duplicate polling, command, receipt and freshness logic. Prefer shared small policies with generation ownership, not a wholesale rewrite. `SystemHistoryModel` and `OMLXStatusModel` offer useful existing patterns.
- **Legacy deployment helpers:** Retained free-signing scripts are not evidence of current paid-signing safety. In particular, `renew-free-signing.sh` automatically retries a failed Watch install without first resolving an ambiguous outcome. They were reviewed but not executed; future reuse should reconcile them with the current deployment/unknown-outcome rules.
- **Dependencies:** Exact package versions/lockfile and build integration were checked. This was not an independent vulnerability-advisory/SBOM audit of all third-party source, and no claim is made that dependencies have no known CVEs.

## Recommended order

1. Unify redirect refusal in both network clients; add the real-transport regressions.
2. Bound terminal HTTP connection lifetime/admission without breaking valid long polls or speech requests.
3. Fix Home receipt retirement and phone refresh ownership; retain the two reproductions as regression tests.
4. Consolidate credential persistence around update-first operations and failure injection.
5. Resolve the known native rendering-test failure and add resource-bound tests.

Keep fixes in small, separately verified changes. No deployed service, authentication mode, credential, household control or installed app should change merely because this report exists.

## Evidence and limitations

Local evidence is retained at **`/tmp/jarvis-app-audit.s0cMG3/`**: baseline/test/build logs, `native-tests.xcresult`, the isolated source snapshot with audit-only tests, `reproduce-network.py`, `redirect-reproduction-summary.json` and `slow-client-summary.json`. These temporary artifacts are not committed and may be removed by normal temporary-directory cleanup. The durable findings are this report.

No physical iPhone/Watch UI, background radio behavior, battery/energy profile, APNs delivery, real credential-failure transition, firewall exposure or live device acceptance was tested. The top-level compound verifier was not run as a single command; the component checks listed above were run explicitly. No claim is made about unlisted suites. Simulator and fixture success do not establish live-device or household-control acceptance.
