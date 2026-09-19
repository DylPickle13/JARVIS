# Kasa mutation retry boundary

## Reviewed stack and findings

- Installed python-kasa reports `0.10.2`, from PR build commit
  [`dd92c05b12c9d55c0bbb7ee75a9352d5689e5f80`](https://github.com/python-kasa/python-kasa/commit/dd92c05b12c9d55c0bbb7ee75a9352d5689e5f80).
  Its reused version string is not enough to identify the reviewed code.
- Installed aiohttp is `3.14.3`.
- `IotProtocol.query` and `SmartProtocol.query` default to three retries: up to
  four submissions after a lost reply. Passing `retry_count` to device-level
  `turn_on`/`turn_off` does not configure those protocol calls.
- SMART can make extra transport calls for response pagination/multi-requests,
  independently of the outer retry count. Mutation payloads must be single,
  recognized desired-state requests; pagination must never repeat a mutation.
- Reviewed XOR/KLAP/AES send paths do not themselves retry the mutation, but
  KLAP/AES can authenticate when a session expires. Kasa's HTTP client delegates
  to aiohttp with redirects enabled by default. HTTP 307/308 can replay a POST.
- aiohttp's persistent-connection retry normally excludes POST. The guard also
  disables that connection-local flag defensively; it does not rely on the
  method exclusion alone. Reviewed request-body writing has no replay loop.

This review covers these mutation paths, not every SDK/dependency function,
firmware behavior, or all devices. Tests use synthetic crypto sessions, not real
credential handshakes or physical device acceptance.

## Implemented guard

`smart-plug/smart_plug/kasa_client.py::_single_attempt_write` surrounds only the
existing `turn_on`/`turn_off` call after pre-write authentication/status reads:

1. Check the reviewed package versions and SHA-256 fingerprints of eleven
   relevant protocol/device/transport/HTTP source files. Missing/changed audited
   sources fail closed. This is a compatibility tripwire, not signed attestation
   or a security boundary against arbitrary code running inside the process.
2. Admit exact `IotPlug`/`IotProtocol` with XOR/KLAP/KLAP-v2, or exact
   `SmartDevice`/`SmartProtocol` with AES/KLAP/KLAP-v2. Child wrappers, other device
   classes, custom power/protocol methods/transports, and other mutation payloads
   fail closed. The existing HS103 fleet uses the admitted IOT path; unreviewed
   device families must not silently inherit this policy. No capability is added.
3. Permit one matching power query with `retry_count=0` and one transport send.
   Each attempt is consumed **before** awaiting it. A lost response, timeout,
   authentication/retryable error, or cancellation never refunds that attempt.
4. For HTTP, require an already established, unexpired SDK-owned session with
   no injected HTTP client, middleware, or trace hooks. Permit one POST to the
   captured mutation endpoint, disable redirects and persistent-connection
   retries. If the session expires during dispatch, an attempted handshake is
   blocked by the endpoint check, not followed by reauthentication and replay.
5. Restore all instance attributes on success, failure, and cancellation before
   normal verification reads. Nothing is patched globally. Other connections
   and read retry policy are unchanged. Missing or swallowed query completion
   cannot be reported as a successful guarded submission.

Toggle uses the same pre-read connection and this guard for its one desired-state
mutation. Public CLI/tool callers using this controller also get the SDK guard,
although they remain outside daemon admission and lack its admitted identity.

## Limits and maintenance

- This bounds application-request submissions on the reviewed paths. It does
  **not** prove exactly-once device execution, packet-level at-most-once delivery,
  cancellation at the device, global serialization, cryptographic identity, or
  protection against another controller. Daemon uncertain-state barriers remain.
- VeSync SDK/transport retries are a separate unfinished review. Do not infer
  equivalent guarantees for purifier, Cast, security, or future integrations.
- Unknown SDK versions, changed audited files, unsupported device protocols, or
  nonstandard sessions reject writes. Reads remain available with their existing
  behavior. Do not fall back to an unguarded controller or automatically retry.
- Requirements currently reference a moving Kasa PR. A reinstall can change
  reviewed source hashes without changing `0.10.2`. Dependency updates require
  maintenance, a source review, both test gates, and deliberate acceptance of
  new hashes; never regenerate them blindly to bypass a failing guard.
- No SDK installation or site-packages edit is part of this change. Retain the
  four matching vendor source files with the frozen backend and rollback record.
  Physical write acceptance needs separate approval.

## Hardware-free acceptance gate

Run both from the operation root:

```bash
PYTHON="$PWD/.venv/bin/python" jarvisd/verify.sh
jarvisd/verify-kasa-sdk.sh
```

During staging, set `JARVIS_TEST_VENDOR_ROOT` to the candidate operation root.
`JARVIS_TEST_KASA_PYTHON` can identify an existing reviewed vendor interpreter;
no package is installed automatically. The SDK gate intentionally fails if the
interpreter or reviewed dependency sources are unavailable.

`tests_sdk/test_kasa_no_replay.py` uses real SDK methods with synthetic loopback
TCP/HTTP peers. It blocks discovery, UDP, DNS, non-loopback connections, and
private settings loading. Cases cover the unguarded four-attempt regression,
all admitted protocol/transport pairs, response loss, timeouts/cancellation,
retryable/auth errors, 301/302/303/307/308 redirects, extra query/send/POST paths,
SMART pagination, source/version drift, unknown paths, instance restoration,
unchanged read retries, and controller-to-real-SDK integration. Backend adapter,
identity, admission, and cache-barrier tests remain a separate SDK-free suite.
