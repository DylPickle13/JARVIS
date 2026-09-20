# Shared Mac room wake worker

`shared_room_wake.py` runs one inference lane for the PowerConf and indoor-camera
listeners. Device capture, playback, server ports, room contexts and credentials
remain in the existing clients. This is deliberately **not** one mixed microphone
stream or one shared openWakeWord history.

- Three shared immutable ONNX sessions: mel frontend, embedding model, wake model.
- Independent openWakeWord model/preprocessor buffers and wake streaks per room.
- One thread per ONNX session; intra/inter-op thread spinning disabled.
- RMS silence gate (default 120 int16 units), 400 ms buffered pre-roll and 1 s
  hangover. The existing command VAD threshold remains 300. Quiet frames never
  reach inference. No captured audio is persisted by this worker.
- Original 80 ms inference chunks, threshold 0.75 and two-hit requirement retained.
- First valid wake acquires an 8-second room lease. Accepted command capture and
  response playback renew it every 500 ms. The idle grace includes the existing
  five-second follow-up window. Other rooms cannot wake or submit commands while
  owned. A dead client loses ownership after eight seconds without renewal.
- Existing active-room interruption behavior is unchanged. The other room cannot
  interrupt. After the conversation, allow up to eight seconds before switching.
- Owner-only Unix socket and directory; bounded messages/timeouts; failure stops
  wake admission, rather than silently falling back to duplicate local inference.

## Deployment (mac-mini-64 only)

The existing PowerConf and camera endpoints must already be configured.

```sh
ROOM=projects/operation-jarvis/room-audio
python3 "$ROOM/configure_shared_room_wake.py"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.operation-jarvis.room-wake.plist"
# Wait for “Shared wake ready” in the worker output log before reloading clients.
launchctl bootout "gui/$(id -u)/com.operation-jarvis.room-audio-mac-client"
launchctl bootout "gui/$(id -u)/com.operation-jarvis.room-audio-camera"
sleep 3  # launchd teardown is asynchronous; immediate bootstrap can fail with EIO
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.operation-jarvis.room-audio-mac-client.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.operation-jarvis.room-audio-camera.plist"
```

Worker state/logs/backups: `~/Library/Application Support/JARVIS/room-wake/`.
Configuration adds `JARVIS_ROOM_WAKE_SOCKET` and `JARVIS_ROOM_WAKE_ROOM` to the
existing client LaunchAgents, not their private credential files. Re-running the
original endpoint configurators may remove these opt-ins; re-run shared config
and reload the affected agents afterward.

Deployment cleanup: after successful user acoustic testing, the initial rollback
backups and temporary test log were deleted at the user's request. Automated
rollback is therefore unavailable for this deployment.

When backups exist, rollback: run `python3 "$ROOM/configure_shared_room_wake.py" --rollback`, then
boot out/reload both client agents as above. Finally boot out
`gui/$(id -u)/com.operation-jarvis.room-wake` and remove its LaunchAgent plist to
prevent it starting at login. The first pre-shared client definitions are retained
in `room-wake/backups/`; rollback does not revert any unrelated source changes.

To disable silence gating for diagnosis, add `--silence-threshold 0` to the worker
LaunchAgent's ProgramArguments and reload it. Model/session sharing and one-room
ownership still apply. Do not change capture rates without separate device tests.

## Validation

Run the room suite with the repository Python (the capture-only venv lacks server
ASR dependencies):

```sh
cd projects/operation-jarvis/room-audio
/Users/dylanrapanan/JARVIS/.venv/bin/python -m unittest discover -p 'test_*.py'
```

Deployment measurements, 2026-09-19:

- Before: PowerConf ~59.9%, camera ~44.6% in `ps` snapshots.
- After: 30-second CPU-time deltas: worker 4.61%, PowerConf 1.73%, camera 1.46%;
  total **7.8% of one core**. Snapshots and interval averages are not identical
  methodologies, and savings depend on room activity.
- Synthetic continuous-noise benchmark: two streams x 20 seconds of audio used
  0.809 CPU seconds in the shared single-threaded configuration.
- Confirmed both frontend ONNX sessions share object identity while room
  preprocessors are distinct; exactly three sessions loaded for both rooms.

Still requires a human acoustic check: wake from each room at normal and distant/
quiet speech levels, verify replies stay in that room, try a competing wake during
an active response, then try the other room after the idle grace expires. Automated
arbitration tests do not establish real-world wake accuracy.
