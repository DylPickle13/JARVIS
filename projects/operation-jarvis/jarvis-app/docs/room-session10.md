# Room Audio / Session 10

Deployed 2026-09-19: iPhone and Watch 0.3.0 (200), backend `20260919T215836Z-room-session10`.

- One Room Audio card opens the actual `jarvis-ios-10` Pi terminal. Both microphones submit to that one interactive process through a private Unix socket; neither server creates a separate RPC conversation in shared mode.
- Sessions 1–9 retain their pane/PID, attachment/socket and exact history identities. Ordinary New/Siri allocation excludes 10. Reconnecting to an offline 10 never creates a replacement conversation.
- The most recent confirmed Mac room conversation is continued in place. Its pre-cutover history and the known original Pi room history were retained privately; other historical files were not deleted or rewritten. These histories were not concatenated into a fabricated conversation.
- Voice admission is serialized without a queue or automatic replay. Manual input during a voice turn is blocked with the draft retained. Stop captures exact speaker turn IDs before parallel cancellation; it does not target a replacement turn.
- `com.operation-jarvis.room-audio-session10` supervises only Session 10. Bootstrap and current-owner metadata live in `.pi/runtime/room-audio-session`; the launcher resumes retained history and never performs an idle reset. Both room server LaunchAgents opt in with `JARVIS_ROOM_AUDIO_SHARED_SESSION=10`.
- Terminald runs from the signed Build200 artifact's source tree. Its original credentials/certificate and configuration were retained. Audio clients were not restarted.

Verified: 595 backend tests, 32 Kasa and 38 VeSync SDK tests, 163 Swift package tests (3 expected skips), 32 terminal tests, 73 room tests, gate/load checks, signed phone/watch/widgets audit, installation and launch on both devices, pinned/authenticated Session10 terminal frame, both speaker statuses, and original-nine identity proofs. A tool-free text-only prompt completed through the shared owner without requesting playback.

The Build200 iOS simulator AppState run was cancelled at the owner's request to reduce machine load; it is not a passing gate. The simulator was shut down and no SimMetalHost remained. Physical wake/speech/Stop acceptance is still pending.

Private rollout evidence: `~/Library/Application Support/JARVIS/room-session10-cutover`, backend deployment record, and signing artifact `20260919T214002Z-build200-room-session10`. Never restore historical conversation/event files as rollback. Any rollback must preserve the live Session10 history and remain compatible with native device commands.

## Build201 follow-up

Build201 (`20260919T220708Z-build201-compact-room-card`) installed/launched on phone and Watch. Room card now uses the same 8-point padding and 42-point minimum content height as other Pi cards, with speaker statuses in the existing second line and inline Stop. No simulator used.

The first physical Mac attempt exposed a constructor wiring bug missed by the initial direct-adapter test: `config.PROJECT_ROOT` resolves to the voice directory after voice configuration loads, not the JARVIS repository. Both servers now construct `SharedRoomSession(PROJECT_ROOT)` using the room server's independently resolved repository constant. Added a real bridge-constructor regression; 74 room tests pass. Tested actual bridge inference plus WAV synthesis, without playback. Both servers restarted with the correction; Session10 and original nine remained running.

The original Build201 install record retains its Watch Bluetooth inventory failure and runtime mismatch (audio restart overlapped that baseline). A separate successful `deployment-continuation` verifies both installed/launched apps and stable ten-session/service/config identities. Physical speaker acceptance after the correction is still pending.
