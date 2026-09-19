#!/usr/bin/env python3
"""Configure (not start) isolated macOS room-audio LaunchAgents, or run one role.

Credentials live only in an owner-only environment JSON file outside the repo.
Run --help for setup. Existing Pi agents, tokens and server ports are untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import secrets
import socket
import stat
import sys
from pathlib import Path

ROOM = Path(__file__).resolve().parent
ROOT = ROOM.parents[3]
DEFAULT_STATE = Path.home() / 'Library/Application Support/JARVIS/room-audio-mac'
LABEL_PREFIX = 'com.operation-jarvis.room-audio-mac-'


def client_arguments(port: int, device: str) -> list[str]:
    return [str(ROOM / 'pi_room_audio_client.py'),
            '--audio-backend', 'coreaudio', '--server-url', f'http://127.0.0.1:{port}',
            '--device', device, '--playback-device', device, '--rate', '48000',
            '--vad-loop', '--local-wake-word', '--openwakeword-inference', 'onnx',
            '--no-openwakeword-auto-download', '--local-wake-word-threshold', '0.75',
            '--no-vad-release-capture-during-turn', '--no-vad-restore-capture-while-waiting',
            '--interrupt-while-busy', '--bt-profile-settle-seconds', '0',
            '--bt-playback-drain-seconds', '0', '--startup-greeting',
            '--no-greeting-on-reconnect', '--async-ack', '--interval', '1.0']


def build_agent(role: str, python: Path, state: Path, agents: Path) -> tuple[Path, dict]:
    label = LABEL_PREFIX + role
    return agents / (label + '.plist'), {
        'Label': label,
        'ProgramArguments': [str(python), str(Path(__file__).resolve()), 'run',
                             '--role', role, '--state-dir', str(state)],
        'WorkingDirectory': str(ROOT),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                                 'PYTHONUNBUFFERED': '1'},
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
        # Background launchd QoS can starve real-time USB capture on a busy Mac.
        'ProcessType': 'Interactive' if role == 'client' else 'Adaptive',
        'ExitTimeOut': 10, 'Umask': 0o077,
        'StandardOutPath': str(state / 'logs' / (role + '.out.log')),
        'StandardErrorPath': str(state / 'logs' / (role + '.err.log')),
    }


def read_environment(path: Path) -> dict[str, str]:
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('Endpoint environment must be owner-only (chmod 600)')
    values = json.loads(path.read_text())
    if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
        raise ValueError('Invalid endpoint environment')
    if not values.get('JARVIS_ROOM_AUDIO_TOKEN'):
        raise ValueError('Endpoint token is required')
    return values


def configure(args) -> None:
    state = args.state_dir.expanduser().absolute()
    client_python = state / '.venv/bin/python'
    server_python = ROOT / '.venv/bin/python'
    for path in (client_python, server_python):
        if not path.is_file():
            raise ValueError(f'Missing Python: {path}; provision dependencies first')
    if not 1024 <= args.port <= 65535 or args.port == 8791:
        raise ValueError('Choose a nonprivileged port other than the Pi server port 8791')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))  # Fail rather than disturb another service.
    agents = Path.home() / 'Library/LaunchAgents'
    definitions = [build_agent(role, python, state, agents)
                   for role, python in [('server', server_python), ('client', client_python)]]
    if not args.replace and any(path.exists() for path, _ in definitions):
        raise ValueError('Mac endpoint agents already exist; stop them first, then use --replace')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    (state / 'logs').mkdir(exist_ok=True, mode=0o700)
    env_path = state / 'environment.json'
    token = read_environment(env_path)['JARVIS_ROOM_AUDIO_TOKEN'] if env_path.exists() else secrets.token_urlsafe(48)
    environment = {
        'JARVIS_ROOM_AUDIO_TOKEN': token,
        'JARVIS_ROOM_AUDIO_CHANNEL_ID': 'room-audio-mac',
        'JARVIS_ROOM_AUDIO_CHANNEL_NAME': 'mac-mini-64-room-audio',
        'JARVIS_ROOM_AUDIO_HOST': '127.0.0.1',
        'JARVIS_ROOM_AUDIO_PORT': str(args.port),
        'JARVIS_ROOM_AUDIO_ASR_BACKEND': 'apple-speech',
        'JARVIS_ROOM_AUDIO_ASR_FALLBACK_BACKEND': '',
        'JARVIS_ROOM_AUDIO_INTERRUPT_ASR_BACKEND': 'apple-dictation',
        'JARVIS_ROOM_AUDIO_INTERRUPT_ASR_FALLBACK_BACKEND': '',
        'JARVIS_ROOM_AUDIO_GREETING_STATE_PATH': str(state / 'greeting-state.json'),
        'JARVIS_ROOM_AUDIO_GREETING_TEXT': 'The Mac room speaker is online, sir.',
        'JARVIS_ROOM_AUDIO_TTS_LEADING_SILENCE_MS': '450',
        'JARVIS_ROOM_AUDIO_DEVICE': args.device,
    }
    temporary = state / 'environment.json.tmp'
    temporary.write_text(json.dumps(environment, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(env_path)
    agents.mkdir(parents=True, exist_ok=True)
    for path, definition in definitions:
        path.write_bytes(plistlib.dumps(definition))
        path.chmod(0o600)
        print(f'Configured: {path}')
    print(f'Private state: {state}\nNot started. Bootstrap the server, check health, then bootstrap the client.')


def run_role(args) -> None:
    state = args.state_dir.expanduser().absolute()
    environment = read_environment(state / 'environment.json')
    os.environ.update(environment)
    port = int(environment['JARVIS_ROOM_AUDIO_PORT'])
    if args.role == 'server':
        command = [str(ROOT / '.venv/bin/python'), str(ROOM / 'room_audio_server.py'),
                   '--host', '127.0.0.1', '--port', str(port)]
    else:
        command = [str(state / '.venv/bin/python'), *client_arguments(port, environment['JARVIS_ROOM_AUDIO_DEVICE'])]
    os.chdir(ROOT)
    os.execv(command[0], command)


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    install = sub.add_parser('configure')
    install.add_argument('--port', type=int, default=8793)
    install.add_argument('--device', default='PowerConf')
    install.add_argument('--replace', action='store_true')
    install.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    run = sub.add_parser('run')
    run.add_argument('--role', choices=['server', 'client'], required=True)
    run.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('macOS only')
    if args.action == 'configure':
        configure(args)
    else:
        run_role(args)


if __name__ == '__main__':
    main()
