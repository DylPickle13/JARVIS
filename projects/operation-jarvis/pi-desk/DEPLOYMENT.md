# Initial deployment — 2026-09-22

## Implemented

- Consolidated trial UI units into persistent `pi-desk.service`, **enabled at boot**.
- Kept `multi-user.target` and the existing pi account; no new account or sudo policy.
- Retired `mac-graphical-terminal.service`, `mac-sessions-trial.service` and the
  transient `mac-session-grid-live` user service; stopped the old local
  `mac-session-panels` tmux server. Mac sessions were not killed or recreated.
- New local socket: `pi-desk`. New manual command: `~/.local/bin/pi-desk`.
- Legacy `mac-sessions` is a compatibility wrapper; obsolete connect/grid/display
  scripts were archived before removal.
- Added per-pane reconnect, pane reconciliation/order recovery, read-only live
  lifecycle feed reconnect and strict freshness handling.
- Retained fullscreen, black background, emoji support, 24/12 pt menu/workspace
  fonts, US keyboard and persistent Wi-Fi power-save disablement.

## Backup

Pi pre-migration snapshot: `~/.local/state/pi-desk/backups/20260922T150937Z/`.
A secret-free archive of that allowlisted snapshot is retained in this project's
`backups/` directory. It excludes SSH configuration/keys, known_hosts, presence
identity files, backend state, session transcripts, and environment files with
credentials. Labwc's keyboard-only environment file is included.

The Mac's previous read-only status helper was separately retained under
`~/.local/state/pi-desk/backups/` before replacement.

## Verified

- **13 tests passed on both Mac and Raspberry Pi**, including fresh/stale/future
  status, invalid telemetry, source projection, retry after failed SSH start,
  group idempotency, missing-middle-pane repair with numeric ordering,
  dead-pane respawn, and session 10 remaining solo.
- `systemd-analyze verify` accepted the installed service.
- `systemctl is-enabled pi-desk.service` → enabled; active, with zero restarts.
- Terminated only the UI's read-only status SSH client: it automatically obtained
  a new PID and resumed its stream.
- Terminated only session 1's Pi-side SSH display client: its wrapper automatically
  reconnected with a new SSH PID; the remote Mac session stayed running.
- Opened group 1 through the graphical menu: all three tagged panes were alive.
  F12 returned to the menu and closed only the workspace display client.
- Old trial units no longer running.
- Presence/audio user services and system Bluetooth/SSH remained active.
- Approximately 658 MiB available memory, 56°C, no active thermal throttle;
  `0x20000` was a historical soft-temperature-limit flag only.

## Reboot acceptance — passed 2026-09-22, 11:19 EDT

Owner-authorized reboot confirmed by a changed boot ID. Pi Desk automatically
started on tty3 at 1080p/60 Hz, enabled and active with zero restarts. The live
status SSH stream resumed. Opened group 1 after boot: sessions 1–3 were alive;
F12 returned to the grid. Presence, audio proxy, Bluetooth and SSH recovered;
the backend reported fresh presence data from both zones. Wi-Fi power saving
remained off. No failed system or user units. Left the display at the menu.

## Connection feedback and health strip — 2026-09-22, 11:30 EDT

Added explicit SSH connection/retry and backend-data availability messages, plus
Wi-Fi association signal, Mac ping latency, CPU temperature and presence-service
active state. Read-only checks run off the UI thread every 10 seconds, with
bounded command timeouts and 25-second reading expiry. No radio scans or
household actions. Service state is explicitly not sensor freshness or occupancy.

- **21 tests passed on Mac and Pi**, including message transitions, watchdog,
  missing commands/data, ping failure, timeouts, single-worker bounds, expired
  readings, worker failure, and the grid layout with its new health strip.
- Live diagnostic stream went from connected → SSH disconnected/retry → connected
  after terminating only its own diagnostic SSH client.
- Live health sampling returned Wi-Fi signal, ping latency, temperature and active
  presence service. Group 1 opened with three live panes; F12 returned to the menu.
- Pi Desk remains boot-enabled, active, with zero restarts; presence and audio
  proxy services remained active throughout this display-only update.
- Pre-update Pi rollback: `~/.local/state/pi-desk/backups/20260922T153003Z/`.

## Visual refinement — 2026-09-22, 15:05 EDT

Session text increased to 14 pt; menu remains 24 pt. Cards now use subtle grey
borders, bright bold numbers and coloured lifecycle dots instead of full-card
colour. Normal diagnostics are muted grey; uncertainty is amber and explicit
service failure red. Active local panes have bold cyan titles and cyan borders;
inactive titles/status chrome are muted. Pure-black backgrounds retained.

All 23 tests passed on Mac and Pi, including diagnostic colours and narrow-card
label fit. Applied the configuration to the existing local `pi-desk` tmux server;
verified expanded active/inactive title styles, 14 pt workspace launch and F12.
Presence and audio services stayed active. Pre-update rollback:
`~/.local/state/pi-desk/backups/20260922T190534Z/`.

## Direct session selection — 2026-09-22, 15:10 EDT

Menu now accepts session numbers 1–10 followed by Enter, opens the corresponding
three-session workspace (10 alone), and focuses the requested session. Removed
row-number shortcuts from the cards; added a visible input prompt, Backspace
editing and Escape clearing. Explicit Enter disambiguates 1 from 10.

All 26 tests passed on Mac and Pi. Live checks: `5` + Enter opened 4/5/6 with
session 5 focused; `10` + Enter opened session 10 alone; F12 returned to the menu.
Presence/audio remained active. Pre-update rollback:
`~/.local/state/pi-desk/backups/20260922T191052Z/`.

## Persistent selector and cross-group navigation — 2026-09-22, 15:25 EDT

Replaced the fullscreen menu with **two native tmux status rows at the top**:
clickable numbered session/status dots, then compact connection/health readings.
The bar is not a pane, so navigation cannot get stuck in it. One fullscreen 14 pt
Foot window keeps coding sessions visible at all times. The current 173×46 display
retains 43 content rows per coding pane plus its title/border row.

F12 opens numeric session selection without hiding the workspace. Ctrl+Left/Right
moves through sessions 1–10, switching groups and focusing the requested session;
it stops at the endpoints. The last selected session is persisted as a number.
Existing healthy groups switch without rebuilding layouts; damaged groups retain
pane-repair behaviour. A lock serializes selection and another prevents duplicate
persistent displays. Status/health collection continues while coding.

- **32 tests passed on both Mac and Pi**, including selector ranges, status styles,
  state restoration, group focus, and cross-group/end-point navigation.
- Live F12 selection of 4, Ctrl+Left → group 1/session 3, Ctrl+Right → group 2/session 4.
- Live 10 → Left → 9 and Right → 10; another Right stayed at 10.
- Actual tmux SGR mouse-input test on session 10's range selected group 4/session 10.
  Used a temporary ignore-size local client; terminal contents were discarded,
  not logged. The temporary client was closed afterwards.
- Restarted the display service and verified automatic restoration of group 2,
  focused on session 4. Two-row bar/live health returned; zero service restarts.
- Presence/audio proxy, Bluetooth and SSH remained active; boot enablement retained.
- Pre-update rollback: `~/.local/state/pi-desk/backups/20260922T192538Z/`.

This supersedes the earlier F12-to-fullscreen-menu and 24 pt menu behaviour.
The existing service's boot acceptance was tested earlier; this version was
service-restart tested, not subjected to another full Pi reboot.

## Cleanup — 2026-09-22, 15:38 EDT

Removed the retired curses/fullscreen-menu implementation and its obsolete UI
and keyboard-buffer tests. Shared transport/workspace code now lives in `core.py`;
`desktop.py` is the sole display entry point. The installer backs up the old app
before removing `terminal.py` and stale Python caches. Blank/health-bar clicks
are ignored rather than displaying an invalid-selection message. Attachment
failures now propagate their exit status to the display service.

- **25 current tests passed on Mac and Pi.** Retired-menu tests were removed and
  overlapping tests consolidated; recovery, status freshness, diagnostics,
  all-ten-session focus, group-boundary navigation, click routing and migration
  cleanup remain covered.
- Live F12 selection and 4 → Left → 3 → Right → 4 verified after deployment.
- Installed SHA-256 manifest verified; no `terminal.py` remains in the installed app.
- Removed six explicitly identified temporary deployment/staging directories.
  All nine Pi rollback backups, saved selection and active lock files retained.
- Pi Desk, presence/audio, Bluetooth and SSH remained healthy; zero display restarts.
- Pre-cleanup rollback: `~/.local/state/pi-desk/backups/20260922T193852Z/`.

## Still untested deliberately

- Prolonged Wi-Fi loss, Mac reboot, and TV hotplug. Retry behaviour is tested
  without deliberately taking the household's network or services offline.

No new public ports, HTTP listeners, household automations, browser installations,
Mac session-layout changes, or credential copies were introduced.
