# JARVIS

**A personal, local-first AI automation system with native iPhone and Apple Watch clients.**

I built JARVIS to access a persistent AI workspace from my Mac, phone, Watch, and a Raspberry Pi room-audio endpoint, and connect that workspace to software tools and household devices. It brings terminal access, tool integrations, device controls, and scheduled-job results into one system.

JARVIS extends the [Pi coding agent](https://github.com/earendil-works/pi-coding-agent). Pi provides the underlying agent runtime and model interaction; this repository contains my extensions, integration services, and native clients. It does not contain a foundation model trained from scratch.

[Explore the architecture](https://dylpickle13.github.io/) · [Native apps](projects/operation-jarvis/jarvis-app/README.md) · [Setup and operation](docs/runtime-guide.md)

## See the native apps

![JARVIS iPhone Home and Apple Watch System screens captured in simulators with clearly labeled sample data](docs/media/jarvis-simulator-overview.png)

[Watch the 8-second simulator showcase](docs/media/jarvis-simulator-showcase.mp4) · [Full-size screenshots and capture details](docs/media/README.md)

Actual simulator rendering with synthetic telemetry. The clip shows interface motion, not live inference or device actions.

## What I implemented

- **Agent extensions:** persistent memory, browser automation, web research, and integrations with software services and connected devices. Optional tool schemas load when needed rather than all at once.
- **Native Apple clients:** SwiftUI iPhone and Apple Watch interfaces for persistent terminal sessions, device controls, telemetry, and read-only scheduled-job results.
- **Backend services:** separate Python services for native state and control APIs, the mobile terminal relay, and room audio.
- **Cross-device access:** Mac-hosted Pi sessions, an SSH-backed iPhone terminal, a protected Watch terminal bridge, and Raspberry Pi audio capture/playback.
- **Reliability boundaries:** bounded history, stale-state handling, validated commands, and explicit handling of uncertain delivery rather than blindly repeating device actions.

These components integrate existing libraries, model providers, and device APIs. The engineering work is in how they communicate, retain state, handle failures, and expose controls across devices.

## Example workflows

| Workflow | What happens |
|---|---|
| Continue a conversation away from the Mac | Open a persistent Pi terminal from the iPhone or Watch without creating a separate chatbot history. |
| Use an agent tool | Ask Pi to research a page or use a configured integration. Pi chooses from the tool schemas available to that session. |
| Control a room device | Use native plug or purifier controls through the validated backend command API. Direct native controls do not pass through an LLM. |
| Check scheduled work | Read retained job results on the phone or Watch. The native Jobs interface does not edit schedules or run arbitrary commands. |
| Speak in the room | The Raspberry Pi handles microphone/speaker transport; Mac-side transcription, Pi RPC, and speech output complete the turn. |

These describe configured workflows, not a hosted public demo. The [interactive architecture map](https://dylpickle13.github.io/) illustrates request paths; its buttons do not control live devices.

## Architecture at a glance

```text
Mac / iPhone / Watch terminal ──────────┐
Raspberry Pi audio → transcription ─────┤
                                       ▼
                              Pi sessions on Mac
                                       │
                           Local or cloud model provider
                                       │
                          Custom tools and integrations

Native iPhone / Watch controls → jarvisd → validated device commands
Watch / Siri terminal access   → terminald → protected Pi sessions
```

**Local-first does not mean fully offline.** Sessions and supporting services run on owned hardware, but cloud models, web research, Google services, and some device integrations require external services. Availability and privacy depend on the selected provider and configured integration. Network access is intended for a trusted LAN or Tailscale, not public internet exposure.

## Explore the implementation

| Area | Start here | Supporting tests |
|---|---|---|
| Persistent sessions and voice | [`pi_rpc.py`](pi_rpc.py), [voice pipeline](projects/operation-jarvis/voice/voice_pipeline.py) | [RPC tests](projects/operation-jarvis/voice/test_pi_rpc.py), [voice tests](projects/operation-jarvis/voice/test_voice_pipeline.py) |
| Tool loading, memory, browser | [lazy tools](.pi/extensions/99-lazy-tools.ts), [memory](.pi/extensions/35-memory.ts), [browser](.pi/extensions/50-browser/) | [tool-loading tests](.pi/scripts/tests/pi-lazy-tools.test.mjs) |
| Scheduled results | [scheduler](.pi/scheduler/runner.py) | [scheduler tests](.pi/scheduler/tests/) |
| Native state and control | [`jarvisd`](projects/operation-jarvis/jarvis-app/jarvisd/jarvisd.py) | [API and state tests](projects/operation-jarvis/jarvis-app/jarvisd/tests/) |
| Apple clients and shared models | [SwiftUI app](projects/operation-jarvis/jarvis-app/JARVIS/), [JARVISKit](projects/operation-jarvis/jarvis-app/JARVISKit/) | [shared Swift tests](projects/operation-jarvis/jarvis-app/JARVISKit/Tests/JARVISKitTests/) |

**Stack:** Python, TypeScript/JavaScript, Swift/SwiftUI, SQLite, SSH/tmux, macOS, iOS/watchOS, and Raspberry Pi.

## Setup and limitations

This is a personal deployment, not a one-click consumer application. Full reproduction needs a Mac host, Pi, integration credentials, and the relevant devices. Native Apple builds require Xcode and appropriate signing; room audio needs a configured Raspberry Pi endpoint. You can inspect the components and tests without granting access to a live system.

- [Setup and runtime guide](docs/runtime-guide.md)
- [Detailed rebuild instructions](.pi/docs/REBUILD_FROM_SCRATCH.md)
- [Pi extensions](.pi/docs/PI_EXTENSIONS.md)
- [Native app architecture, verification, and operations](projects/operation-jarvis/jarvis-app/docs/README.md)
- [Room audio](projects/operation-jarvis/raspberry-pi/room_audio/README.md)

Tests are included, but this README does not claim a fresh passing test run, measured production performance, or physical-device acceptance. Source implementation, signed builds, and live deployment are separate checkpoints.

## Safety and privacy

Do not publish credentials, conversation history, runtime databases, device identifiers, signing artifacts, or unreviewed screenshots. Native hardware writes use explicit validated actions and must not be queued or replayed after ambiguous delivery. `jarvisd` supports trusted-network and token modes; network allowlisting is not per-user authentication. See the [security boundaries](projects/operation-jarvis/jarvis-app/docs/architecture.md#security-and-trust-boundaries) before operating services.

## License and attribution

JARVIS is [MIT-licensed](LICENSE). Pi and other dependencies retain their own licenses. The native-app documentation includes [retained third-party license material](projects/operation-jarvis/jarvis-app/docs/third-party/).
