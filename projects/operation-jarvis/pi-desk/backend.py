"""Explicit local/SSH transport configuration. Never infer the session host."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
CONFIG = Path.home() / '.config/pi-desk/client.json'
SSH_OPTIONS = ['-a', '-x', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=5',
               '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2']


@dataclass(frozen=True)
class Backend:
    mode: str = 'ssh'
    host: str = 'mac-mini-64'
    project_root: str = '/Users/dylanrapanan/JARVIS'

    def __post_init__(self):
        if self.mode not in ('local', 'ssh'):
            raise ValueError('Backend must be local or ssh')
        if not isinstance(self.host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', self.host):
            raise ValueError('Host must be an SSH alias')
        if not isinstance(self.project_root, str) or not self.project_root.startswith('/') or '\n' in self.project_root:
            raise ValueError('Host project root must be an absolute path')

    def run_on_host(self, command, tty=False):
        if self.mode == 'local':
            return command
        # Quote every token: shlex.join leaves =targets bare, and zsh expands
        # =jarvis-ios as a command-path lookup before tmux ever sees it.
        remote = ' '.join("'" + arg.replace("'", "'\"'\"'") + "'" for arg in command)
        return ['ssh', '-t' if tty else '-T', *SSH_OPTIONS, self.host, remote]

    def attachment(self, number):
        if type(number) is not int or not 1 <= number <= 10:
            raise ValueError('Session must be between 1 and 10')
        target = 'jarvis-ios' + (f'-{number}' if number > 1 else '')
        return self.run_on_host(['/opt/homebrew/bin/tmux', '-L', 'jarvis-mobile',
                                 'attach-session', '-E', '-f', 'ignore-size', '-t', '=' + target], tty=True)

    def status(self):
        if self.mode == 'local':
            return [sys.executable, str(ROOT / 'status_stream.py')]
        return ['ssh', '-T', *SSH_OPTIONS, self.host,
                'exec /usr/bin/python3 "$HOME/.local/share/pi-desk/status_stream.py"']

    def restart(self, dry_run=False):
        helper = Path(self.project_root) / 'projects/operation-jarvis/jarvis-app/scripts/jarvis-mobile-vscode-restart.py'
        return self.run_on_host(['/usr/bin/python3', '-u', str(helper), '--all',
                                 *(['--dry-run'] if dry_run else [])])


def load(path=CONFIG):
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return Backend()  # Existing Pi installations remain SSH clients.
    if not isinstance(data, dict) or set(data) - {'mode', 'host', 'project_root'}:
        raise ValueError('Invalid Pi Desk client configuration')
    return Backend(**data)


def clean_environment():
    env = os.environ.copy()
    # Only the display's nesting markers; never change the real server environment.
    for name in ('TMUX', 'TMUX_PANE'):
        env.pop(name, None)
    env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + env.get('PATH', '/usr/bin:/bin')
    return env
