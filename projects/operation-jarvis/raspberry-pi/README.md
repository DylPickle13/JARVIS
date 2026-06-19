# Raspberry Pi

Operation JARVIS Raspberry Pi endpoint documentation and helper scripts.

**Local/private operations note:** this README intentionally contains LAN IPs, SSH users/keys, Bluetooth MACs, service names, and recovery commands. Keep it private; do not publish without review.

Project folder: `projects/operation-jarvis/raspberry-pi/`

## Recovery quick actions

| Symptom | First action |
|---|---|
| Pi unreachable | Check power/network, then run `scripts/check-pi.sh`. |
| Room audio unhealthy | Check `systemctl status jarvis-room-audio --no-pager` and `/home/pi/jarvis-room-audio/logs/client.log`. |
| PowerConf disconnected | Run `scripts/test-anker-powerconf.sh` or reinstall/refresh room-audio service. |
| HDMI blank | Run `scripts/restore-visible-console.sh`. |
| Need to print to Pi monitor | Run `scripts/print-terminal.sh "message"`. |

## Quick status

| Item | Current value |
|---|---|
| Hostname | `raspberrypi` |
| LAN IP | `<private-lan-ip>` |
| SSH user | `pi` |
| Hardware | configured Raspberry Pi endpoint Rev 1.2 |
| OS | Raspberry Pi OS Lite / Raspbian 12 `bookworm`, CLI-only |
| Kernel | `6.12.87+rpt-rpi-v7` after the 2026-05-17 refresh |
| SSH key from JARVIS VM | `~/.ssh/jarvis_dashboard_host` |
| Confirmed configured host jump/tool host | `<host-name> / `<private-lan-ip>` / user `<ssh-user>` / Pi SSH tool alias `minecraft-mac-mini` |
| SSH key on that configured host | `/path/to/local/user` authorized on this Pi on 2026-06-11 EDT |
| HDMI display state | Safe console mode, `1024x768@60`, `multi-user.target` |
| Room audio | Anker PowerConf over Bluetooth: SCO mic + A2DP speaker |

## Purpose

1. **Operation JARVIS room audio endpoint** — microphone and speaker bridge for the room.
2. **Headless Pi services** — lightweight CLI-only support processes.
3. **Hardware test bed** — audio, display, and small automation experiments.

## Important docs

- [`room_audio/README.md`](./room_audio/README.md) — current room-audio bridge, VAD, Bluetooth profile-switching, and server/client commands.
- [`docs/audio-hardware.md`](./docs/audio-hardware.md) — Anker PowerConf USB/Bluetooth hardware notes.
- [`docs/display-hdmi-console.md`](./docs/display-hdmi-console.md) — known-good HDMI terminal state and recovery commands.
- [`docs/upgrade-log-20260517.md`](./docs/upgrade-log-20260517.md) — detailed fresh Bookworm install and troubleshooting log.

## SSH access

From this JARVIS coding-agent environment:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip>
```

Quick test:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o ConnectTimeout=5 \
  pi@<private-lan-ip> 'hostname; whoami; pwd'
```

Expected output:

```text
raspberrypi
pi
/home/pi
```

File copy examples:

```bash
scp -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes ./local-file.txt pi@<private-lan-ip>:/home/pi/
scp -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip>:/home/pi/remote-file.txt ./
```

If direct LAN access fails, use the confirmed configured host SSH/tool host as a jump point:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes <ssh-user>@<private-lan-ip>
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip>
```

The Pi harness SSH tool can also reach that configured host through alias `minecraft-mac-mini`; from there, `~/.ssh/jarvis_dashboard_host` can SSH onward to this Pi.

## Room audio

The active room-audio endpoint is documented in [`room_audio/README.md`](./room_audio/README.md).

Current deployed shape:

```text
PowerConf Bluetooth mic/speaker
  -> Raspberry Pi VAD listener
  -> Mac room-audio server
  -> oMLX Whisper ASR
  -> wake-word gate
  -> immediate acknowledgement audio
  -> Pi RPC JARVIS response
  -> Piper TTS
  -> high-quality A2DP playback
```

Important current details:

- Bluetooth device: Anker PowerConf `<bluetooth-device-mac>`.
- Capture: BlueALSA SCO/HFP at `8000 Hz`.
- Playback: BlueALSA A2DP for higher-quality JARVIS voice.
- Persistent listener service: `jarvis-room-audio.service`.
- The service reconnects the trusted PowerConf by MAC, restores SCO mixer volume to `100%`, and restarts automatically after Pi reboot or client failure.
- The client releases SCO capture around A2DP playback, then restores/drains the mic while waiting for the async final answer.
- BlueALSA is configured with `--keep-alive=1` to reduce Bluetooth profile-switch delay.
- `JARVIS_ROOM_AUDIO_TTS_LEADING_SILENCE_MS=1000` prevents clipped first syllables on A2DP wake-up.
- Startup/reconnect greetings are served by `GET /greeting` on the Mac room-audio server and played through the PowerConf once capture is healthy.

USB remains the best long-term simultaneous mic+speaker option, but this Pi/PowerConf pairing has shown USB `over-current change` instability without a powered hub. Use a powered hub for a future wired configuration.

## Pi-side client deployment

Current client destination on the Pi:

```text
/home/pi/jarvis-room-audio-client.py
```

Copy the local client:

```bash
scp -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes \
  projects/operation-jarvis/raspberry-pi/room_audio/pi_room_audio_client.py \
  pi@<private-lan-ip>:/home/pi/jarvis-room-audio-client.py
```

Current listener command is in [`room_audio/README.md`](./room_audio/README.md).

Install or refresh the boot-time service from this repo:

```bash
projects/operation-jarvis/raspberry-pi/scripts/install-room-audio-service.sh
```

Check it on the Pi:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> \
  'systemctl status jarvis-room-audio --no-pager; tail -n 80 /home/pi/jarvis-room-audio/logs/client.log'
```

## HDMI display / monitor recovery

The Pi monitor is intentionally left in safe console mode because starting LightDM/X made the monitor go blank after boot. The working state is:

- `/boot/firmware/cmdline.txt` contains `video=HDMI-A-1:1024x768@60D`.
- Boot target is `multi-user.target`.
- `lightdm`, `lightdm-gtk-greeter`, `light-locker`, `lxlock`, `lxde-core`, and `lxsession` were purged.
- Recovery service: `jarvis-visible-console.service`.

Useful commands from this repo:

```bash
projects/operation-jarvis/raspberry-pi/scripts/print-terminal.sh "this is jarvis"
projects/operation-jarvis/raspberry-pi/scripts/restore-visible-console.sh
```

Details are in [`docs/display-hdmi-console.md`](./docs/display-hdmi-console.md).

## Maintenance commands

Update packages:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt autoremove -y
```

Check system status:

```bash
hostnamectl
uname -a
hostname -I
df -h /
systemctl status ssh
```

Run the local status script:

```bash
projects/operation-jarvis/raspberry-pi/scripts/check-pi.sh
```

## Backup and image locations

configured host backup path:

```text
/path/to/JARVIS-Backups/raspberry-pi/20260517-145635-EDT
```

configured host image cache:

```text
/path/to/JARVIS-Backups/raspberry-pi/image-cache/
```

Do **not** blindly restore `/etc` from the old backup onto Bookworm. Use the backup as reference material and restore only selected files.

## Folder map

```text
projects/operation-jarvis/raspberry-pi/
├── README.md
├── docs/
│   ├── audio-hardware.md
│   ├── display-hdmi-console.md
│   └── upgrade-log-20260517.md
├── room_audio/
│   ├── README.md
│   ├── pi_room_audio_client.py
│   └── room_audio_server.py
└── scripts/
    ├── check-pi.sh
    ├── print-terminal.sh
    ├── install-room-audio-service.sh
    ├── restore-visible-console.sh
    └── test-anker-powerconf.sh
```

## File guide

| Path | Purpose |
|---|---|
| [`README.md`](./README.md) | Main Pi overview, SSH, room-audio integration, and maintenance index. |
| [`room_audio/README.md`](./room_audio/README.md) | Room-audio architecture, server/client commands, VAD tuning, and service notes. |
| [`room_audio/pi_room_audio_client.py`](./room_audio/pi_room_audio_client.py) | Pi-side PowerConf capture/playback client copied to `/home/pi/jarvis-room-audio-client.py`. |
| [`room_audio/room_audio_server.py`](./room_audio/room_audio_server.py) | Mac-side room-audio HTTP bridge for ASR, Pi RPC, and TTS; Pi-side openWakeWord is the wake gate. |
| [`docs/audio-hardware.md`](./docs/audio-hardware.md) | Anker PowerConf USB/Bluetooth findings and test commands. |
| [`docs/display-hdmi-console.md`](./docs/display-hdmi-console.md) | HDMI safe-console settings, recovery commands, and direct terminal print command. |
| [`docs/upgrade-log-20260517.md`](./docs/upgrade-log-20260517.md) | Fresh Bookworm install, troubleshooting, SSH bootstrap, and update log. |
| [`scripts/check-pi.sh`](./scripts/check-pi.sh) | Basic Pi status checks over SSH. |
| [`scripts/install-room-audio-service.sh`](./scripts/install-room-audio-service.sh) | Copy the canonical room-audio client to the Pi and install/enable the boot-time systemd listener. |
| [`scripts/print-terminal.sh`](./scripts/print-terminal.sh) | Print a message directly to the Pi monitor terminal over SSH. |
| [`scripts/restore-visible-console.sh`](./scripts/restore-visible-console.sh) | Reapply safe HDMI console mode and visible framebuffer recovery banner. |
| [`scripts/test-anker-powerconf.sh`](./scripts/test-anker-powerconf.sh) | USB PowerConf ALSA smoke test. |
