# Raspberry Pi Fresh Bookworm Install Log — 2026-05-17

## Summary

We replaced the old Raspbian 10 `buster` install on the existing 16GB microSD card with a fresh Raspberry Pi OS / Raspbian 12 `bookworm` Lite 32-bit install.

Current verified state:

- Device: configured Raspberry Pi endpoint Rev 1.2
- Hostname: `raspberrypi`
- IP: `<private-lan-ip>`
- SSH user: `pi`
- OS: Raspbian GNU/Linux 12 `bookworm`
- Kernel after update/reboot: `6.12.87+rpt-rpi-v7`
- Root filesystem: about 15GB total, about 11GB free
- SSH: active and reachable from the JARVIS VM with `~/.ssh/jarvis_dashboard_host`
- GUI: none; this is Raspberry Pi OS Lite / CLI-only

## Why we chose a fresh install

The Pi originally ran Raspbian GNU/Linux 10 `buster` with incomplete apt sources:

- `/etc/apt/sources.list` was missing.
- `/etc/apt/sources.list.d/raspi.list` only had the Raspberry Pi Foundation Buster repo.

A remote in-place Buster → Bullseye → Bookworm upgrade would have been risky, so the safer path was a fresh OS install.

## Backup created before wiping the SD card

Backup destination on the configured host:

```txt
/path/to/JARVIS-Backups/raspberry-pi/20260517-145635-EDT
```

Backup contents:

```txt
home-pi.tar.gz            /home/pi backup
boot.tar.gz               /boot backup
etc.tar.gz                /etc config backup
var-spool-cron.tar.gz     cron spool backup, empty/minimal
system-snapshot.txt       packages, services, disk/network info
SHA256SUMS.txt            checksums
README.txt                backup notes
```

The old install used about 4.7GB and `/home/pi` was about 142MB at the time of backup.

## Images tried

### Attempt 1: Trixie Lite 32-bit

Image downloaded and checksum-verified on the configured host:

```txt
2026-04-21-raspios-trixie-armhf-lite.img.xz
```

Result: the Pi showed only the red power LED and did not boot successfully on this Raspberry Pi 3. We abandoned this image for this device.

### Successful image: Bookworm Lite 32-bit

Image downloaded and checksum-verified on the configured host:

```txt
2025-05-13-raspios-bookworm-armhf-lite.img.xz
```

Image cache path on the configured host:

```txt
/path/to/JARVIS-Backups/raspberry-pi/image-cache/
```

This image booted successfully.

## Flashing notes

The microSD card appeared on the configured host as:

```txt
/dev/disk4 external physical, 15.9 GB
```

The successful reflash used a temporary configured host script:

```txt
/tmp/jarvis-flash-rpi-bookworm-sd.sh
```

That script:

- Verified the Bookworm image checksum.
- Unmounted `/dev/disk4`.
- Decompressed/wrote the `.img.xz` image to `/dev/rdisk4`.
- Mounted the boot partition.
- Added SSH/headless helper files.
- Added HDMI troubleshooting lines to `config.txt`:

```txt
hdmi_force_hotplug=1
hdmi_group=1
hdmi_mode=16
```

## First boot notes

On first successful Bookworm boot, the Pi asked for a new username. User `pi` was created manually at the Pi keyboard/screen. The password was typed locally and is not documented here.

Wi-Fi initially showed:

```txt
Wi-Fi is currently blocked by rfkill.
Use raspi-config to set the country before use.
```

Commands used locally on the Pi to unblock and connect Wi-Fi:

```bash
sudo raspi-config nonint do_wifi_country CA
sudo rfkill unblock wifi
sudo nmtui
```

After joining Wi-Fi, the Pi got:

```txt
<private-lan-ip>
```

## SSH bootstrap

A temporary HTTP server was started on the configured host at:

```txt
http://<private-lan-ip>:8765/bootstrap-pi.sh
```

Because the keyboard did not have an easy pipe `|` key, the no-pipe method was recommended:

```bash
curl -fsSL -o /tmp/bootstrap-pi.sh http://<private-lan-ip>:8765/bootstrap-pi.sh
bash /tmp/bootstrap-pi.sh
```

The bootstrap script:

- Created/updated `/home/pi/.ssh/authorized_keys`.
- Installed the JARVIS VM public key for SSH access.
- Enabled and started SSH.
- Wrote key-only SSH settings.

After SSH was confirmed, the temporary configured host HTTP server on port `8765` was stopped.

## SSH from the JARVIS VM

Direct command:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip>
```

After reflashing, SSH warned that the host identification changed. This was expected because the OS was freshly installed. The old host key was removed with:

```bash
ssh-keygen -R <private-lan-ip>
ssh-keygen -R raspberrypi.local
```

Then the new host key was accepted.

## Package update and repair notes

A full package update was run after SSH access was working.

Initial update command:

```bash
sudo apt-get update
sudo apt-get -y full-upgrade
sudo apt-get -y autoremove
```

The first upgrade run stopped at a conffile prompt for:

```txt
/etc/initramfs-tools/initramfs.conf
```

Repair/completion commands used:

```bash
sudo dpkg --force-confold --configure -a
sudo apt-get -y -o Dpkg::Options::="--force-confold" -f install
sudo apt-get -y -o Dpkg::Options::="--force-confold" full-upgrade
sudo apt-get -y autoremove
```

Then the Pi was rebooted:

```bash
sudo reboot
```

Verified after reboot:

```txt
kernel: 6.12.87+rpt-rpi-v7
ssh: active
root filesystem: 15G total, 11G free
```

## Verification commands

From the JARVIS VM:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o ConnectTimeout=5 \
  pi@<private-lan-ip> 'hostname; whoami; uptime; uname -r; df -h /; systemctl is-active ssh'
```

Expected/current output includes:

```txt
raspberrypi
pi
6.12.87+rpt-rpi-v7
active
```

## Showing a visible sign on the Pi screen

A message was written directly to the Pi console with:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> \
  'sudo sh -c '\''printf "\r\n\r\n============================================================\r\n  JARVIS is here. SSH link confirmed from the coding VM.\r\n  Time: %s EDT\r\n============================================================\r\n\r\n" "$(TZ=America/Toronto date +%H:%M:%S)" > /dev/tty1'\'''
```

## GUI status

This install is Raspberry Pi OS Lite. It does not have a desktop GUI.

Verified:

```txt
systemctl get-default -> multi-user.target
no startx/lightdm desktop commands present
```

Keep it Lite unless a GUI is truly needed; a Pi 3 will perform better headless.

## Restore/migration notes

Do not blindly overwrite `/etc` from the old backup onto Bookworm. Use the old backup as a reference and restore only selected files.

Example: inspect old home backup on the configured host:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes <ssh-user>@<private-lan-ip>
cd /path/to/JARVIS-Backups/raspberry-pi/20260517-145635-EDT
tar -tzf home-pi.tar.gz | less
```

Example: copy a selected file from this JARVIS VM to the Pi:

```bash
scp -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes ./local-file.txt pi@<private-lan-ip>:/home/pi/
```

## Current maintenance commands

Update packages:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt autoremove -y
```

Check device status:

```bash
hostnamectl
uname -a
hostname -I
df -h /
systemctl status ssh
```
