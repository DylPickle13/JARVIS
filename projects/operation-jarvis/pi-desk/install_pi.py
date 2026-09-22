#!/usr/bin/env python3
"""Install reviewed Pi Desk files; retain allowlisted, secret-free rollback copies.
Run as pi from an extracted project directory. Does not enable/start/stop services.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parent
HOME = Path.home()
APP = HOME / '.local/share/pi-desk'


def install():
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = HOME / '.local/state/pi-desk/backups' / stamp
    backup.mkdir(parents=True, mode=0o700)
    old = [
        '.local/bin/mac-sessions', '.local/bin/mac-session-connect',
        '.local/bin/mac-session-grid.py', '.local/bin/mac-terminal-browser',
        '.local/bin/pi-desk', '.config/foot/foot.ini',
        '.config/mac-sessions/tmux.conf', '.config/labwc/environment',
        '.config/labwc/rc.xml',
    ]
    for name in old:
        path = HOME / name
        if path.is_file():
            dest = backup / 'home' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    for directory, label in ((APP, 'app'), (HOME / '.config/pi-desk', 'config')):
        if directory.exists():
            shutil.copytree(directory, backup / label, ignore=shutil.ignore_patterns('__pycache__'))
    unit = Path('/etc/systemd/system/pi-desk.service')
    if unit.is_file():
        shutil.copy2(unit, backup / 'pi-desk.service')
    APP.mkdir(parents=True, exist_ok=True)
    for name in ('terminal.py', 'health.py', 'connect.sh', 'launch.sh', 'status_stream.py', 'install_pi.py'):
        shutil.copy2(SOURCE / name, APP / name)
        (APP / name).chmod(0o700)
    shutil.copytree(SOURCE / 'config', APP / 'config', dirs_exist_ok=True)
    labwc = HOME / '.config/pi-desk/labwc'
    labwc.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / 'config/labwc.xml', labwc / 'rc.xml')
    (labwc / 'environment').write_text('XKB_DEFAULT_MODEL=pc105\nXKB_DEFAULT_LAYOUT=us\n')
    foot = HOME / '.config/foot/foot.ini'
    foot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / 'config/foot.ini', foot)
    bindir = HOME / '.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / 'pi-desk').write_text('#!/bin/sh\nsudo systemctl start pi-desk.service && sudo chvt 3\n')
    (bindir / 'pi-desk').chmod(0o700)
    # Compatibility with the earlier manual launcher name.
    (bindir / 'mac-sessions').write_text('#!/bin/sh\nexec python3 "$HOME/.local/share/pi-desk/terminal.py"\n')
    (bindir / 'mac-sessions').chmod(0o700)
    subprocess.run(['sudo', 'install', '-m', '644', str(SOURCE / 'config/pi-desk.service'),
                    str(unit)], check=True)
    manifest = {str(p.relative_to(APP)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in APP.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    (APP / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (backup / 'deployment.json').write_text(json.dumps({'createdAt': stamp, 'installed': manifest}, indent=2)+'\n')
    print('Rollback backup: ' + str(backup))
    print('Installed files; service activation is a separate explicit step.')


if __name__ == '__main__':
    install()
