# JARVIS for iPhone and Apple Watch

**Native clients for a Mac-hosted AI workspace and connected-device controls.**

The app makes persistent Pi terminal sessions, room-device controls, system telemetry, and scheduled-job results accessible from iPhone and Apple Watch. SwiftUI clients share networking and presentation models through JARVISKit, while separate Python services handle native control and terminal access.

[Project overview](../../../README.md) · [Architecture](docs/architecture.md) · [Build and operations](docs/operations.md) · [Documentation index](docs/README.md)

## Simulator preview

![JARVIS iPhone and Watch interfaces using sample data in Apple simulators](../../../docs/media/jarvis-simulator-overview.png)

[Short simulator video](../../../docs/media/jarvis-simulator-showcase.mp4) · [Full-size Home, System, and Jobs screenshots](../../../docs/media/README.md)

These are real app renders with synthetic read-only data, not a live execution demo or physical-device acceptance evidence.

## Capabilities

| Surface | Purpose |
|---|---|
| iPhone Home | Pi session status, plug and purifier controls, room-audio state, and read-only model-server telemetry. |
| iPhone terminal | SSH-backed access to persistent Pi sessions, with native keyboard controls. Photos/Files staging is gated by the signed build's attachment configuration. |
| Apple Watch | Terminal, Plugs, System, and Jobs pages, with bounded foreground refresh and explicit stale/unavailable states. |
| Jobs | Read-only schedules and retained per-job results. Reading a result does not execute a job or edit a schedule. |
| Siri | A prompt entry path into the protected terminal service. Admission and routing depend on compatible host and client versions. |
| Widgets | Neural Core and Open JARVIS surfaces, separate from native hardware command controls. |
| Notifications | Opt-in scheduled-result and session-completion support. Signing, registration, permissions, and host activation are separate requirements. |

This describes the checked-in implementation, not a claim that every feature is enabled or that a particular build is currently installed. The repository contains historical candidate and deployment notes; the [status register](docs/planned-work.md) explains their limits.

## How it fits together

- **iPhone terminal:** SwiftTerm and SwiftNIO SSH connect to fixed, persistent Mac-side Pi sessions.
- **Watch and Siri terminal:** `terminald` provides a separate authenticated, certificate-pinned terminal bridge.
- **Native device controls and state:** `jarvisd` serves cached telemetry and validated, allowlisted commands. Native plug and purifier actions do not need model generation.
- **Shared logic:** JARVISKit contains API models, state/freshness handling, networking, Watch bridging, and reusable presentation components.

Pi supplies the agent runtime. JARVIS supplies the native interfaces, integration services, and project-specific extensions. The clients also use third-party terminal and networking libraries rather than implementing those protocols from scratch.

## Source map

| Path | Responsibility |
|---|---|
| [`JARVIS/`](JARVIS/) | SwiftUI iPhone app, terminal, settings, and notification coordination. |
| [`JARVISWatch/`](JARVISWatch/) | Watch interface, terminal, device controls, and Jobs. |
| [`JARVISKit/`](JARVISKit/) | Shared models, networking, state policies, and tests. |
| [`JARVISWidget/`](JARVISWidget/), [`JARVISWatchWidget/`](JARVISWatchWidget/) | WidgetKit targets. |
| [`jarvisd/`](jarvisd/) | Python state, hardware-command, and service API. |
| [`terminald/`](terminald/) | Isolated terminal relay. |
| [`project.yml`](project.yml) | XcodeGen project specification. |
| [`scripts/`](scripts/) | Verification, packaging, and guarded deployment helpers. |

## Verification

On a configured Mac with the required Xcode components and dependencies, run from this directory in an **isolated development checkout**:

```bash
./scripts/verify-jarvis-app.sh
```

The verifier regenerates the Xcode project, runs Python/Node/Swift checks, and builds simulator products. It is not a read-only documentation check. iOS test execution and live integration tests have separate opt-in flags; see [operations](docs/operations.md#verification). A simulator build is not evidence of physical-device acceptance.

Representative tests: [daemon contracts](jarvisd/tests/), [terminal relay](terminald/tests/), [shared Swift behavior](JARVISKit/Tests/JARVISKitTests/), and [iPhone app tests](JARVISTests/).

## Operating boundaries

This is a private deployment over configured LAN/Tailscale access, not an App Store release or a public control endpoint. `jarvisd` network allowlisting and token authentication are distinct modes. Credentials remain outside source control, and device actions must fail closed when authoritative state or delivery is uncertain.

Do not run deployment, signing, service-restart, or terminal-recovery scripts simply to preview the project. Preserve live Pi conversations, session identities, device configuration, and rollback artifacts. Physical installation requires a separately approved, audited build.

## Further reading

- [Architecture and security](docs/architecture.md)
- [Verification, signing, deployment, and recovery](docs/operations.md)
- [Pending work and status reconciliation](docs/planned-work.md)
- [Development history](docs/development-history.md)
- [Implementation history](docs/implementation-history.md)

Historical material is retained for traceability, not presented as the current product introduction or as deployment authorization.
