#!/usr/bin/env python3
"""Shared installer. No hosted agents are started, stopped or restarted."""
import argparse
from dataclasses import asdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import shlex
import shutil
import sys

from backend import Backend

SOURCE = Path(__file__).resolve().parent
FILES = ('backend.py', 'cli.py', 'connect.py', 'core.py', 'desktop.py', 'health.py',
         'connect.sh', 'status_stream.py', 'install.py', 'navigate.py', 'native_navigation.py',
         'layout.py', 'workspace.py', 'restart_status.py', 'codex_quota.py', 'provider_quotas.py', 'tmux_runtime.py')
PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH" # Pi Desk CLI'


def remove_retired(app):
    (app / 'terminal.py').unlink(missing_ok=True)
    (app / 'config/open-terminal.applescript').unlink(missing_ok=True)
    shutil.rmtree(app / '__pycache__', ignore_errors=True)


def install(mode, project_root='/Users/dylanrapanan/JARVIS'):
    config = Backend(mode=mode, project_root=project_root)
    home = Path.home()
    app = home / '.local/share/pi-desk'
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = home / '.local/state/pi-desk/backups' / stamp
    backup.mkdir(parents=True, mode=0o700)
    mac = platform.system() == 'Darwin'
    shell_rc = '.zshrc' if mac else '.bashrc'
    # Do not copy shell profiles: they may contain unrelated private credentials.
    # Rollback removes only our exact PATH_LINE, leaving all other contents intact.
    old = ['.local/bin/pi-desk']
    for name in old:
        path = home / name
        if path.is_file():
            dest = backup / 'home' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    for directory, label in ((app, 'app'), (home / '.config/pi-desk', 'config'),
                             (home / 'Applications/Pi Desk.app', 'mac-app')):
        if directory.exists():
            shutil.copytree(directory, backup / label, ignore=shutil.ignore_patterns('__pycache__'))
    app.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copy2(SOURCE / name, app / name)
        (app / name).chmod(0o700)
    remove_retired(app)
    shutil.copytree(SOURCE / 'config', app / 'config', dirs_exist_ok=True)
    # Ship the optional, offline-buildable VS Code bridge without installing it
    # or changing editor settings. Pi Desk remains usable in any terminal.
    shutil.copytree(SOURCE / 'vscode-selection', app / 'vscode-selection', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('test_*', '__pycache__', '*.vsix'))
    config_dir = home / '.config/pi-desk'
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = config_dir / 'client.json'
    client.write_text(json.dumps(asdict(config), indent=2) + '\n')
    client.chmod(0o600)
    bindir = home / '.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    launcher = bindir / 'pi-desk'
    launcher.write_text('#!/bin/sh\nexport PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
                        f'exec {shlex.quote(sys.executable)} "$HOME/.local/share/pi-desk/cli.py" "$@"\n')
    launcher.chmod(0o700)
    rc = home / shell_rc
    existing = rc.read_text() if rc.exists() else ''
    if PATH_LINE not in existing:
        with rc.open('a') as stream:
            stream.write('\n' + PATH_LINE + '\n')
    if mac:
        profile = plistlib.loads((SOURCE / 'config/pi-desk.terminal').read_bytes())
        profile['CommandString'] = shlex.join(['/bin/sh', '-c', 'exec "$HOME/.local/bin/pi-desk"'])
        profile['RunCommandAsShell'] = False
        (app / 'launch.terminal').write_bytes(plistlib.dumps(profile))
        contents = home / 'Applications/Pi Desk.app/Contents'
        (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleName': 'Pi Desk', 'CFBundleIdentifier': 'local.jarvis.pi-desk',
            'CFBundleExecutable': 'Pi Desk', 'CFBundlePackageType': 'APPL',
            'CFBundleVersion': '1', 'LSUIElement': True,
        }))
        entry = contents / 'MacOS/Pi Desk'
        entry.write_text('#!/bin/sh\nexec /usr/bin/open -a Terminal "$HOME/.local/share/pi-desk/launch.terminal"\n')
        entry.chmod(0o700)
    manifest = {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in app.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    (app / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (backup / 'deployment.json').write_text(json.dumps({'createdAt': stamp, 'installed': manifest}, indent=2) + '\n')
    print('Rollback backup: ' + str(backup))
    print('Installed pi-desk; open a new terminal or use ~/.local/bin/pi-desk.')
    print('No hosted sessions or services were restarted.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('local', 'ssh'), required=True)
    parser.add_argument('--project-root', default='/Users/dylanrapanan/JARVIS')
    args = parser.parse_args()
    install(args.backend, args.project_root)
