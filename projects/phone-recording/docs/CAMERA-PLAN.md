# Target: four cameras

The user confirmed that **Overhead will be added soon**. Three cameras are the current rollout, not the final scope.

| Role | Device | Status |
|---|---|---|
| Wide Angle | LG G6 | Integrated; 2880×2160 target 30 |
| Dyl Cam | Samsung S21 FE | Integrated; native 4K/30 |
| Bass Pedals | iPhone 11 | Integrated; native 4K/30, proxies off |
| Overhead | Second Samsung S21 FE | Planned fourth camera; not enabled/onboarded |

Keep the unonboarded camera out of current Start/readiness requirements. Do not silently skip an enabled camera later.

Before enabling Overhead:
1. Verify device identity, camera settings/audio, available storage/power, and its own paired Wi-Fi connection; preserve unrelated media.
2. Use the shared `camera-config.json` registry after onboarding; add Overhead’s explicit runtime Android transport entry before enabling it. Controller/gates/cards/framing/export role sets now derive from that registry. It is not a clickable onboarding UI; see [READINESS.md](READINESS.md).
3. Deploy the identical registry to both Macs, restart the idle dashboard and verify all four derived cards/readiness, framing, job scope, inventories and export paths. Audio/Resolve source discovery is already manifest-driven. Existing takes retain their recorded scope.
4. Extend unknown/partial-start rollback, missing-fourth-camera, verified-collection and cross-camera audio-sync tests.
5. Perform a bounded four-camera recording/collection check before claiming four-camera reliability.

Shared requirements stay unchanged: encoding on phones, no continuous preview/cues/cloud, file transfer only after verified stop, verified phone-original deletion, both Mac copies retained, durable single-send jobs and REAPER untouched.
