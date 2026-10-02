# Terminal recovery and completion-notification taps — build 239

Build **239** was installed once on each approved physical iPhone and Watch, with
independent installed-version, launch and running-process verification on
**2026-10-02 at 12:15 EDT**. It includes the [navigation/Home changes](navigation-and-home.md).
Actual notification taps, tab gestures and Crown behaviour still need owner acceptance.

## Terminal outage and recovery

The old terminal bridge was alive but its listener thread was stuck reading an
unfinished TLS handshake. Read-only sampling showed `ssl3_accept` →
`ssl3_get_client_key_exchange` → socket `read`; authenticated health requests could
not complete. The dashboard service remained healthy. An owner-approved bridge-only
restart restored authenticated health without replacing Pi sessions or credentials.

The durable correction in `terminald/jarvis_terminald.py` keeps the listener socket
as plain TCP and performs TLS setup on each request's worker thread. Setup has a
**five-second timeout**. Failed/partial handshakes are closed without reaching the
HTTP handler. Once setup succeeds, the temporary socket timeout is removed, so
existing HTTP polling/input semantics remain unchanged. TLS version minimum,
certificate, private key, bearer token, trusted CIDRs and authorization checks are
unchanged; a plain HTTP connection cannot bypass TLS.

The separately approved backend rollout uses an immutable runtime release under
`~/Library/Application Support/JARVIS/terminald/releases/`, rather than a temporary
app build directory. Only the terminald LaunchAgent's executable-script location
and working directory changed; its original plist and code remain available for
rollback. The service was activated once, then its process command and authenticated
health were checked. Existing Pi pane/session process identities and credential
hashes matched before/after. No terminal input, Pi restart or provisioning reset
was used for verification.

## Repeat notification taps

Both platforms used the same process-local inbox, which retained the last 64
notification identifiers even after navigation completed. An explicit repeat tap
on a retained alert was therefore discarded. This is a confirmed code defect;
without the original tap/session details, it is **not proof that it caused the
owner's particular notification failure**.

`PiTerminalNotificationInbox` now retains only the pending action:

- Duplicate callbacks coalesce while that action is being routed.
- Completing or superseding it releases the identifier for a later explicit tap.
- Each accepted action has a fresh UUID, so SwiftUI can observe reopening the same
  alert and an older completion cannot consume a newer action.
- Both phone and Watch coordinators consume/cancel the shared inbox consistently.
- The fixed route/version and session allowlist (1–9) remain unchanged. No payload
  schema, APNs provider, credentials, Jobs results or input-delivery policy changes.
- A tap only requests local navigation; terminal input is never automatically sent
  or replayed. Being offline does not itself prohibit selecting the destination.

No synthetic push alert or historical notification backfill was sent during this work.

## Verification and retained evidence

- **285 shared-package tests**, 3 expected live-test skips, no failures.
- **149 iPhone tests passed**; the previously documented unrelated
  `testPlainPasteButtonRendersWithoutBlackPlatter` rendering failure was excluded.
- **37 terminal-service tests passed**, including five new TLS regression tests;
  those five also passed using the production system Python interpreter.
- TLS tests use generated temporary credentials and loopback fake services. They
  prove a stalled client does not block another authenticated connection, the
  deadline closes incomplete setup, bearer authentication remains required and
  plain HTTP is rejected.
- iPhone/Watch simulator builds and the signed Release archive succeeded. All
  four app/widget bundles were audited for identities, versions, device-profile
  coverage, signatures, unchanged entitlements, nesting and payload exclusions.
- Dependency lock unchanged. Exact audited products installed once per device;
  final version/process readbacks confirmed **239** on both.
- The pre-deployment devices reported build **127**. Its deleted original binaries
  could not be retained; a signed rollback was reconstructed from the pre-change
  source and explicitly labelled as such. The older exact build-237 archive also
  remains untouched. Prepared build 238 was never installed.

Private audit/install/runtime evidence is retained in signing-renewal artifact
`20261002T160824Z-build239-navigation-recovery`. The app-install phase did not restart
services; the terminal bridge update was separately owner-approved and verified.
