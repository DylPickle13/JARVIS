# Pi Desk

A lightweight living-room workspace for the Mac's ten Pi Coding Agent sessions.
Runs on the Raspberry Pi 3 using **labwc + foot + local tmux + SSH**, not a browser
or streamed desktop. Presence, Bluetooth, SSH and audio services stay independent.

## Use

Pi Desk starts automatically on the TV after the Pi boots, on **tty3**.

| Key | Action |
| --- | --- |
| `1` | Mac sessions 1, 2, 3 side by side |
| `2` | Sessions 4, 5, 6 |
| `3` | Sessions 7, 8, 9 |
| `4` | Session 10 alone |
| `s` | Interactive Mac shell; type `exit` to return |
| `q` | Close Pi Desk; it starts again on the next boot or manual start |
| `F12` | Leave a session group and return to the clean menu |
| Click a pane | Focus that terminal |
| `Ctrl+A`, then arrow | Select a local pane |
| `Ctrl` + `+` / `-` | Adjust the focused terminal's font size |
| `Alt+F11` | Toggle fullscreen |

The large menu uses 24 pt text; workspaces use 12 pt. Pure-black background,
DejaVu Sans Mono, Noto Color Emoji, US keyboard, 1080p output. App-specific
coloured content is not rewritten. F12 belongs to the local tmux workspace;
it is not a global shortcut inside the standalone Mac shell.

Manual start on the Pi:

```sh
~/.local/bin/pi-desk
```

## Architecture and recovery

- `terminal.py`: card-grid UI, status stream management, workspace reconciliation.
- `connect.sh`: one reconnecting SSH client per local pane. Retries after three
  seconds; 5-second keepalives, two missed replies, 5-second connection timeout.
- `status_stream.py`: Mac-side read-only projection of the **same jarvisd Pi
  lifecycle data used by the iPhone app**, over existing key-authenticated SSH.
- `launch.sh`: fullscreen terminal launcher.
- `config/`: reviewed foot, local tmux, compositor and systemd configuration.
- `install_pi.py`: allowlisted backups and installation; activation is explicit.

Local tmux uses the dedicated **`pi-desk` socket**. Remote tmux uses
**`jarvis-mobile`**, exact session names, and `attach-session -f ignore-size`.
No remote layouts are resized, other clients detached, or Mac Pi sessions
created/killed. A narrow existing Mac layout can therefore leave blank space.

Every workspace entry checks its tagged panes, restores missing ones, respawns
exited ones and restores numeric order. A lost SSH connection normally reconnects
inside its existing pane. Local dead panes remain visible until the next entry,
rather than silently disappearing.

Status is fetched every **3 seconds while the menu is visible**; only session
numbers and lifecycle labels are streamed. Running = green, Idle = purple,
New = cyan, Compacting = blue, Offline = grey, Unknown = amber. Collector samples
older than 15 seconds, backend errors and disconnected feeds become **Unknown**,
never a fabricated Idle/Offline. The UI expires its stream after 12 seconds and
reconnects failed streams automatically. It pauses polling while a workspace is open.

## Installation / restore from source

This deployment is intentionally hardware-specific: existing `pi` account,
UID 1000, HDMI-A-1, tty3, Raspberry Pi OS, NetworkManager, and the existing
`mac-mini-64` SSH alias. Review paths before using another machine.

Required Pi packages:

```sh
sudo apt-get install --no-install-recommends \
  labwc foot tmux wlr-randr fonts-dejavu-core fonts-noto-color-emoji
```

Python 3 and OpenSSH are supplied by the OS. `wtype` was used for display smoke
tests, but is not a runtime dependency. No browser or full desktop is required.

Prerequisite: `ssh mac-mini-64` from the Pi must use the existing dedicated key
and a separately verified host key. Keep `StrictHostKeyChecking yes`,
`IdentitiesOnly yes` and `ForwardAgent no`. **Do not put private keys, tokens,
IRKs, host-key databases or personal runtime data into this project.**

1. On the Mac, back up `~/.local/bin/pi-grid-status`, then copy
   `status_stream.py` there (mode 0700). It uses the existing trusted-loopback
   `http://127.0.0.1:8790/api/v1/state` endpoint. If backend authentication changes,
   it fails closed to Unknown; do not hardcode credentials to work around that.
2. Copy this project's source to a Pi staging directory using the existing SSH
   connection. Run the tests there, then `python3 install_pi.py` **as pi**.
3. Stop the old display service before activating a replacement. For updates:

   ```sh
   sudo systemctl stop pi-desk.service
   python3 install_pi.py
   sudo systemctl daemon-reload
   sudo systemctl enable --now pi-desk.service
   ```

   Only local display clients are closed; the Mac's tmux sessions survive.
4. Verify `systemctl is-enabled pi-desk.service` and
   `systemctl is-active pi-desk.service`. Enablement installs a
   `multi-user.target.wants` link; it does not change the default boot target.

The system service owns the compositor and local display clients, uses the
existing `pi` account through PAM, and restarts on failure. Choosing Quit is a
clean exit, not an endless automatic relaunch. The existing unrestricted sudo
policy is **not** created or broadened by this project. Physical access to this
terminal provides access to the Mac account; it is a trusted household console,
not a locked-down kiosk.

## Backups and rollback

- **Source of truth:** this project, including its tested configurations.
- **Pre-migration snapshot:** [`backups/`](backups/), containing only the explicitly
  allowlisted old terminal scripts/configuration and deployment metadata.
- **Pi runtime rollback copies:** `~/.local/state/pi-desk/backups/<UTC timestamp>/`.
- **Mac status-helper rollback copies:** `~/.local/state/pi-desk/backups/`.
- **Installed Pi source:** `~/.local/share/pi-desk/`; `manifest.json` records SHA-256s.
- **Service:** `/etc/systemd/system/pi-desk.service`.

For source rollback, stop Pi Desk, deploy a known-good project revision using
`install_pi.py`, reload systemd, then start the service. To disable boot startup
without touching presence/audio/SSH:

```sh
sudo systemctl disable --now pi-desk.service
sudo chvt 1
```

The legacy snapshot is archival, not an automatic rollback installer. Its files
are relative to the old `pi` home and require deliberate path-by-path restoration.
Never blindly extract a snapshot over `/` or `$HOME`.

## Wi-Fi and keyboard

Wi-Fi power saving is disabled in the **existing NetworkManager connection**
(`802-11-wireless.powersave = 2`), not in a replacement network profile. That
setting survives reconnects and boots. `iw dev wlan0 get power_save` should say
`off`. Ethernet remains the best latency improvement if practical.

Console `/etc/default/keyboard` and the dedicated compositor environment both
use US English. The installer only manages the compositor's configuration;
it does not overwrite the console or network profiles.

## Checks

```sh
python3 -m unittest -v test_pi_desk
bash -n connect.sh
sh -n launch.sh
foot --check-config
systemctl status pi-desk.service
journalctl -u pi-desk.service -n 40 --no-pager
tmux -L pi-desk list-panes -a -F '#{session_name} #{@pi-desk-session} #{pane_dead}'
systemctl --user is-active jarvis-presence.service mpris-proxy.service
```

Tests use isolated `pi-desk-test-*` tmux sockets and `sleep` processes, never the
Mac's actual sessions. See [DEPLOYMENT.md](DEPLOYMENT.md) for initial validation
and remaining acceptance checks.
