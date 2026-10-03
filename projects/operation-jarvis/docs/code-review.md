# Code review and verification

Review date: **2026-10-03 EDT**. Scope: the Operation JARVIS source checkout,
existing offline suites, maintained documentation, and non-disruptive local
service checks. Historical deployment records are retained as history, not
fresh evidence that a device or release is currently installed.

## Findings and corrections

1. **High — vendor staging blocked by source drift.** The staging baseline
   preceded smart-plug DHCP recovery (`17896c9`). This caused 20 backend errors
   and prevented the delegation SDK suite from running. Comparison against the
   previous reviewed source confirmed that only `status_all` changed in
   `SmartPlugController`; power-write methods and SDK audit pins were unchanged.
   The candidate staging baseline was deliberately re-reviewed, not bypassed.
   Fenced copies now suppress automatic DHCP/catalogue recovery, preserving
   immutable ownership-bound targets. A synthetic regression verifies repeated
   failed batch reads cannot invoke recovery. The existing standalone recovery
   path remains unchanged. This does **not** activate exclusive ownership.
2. **Medium — repeated terminal fixture deadline failures.** Three asynchronous
   tests repeatedly failed with 50–70 ms long-poll deadlines. macOS condition-wait
   scheduling can exceed those deadlines even with the fake runner. Fixtures now
   allow a scheduling budget and wait for actual sampler shutdown instead of
   assuming sleep durations prove it. Production polling, input, byte ordering,
   terminal services, and protected sessions are unchanged.
3. **Medium — offline entry point omitted substantial regression coverage.**
   Default verification now includes purifier, keyboard/C++ bridge, Pi Desk,
   terminald, Android-monitor policies, departure-greeting, and documentation
   checks, plus isolated archive/doorbell SDK tests. Security, room audio, and
   presence use their full offline discovery suites rather than selected files. Missing interpreters fail explicitly;
   `JARVIS_LIVE_TESTS=0` is enforced even if inherited as `1`.
4. **Low — outdated current documentation.** Corrected keyboard paths and away
   lighting, tool-group names/count, Mac room-audio roles, current app navigation,
   Watch widget inventory, historical versus current health UI, security feature
   coverage/commissioning, and inaccurate legacy-client removal wording. Added
   local Markdown target checks and verifier regression tests. Private archives
   and ignored runtime files are excluded; external URLs and heading anchors are
   not certified by this check.
5. **Medium — failed candidate drain silently discarded its error.** A return
   inside `finally` erased exceptions from `begin_drain()` after a readback-loop
   failure. The candidate now surfaces an incomplete drain. A regression proves
   admission is still revoked, the stop flag is set, ownership remains held,
   and no effect is replayed. This path remains uninstalled, not a live-service fix.
6. **Medium — native verification stopped on retired source contracts.** Updated
   checks for the system-health projection, authenticated bounded oMLX GET helper,
   static health card, five-tab navigation, shared status colours/Pi motion,
   shared session-indicator gaps, incremental ANSI parser, passive state reads,
   directional page transitions, and fixed Session 10 Talk routing. Assertions now
   validate current behavior rather than retired source spellings. No native app
   behavior was changed to appease the verifier.

## Verification

The corrected working tree passed the following checks; it is **not** an installed
or signed release artifact.

| Check | Result |
|---|---|
| Broad offline Python entry point | 2,138 test executions; zero failures, 3 interpreter-specific skips |
| JARVISKit Swift package | 290 tests; zero failures, 3 opt-in live-test skips |
| Native verifier, isolated source copy, `JARVIS_SKIP_NATIVE_BUILDS=1` | Passed, including source contracts, terminal/scheduler tests and 10 Node tests |
| iOS and watchOS generic simulator Debug builds | Both succeeded with `CODE_SIGNING_ALLOWED=NO`; no simulator boot or installation |
| Maintained Markdown documentation | 92 files, zero missing local inline link targets |
| Python/shell/Node syntax, JSON and plist validation | Passed; no tracked Python compile warnings |
| Installed dependency compatibility | Eight existing Python environments passed `pip check`/`uv pip check`; no installation or upgrade |
| Standalone Android presence policy | 20 Java assertions passed |

The three security skips belong to the ordinary Python environment; the separate
archive suite ran all 86 relevant archive/doorbell/quick-response tests against
its installed isolated SDK, including those skipped transport tests. Counts are
test executions across environments, not unique tests or physical acceptance.

Read-only local checks also passed:

- `jarvisd` health and cached state returned HTTP 200; the cached health summary
  and all projected components reported healthy in the sample. Cached reads did
  not renew active collection leases or force device refreshes.
- Room-audio server health on ports 8791 and 8793 returned HTTP 200/`ok=true`.
- `terminald` rejected unauthenticated TLS health with 401, then returned
  HTTP 200/`ok=true` with the paired certificate pinned before bearer transmission.
- Local ADB found the Android monitor installed as version 1.8, with its foreground
  service running. No screen wake, launch, stream, app installation or restart
  was requested; this does not establish advancing media frames or audio.

## Boundaries and remaining acceptance

- No device switching, alarms, speech/playback, camera streaming, BLE enrollment,
  notification-delivery test, bandwidth test, credential change, installation,
  service restart, or protected-session reset is part of this review.
- Passing tests/builds does not establish physical plug/purifier transitions,
  sensor radio freshness, acoustic wake/reply quality, notification display,
  keyboard reconnect/sleep behavior, or iPhone/Watch gesture/VoiceOver acceptance.
- CLI/Pi and native write routing remains best-effort coordination, not exclusive
  SDK ownership. The ownership stack remains an uninstalled candidate.
- Python syntax/package checks and compilation are not an exhaustive proof that
  every runtime path works. Optional platform/live checks and historic deployment
  claims must be validated separately before rollout.

## Reproduce safely

From the repository root, with existing component environments:

```sh
python3 projects/operation-jarvis/scripts/verify-offline.py
python3 projects/operation-jarvis/scripts/verify-offline.py --suite swift
python3 projects/operation-jarvis/scripts/verify_docs.py
git diff --check
```

Use `--suite` to narrow the run. Interpreter overrides include `--python`,
`--kasa-python`, `--security-python`, `--archive-python`, `--vesync-python`,
`--keyboard-python`, and `--presence-python`. No dependencies are automatically
installed.

Native verification regenerates the Xcode project; run it in an isolated checkout:

```sh
cd projects/operation-jarvis/jarvis-app
JARVIS_SKIP_NATIVE_BUILDS=1 JARVIS_LIVE_TESTS=0 ./scripts/verify-jarvis-app.sh
```

That flag skips artwork rendering, native builds, and simulator UI tests; shared
Swift tests and source contracts still run. Generic simulator builds can be
performed separately without booting a simulator or installing an app. See
[native operations](../jarvis-app/docs/operations.md) for deployment gates.
