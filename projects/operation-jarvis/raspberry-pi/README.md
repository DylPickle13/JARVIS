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
| SSH key from native JARVIS | `~/.ssh/jarvis_dashboard_host` |
| Native JARVIS host | `mac-mini-64` / `<private-lan-ip>` / user `dylanrapanan`; no jump host |
| Native JARVIS key | `~/.ssh/jarvis_dashboard_host.pub` authorized on this Pi |
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

From JARVIS, use the SSH tool with explicit host `raspberrypi`; no VM or jump host is involved. If direct LAN access fails, diagnose the Pi or LAN rather than routing through another Mac.

## Room audio

The active room-audio endpoint is documented in [`room_audio/README.md`](./room_audio/README.md).

Current deployed shape:

```text
PowerConf USB mic/speaker
  -> Raspberry Pi VAD + local openWakeWord listener
  -> Mac room-audio server
  -> Apple SpeechTranscriber turn ASR with oMLX fallback
  -> Apple DictationTranscriber busy-only stop ASR with oMLX fallback
  -> immediate acknowledgement audio
  -> Pi RPC JARVIS response
  -> Piper TTS
  -> full-duplex USB playback
```

Important current details:

- Capture/playback: Anker PowerConf USB ALSA at 48 kHz (`plughw:CARD=PowerConf,DEV=0`).
- Persistent listener service: `jarvis-room-audio.service`.
- USB capture remains active during acknowledgement, generation, and playback so bare-`stop` barge-in works.
- The service restarts automatically after Pi reboot or client failure.
- Bluetooth BlueALSA SCO/A2DP remains an installer fallback, but it cannot provide reliable simultaneous capture/playback.
- Startup greetings are served by `GET /greeting` on the Mac room-audio server and played once capture is healthy.

Use a good powered USB hub if electrical instability returns.

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
