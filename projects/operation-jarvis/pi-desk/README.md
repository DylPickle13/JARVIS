# Pi Desk

Lightweight living-room access to the Mac's ten Pi Coding Agent sessions using
**labwc + Foot + local tmux + SSH**. No browser or streamed desktop.

## Interface

A persistent **two-line top bar** replaces the fullscreen menu:

1. All ten session numbers with live coloured dots. Click a number to open its
   group and focus that session. The current group is shaded; the focused number
   is bold cyan.
2. Compact connection status, Wi-Fi signal, Mac ping, temperature and presence
   service state.

The rest of the screen is always a coding workspace: **1/2/3**, **4/5/6**,
**7/8/9**, or **10 alone**. The bar is native tmux status chrome, not a fourth
pane: it consumes only two rows and cannot trap pane-navigation shortcuts.
At the deployed 173×46 terminal size, coding panes retain 43 content rows plus
their existing title/border row.

| Control | Action |
| --- | --- |
| Click a session number in the top bar | Open its group and focus that session |
| `F12`, type `1`–`10`, Enter | Select a session without hiding the workspace |
| Escape in the F12 prompt | Cancel selection |
| `Ctrl+Left/Right` | Previous/next session, including across group boundaries |
| `Ctrl+A`, then Left/Right | Alternative previous/next session navigation |
| Click a coding pane | Focus that pane |
| `Ctrl` + `+` / `-` | Adjust terminal font size |
| `Alt+F11` | Toggle fullscreen |

**4 → Left opens 1/2/3 focused on 3; 3 → Right opens 4/5/6 focused on 4.**
Navigation stops at 1 and 10, rather than wrapping. Direct Ctrl+Arrow shortcuts
are consumed locally, not passed to the remote editor for word navigation.
Plain arrows are unchanged. Session selection is serialized to handle rapid clicks.

Pi Desk starts at boot and restores the last session chosen through its controls
(default 1). All text is **14 pt**, with DejaVu Sans Mono and Noto Color Emoji,
a pure-black background, US keyboard and 1080p output. The active coding pane has
a cyan border/bold title; inactive chrome is muted. The old standalone fullscreen
menu remains in source for rollback/reference but is not launched.

Manual start on the Pi: `~/.local/bin/pi-desk` (legacy `mac-sessions` redirects here).
There is no separate menu window or automatic return to a menu when a group closes.

## Status and diagnostics

Session dots: Running green, Idle purple, New cyan, Compacting blue, Offline grey,
Unknown amber. They use the same jarvisd lifecycle data as the iPhone app, streamed
over existing key-authenticated SSH every **3 seconds**, continuously while coding.
Only numbered lifecycle labels are streamed, never conversation contents.

The connection banner distinguishes connecting/reconnecting, disconnected SSH,
live session data, and a connected Mac with unavailable backend data. Source
samples older than 15 seconds become Unknown; a stream silent for 12 seconds is
restarted. SSH failures do not prove that the Mac is powered off.

Health sampling runs in one background worker every **10 seconds**, with 2-second
command timeouts and 25-second expiry. It reads Wi-Fi association signal (`wlan0`),
one ICMP ping to the existing Mac SSH alias, CPU temperature, and the local
presence unit's state. Missing data shows `--`/unknown. Normal readings are muted;
uncertainty is amber and explicit service failure red.

**Presence service: active means a running unit, not fresh sensor data or anyone's
location.** Ping `no reply` does not prove the Mac is offline. No radio scans,
privileged health commands, new ports, credentials or persistent diagnostic logs.

## Architecture

- `desktop.py`: persistent tmux attachment, top bar, click/keyboard routing,
  ordered cross-group navigation and last-session persistence.
- `terminal.py`: shared bounded status feed, tagged-pane recovery and legacy grid.
- `health.py`: read-only asynchronous diagnostics.
- `connect.sh`: reconnecting SSH client per pane (3-second retry, 5-second
  connection timeout/keepalives, two missed keepalives).
- `status_stream.py`: read-only Mac jarvisd lifecycle projection.
- `launch.sh`, `config/`: fullscreen display, local tmux, labwc and system service.
- `install_pi.py`: allowlisted backups and installation; activation stays explicit.

The dedicated **local `pi-desk` tmux socket** contains the grouped workspaces.
The remote Mac uses **`jarvis-mobile`** and `attach-session -f ignore-size`.
Mac sessions are never recreated, killed, resized, or detached from other clients.
Group switching affects only the Pi's display. Existing Mac layouts may therefore
leave unused space in a Pi pane. Missing/dead local panes are repaired on selection;
healthy groups switch without rebuilding their layouts.

## Install/update

This is hardware-specific: existing `pi` account/UID 1000, Raspberry Pi OS,
HDMI-A-1, tty3, and the established `mac-mini-64` SSH alias.

```sh
sudo apt-get install --no-install-recommends \
  labwc foot tmux wlr-randr fonts-dejavu-core fonts-noto-color-emoji
```

Python 3/OpenSSH are OS-provided. `wtype` is for display smoke tests, not runtime.
Keep existing SSH host verification, `IdentitiesOnly yes`, `ForwardAgent no`, and
private keys outside this project. The existing pi account's sudo policy is not
created or broadened here. This is a trusted household console, not a locked kiosk.

On the Mac, back up `~/.local/bin/pi-grid-status`, then install `status_stream.py`
there. It reads existing trusted-loopback `http://127.0.0.1:8790/api/v1/state`;
backend/authentication failures become Unknown, never a reason to hardcode tokens.

Copy source to a Pi staging directory, run its tests as pi, then:

```sh
sudo systemctl stop pi-desk.service
python3 install_pi.py
sudo systemctl daemon-reload
sudo systemctl enable --now pi-desk.service
```

Startup reapplies the local tmux configuration, including to a surviving server.
The service owns the display/compositor on tty3 and restarts on failure, without
changing `multi-user.target` or touching presence, audio, Bluetooth or SSH units.
`~/.local/state/pi-desk/last-session` stores only the selected number, not contents.

Wi-Fi power saving remains disabled in the existing NetworkManager profile
(`802-11-wireless.powersave=2`); no network profile is replaced. Console and labwc
use US English; the installer manages only the dedicated compositor settings.

## Backups/rollback

- Source of truth: this project.
- Historical, secret-free pre-migration archive: [`backups/`](backups/).
- Pi rollback files: `~/.local/state/pi-desk/backups/<UTC timestamp>/`.
- Mac helper backups: `~/.local/state/pi-desk/backups/` on the Mac.
- Installed source: `~/.local/share/pi-desk/`, with SHA-256 `manifest.json`.
- Service: `/etc/systemd/system/pi-desk.service`.

For rollback, stop Pi Desk and install a known-good source revision (or the
reviewed `app/` tree in a pre-update backup) using that revision's installer.
When restoring the old menu, also stop the **local** tmux server so new status-bar
options and key bindings do not survive into the old configuration:

```sh
sudo systemctl stop pi-desk.service
tmux -L pi-desk kill-server   # Pi clients only; Mac sessions keep running
# Run the chosen revision's install_pi.py here.
sudo systemctl daemon-reload
sudo systemctl start pi-desk.service
```

To disable boot startup: `sudo systemctl disable --now pi-desk.service`, then
`sudo chvt 1`. Do not blindly extract snapshots over `/` or `$HOME`. Never commit
SSH keys/config, IRKs, credentials, backend state or session transcripts.

## Verification

```sh
python3 -m unittest -v test_pi_desk
bash -n connect.sh
sh -n launch.sh
systemctl status pi-desk.service
journalctl -u pi-desk.service -n 40 --no-pager
tmux -L pi-desk list-clients -F '#{session_name} focus=#{@pi-desk-session}'
tmux -L pi-desk list-panes -a -F '#{session_name} #{@pi-desk-session} #{pane_dead}'
systemctl --user is-active jarvis-presence.service mpris-proxy.service
```

Tests use isolated `pi-desk-test-*` sockets, temporary state and `sleep` processes;
never real Mac sessions. Deployment results and remaining acceptance checks:
[DEPLOYMENT.md](DEPLOYMENT.md).
