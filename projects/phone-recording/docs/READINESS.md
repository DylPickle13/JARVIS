# Camera readiness and shared configuration

Implemented September 7, 2026. Phones are currently disconnected; further live validation is deferred. No recording test was run.

## Before Start

**Check cameras** now refreshes camera state plus battery, external-power/charging information, free storage and available temperature/thermal readings. Start requires:

- Every enabled camera freshly verified idle, no pending take and no active/uncertain job.
- A matching camera-configuration fingerprint on both Macs.
- Successful health checks less than 120 seconds old, with required telemetry present.
- At least 5 GiB free on each Mac. The local Mac is checked by the local job engine; the collection Mac is checked remotely.

The remote controller independently repeats health checks before file inventories, durable take intent or recording commands. Cached UI readiness alone never authorizes a camera command. A fresh framing snapshot does **not** refresh an old health timestamp. Successful Stop, failed control and other control transitions invalidate cached health so a new take needs fresh checks.

### Initial conservative thresholds

| Reading | Block Start | Warn, but do not block |
|---|---|---|
| Battery | Below 20%, missing or invalid | Below 40%; running on battery |
| Phone free storage | Below 2 GiB, missing or invalid | Below 5 GiB |
| Mac free storage | Below 5 GiB or unavailable | — |
| Android battery temperature | 45°C or higher | 40°C or higher |
| Android thermal-service severity | Severe or higher (3–6) | Moderate (2) |
| Missing temperature | Not a block by itself | Manual temperature check required |
| Unknown external power | Not a block by itself | Status unavailable |

These are minimum safeguards, **not a duration estimate, complete thermal assessment, or guarantee against a phone dying mid-take**. Charging does not override the low-battery block. Battery temperature is not image-sensor/GPU temperature. iPhone temperature is not currently exposed by the implemented probe and is explicitly reported unavailable, never inferred to be safe. An iPhone saying “not charging” does not alone establish whether it is plugged in; the UI keeps that distinction.

## Observation behavior

- `readiness.py` reads Android battery/`df -k`/thermal-service diagnostics and iPhone lockdown battery/storage metadata through the existing **Network-only** pairing. It never opens AFC/House Arrest or transfers media.
- Offline/unknown-state cameras are not probed for health or silently omitted. Other known-idle cameras can still be checked. If any camera is recording, **all phone health probes are deferred**. Pending takes also defer health scans.
- This runs on explicit status checks and before Start, not continuously. Browser refreshes read cached data; they do not trigger recurring phone polling. There is no battery/thermal recording watchdog yet.
- Disconnected phones produce blocked readiness, not fabricated battery values. No apps are reopened, trust created, settings changed or recordings started by health checks.

## One registry for the four-camera target

**`camera-config.json`** in the project root is shared by mac-mini-64 and mac-mini-16. `camera_config.py` validates it and supplies:

- Enabled role sets and fixed Android identities.
- Names, model/video labels, and preview capability for dynamically generated dashboard cards.
- Planned cameras for Advanced; **Overhead remains disabled and not onboarded**.
- Controller routing, job/Start gates, framing/preview allowlists and export role discovery.
- A fingerprint carried in snapshots, readiness reports and new pending takes. Configuration mismatch blocks Start; changing configuration during a pending take blocks camera mutations until deliberately recovered.

The registry is not a clickable onboarding UI. The current managed collector requires the bound iPhone plus enabled Android cameras; adding a second iPhone or switching to Android-only managed capture is not implemented.

### Enabling Overhead later

1. Keep all cameras idle, with no active job or pending take. Never change the registry during a take.
2. Verify Overhead identity, 4K/30/audio settings, battery/storage and its own paired Wi-Fi control/verified transfer path.
3. Add its explicit endpoint/service to **mac-mini-16:`~/phone-recording/android-transports.json`**. This runtime file is separate from the shared camera registry; enabling an Android without its transport entry fails closed.
4. Only after onboarding, set Overhead `onboarded:true` and `enabled:true` in `camera-config.json`, deploy matching files to both Macs and restart the idle dashboard server. Future workers import the new role set.
5. Refresh and inspect all four cards/readiness before any recording. Existing audio sync already derives roles from the verified take manifest; archived exports use the declared take scope rather than requiring today's active scope.
6. Run a bounded four-camera recording/collection and Resolve check before claiming four-camera reliability.

## Validation

- **120 automated tests pass**, plus JS syntax and Python compilation checks.
- New coverage: low/missing/nonfinite battery/storage, heat thresholds, unsupported temperature, offline/recording health deferral, stale/future timestamps, local disk gate, independent remote Start health check and pending-configuration protection.
- Registry tests reject duplicate/unsafe identities/roles and premature enablement. An isolated temporary four-camera configuration proves four-role routing, preview/export discovery and the missing-fourth-camera Start guard without contacting phones or enabling Overhead.
- Visible Chrome shows three registry-generated cards and blocks Start with disconnected cameras. Healthy/low-battery UI readings and actual hardware threshold behavior still require live verification when phones are connected. See `validation/readiness-registry-validation.json`.
