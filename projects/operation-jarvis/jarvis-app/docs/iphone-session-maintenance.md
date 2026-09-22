# iPhone session maintenance

Settings → Pi Terminal → Session Maintenance → **Restart All 10 Pi Sessions**.
The control and SSH client are in the iPhone JARVIS target only. There is no
WatchConnectivity, Siri, widget, or Watch action. Restarting still affects the
underlying sessions used by Watch and room audio.

The confirmation describes the scope: preserve active histories, reopen quit
slots fresh, and refuse busy sessions. Successful completion reconnects the
phone terminal without changing the selected slot.

## Protocol and lifetime

`JARVIS/Terminal/PiMaintenanceSSHTransport.swift` uses a separate non-PTY SSH exec
channel, the saved Pi login, and the already-trusted host key. The only remote
command is `/usr/bin/python3` with the fixed
`scripts/jarvis-mobile-maintenance.py` path. The bounded stdin JSON accepts only
`action` (`start`/`status`) and a canonical UUID `operationID`.

The host writes operation state under `.pi/runtime/mobile-maintenance/`, then
starts a detached worker. Repeating the same UUID is idempotent. A submission
lock prevents competing phone operations; the existing restart lock also
serializes against VS Code restarts. The worker invokes the same restart engine,
records verified progress, and persists success or partial failure. Reconnecting
terminal bootstrap creation shares the restart lock, so it cannot race missing
slot allocation. Existing attachments remain usable.

The phone persists the pending UUID and host identity before submission. After
connection loss or app termination, **Check Restart Status** resumes observation,
not execution. An explicitly absent operation permits **Retry Same Request**
with the same UUID. Changing the configured SSH host while an operation is pending
requires returning to the original host to resolve it. Foreground polling is
bounded; the Mac worker is independent of it.

If status is older than ten minutes, it is reported as unknown, never as success.
Unknown host operations block new mobile submissions. Investigate the Mac worker
and restart lock before manually archiving an unresolved JSON record; do not
blindly resubmit. Finished records are retained locally for diagnosis.

## Verification / deployment

Host tests:

```sh
python3 -m unittest discover -s projects/operation-jarvis/jarvisd/tests -p 'test_mobile*py'
```

Generate the Xcode project using `xcodegen generate` from `jarvis-app`, then build
and sign through the normal iPhone deployment workflow. Host scripts are used
from the checkout; no new daemon or network listener is required. Installing the
app is a separate step. Simulator compilation and mocked host tests do not
constitute an on-device restart test.
