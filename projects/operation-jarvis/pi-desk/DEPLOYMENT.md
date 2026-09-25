# Startup optimization — 2026-09-24, 22:40 EDT

Deployed startup-only changes to Mac and Pi without restarting any viewer, service,
or hosted agent. Installed desktop code was patched by function so the separate
`attach_viewer()` reliability changes remain source-only. Session 2's already-installed
Mac timeout handling was preserved; its two stale manifest entries were reconciled
after confirming exact source hashes. All installed manifest entries now verify.

- Configuration cache: server-local `@pi-desk-config` fingerprints desktop.py,
  native_navigation.py, tmux.conf and install path. A new server or changed file
  triggers configuration. Pane readiness is NEVER cached: choose() still validates
  live tags/order/liveness and retains recovery. Use `configure(force=True)` to
  restore bindings changed manually without modifying configuration files.
- Initial setup loads all six native bindings from a private temporary tmux config
  in one client call (then deletes the file). A direct argv batch exceeded tmux's
  message-size limit in isolation and was rejected before deployment.
- Status rows and row count are applied in one command queue.
- Added real-server coverage for cache reuse/invalidation, forced binding repair,
  both warning-row states, all six native bindings, and unchanged dummy pane
  identities. Fixed an older state-restoration test that inadvertently read the
  live server. These focused tests passed on both platforms. The full working-tree
  suite (including the separate reliability/timeout changes) passed 51 tests on
  Mac; Pi ran 51 with one zsh-only skip.

Installed CLI -> first PTY output, healthy dummy workspace, five openings/platform:

| Platform | Previous median | Updated repeat-open median | First open, uncached config |
| --- | --- | --- | --- |
| Mac | 116.44 ms | 65.73 ms (65.19–67.89) | 95.66 ms |
| Pi | 854.67 ms | 557.79 ms (541.16–562.06) | 807.37 ms |

Repeat-open samples exclude the first configuration-building run. Approximately
44% faster on Mac and 35% on Pi. These are isolated software timings, not physical
screen latency or fresh SSH/session startup. The real installed status monitor ran,
with its election lock/state isolated. The local harness remains at
`/tmp/pi-desk-full-startup.py`; the temporary Pi candidate stage was removed after
validation and deployment. No claim that cold agent connections or the original
blocked-write fault are improved.

The deployment backups were subsequently removed after validation; no rollback
copies remain in the runtime backup directories. Live pane identities
were unchanged at deployment. Optimizations apply on the next open; existing viewers
were left alone. If rollback is needed, restore the prior source files and regenerate
the install manifest; never kill the hosted server. mac-mini-16 was untouched.

# Multiple-viewer acceptance — 2026-09-24, 22:05 EDT

Isolated synthetic-output tests passed on Mac and Pi for two independent viewer
terminals, two seconds with both readers paused, closing one while retaining the
other, attaching a replacement, closing all clients, and overlapping two clients
on the same terminal then closing them separately. The dummy pane PID was preserved
throughout; no live display or agent sockets were used. Two viewers alone did not
reproduce the original stall. This does not rule out a timing-dependent interaction.

`probe_viewers.py` records the reusable test. On Mac it additionally exercised the
new source wrapper with actual SIGTERM, SIGHUP, and a SIGSTOP-stopped tmux child;
the owned child was reaped in every case. 14 checks passed, followed by all 46 unit
tests at that point (including status-monitor election/failover). The Pi ran the
eight raw tmux multi-viewer checks, not wrapper acceptance at that point. Subsequent
updated full-suite validation passed 51 tests on Mac and ran 51 on Pi with one
zsh-only skip. The actual signal/stopped-child wrapper acceptance remains Mac-only.
A probe-cleanup exception on macOS was fixed and its unique leftover test socket
removed; the full Mac probe then passed including cleanup.

Hardening remains source-only. Actual-signal wrapper acceptance on Pi and deployment
verification remain outstanding. No claim of a root-cause fix or deployment.

# Viewer reliability investigation — 2026-09-24, 22:01 EDT

Session 2 recovered the Mac display server by flushing the stale terminal's output
queue. A process sample showed the tmux server blocked in `writev` from its terminal
write callback. This identifies the blocking location, not the initiating cause.

Isolated controlling-PTY tests on Mac and Raspberry Pi exercised a continuously
printing dummy pane, fresh attach, two seconds without reading output, resumed
reading, terminal hangup, and reattach. Neither reproduced a stall. Each server
remained responsive (Mac queries 19.6–33.5 ms; Pi 20.6–33.6 ms), and the dummy
pane identity was preserved. These are command response times, not display latency.
Live viewers and hosted agents were not changed by these probes.

Source-only hardening in `desktop.attach_viewer`: own/reap the display client on
HUP, TERM or interruption; bounded TERM then KILL for an unresponsive/stopped client;
restore prior signal handlers. Never signal a server or process group. Three new
mocked cleanup tests brought the Mac suite to 46 passing tests at that point.
Subsequent full-suite runs passed 51 tests on Mac and ran 51 on Pi with one zsh-only
skip. Actual signal/PTY wrapper acceptance was run on Mac, not Pi. Session 2's timeout
handling is preserved. This patch is NOT deployed and does not establish prevention
of the original blocked-write fault. Validate the wrapper on Pi and verify installed
manifests if deployment is ever authorized.

# Cross-platform software latency — 2026-09-24, 21:53 EDT

Isolated Pi-local PTY input injection to first readable terminal output, using
installed native bindings, selector and ten dummy panes: 36 switches, median
31.081 ms, range 23.945–56.810 ms. Within-group median 30.869 ms; cross-group
31.223 ms. Mac source benchmark: 36 switches, median 5.931 ms, range
3.397–13.059 ms; within-group 6.146 ms, cross-group 5.060 ms.

These exclude physical keyboard, Foot/VS Code rendering, TV processing and scanout.
Dummy panes also exclude live agent output load. Focus was verified after each
timed interval. The Pi output is 1920×1080 at 60 Hz. No camera measurement exists.
`benchmark_navigation.py` provides the isolated cross-platform reproduction;
periodic status redraws are disabled to avoid false first-output measurements.

Mac native navigation files now installed with manifest updates; active Pi Desk
bindings refreshed without disconnecting viewers. Hosted pane identities unchanged.
41 Mac tests passed. Existing viewer monitor code updates on reopening Pi Desk;
native bindings are active immediately. Pi installation was already native and was
not changed. mac-mini-16 untouched. The historical Mac rollback snapshot was later
removed; no runtime rollback copy remains. Never restart agents.

# Native tmux navigation — 2026-09-24, 18:18 EDT

Deployed to Raspberry Pi only. Healthy Ctrl + arrow navigation now runs directly
inside tmux, validating live workspace pane order/tags/window/liveness before
switching. Missing/unhealthy groups fall back to the existing Python recovery.
No Python or shell launch for a normal keypress. tmux records the last selection
synchronously; the elected status monitor atomically persists it in the background.
Reopening a viewer also reads the live tmux selection to avoid persistence lag.

41 tests passed on Mac and Pi (one zsh test skipped on Pi). Isolated tests exercise
actual key bindings, both directions/all groups, clamping, persistence, unchanged
pane PIDs and refusal of the fast path for a missing pane. Live Pi traversed 1–10
and back, including recovery of previously uncreated groups, then restored and
persisted the original selection. Key dispatch plus verification measured 78–96 ms
(median 90 ms); this is not a physical keyboard-to-screen latency measurement.
Only the Pi display service was refreshed; hosted agents were not restarted.

Pi backup: `~/.local/state/pi-desk/backups/20260924T221807712278Z-native-navigation/`.
Rollback restores backed-up desktop/navigation/installer/manifest files, removes
new `native_navigation.py`, then restarts the Pi display service. Mac installations
remain on the prior lightweight helper; source/installer include the native path.

# Navigation latency and shortcut labels — 2026-09-24, 18:08 EDT

Measured full display imports at 362–375 ms on Raspberry Pi for every arrow press.
Added `navigate.py`: lightweight imports, two batched tmux calls, existing selection
lock and atomic selection persistence. Missing/dead/mistagged groups retain the
full recovery path. Direct arrow bindings and prefix fallbacks use the new helper.
Displayed navigation hints now say `Ctrl + ←/→`; the user configured the Mac to
accept those keys directly. No macOS keyboard settings changed by this patch.

41 tests pass on Mac and Pi (Pi skips the Mac/zsh-specific test). Isolated tmux
coverage traverses all groups in both directions, checks endpoint clamping,
selection persistence, invalid-client rejection and unchanged pane identities.
Live Pi end-to-end navigation measurements: old path 610–735 ms, new 321–403 ms.
This reduces delay but does not establish zero-latency navigation.

Deployed navigation, desktop, tmux config and installer to Mac/Pi; refreshed only
viewers. mac-mini-16 untouched. Backups under `~/.local/state/pi-desk/backups/`:
Mac `20260924T220816052394Z-navigation`; Pi `20260924T220759345425Z-navigation`.
Rollback restores backed-up files/manifest and removes newly added `navigate.py`.

# SSH attachment quoting fix — 2026-09-24, 17:58 EDT

User reported persistent pane errors despite an active display and healthy status
projection. Capturing the Pi panes revealed `zsh:1: jarvis-ios not found`: Python's
`shlex.join()` leaves `=jarvis-ios` unquoted, triggering zsh command-path expansion
before tmux receives the exact-session target. `Backend.run_on_host()` now quotes
every argument, including equals-prefixed targets and embedded apostrophes.

40 tests passed on Mac, including execution through real zsh for all ten target
names. Deployed `backend.py` to Raspberry Pi with manifest update and rollback:
`~/.local/state/pi-desk/backups/20260924T215819930853Z-ssh-quote/`.
Respawned only its six existing `pi-desk` display connectors (not hosted agents).
All six SSH viewers subsequently appeared as attached clients on the host and
rendered session content. No Mac installation or mac-mini-16 changes in this fix.
The healthy status projection does not currently prove successful pane attachment;
service-active/status-row checks alone must not be treated as viewer acceptance.

# Warning-only health row — 2026-09-24, 17:19 EDT

Updated `desktop.py` and `config/tmux.conf` on mac-mini-64 and Raspberry Pi;
mac-mini-16 deliberately left unchanged because it is no longer used for Pi Desk.
Healthy displays now use one status row; warnings add a second row only while
needed. Only unhealthy fields are shown. Selector shortcuts are right-aligned,
with compact hints below 120 columns; session click ranges are unchanged.

**39 tests passed on each updated machine**, including isolated live-tmux tests
verifying the warning row removes/restores exactly one line of pane height without
changing pane PIDs. Tests never attach real agents. Live Mac and Pi displays both
confirmed one-row healthy mode; Mac shortcuts confirmed right-aligned in the live
format. Only viewers were refreshed (VS Code integrated terminal on Mac; display
service on Pi). All ten hosted session/pane/PIDs unchanged. Rollbacks:

- Mac: `~/.local/state/pi-desk/backups/20260924T211619003272Z-warnings/`
- Pi: `~/.local/state/pi-desk/backups/20260924T211719038733Z-warnings/`

These focused backups contain only `desktop.py`, `config/tmux.conf`, and
`manifest.json`; restore those to the installed app, then reopen the viewer.
No reboot or prolonged network-outage test performed for this revision.

# Enter-only restart confirmation — 2026-09-24, 17:02 EDT

Updated `cli.py` on all three machines with per-machine rollback copies and
refreshed manifests. F10 / `pi-desk restart` now requires only Enter at an
interactive prompt. Ctrl+C, EOF, nonempty input and noninteractive execution
cancel without invoking the host helper. Existing host preflight checks remain
unchanged. **37 tests passed on each machine**; no real agents were restarted.
An already-open confirmation popup must be closed and reopened to load the change.
SSH to both remote hosts succeeded again during this update; the earlier network
failure's cause remains unconfirmed, and the older extended acceptance checks
below were not rerun as part of this focused patch.

# Portable deployment — 2026-09-24

Installed the same shared app on all three machines. mac-mini-64 is explicitly
`local`; mac-mini-16 and Raspberry Pi are explicitly `ssh` viewers of its ten
existing sessions. `pi-desk` opens the current terminal; Mac app shortcuts open
Terminal using a dedicated `.terminal` profile without AppleScript/Automation
permission. The Pi's fullscreen service is retained separately.

## Acceptance

- **36 tests passed on each of the three machines.** The existing host restart
  helper's **17 tests** also passed; that helper and VS Code tasks were not edited.
- All three interactive viewers were observed running. Both Macs reported live
  status and the correct local/SSH mode. The Pi's first portable deployment
  reported live status; the final launcher-only update was observed active and
  connecting before subsequent LAN access was blocked.
- Primary Mac: all ten display panes, focus selection, group-boundary navigation,
  source manifest and F10 popup tested. Popup closed without confirming restart.
- All ten original host session names, pane IDs and **agent PIDs stayed unchanged**.
  No real agent restart was attempted while work was running.
- Observed tmux caveat: with every host client marked `ignore-size`, attaching
  another viewer can still reflow host pane dimensions. No host resize/layout
  commands were issued. See README; do not describe this flag as an absolute
  geometry guarantee.
- Multiple-viewer monitor election/failover covered by tests; repeated installation
  preserves profiles, retains backups and adds the PATH marker only once.
- mac-mini-16 required tmux 3.7c via Homebrew. Its dependency installation also
  upgraded ca-certificates/OpenSSL; no REAPER/oMLX service restart was requested.
- Latest backups: primary Mac `20260924T204203879898Z`, secondary Mac
  `20260924T204335426464Z`, Pi `20260924T204342822825Z`, each under that machine's
  `~/.local/state/pi-desk/backups/`. Earlier backups retained.

## Remaining acceptance / blocker

After installation and successful Mac GUI checks, new LAN requests from the
primary Mac began returning **No route to host** for both trusted remote hosts.
The local interface and routes remained present. macOS Local Network permission
is a possibility, **not a confirmed diagnosis**; no permission, firewall, route or
network-service settings were changed to bypass it. Final remote all-ten-pane /
F10 checks and cross-host manifest comparison remain pending reconnection.

Only allowlisted release staging remains remotely at
`mac-mini-16:/tmp/pi-desk-portable.e6JLkp` and
`raspberrypi:/tmp/pi-desk-portable.PQumK1`; remove those after reconnection, not the
rollback backups. No full reboot or prolonged-disconnection test was performed.
The existing VS Code workflow remains an untouched fallback.

---

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
