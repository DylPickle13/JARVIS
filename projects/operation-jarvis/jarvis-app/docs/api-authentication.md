# History access — existing dashboard authorization

## Owner-requested token rollout reversal — 2026-10-06

Earlier enrollment/token-mode work is undone, not resumed. Installed build 259
restores pre-enrollment app/client/Watch behavior while preserving loaded-model
visibility. Provisioning, bound-configuration discovery and token transfer are
removed. Source tests use synthetic stores only.

An explicit action on each installed device removes only added account
`jarvis.api.configuration.v1` in service `com.operation-jarvis.app`, then verifies
absence without requesting credential data and removes `jarvis.api.enrolled.v1`
from that target's defaults. Locked/failed deletion or uncertain absence does not
clear the marker or claim success. Legacy `jarvis.api.token`, endpoint, saved SSH,
widgets and backend API/event/local-control credentials are preserved. No automatic
cleanup, Keychain reset, rotation or remote credential inspection. Installation
is independently verified. The owner reported a removal success on an unspecified
device, then **deferred unused Watch-record cleanup** after its removal-screen
relaunch failed before any app restart. Do not count both Keychains as cleared.
No cleanup/relaunch retry is pending or scheduled; future removal needs a fresh
owner request. The restored client does not read the added configuration account.

Pi Desk's exact preceding helper/tests are restored and 202 tests passed. The
initial rollback stopped before writes/signals on an outdated backend baseline;
that failure is retained. Fresh owner approval and verified picture-frame-health
baseline allowed a new scoped helper rollback and one existing-child reconnect at
16:39 EDT. Ten fresh sanitized sessions, unchanged supervisor/viewers/agents,
manifest entries and all 18 service records were verified. No failed helper was
replayed. The restored runtime uses the original tokenless trusted-network read.
Backend token mode was never activated. Trusted-network policy and pre-existing
credentials remain unchanged. LAN HTTP lacks transport encryption; Internet
exposure/isolation has not been established. Future hardening needs a fresh request.

## Existing history policy


The owner explicitly requested removing history's additional token setup. The
uninstalled provisioning experiment is superseded and removed from active source;
its test evidence remains archived. No production credentials were exported,
transferred, injected, removed or rotated.

History now uses the same endpoint and API authorization policy as cached state:

- **Trusted-network mode:** the existing allowed source networks can read history
  without a token. Untrusted sources remain denied, even if they provide a token.
- **Token mode:** the existing configured API token remains required, exactly as
  for the dashboard. No new history-specific credential or setup is introduced.
- Unapproved origins and ambiguous duplicate token headers remain denied.

The app no longer preemptively blocks history merely because its endpoint token
is empty. It sends the existing token if available, otherwise omits the header
and lets the backend apply its configured policy. HTTP 401/403 displays a generic
backend access denial without changing current controls, discovery or auth mode.

No Keychain/token setup UI, file export or new Watch credential relay is shipped.
The one-hour Watch timeline still requires a direct route to the existing backend,
not the phone-state relay. Existing visibility, background, Always-On and detail
cover gates, 60-second single-flight polling, bounds, timeout and redirect refusal
are preserved. Historical reads remain cached/database-only and never poll devices.

Validation includes tokenless phone and Watch polling/request construction,
production AppState endpoint-provider use without a credential fixture override,
and backend HTTP tests for allowed/disallowed networks, token mode, duplicate
headers and origins. Physical layout/gesture acceptance remains owner review.
