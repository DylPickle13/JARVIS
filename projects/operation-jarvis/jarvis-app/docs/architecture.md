# Native app architecture

[App overview](../README.md) · [Documentation index](README.md) · [Operations](operations.md)

Pi sessions run on the Mac. The apps connect to those sessions and use separate APIs for device controls and status. Earlier designs and build-specific notes are in the [development archive](development-history.md) and [implementation archive](implementation-history.md).

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

The source supports nine fixed mobile slots; older notes describe three- and six-slot versions. Check the host to see which sessions are actually running.

### Direct native controls

Plug and purifier buttons call `jarvisd` directly, without an LLM. The daemon validates the request, then calls the existing device adapter. Each resource has its own state, concurrency, and freshness checks, so a command cannot rely on stale state from another subsystem.

### State and results

Background collectors update a cache so each UI request does not need a fresh device probe. Saved values include their freshness and any errors. Once stale, they must no longer appear live. An older read that finishes late must not overwrite a confirmed command result.

Jobs reads the scheduler's limited inventory and saved results. It cannot edit schedules and does not expose prompts, model configuration, command lines, or private database paths. Notifications are configured separately; reading a result does not send one.

### Room audio

The Raspberry Pi handles microphone capture and wake detection; the Mac handles transcription and responses. The app shows room-audio status and can stop the current turn. See the [room-audio guide](../../raspberry-pi/room_audio/README.md).

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

Notifications need more than app code: the signed build must have the right capabilities, the owner must opt in, devices must register, and the host must enable dispatch. Check each step before assuming alerts are active.

Build 144 used generic job alerts. Build 145 added short, sanitized job names and result previews, so the earlier generic-only description no longer covers the notification format. Full output stays in Jobs. Read the [notification history](implementation-history.md#native-iphone-and-apple-watch-apns-scheduled-job-notifications) and [privacy update](implementation-history.md#build-145-privacy-contract-addendum) before changing payload contents.

## Limits and evidence

The apps need compatible host services, configured integrations, and platform permissions. Agent requests can use external model providers even though the sessions run locally; device APIs and model providers have separate access rules.

Tests cover the [daemon](../jarvisd/tests/), [terminal relay](../terminald/tests/), and [shared Swift code](../JARVISKit/Tests/JARVISKitTests/). See [operations](operations.md#verification) for running them. Passing tests does not replace checking the signed build and its behavior on the intended devices.
