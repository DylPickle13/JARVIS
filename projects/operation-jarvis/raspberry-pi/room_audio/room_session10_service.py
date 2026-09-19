#!/usr/bin/env python3
"""Supervise only the explicitly provisioned Room Audio tmux Session 10.

Never creates or changes Sessions 1–9. Bootstrap requires a retained existing
conversation file; current owner metadata wins on later restarts. No idle reset.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]
STATE = ROOT / '.pi/runtime/room-audio-session'
TMUX = '/opt/homebrew/bin/tmux'
SESSION = '=jarvis-ios-10'


def run(*args, check=True):
    return subprocess.run([TMUX, '-L', 'jarvis-mobile', *args], check=check, capture_output=True, text=True)


def main():
    os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    config = json.loads((STATE / 'bootstrap.json').read_text())
    while True:
        exists = run('has-session', '-t', SESSION, check=False).returncode == 0
        dead = exists and run('display-message', '-p', '-t', SESSION + ':0.0', '#{pane_dead}').stdout.strip() == '1'
        if not exists or dead:
            source = config['sessionFile']
            owner = STATE / 'owner.json'
            if owner.is_file():
                saved = json.loads(owner.read_text())
                if saved.get('sessionID') == 10 and saved.get('sessionFile'):
                    source = saved['sessionFile']
            path = Path(source)
            allowed = Path.home() / '.pi/agent/sessions'
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(allowed.resolve()):
                raise RuntimeError('Retained Room Audio history unavailable; refusing a replacement conversation')
            command = shlex.join(['/opt/homebrew/bin/pi', '--tui-mode', 'regular', '--session', str(path),
                '--model', config['model'], '--thinking', config.get('thinking', 'high'),
                '--append-system-prompt', str(STATE / 'system.md')])
            if dead:
                run('respawn-pane', '-t', SESSION + ':0.0', '-c', str(ROOT), 'exec ' + command + ' 2>' + shlex.quote(str(STATE / 'startup-error.log')))
            else:
                run('new-session', '-d', '-s', 'jarvis-ios-10', '-c', str(ROOT), 'exec ' + command + ' 2>' + shlex.quote(str(STATE / 'startup-error.log')))
        time.sleep(3)


if __name__ == '__main__':
    os.umask(0o077)
    main()
