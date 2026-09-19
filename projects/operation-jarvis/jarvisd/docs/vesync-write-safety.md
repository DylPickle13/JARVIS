# VeSync mutation and observation boundary

## Reviewed behavior

The installed stack is **pyvesync 3.4.2 / aiohttp 3.14.3**. No dependency is
installed or modified by this change. Fifteen relevant SDK/HTTP source files are
fingerprinted in `air-purifier/air_purifier/write_safety.py`. Version/source drift
rejects writes until deliberately reviewed; these checks are compatibility
tripwires, not signed attestation against arbitrary in-process code.

The reviewed `VeSync._api_response_wrapper` reauthenticates after a token error
and recursively resends the original request, including mutations. aiohttp also
follows redirects by default; HTTP 307/308 can repeat a POST. Both behaviors are
reproduced against synthetic loopback peers in the SDK gate.

The SDK also optimistically changes local state after acknowledgements, while
`get_details()` can silently return after malformed/incomplete status data.
`update()` returning `None` alone does not prove a new observation. Raw discovery
strings can also be truthy (`bool('off')`), affecting SDK no-op decisions, and a
zero timer observation does not clear the SDK's optimistic timer on its own.

## Implemented write scope

- Existing Vital 200S model allowlist and exact `VeSyncAirBaseV2`/`VeSync` classes
  only; unknown device families, custom sessions/methods and operations fail
  closed. No new public commands or device capabilities are added.
- A **device-local manager view** runs the reviewed unbound SDK API method with
  guarded dispatch. Token rejection raises before reauthentication or replay.
  Calling the original bound method here would bypass the recursive-call guard.
  SDK objects use slots; no global SDK methods are patched.
- At most one mutation API entry and one POST to the captured regional bypassV2
  endpoint. The request must match the selected/admitted CID, device ID, and
  exact existing setting payload. Attempts are consumed before awaiting; failure
  or cancellation never refunds them. Extra calls and swallowed failures cannot
  be reported as guarded success.
- HTTP redirects and persistent-connection retries are disabled only during the
  mutation. The SDK-owned session cannot have injected middleware, trace hooks,
  or an externally supplied client. The manager and HTTP attributes are restored
  on every normal/exception/cancellation exit, before verification reads.
- Recognized SDK no-ops may submit zero requests. Power/display/light-detection
  writes get a validated pre-read so skip decisions do not use raw discovery
  fields. An ambient-light skip is not accepted when the configured switch differs.
- Toggle observes first, performs one desired-state mutation on that same target,
  then checks the resulting expected state. It can still race another controller.
- Clear-timer preparation requires a valid timer observation; a failed read can
  no longer be swallowed before deleting a cached timer ID.

The public CLI uses this controller too, but remains outside daemon admission.
The existing daemon identity, cache-revision and uncertain-outcome barriers remain
required. No API route/JSON field, outer command deadline, or permission changes.

## Observation and backoff

Write preparation/verification requires a complete successful status response,
not an optimistic SDK value. Timer zero clears a stale local timer. Valid but
not-yet-matching observations retain the existing `verification_pending` contract;
malformed/error responses propagate uncertainty without another mutation.

Ordinary status/status-all reads for the known Vital 200S models now require a
new SDK response object and a valid model payload too, so later daemon polling
cannot release uncertainty using silently rejected data. Batch failures remain
per-device and sanitized. Other model read paths are unchanged. Ordinary reads
are not subjected to the write-version admission gate and retain SDK token
recovery; read scheduling, session serialization and cooldown policy are unchanged.

JSON rate limits preserve account-wide backoff. The guarded API path also maps
this pinned SDK's otherwise unstructured HTTP 429 exception to its rate-limit
exception so the existing backoff can see it. No cooldown bypass or scheduled
retry is added; explicit read recovery remains the existing owner-requested path.

## Limits and deployment

This bounds application-request submissions on reviewed paths. It does **not**
prove exactly-once cloud/device execution, packet-level at-most-once delivery,
remote cancellation, immutable catalogue identity or global serialization. It is
not a physical-device, real-login/region-handshake or cloud acceptance test.
Credential recovery before writes and during reads remains separate. Other
families/integrations need their own review. SDK read recovery and stdout/process
shutdown remain bounded by the existing outer worker deadline, not a new guarantee.

Deploy the complete frozen backend with the existing four vendor controller/CLI
files **and** `air-purifier/air_purifier/write_safety.py`. Install the helper before
the purifier controller. Retain the original files and record whether the helper
previously existed. Rollback restores the old controller before removing a newly
introduced helper, and keeps current event/configuration history. No SDK files,
private settings, app installations, or unrelated services are touched.

Required hardware-free gates:

```bash
PYTHON="$PWD/.venv/bin/python" jarvisd/verify.sh
jarvisd/verify-kasa-sdk.sh
jarvisd/verify-vesync-sdk.sh
```

Set `JARVIS_TEST_VENDOR_ROOT` for staged vendor sources;
`JARVIS_TEST_VESYNC_PYTHON` selects an existing vendor interpreter. The SDK gate
blocks discovery, DNS, external connections, and private configuration/auth-file
access. Only synthetic loopback peers receive simulated mutations. Tests cover
replayed token/redirect regressions, all existing settings, independent API/HTTP
budgets, cancellation/timeouts, drift/identity rejection, no-ops, restoration,
backoff, read recovery, malformed observations and controller/session integration.

Remaining convergence gates: explicit client outage/maintenance and write-ownership
policy, separately approved physical acceptance, and scoped credentials/auditing
before sensitive integrations. Neither SDK guard is a new permission boundary.
