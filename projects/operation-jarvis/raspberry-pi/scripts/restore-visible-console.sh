#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-pi}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/jarvis_dashboard_host}"

if [[ -z "$PI_HOST" ]]; then
  echo "Set PI_HOST to the Raspberry Pi hostname or IP." >&2
  exit 2
fi

ssh -i "$SSH_KEY" \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o ConnectTimeout=5 \
  "$PI_USER@$PI_HOST" \
  'sudo python3 -' <<'PY'
from pathlib import Path
import datetime
import os
import re
import subprocess

boot = Path("/boot/firmware")
cmd = boot / "cmdline.txt"
ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

if cmd.exists():
    (boot / f"cmdline.txt.jarvis-visible-backup-{ts}").write_bytes(cmd.read_bytes())
    text = cmd.read_text().strip()
    text = re.sub(r"(^|\s)video=HDMI-A-1:\S+", " ", text)
    text = re.sub(r"(^|\s)video=HDMI-1:\S+", " ", text)
    cmd.write_text(" ".join(text.split()) + " video=HDMI-A-1:1024x768@60D\n")

script = Path("/usr/local/sbin/jarvis-visible-console")
script.write_text(r'''#!/usr/bin/env python3
import mmap
import os
import struct
import subprocess

subprocess.run(['/usr/bin/chvt', '1'], check=False)
subprocess.run('/usr/bin/setterm -blank 0 -powerdown 0 -powersave off </dev/tty1 >/dev/tty1 2>/dev/null', shell=True, check=False)
subprocess.run(['/usr/bin/vcgencmd', 'display_power', '1'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    open('/sys/class/graphics/fb0/blank', 'w').write('0')
except Exception:
    pass
try:
    open('/dev/tty1', 'wb', buffering=0).write(b'\033c\033[?25l\033[1;1H\n\n\n                    HELLO WORLD\n\n                    SAFE CONSOLE MODE\n\n                    - JARVIS\n')
except Exception:
    pass

def read_int(path, default):
    try:
        return int(open(path).read().strip())
    except Exception:
        return default

try:
    w, h = map(int, open('/sys/class/graphics/fb0/virtual_size').read().strip().split(',')[:2])
except Exception:
    w, h = 1024, 768
bpp = read_int('/sys/class/graphics/fb0/bits_per_pixel', 16)
try:
    line = int(open('/sys/class/graphics/fb0/stride').read().strip())
except Exception:
    line = w * max(1, bpp // 8)

font = {
    ' ': [0,0,0,0,0,0,0], '-': [0,0,0,31,0,0,0],
    'A': [14,17,17,31,17,17,17], 'C': [14,17,16,16,16,17,14],
    'D': [30,17,17,17,17,17,30], 'E': [31,16,16,30,16,16,31],
    'F': [31,16,16,30,16,16,16], 'H': [17,17,17,31,17,17,17],
    'I': [31,4,4,4,4,4,31], 'J': [1,1,1,1,17,17,14],
    'L': [16,16,16,16,16,16,31], 'M': [17,27,21,21,17,17,17],
    'N': [17,25,21,19,17,17,17], 'O': [14,17,17,17,17,17,14],
    'R': [30,17,17,30,20,18,17], 'S': [15,16,16,14,1,1,30],
    'V': [17,17,17,17,17,10,4], 'W': [17,17,17,21,21,21,10],
}

def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

def pixbytes(color):
    if bpp == 32:
        r, g, b = color
        return bytes([b, g, r, 0])
    return struct.pack('<H', rgb565(*color))

def rect(buf, x, y, width, height, color):
    x0, x1 = max(0, x), min(w, x + width)
    y0, y1 = max(0, y), min(h, y + height)
    if x1 <= x0 or y1 <= y0:
        return
    px = pixbytes(color)
    row = px * (x1 - x0)
    for yy in range(y0, y1):
        off = yy * line + x0 * len(px)
        buf[off:off + len(row)] = row

def text(buf, s, x, y, scale, color):
    cx = x
    for ch in s.upper():
        glyph = font.get(ch, font[' '])
        for gy, row in enumerate(glyph):
            for gx in range(5):
                if row & (1 << (4 - gx)):
                    rect(buf, cx + gx * scale, y + gy * scale, scale, scale, color)
        cx += 6 * scale

try:
    fd = os.open('/dev/fb0', os.O_RDWR)
    buf = mmap.mmap(fd, line * h, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
    rect(buf, 0, 0, w, h, (0, 0, 170))
    rect(buf, 0, 0, w, 70, (210, 0, 0))
    rect(buf, 0, h - 70, w, 70, (0, 160, 0))
    rect(buf, 32, 92, w - 64, h - 184, (255, 255, 255))
    rect(buf, 52, 112, w - 104, h - 224, (0, 0, 0))
    sc = max(7, min(w // 82, h // 36))
    text(buf, 'HELLO WORLD', (w - (11 * 6 - 1) * sc) // 2, h // 2 - 7 * sc, sc, (255, 255, 255))
    text(buf, 'SAFE CONSOLE MODE', (w - (17 * 6 - 1) * max(4, sc // 2)) // 2, h // 2 + 6 * sc, max(4, sc // 2), (0, 230, 255))
    text(buf, '- JARVIS', (w - (8 * 6 - 1) * max(5, sc // 2)) // 2, h // 2 + 11 * sc, max(5, sc // 2), (255, 230, 0))
    buf.flush()
    os.close(fd)
except Exception as exc:
    open('/tmp/jarvis-visible-console.log', 'a').write(str(exc) + '\n')
''')
script.chmod(0o755)

service = Path("/etc/systemd/system/jarvis-visible-console.service")
service.write_text("""[Unit]
Description=JARVIS visible safe HDMI console banner
After=getty@tty1.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/jarvis-visible-console
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
""")

subprocess.run(["systemctl", "stop", "lightdm"], check=False)
subprocess.run(["systemctl", "disable", "lightdm"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(["systemctl", "set-default", "multi-user.target"], check=False)
subprocess.run(["systemctl", "daemon-reload"], check=False)
subprocess.run(["systemctl", "enable", "jarvis-visible-console.service"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(["/usr/local/sbin/jarvis-visible-console"], check=False)

print("Restored Raspberry Pi known-good visible console mode.")
print("Reboot if the HDMI/KMS state still appears wrong: sudo reboot")
PY
