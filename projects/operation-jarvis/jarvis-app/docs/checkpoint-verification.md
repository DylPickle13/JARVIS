# Repository checkpoint — 2026-09-19

Reviewed after the Build200 / shared Session10 rollout completed. This checkpoint
records source verification, not another deployment or physical acceptance.

## Passed

- Backend isolated suite: 595 tests; Python syntax and LaunchAgent plist checks.
- Kasa / VeSync synthetic SDK safety suites: 32 / 38 tests.
- Room-audio suite: 74 tests; shared-session Node gate test also passed.
- Swift package: 163 tests, including three expected live-test skips.
- Scheduler: 43 tests; guarded Siri admission Node tests passed.
- Updated app source contracts passed, including Session10 and shared-room UI.
- Diff whitespace checks; targeted credential-pattern scan found only a test
  placeholder. This scan is not a comprehensive security audit.

## Limitations

- The 32-test terminald suite passed on some runs, but
  `test_concurrent_long_polls_share_one_sampler_and_stop_when_idle` intermittently
  failed its timing-based capture-count assertion (one capture rather than two).
  It also exhausted the verifier's existing three attempts on some runs. The
  aggregate app verifier is therefore **not a consistently passing gate**.
  Remaining source checks and Swift tests were run separately and passed; the
  flaky assertion was not weakened or skipped in the repository verifier.
- Native builds, artwork rendering and simulator AppState tests were not rerun,
  respecting the prior request to reduce machine load. The verifier now supports
  explicit `JARVIS_SKIP_NATIVE_BUILDS=1`; default full-build behavior is unchanged.
- Dormant `jarvisd_core/control_runtime.py` retains a Python warning for a return
  inside `finally`. Exclusive-ownership runtime remains inactive and unchanged.
- Physical wake/speech/Stop and native device-button acceptance remain pending.
  See [deployed Build200 evidence](room-session10.md).

No live service restart, device write, or configuration change was performed for
this review. Credentials, recordings, security inventory/code and shared-session
runtime/history files remain ignored and outside this checkpoint.
