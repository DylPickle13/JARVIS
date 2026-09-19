# Build 198: restore iPhone and Watch device controls

Both devices were verified on Build197 before the update. The preceding CLI-first
backend rollout intentionally retired `/api/v1/command` device writes, causing the
reported HTTP409 errors. Build198 was installed and launched on both devices.

- Shared `JarvisClient` routes only plug on/off/toggle and purifier-set to
  `/api/v1/device-command`, preserving the configured endpoint and app token.
- Each invocation creates one random request ID. Device tasks refuse redirects;
  errors never trigger application retry, alternate-host or old-route fallback.
- The backend applies existing API authentication and the same dispatcher,
  per-device admission, freshness/identity checks and SDK no-replay guards used
  by CLI/Pi. The local CLI token is not copied into the apps.
- Native request IDs are consumed before dispatch, including failed/unknown
  outcomes. Duplicates return409 instead of executing again. The bounded4096-entry
  set is process-local with no eviction; capacity returns503, restart clears it.
  This is not durable exactly-once execution. Inspect state after uncertain errors.
- Read-only/non-device APIs, UI, terminal, attachment flags, widgets, signing
  entitlements and endpoint settings are preserved. Legitimate busy/stale409s
  remain possible; this fix does not suppress safety errors.

Verification: 588 backend tests, 32 Kasa/38 VeSync safety tests, 161 shared Swift
checks (3 expected live skips), signed phone/watch/widget archive audit, installed
version and launched-process checks on both devices. No physical device-control
commands were issued for testing; owner button acceptance remains to be checked.
All nine terminal session/attachment/history identities and protected services
were preserved across app installation. Only daemon/watchdog were restarted for
the separate backend update before app-install baselines.

An initial read-only Watch inventory timed out before any installation. That
record is retained unchanged. A fresh continuation installed the phone first,
then successfully installed and launched the Watch; no unpair/reset/reboot.

Artifacts:
- Backend: `~/Library/Application Support/JARVIS/jarvisd/deployments/20260919T204928Z-native-clients`
- Exact audited Build198: `~/Library/Application Support/JARVIS/signing-renewal/artifacts/20260919T204848Z-build198-native-device-control`
- Successful device continuation: see `/tmp/JARVIS-native198-continuation`.

Rollback planning must keep a backend supporting the native route while Build198
is installed. Rolling the backend back to CLI-only mode would break these controls
again. Prior signed Build197 is retained, but do not reinstall it automatically or
restore historical runtime/configuration data.
