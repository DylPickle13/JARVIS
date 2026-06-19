# Raspberry Pi HDMI display / safe console mode

Date documented: 2026-05-20 EDT

This note captures the working display state discovered while testing the Pi on the Dell P1913 monitor. The symptom was:

1. The monitor showed the Pi boot messages.
2. The terminal appeared briefly.
3. As soon as the graphical desktop / LightDM took over, the monitor went blank.

SSH continued to work the entire time, so the Pi was healthy; this was an HDMI/KMS/X desktop display issue.

## Known-good visible state

The known-good state is **console-only safe mode**:

| Item | Working value |
|---|---|
| Host | `raspberrypi` / `<private-lan-ip>` |
| SSH user | `pi` |
| SSH key from JARVIS VM | `~/.ssh/jarvis_dashboard_host` |
| Display connector | `HDMI-A-1` / X name `HDMI-1` |
| Monitor detected | Dell P1913 |
| Safe resolution | `1024x768@60` |
| Boot target | `multi-user.target` |
| Desktop / LightDM | LightDM and LXDE session packages purged; no graphical login manager |
| Active terminal | `tty1` |
| Kernel mode override | `video=HDMI-A-1:1024x768@60D` |

Current boot command-line setting on the Pi:

```txt
/boot/firmware/cmdline.txt
... console=tty1 root=PARTUUID=44f56462-02 rootfstype=ext4 fsck.repair=yes rootwait cfg80211.ieee80211_regdom=CA video=HDMI-A-1:1024x768@60D
```

Current systemd/package state:

```bash
sudo systemctl set-default multi-user.target
# `lightdm`, `lightdm-gtk-greeter`, `light-locker`, `lxlock`, `lxde-core`, and `lxsession`
# were purged on 2026-05-20 after the desktop stack repeatedly blanked the monitor.
```

The Pi also has a recovery banner service installed:

```txt
/etc/systemd/system/jarvis-visible-console.service
/usr/local/sbin/jarvis-visible-console
```

That service switches to `tty1`, disables console blanking, and draws a bright framebuffer banner at boot.

## Do not start the desktop blindly

Starting LightDM/X made the monitor blank again, even after the safe HDMI mode was forced. LightDM has now been removed, so graphical desktop work should be treated as a deliberate reinstall/debug task, not a casual service start.

If the display goes blank after experimenting with graphics, restore console mode with the commands below.

## Print text directly to the monitor terminal

From this repo:

```bash
projects/operation-jarvis/raspberry-pi/scripts/print-terminal.sh "this is jarvis"
```

Equivalent one-liner:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> \
  'sudo chvt 1; sudo sh -c '\''setterm -blank 0 -powerdown 0 -powersave off </dev/tty1 >/dev/tty1 2>/dev/null || true; printf "\033c\033[1;1Hthis is jarvis\n" >/dev/tty1'\'''
```

## Restore the known-good visible console state

From this repo:

```bash
projects/operation-jarvis/raspberry-pi/scripts/restore-visible-console.sh
```

That script:

1. Forces `video=HDMI-A-1:1024x768@60D` in `/boot/firmware/cmdline.txt`.
2. Stops/disables LightDM if it is installed.
3. Sets the boot target to `multi-user.target`.
4. Installs/enables `jarvis-visible-console.service`.
5. Switches to `tty1` and redraws the framebuffer banner.

Reboot afterwards if the KMS/display state still looks wrong:

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> 'sudo reboot'
```

## Useful diagnostics

```bash
ssh -i ~/.ssh/jarvis_dashboard_host -o IdentitiesOnly=yes pi@<private-lan-ip> '
  echo "active vt:"; cat /sys/class/tty/tty0/active
  echo "default target:"; systemctl get-default
  echo "lightdm package:"; dpkg-query -W lightdm 2>/dev/null || echo "lightdm not installed"
  echo "cmdline:"; cat /proc/cmdline
  echo "kms:"; kmsprint 2>/dev/null | head -12 || true
'
```

Expected good output includes:

```txt
active vt: tty1
default target: multi-user.target
lightdm not installed
video=HDMI-A-1:1024x768@60D
HDMI-A-1 (connected)
1024x768@60.00
```

## Notes from the session

- The Pi was reachable over SSH at `<private-lan-ip>` while the display was blank.
- The green ACT LED was temporarily set to fast blink to confirm we were controlling the same Pi.
- Writing to `/dev/tty1` alone was not always visible until the framebuffer/console state was forced.
- Direct framebuffer drawing to `/dev/fb0` made the message visible.
- The successful quick terminal print was `this is jarvis` written directly to `/dev/tty1`.
- On 2026-05-20, `lightdm`, `lightdm-gtk-greeter`, `light-locker`, `lxlock`, `lxde-core`, and `lxsession` were purged to keep the Pi in CLI/console mode.
