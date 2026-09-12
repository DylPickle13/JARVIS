# Native app architecture

[App overview](../README.md) · [Documentation index](README.md) · [Operations](operations.md)

This is an implementation overview, not a live deployment audit. Historical contracts and build-specific exceptions remain in the [development archive](development-history.md) and [implementation archive](implementation-history.md).

## Components and ownership

| Component | Owns | Does not own |
|---|---|---|
| Pi | Agent conversations, model interaction, and tool execution. | Native plug/purifier UI or Apple app signing. |
| iPhone app | Native UI, SSH terminal connection, local preferences, and reviewed attachment staging when enabled. | A replacement agent runtime or arbitrary backend command execution. |
| Watch app | Foreground terminal access, device controls, telemetry, and its own bounded Jobs presentation. | iPhone attachment staging or continuous background connectivity. |
| JARVISKit | Shared API models, clients, state policies, and reusable presentation logic. | Host credentials or model inference. |
| `jarvisd` | Cached state, validated device commands, bounded results, and server-allowlisted service operations. | General-purpose shell access or the terminal data plane. |
| `terminald` | Fixed-session terminal frames, validated input, and Watch/Siri terminal transport. | Native hardware commands or arbitrary client-selected tmux targets. |
| Private scheduler | Job execution, bounded retained results, and configured notification dispatch. | A native schedule-editing UI. |

Source entry points: [app root](../JARVIS/JARVISApp.swift), [shared package](../JARVISKit/), [jarvisd](../jarvisd/jarvisd.py), [terminald](../terminald/jarvis_terminald.py), and [scheduler](../../../../.pi/scheduler/runner.py).

## Request paths

### Agent interaction

The iPhone terminal uses SwiftTerm and SwiftNIO SSH to attach to fixed Mac-side Pi sessions. Watch and Siri use the separate terminal relay. Pi owns conversation continuity and invokes configured models and tools. Clients reconnect to persistent sessions instead of treating every app launch as a new conversation.

The current source supports nine fixed mobile slots. Older six-slot and three-slot notes describe earlier checkpoints, not the current source interface. This count does not prove how many processes are running on a live host.

### Direct native controls

A native plug or purifier action goes to `jarvisd`, not through an LLM. The daemon validates the action and parameters and delegates to the existing JARVIS device-control implementation. Per-resource state, concurrency, and freshness checks prevent an unrelated stale subsystem from being treated as authority for a command.

### State and results

Background collectors populate cached state. HTTP handlers read that cache rather than starting expensive device probes for every UI request. Last-good values carry freshness/error information; cached data must not be labeled live after its freshness window expires. Authoritative command results must not be overwritten by older in-flight reads.

Native Jobs surfaces consume bounded scheduler inventory and retained results. They do not expose prompts, model configuration, command lines, private database paths, or schedule mutation. Notification delivery, when explicitly configured, is separate from reading durable results.

### Room audio

The Raspberry Pi endpoint and Mac voice pipeline belong to the wider JARVIS project. Native room-audio state and its bounded Stop route do not make the app a microphone/wake-word engine. See the [room-audio documentation](../../raspberry-pi/room_audio/README.md).

## Security and trust boundaries

- **Network trust is explicit.** `JARVISD_AUTH_MODE=trusted-network` accepts configured source CIDRs. It trusts allowed peers and is not per-user authentication.
- **Token mode is distinct.** `JARVISD_AUTH_MODE=token` requires the configured API token for protected native endpoints. Missing token configuration fails startup. The minimal health route is not proof of authorization.
- **Event credentials are scoped.** The event-ingestion token does not authorize device commands or general native state access.
- **Terminal transports are separate.** iPhone SSH host-key trust and Watch/Siri certificate pinning must not be bypassed to repair a connection.
- **Commands are bounded.** Unknown actions, malformed payloads, arbitrary paths, and client-selected shell commands are outside the native command contract.
- **Ambiguous delivery is not success or permission to retry.** Hardware and terminal input must not be blindly queued, replayed, or retried after an uncertain send.
- **Private state stays private.** Credentials, conversations, device selectors, notification registrations, databases, and signing artifacts are excluded from public source and screenshots. Private runtime directories/files use owner-only permissions as specified by each component.
- **Trusted transport is not public hosting.** Do not expose these services to the public internet or describe LAN HTTP as end-to-end encrypted transport.

## Notifications and privacy

The repository implements notification registration, delivery, and routing, but a checked-in implementation does not prove that host dispatch or device permissions are enabled. Source support, signed capabilities, owner opt-in, registration, and host activation are independent gates.

Historical Build 144 notes specified generic-only job alerts; later Build 145 notes changed that contract to bounded sanitized job-name/result previews. Do not use the older generic-only language as a blanket current privacy promise. Full output is read through Jobs, not placed in the notification payload. See the [notification implementation history](implementation-history.md#native-iphone-and-apple-watch-apns-scheduled-job-notifications) and its [privacy addendum](implementation-history.md#build-145-privacy-contract-addendum) before changing this boundary.

## Limits and evidence

The clients depend on compatible host services, configured integrations, and platform permissions. Local-first agent access can still invoke external model providers and services. Native state/command APIs and model providers have different trust boundaries.

The [daemon tests](../jarvisd/tests/), [terminal tests](../terminald/tests/), and [Swift tests](../JARVISKit/Tests/JARVISKitTests/) provide implementation evidence. Their presence is not a claim of a fresh passing run, public security certification, or live-device acceptance.
