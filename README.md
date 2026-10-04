# JARVIS

**A personal, local-first AI automation system with native iPhone and Apple Watch clients.**

I built JARVIS to keep a Mac-hosted AI workspace within reach from my iPhone, Apple Watch, or a Raspberry Pi microphone and speaker. It connects persistent terminal sessions to browser tools, scheduled jobs, and household devices.

It runs on the [Pi coding agent](https://github.com/earendil-works/pi-coding-agent), which handles the agent loop and model interaction. My work is in the custom tools, backend services, and native apps that connect it all.

[Explore the architecture](#architecture-at-a-glance) · [Directory layout](#directory-layout) · [Documentation](#documentation) · [Native apps](projects/operation-jarvis/jarvis-app/README.md) · [Setup and operation](projects/operation-jarvis/docs/runtime-guide.md)

## See the native apps

![JARVIS iPhone Home and Apple Watch System screens captured in simulators with clearly labeled sample data](projects/operation-jarvis/docs/media/jarvis-simulator-overview.png)

[Watch the 8-second simulator showcase](projects/operation-jarvis/docs/media/jarvis-simulator-showcase.mp4) · [Full-size screenshots and capture details](projects/operation-jarvis/docs/media/README.md)

Captured in the iPhone and Watch simulators with sample data. The short clip shows the UI animations.

## What I built

- **Pi extensions** for persistent memory, browser automation, web research, and service and device integrations.
- **SwiftUI apps** for iPhone and Apple Watch, with terminal access, plug and purifier controls, system status, and read-only scheduled-job results.
- **Python services** for the native control API, Watch terminal access, and room audio.
- **Room audio integration** with Raspberry Pi microphone/speaker transport and Mac-side transcription, Pi RPC, and speech output.

## A few design decisions

**Keep the sessions on the Mac.** The iPhone connects over SSH, while the Watch uses a terminal bridge. Both access persistent Pi sessions rather than keeping separate chatbot histories.

**Keep device buttons separate from the model.** Tapping a plug or purifier control sends a validated command through `jarvisd`. It does not need an LLM response. When delivery is uncertain, the system leaves that uncertainty visible rather than blindly repeating the action.

**Load tool schemas as needed.** Optional integrations stay out of a session's tool list until requested. Pi extensions handle this loading, alongside memory and browser access.

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

Sessions and services run on my own hardware, with either a local or cloud model provider. Web research, Google services, and some device integrations still need external services, so local-first does not mean offline.

## Directory layout

The JARVIS root is the Pi workspace and the home of shared infrastructure. `projects/` groups individual components and local work; it is not the agent's project root.

Main directories and shared files:

```text
JARVIS/
├── .pi/                 # workspace-specific Pi configuration and agent infrastructure
│   ├── extensions/      # custom tools and shared extension helpers
│   ├── scripts/         # launchers, attachment helpers, and verification utilities
│   ├── tests/           # extension regression tests
│   ├── docs/            # Pi integration, setup, and rebuild documentation
│   ├── memory/          # durable-memory backend and private local database
│   └── runtime/         # private generated state, sockets, caches, and logs
├── projects/            # applications, integrations, and local personal work
├── config.py            # shared environment parsing and logging
├── pi_rpc.py            # shared Pi RPC client for local services
├── requirements.txt     # dependencies for the root Python runtime
├── .env.example         # tracked shared-configuration template
├── .env                 # private local configuration; ignored by Git
├── .venv/               # root Python environment; ignored by Git
└── attachments/         # private Pi attachment copies; ignored by Git
```

**Why `.pi/` is outside `projects/`:** Pi launched from `JARVIS/` discovers its project configuration and extensions here. This directory is separate from the default user-level `~/.pi/agent/`, which holds Pi's installed runtime, user configuration, and sessions.

**Why Python files live at the root:** `config.py` and `pi_rpc.py` provide shared support rather than belonging to one standalone project. The root environment serves that shared runtime; components may also have their own dependency files and environments.

**Source versus local state:** `.pi/` contains both tracked source and ignored private/generated data. Only selected projects are tracked; private and local-only work is deliberately excluded. See [`.gitignore`](.gitignore) for the actual Git policy, which is separate from backup coverage.

## Explore the implementation

| Area | Start here | Supporting tests |
|---|---|---|
| Persistent sessions and voice | [`pi_rpc.py`](pi_rpc.py), [voice pipeline](projects/operation-jarvis/voice/voice_pipeline.py) | [RPC tests](projects/operation-jarvis/voice/test_pi_rpc.py), [voice tests](projects/operation-jarvis/voice/test_voice_pipeline.py) |
| Tool loading, memory, browser | [lazy tools](.pi/extensions/99-lazy-tools.ts), [memory](.pi/extensions/35-memory.ts), [browser](.pi/extensions/50-browser/) | [tool-loading tests](.pi/tests/lazy-tools.test.mjs) |
| Scheduled results | [scheduler](projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py) | [scheduler tests](projects/operation-jarvis/jarvisd/tests/scheduler/) |
| Native state and control | [`jarvisd`](projects/operation-jarvis/jarvisd/jarvisd.py) | [API and state tests](projects/operation-jarvis/jarvisd/tests/) |
| Apple clients and shared models | [SwiftUI app](projects/operation-jarvis/jarvis-app/JARVIS/), [JARVISKit](projects/operation-jarvis/jarvis-app/JARVISKit/) | [shared Swift tests](projects/operation-jarvis/jarvis-app/JARVISKit/Tests/JARVISKitTests/) |

**Stack:** Python, TypeScript/JavaScript, Swift/SwiftUI, SQLite, SSH/tmux, macOS, iOS/watchOS, and Raspberry Pi.

## Documentation

Start with the workspace guides for Pi tooling, or the runtime guides for JARVIS services. Component-specific documentation stays beside its source; this index connects the guides without relocating them.

### Pi tooling and workspace — [`.pi/docs/`](.pi/docs/)

- [Managed Pi installation](.pi/docs/PI_MANAGED_INSTALL.md) — runtime layout, verification, and recovery.
- [Pi extensions](.pi/docs/PI_EXTENSIONS.md) — custom tools and integration reference.
- [Optional codemode](.pi/docs/CODEMODE.md) — integration and verification notes.
- [Rebuild from scratch](.pi/docs/REBUILD_FROM_SCRATCH.md) — restoring the workspace and its dependencies.

### JARVIS architecture and runtime — [`projects/operation-jarvis/docs/`](projects/operation-jarvis/docs/)

- [Setup and runtime guide](projects/operation-jarvis/docs/runtime-guide.md) — setup, component map, and runtime safety.
- [Shared backend architecture](projects/operation-jarvis/docs/backend-architecture.md) — backend boundaries and refactoring history.
- [Native app documentation](projects/operation-jarvis/jarvis-app/docs/README.md) — app architecture, verification, and operations.
- [Room audio](projects/operation-jarvis/room-audio/README.md) — audio pipeline, components, and checks.

## Setup and limitations

This is my personal setup, not a one-click installer. To run it, you need a Mac host, the Pi coding agent, and credentials for whichever integrations you choose. The Apple apps need Xcode and appropriate signing; room audio also needs a Raspberry Pi. The guides cover each component separately.

## Running it safely

Keep services on a trusted LAN or Tailscale, and keep credentials, conversations, and runtime data out of Git. `jarvisd` supports network allowlisting and token authentication; allowlisting is not per-user authentication.

Read the [runtime safety notes](projects/operation-jarvis/docs/runtime-guide.md#runtime-safety) and [app security guide](projects/operation-jarvis/jarvis-app/docs/architecture.md#security-and-trust-boundaries) before connecting devices. Build, test, and installation procedures are in the [operations guide](projects/operation-jarvis/jarvis-app/docs/operations.md).

## License and attribution

JARVIS is [MIT-licensed](LICENSE). Pi and other dependencies retain their own licenses. The native-app documentation includes [retained third-party license material](projects/operation-jarvis/jarvis-app/docs/third-party/).
