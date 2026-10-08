# Room audio

Mac-hosted room conversations: microphone capture, wake detection, two-part turns,
room ownership, playback, and exact busy-only `stop`. Room audio does not depend
on Raspberry Pi hardware. Pi RPC means the AI agent software running on the Mac.

## Endpoint map

These are documented deployment roles, not a fresh live health check.

| Endpoint | Transport | Server | Guide |
|---|---|---|---|
| Mac USB PowerConf | Explicit Core Audio microphone/speaker | Loopback 8793 | [Mac endpoint](MACOS.md) |
| C230 camera | Camera microphone/speaker through local go2rtc | Loopback 8791 | [Camera endpoint](CAMERA.md) |
| Raspberry Pi | Hardware endpoint retired; Pi-only installers/guides removed | None active | — |

The Raspberry Pi is currently offline per the owner. Its absence is not a room
conversation failure. Family-room Cast speaker commands are a separate transport;
this directory owns the documented conversational microphone/speaker endpoints.

## Components

- `room_audio_server.py`: Apple ASR, wake verification, follow-up authorization,
  agent responses, TTS, and room controls. Shared ASR/TTS lives in [`../voice/`](../voice/).
- `room_tts_prerender.py`: bounded silent sentence synthesis during Session 10
  generation; audio is reusable only after matching the confirmed final answer.
- `pi_room_audio_client.py`: shared client with Core Audio, camera, and legacy ALSA
  backends. The historical filename is retained for compatibility, not hardware ownership.
- `room_audio_coreaudio.py` / `room_audio_camera.py`: device-specific transports.
- `shared_room_wake.py`: shared inference with separate per-room wake state and
  ownership arbitration; see [shared wake](SHARED-WAKE.md).
- `shared_room_session.py` / `room_session10_service.py`: shared conversation and
  retained Session 10 supervision. Keep existing history and runtime identity.
- `macos_room_audio_service.py` / `camera_room_audio_service.py`: endpoint provisioning/supervision.
- `scripts/install-macos-room-audio.sh`: Mac provisioning; does not start services.

Say “Hey Jarvis”, wait for “Yes sir?”, then start a separate request within five
seconds. During a response, exact `stop` interrupts. Endpoint capture is continuous;
idle ordinary speech is discarded by wake gating. Keep credentials, transcripts,
and endpoint state private; do not add them to the repository.

Startup, reconnect, and quick-return announcements are removed; both endpoint
clients start and recover silently. The separate computer-presence arrival notice
remains opt-in. Legacy greeting CLI flags are accepted but ignored, and `/greeting`
returns no text or audio. Activating these source changes requires an explicitly
authorized restart of affected servers/clients; preserve Session 10 and its history.

Wake verification retains up to two seconds of the active capture preceding local
wake detection, plus the existing ~300 ms tail, rather than sending a long preceding
VAD segment. Follow-up commands and interrupts are not cropped. Apple verification
requires the exact consecutive words `hey jarvis` anywhere in the verification
transcript, ignoring case and punctuation, with no restriction on preceding speech.
Quoted or TV mentions can therefore pass if the acoustic detector also triggers;
spelling aliases and substrings remain rejected. The acoustic detector and
independent server verification are both retained. These Python changes require
an explicitly authorized restart of affected endpoint clients and room servers to
activate; they do not require replacing or resetting Session 10.

## Completed-response cache lifecycle

The HTTP server's existing `serve_forever` housekeeping lane expires completed
response/audio payloads even with no incoming requests (default polling interval
0.5 seconds). It adds no timer thread, agent request, audio capture or playback.
Pending turns are never removed by this sweep. The existing
`JARVIS_ROOM_AUDIO_ASYNC_JOB_TTL_SECONDS` remains **900 seconds by default**;
completed results retain that full retry/polling window after completion, with
safe timestamp fallbacks for cancelled/older entries. Hot Piper/wake models and
approved announcement banks are not unloaded or altered.

`test_room_audio_cache.py` covers genuine idle-server expiry, active-turn safety,
completion-based retention, cancellation, old-entry compatibility and no
session/control side effects. This is an expiry fix, not a new count/byte cap
that could discard a valid response before a client receives it. Restart only
the affected idle audio servers to activate; preserve clients, shared Session 10
and its history. Never replay a lost voice request during reconnect.

Owner-approved activation on October 8, 2026 replaced only the two audio server
processes. Both clients recovered with fresh idle heartbeats; metadata health
confirmed Session 10 routing, installed ASR assets, unchanged 60-clip announcement
banks and TTS pre-rendering. All ten hosted agents, wake and capture clients kept
their process identities. The primary server measured 62 MiB immediately afterward;
that is a **cold post-restart measurement**, not a guaranteed floor: the legitimate
Piper model/work buffers will warm again on use. No voice playback test was issued.

Verification ran 256 tests across presence, audio and voice: 253 passed. Three
arrival-notice tests failed identically against the retained original server
under the existing host voice policy; that policy was not changed to force a pass.
All eight new response-cache tests passed, including real idle HTTP housekeeping.

## Shared core prompt, voice-only presentation

Session 10 uses the same Pi prompt discovery, tools, permissions, and local
context as normal sessions. The supervisor launches from the repository root
without a separate `--system-prompt` or `--append-system-prompt` override.
Do not restore the old `.pi/runtime/room-audio-session/system.md` policy snapshot.

The identity-gated `.pi/extensions/04-room-audio-session.ts` adds only spoken
presentation from [`../voice/APPEND_SYSTEM.md`](../voice/APPEND_SYSTEM.md): short
natural sentences, spoken units, appropriate JARVIS wit, and no routine narration.
Only the confirmed final response is spoken, not reasoning or tool chatter.
Sessions 1–9 do not receive this overlay. Standalone room RPC uses the current
`.pi/APPEND_SYSTEM.md` followed by the same presentation file, not copied device
instructions. Prompt edits require an idle Session 10 `/reload`, never `/new`;
retain the owner/history and leave other panes alone.

An already-running legacy Session 10 may still have `--append-system-prompt`
pointing to the runtime file. For that process, migrate the runtime path to a
symlink to the canonical `.pi/APPEND_SYSTEM.md` before an idle `/reload`; this
avoids another stale copy while preserving the PID/history. Keep a private backup
of the old snapshot outside Git. The new supervisor does not use this alias.
No server restart is needed for the shared Session 10 overlay.

## Silent TTS pre-rendering

Shared Session 10 room turns can synthesize ordinary text while it is generated,
without speaking it early. Tool-call/replaced messages are invalidated; only WAVs
matching the confirmed final answer are reused. Existing PowerConf/camera
whole-WAV playback and stop/ownership behavior remain unchanged.

`JARVIS_ROOM_AUDIO_TTS_PRERENDER=0` disables this server feature (default `1` for
shared Session 10 only). The owner must advertise `tts-candidates-v1`; old owners
remain compatible through the legacy final-only prompt. `/health` reports server
configuration and turn results include `ttsPrerender` reuse/timing counters.
See [implementation, tests, activation, and rollback](STREAMING-TTS-PLAN.md).
Owner-approved activation on September 29, 2026 verified the Session 10 capability
and both servers enabled with freshly idle clients. Human spoken-turn validation
remains pending; health/telemetry alone does not prove acoustic performance.

## Bounded server logs

**Port 8791 is active; port 8793 remains staged until separately approved.**

Server source sends Python stderr and existing stderr-backed loggers to
`.pi/runtime/room-audio-logs/server-<port>.log`. Defaults are **one MiB per file
plus three backups** (approximately four MiB per server), with separate files for
8791 and 8793. The log directory is mode `0700`; active/rotated files are `0600`.
Logger levels/formatters and non-stderr handlers are unchanged. Importing the
helper does not create files or redirect a running process.

Successful `GET /health`, `GET /control/status` and `POST /client-state` access
logs are coalesced per client/method/route over 60 seconds, with a suppressed count
on the next logged success. Failures and ordinary turns remain logged. Access logs
omit query strings and arbitrary path values. This is not a general exception or
transcript scrubber; keep operational logs private.

Optional settings (no live configuration was changed):
- `JARVIS_ROOM_AUDIO_LOG_FILE`: override the port-specific path; never share one
  rotating file between independent server processes.
- `JARVIS_ROOM_AUDIO_LOG_MAX_BYTES`: default 1048576, constrained to 64 KiB–16 MiB.
- `JARVIS_ROOM_AUDIO_LOG_BACKUP_COUNT`: default 3, constrained to 1–10.
- `JARVIS_ROOM_AUDIO_ROUTINE_LOG_INTERVAL`: default 60 seconds, constrained to 10–600.

Native OS-fd-2 output still uses launchd's fallback stderr file. Setup failure
retains that original stream with a fixed warning instead of preventing startup;
those fallback files are not automatically rotated by this Python helper.

The accumulated `.pi/runtime/room_audio_server.launchd.err.log` was cleared in
place after verifying its append-mode writer and preserving the latest two MiB
of complete diagnostic lines in a private, verified compressed tail archive under
`.pi/runtime/room-audio-log-archive/`. The writer PID/inode were preserved; no
service, endpoint, Session 10 or browser was restarted. Copy/truncate has a small
concurrent-write loss window and is not a complete historical backup.

Owner-approved activation restarted only `com.operation-jarvis.room-audio-server`
(port 8791) after fresh idle telemetry. The new server holds the private bounded
log; health is OK and the existing endpoint reconnected online/idle. Five read-only
health probes produced one access-log entry, confirming coalescing. The other five
room-service PIDs, Session 10's owner descriptor/PID, conversation configuration,
and private project configuration remained unchanged. No voice/device action was
sent; launchd fallback stderr stayed unchanged during the probes.

Port 8793 was not restarted, so its logging change remains staged. Any further
activation requires separate owner approval during an idle window; do not restart
endpoint clients, the shared wake service or Session 10. Ten new logging tests and
the full 173-test room suite passed offline; the focused tests passed again after
activation. Health/telemetry alone does not establish spoken-turn/acoustic acceptance.

## Checks

Offline regression suite from the repository root:

```sh
.venv/bin/python -m unittest discover -s projects/operation-jarvis/room-audio -p 'test_*.py'
```

For endpoint health, deployment, and rollback, use the endpoint guides above.
Do not reinstall the retired Pi listener as a remedy for a Mac endpoint failure.
Pi-only provisioning/supervision scripts and setup guides have been deleted;
the shared client retains its historical filename and legacy ALSA backend.
Tracked history remains in Git.

## Completed source-path cutover

On 2026-09-20, the six installed LaunchAgents (Mac client/server, camera, main
room server, shared wake, and Session 10 supervisor) were updated to this canonical
source directory and reloaded during an owner-approved idle maintenance window.
Both endpoints recovered online/idle; Session 10's owner descriptor was unchanged.
Ports, credentials, state directories, service labels, and conversation history
were preserved. Human spoken wake/request/reply verification remains required.

The compatibility symlink and empty `raspberry-pi/` directory have been removed.
Use the canonical Mac installer path. Private pre-cutover agent definitions are
retained outside Git at
`~/Library/Application Support/JARVIS/room-audio-path-migration/20260920-122103/`.
To roll back paths, first recreate `raspberry-pi/room_audio -> ../room-audio`, then
restore/reload those definitions in an approved idle window. Do not restore the
saved owner descriptor over a live conversation; it is verification evidence only.

Keep shared configuration opt-ins when updating agents; do not blindly rerun
endpoint installers. A future cleanup may rename the historical client module
and organize transports/tests into packages; this migration deliberately does not.
