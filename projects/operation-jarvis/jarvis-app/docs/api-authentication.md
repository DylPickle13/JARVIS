# History access — existing dashboard authorization

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
