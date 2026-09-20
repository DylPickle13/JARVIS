#!/usr/bin/env python3
"""Configure the shared wake LaunchAgent and opt in existing Mac/camera clients.

Does not start/stop agents. Backups permit rollback without editing credentials.
"""
import argparse
import os
from pathlib import Path
import plistlib
import shutil

ROOM = Path(__file__).resolve().parent
STATE = Path.home() / 'Library/Application Support/JARVIS/room-wake'
LABEL = 'com.operation-jarvis.room-wake'
AGENT = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
CLIENTS = {
    'powerconf': Path.home() / 'Library/LaunchAgents/com.operation-jarvis.room-audio-mac-client.plist',
    'camera': Path.home() / 'Library/Application Support/JARVIS/room-audio-camera/trial.plist',
}


def configure():
    python = Path.home() / 'Library/Application Support/JARVIS/room-audio-mac/.venv/bin/python'
    if not python.is_file() or not all(p.is_file() for p in CLIENTS.values()):
        raise RuntimeError('Both existing room clients and their Python environment are required')
    socket = STATE / 'wake.sock'
    if len(os.fsencode(socket)) >= 104:
        raise RuntimeError('UNIX socket path is too long')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    logs = STATE / 'logs'
    logs.mkdir(exist_ok=True, mode=0o700)
    backups = STATE / 'backups'
    backups.mkdir(exist_ok=True, mode=0o700)
    # Preserve the first pre-shared configuration across repeated configuration.
    for room, path in CLIENTS.items():
        backup = backups / (room + '.plist')
        if not backup.exists():
            shutil.copy2(path, backup)
            backup.chmod(0o600)
        definition = plistlib.loads(path.read_bytes())
        definition.setdefault('EnvironmentVariables', {}).update(
            JARVIS_ROOM_WAKE_SOCKET=str(socket), JARVIS_ROOM_WAKE_ROOM=room)
        path.write_bytes(plistlib.dumps(definition))
        path.chmod(0o600)
    definition = {
        'Label': LABEL,
        'ProgramArguments': [str(python), str(ROOM / 'shared_room_wake.py'), '--socket', str(socket)],
        'WorkingDirectory': str(ROOM),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin', 'PYTHONUNBUFFERED': '1'},
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 5,
        'ProcessType': 'Interactive', 'Umask': 0o077,
        'StandardOutPath': str(logs / 'worker.out.log'),
        'StandardErrorPath': str(logs / 'worker.err.log'),
    }
    AGENT.write_bytes(plistlib.dumps(definition))
    AGENT.chmod(0o600)
    print(f'Configured worker: {AGENT}')
    print(f'Client backups: {backups}')
    print('Not started. Bootstrap worker, then reload both client agents.')


def rollback():
    for room, path in CLIENTS.items():
        backup = STATE / 'backups' / (room + '.plist')
        if not backup.is_file():
            raise RuntimeError(f'Missing rollback backup for {room}')
    for room, path in CLIENTS.items():
        shutil.copy2(STATE / 'backups' / (room + '.plist'), path)
    print('Client definitions restored. Reload clients, then boot out the shared worker.')


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollback', action='store_true')
    rollback() if parser.parse_args().rollback else configure()
