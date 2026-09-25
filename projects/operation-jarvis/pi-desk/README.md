# Pi Desk

One lightweight terminal workspace for the same ten Mac-hosted Pi Coding Agent
sessions, on **mac-mini-64, mac-mini-16 and Raspberry Pi**. No browser, desktop
streaming, or VS Code dependency. The agents always run on mac-mini-64.

## Open it

```sh
pi-desk
```

This opens the shared workspace **in the current terminal**, just as `pi` opens
its TUI. Open a new terminal after installation for the PATH update, or run
`~/.local/bin/pi-desk`. On Macs, `~/Applications/Pi Desk.app` opens a dedicated
black Terminal window with 14 pt Menlo. Existing terminal profiles are untouched.
The app sets its own profile, not Terminal's default profile.

On the Raspberry Pi, the existing Foot/labwc fullscreen service still starts at
boot. `pi-desk-display` (or legacy `mac-sessions`) switches to that display;
`pi-desk` itself is now the portable terminal command. Multiple terminal viewers
are supported, with one elected status monitor per machine and failover on exit.

## Interface

The persistent `PI-DESK` top row contains ten clickable session numbers and lifecycle
dots, with shortcut hints aligned at the right (abbreviated below 120 columns). Numbers
use two digits, with muted separators between 01–03, 04–06, 07–09, and 10; there
are no group labels. Running and compacting dots alternate between bright
and clearly dim shades every 0.75 seconds (a 1.5-second full cycle); text, focus
styling, and other states stay steady. This uses the existing shared monitor, not terminal blink support.
A second row appears only for connection/diagnostic warnings and disappears when
healthy, returning its terminal row to the coding panes. Healthy diagnostic values are hidden.
Coding workspaces remain **1/2/3**, **4/5/6**, **7/8/9**, or **10 alone**. No extra menu pane.
Last selected session is restored independently on each machine.

| Control | Action |
| --- | --- |
| Click a number | Open its group and focus that session |
| F12, number, Enter | Select session 1–10 |
| Ctrl+A, then g | Selection alternative for Mac function/media keys |
| Ctrl + ←/→ | Previous/next session, crossing group boundaries |
| Click a pane | Focus that pane |
| F10 or Ctrl+A, then Shift+R | Explicit start/restart confirmation popup |
| Ctrl+A, then d | Leave this viewer; agents keep running |

Navigation stops at 1 and 10. Plain arrows are unchanged. Font/fullscreen controls
belong to the terminal: Cmd+Plus/Minus and Ctrl+Cmd+F on macOS; Ctrl+Plus/Minus and
Alt+F11 in the Pi desktop. The Pi retains 1080p, 14 pt DejaVu/Noto Emoji and a black
background. The Mac app requests a 173×47 terminal; ordinary CLI usage preserves
the user's terminal size/profile.

## Start/restart agents without VS Code

```sh
pi-desk restart            # press Enter to confirm; Ctrl+C to cancel
pi-desk restart --dry-run  # preflight only, no changes
```

The F10 popup uses this same command. It delegates to the host's existing
`jarvis-mobile-vscode-restart.py --all` helper rather than duplicating its safety
logic. All ten identities and status records must pass preflight. Busy, stale or
ambiguous sessions block the operation. Existing conversations are resumed by
explicit session path; missing/dead slots start fresh. This affects **every**
viewer. Partial failures are reported and never automatically retried.

Opening Pi Desk, switching groups, recovering SSH, and closing a viewer **never
restart agents**. If hosted slots are absent, explicitly use start/restart after
reviewing the confirmation. Existing VS Code tasks remain available as fallback;
they have not been removed or changed.

## Shared app, explicit transport

Installed source: `~/.local/share/pi-desk/` on every machine.
Private machine configuration: `~/.config/pi-desk/client.json`.

| Machine | Backend | Hosted sessions |
| --- | --- | --- |
| mac-mini-64 | `local` | Its existing `jarvis-mobile` socket |
| mac-mini-16 | `ssh` | mac-mini-64's same socket |
| Raspberry Pi | `ssh` | mac-mini-64's same socket |

There is no hostname guessing. A missing config retains the original SSH default;
invalid configuration fails closed. SSH uses the existing alias/keys, strict host
verification, no agent/X11/port forwarding, bounded connect/keepalive timeouts,
and automatic attachment/status reconnection. No keys or credentials are copied.

The separate **local `pi-desk` tmux socket** holds only display panes. Hosted
attachments use `-E -f ignore-size`: they do not update the host's tmux environment
or detach existing clients. No host resize/layout commands are issued by the
viewer. **tmux sizing caveat:** when *all* attached clients have `ignore-size`,
tmux can fall back to the latest client's dimensions and reflow a hosted pane.
The flag is not an absolute guarantee against reflow; this was observed during
Mac acceptance. Agent identities/conversations are unaffected. Only local display
panes are equalized on terminal resize.

## Status and diagnostics

Running green, Idle purple, New cyan, Compacting blue, Offline grey, Unknown amber.
The host projects numbered lifecycle labels from the existing trusted-loopback
jarvisd endpoint every 3 seconds. Local viewing uses a local subprocess; remote
viewing streams the same installed helper over SSH. No transcript data is sent
by the status stream. Samples older than 15 seconds become Unknown; a stream
silent for 12 seconds is retried. Failures never imply that the host is off.

Mac diagnostics show local/SSH mode and local load, without Linux-only commands.
Pi diagnostics retain Wi-Fi association signal, host ping, CPU temperature and
presence-service state: 10-second sampling, bounded commands, 25-second expiry.
**Presence active means only that the service is running**, not fresh sensing or
human presence. No radio scans, new ports, privileged health commands or logs.

## Install/update

Python 3.9+ and tmux 3.3+ are required. Macs can install tmux with Homebrew. Both
remote clients must already have a working, trusted `mac-mini-64` SSH alias.
From a reviewed source/staging directory:

```sh
# Primary Mac only:
python3 install.py --backend local

# Secondary Mac:
python3 install.py --backend ssh

# Pi with its existing fullscreen adapter/account/permissions:
sudo systemctl stop pi-desk.service
python3 install.py --backend ssh --pi-desktop
sudo systemctl daemon-reload
sudo systemctl enable --now pi-desk.service
```

`install_pi.py` remains a compatibility entry point for the last option. The Pi
adapter alone depends on labwc, Foot, wlr-randr, HDMI-A-1, tty3 and the existing
pi account/sudo policy. No installer starts/restarts hosted agents. Mac installation
does not touch system services, Terminal defaults, VS Code tasks or other apps.
Only an explicit PATH line is appended to `.zshrc` (Mac) or `.bashrc` (Pi).
The host repository path for maintenance can be set with `--project-root`.

Reopen viewers after updating Python code. If resetting display panes is needed,
stop only the dedicated `pi-desk` socket, **never `jarvis-mobile`**. The Pi service
owns only its compositor/display and does not control presence/audio/Bluetooth/SSH.

## Implementation

- `cli.py`: common `pi-desk` entry point and confirmed maintenance.
- `backend.py`: validated local/SSH commands and cleaned nesting environment.
- `connect.py`: reconnecting attachment; `connect.sh` is a compatibility shim.
- `desktop.py`, `core.py`: shared UI, selection, status stream and pane recovery.
- `native_navigation.py`: in-tmux arrow switching with live pane validation; the status
  monitor saves selection in the background. No Python process per healthy keypress.
- `navigate.py`: fallback for missing or unhealthy workspaces; imports full recovery
  only when needed.
- `health.py`, `status_stream.py`: bounded diagnostics and host lifecycle projection.
- `install.py`: common deployment, manifest and allowlisted rollback copies.
- `launch.sh`, `config/`: optional Pi fullscreen adapter, shared tmux configuration,
  and Mac Terminal launcher.

## Backups, rollback and verification

Private rollback copies: `~/.local/state/pi-desk/backups/<UTC timestamp>/` on each
machine. All earlier backups remain intact. Shell profiles are **not** copied
because they may contain secrets; undo only the exact line marked `# Pi Desk CLI`
if removing the command. No credentials, IRKs, SSH configuration or transcripts
belong in Git or project backups. Historical source archive: [`backups/`](backups/).

To roll back, close Pi Desk viewers (stop its Pi service when applicable), restore
reviewed app/config/launcher files from that machine's backup or install a known-good
source revision with the correct backend. Do not blindly extract over `$HOME`.
An initial Mac install can be removed by deleting its dedicated app, launcher and
configuration, and removing the exact added PATH line; leave hosted sessions alone.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_pi_desk
sh -n connect.sh && sh -n launch.sh
pi-desk --help
tmux -L pi-desk list-clients -F '#{session_name} focus=#{@pi-desk-session}'
```

Tests use isolated sockets, temporary state and sleep processes, never real agent
restarts. Deployment results and acceptance limits: [DEPLOYMENT.md](DEPLOYMENT.md).
