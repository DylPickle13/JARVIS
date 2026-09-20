#!/usr/bin/env python3
"""Supervise an opt-in C230 room endpoint on the Mac, replacing the Pi USB client.

Uses the EXISTING Pi-room server/context on loopback 8791. The Mac USB endpoint
and server are untouched. Configure only writes private trial configuration;
operator must separately stop the old Pi client and bootstrap the trial agent.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time

ROOM = Path(__file__).resolve().parent
OPERATION = ROOM.parent
ROOT = OPERATION.parents[1]
SECURITY = OPERATION/'security'
sys.path.insert(0, str(SECURITY))
from security_audio import (APP, MIC16_APP, AudioError, CameraSession, identify, interruptible,
                            private_dir, read_json, save_json)
from security_cli import registry, load_settings, device_lock

STATE = Path.home()/'Library/Application Support/JARVIS/room-audio-camera'
LABEL = 'com.operation-jarvis.room-audio-camera'


def client_arguments(device):
    return [str(ROOM/'pi_room_audio_client.py'), '--audio-backend', 'camera',
            '--server-url', 'http://127.0.0.1:8791', '--device', device,
            '--playback-device', device, '--rate', '16000',
            '--vad-loop', '--local-wake-word', '--openwakeword-inference', 'onnx',
            '--no-openwakeword-auto-download', '--local-wake-word-threshold', '0.75',
            '--no-vad-release-capture-during-turn', '--no-vad-restore-capture-while-waiting',
            '--interrupt-while-busy', '--bt-profile-settle-seconds', '0',
            '--bt-playback-drain-seconds', '0', '--no-startup-greeting',
            '--no-greeting-on-reconnect', '--async-ack', '--interval', '1.0']


def configure(args):
    if not args.confirm:
        raise AudioError('confirmation_required')
    state = private_dir(args.state_dir.expanduser())
    if (state/'environment.json').exists():
        raise AudioError('camera_endpoint_already_configured')
    entry = registry().get(args.device)
    if not entry or entry.get('model') != 'C230':
        raise AudioError('camera_not_commissioned')
    client_python = Path.home()/'Library/Application Support/JARVIS/room-audio-mac/.venv/bin/python'
    app = MIC16_APP if args.native_microphone16 else APP
    if not client_python.is_file() or not (app/'Contents/MacOS/go2rtc').is_file():
        raise AudioError('camera_endpoint_dependency_missing')
    # Only the existing room token is copied, not cloud or other project secrets.
    sys.path.insert(0, str(OPERATION/'voice'))
    import config
    token = config.parse_dotenv_file(ROOT/'.env').get('JARVIS_ROOM_AUDIO_TOKEN', '')
    if not token:
        raise AudioError('existing_room_token_required')
    save_json(state/'environment.json', {'device': args.device, 'volume': args.volume,
              'client_python': str(client_python), 'room_token': token,
              'microphone16': args.native_microphone16})
    private_dir(state/'logs')
    definition = {
        'Label': LABEL,
        'ProgramArguments': [str(SECURITY/'.venv-313/bin/python'), str(Path(__file__).resolve()),
                             'run', '--state-dir', str(state)],
        'WorkingDirectory': str(ROOT),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                                 'PYTHONUNBUFFERED': '1'},
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 15,
        'ProcessType': 'Interactive', 'ExitTimeOut': 15, 'Umask': 0o077,
        'StandardOutPath': str(state/'logs/client.out.log'),
        'StandardErrorPath': str(state/'logs/client.err.log')}
    path = state/'trial.plist'
    path.write_bytes(plistlib.dumps(definition)); path.chmod(0o600)
    print('Configured private trial agent. Not started; no USB client changed.')


def run(args):
    state = private_dir(args.state_dir.expanduser())
    config = read_json(state/'environment.json')
    entry = registry().get(config['device'])
    if not entry or entry.get('model') != 'C230':
        raise AudioError('camera_not_commissioned')
    settings = load_settings(SECURITY/'.env')
    # Separate lease prevents two supervisors, without blocking normal camera
    # status/settings forever. Individual speaker replies take the device lock.
    with device_lock('room-camera-' + config['device']), interruptible():
        asyncio.run(asyncio.wait_for(identify(entry['host'], settings), 18))
        # No spaces: ffmpeg source syntax has path-sensitive parsing upstream.
        runtime = private_dir(SECURITY/'.audio-runtime')
        with tempfile.TemporaryDirectory(prefix='room-camera-', dir=runtime) as name:
            tmp = Path(name)
            mic16 = config.get('microphone16', False)
            session = CameraSession(MIC16_APP if mic16 else APP, tmp, entry['host'], settings.password,
                                    lambda: None, microphone16=mic16)
            child = None
            try:
                session.start()
                manifest = tmp/'room-session.json'
                save_json(manifest, {'device': config['device'], 'volume': config['volume'],
                          'api': session.base, 'rtsp': session.rtsp_audio_url, 'token': session.token})
                env = {**os.environ, 'JARVIS_ROOM_AUDIO_TOKEN': config['room_token'],
                       'JARVIS_ROOM_CAMERA_SESSION_FILE': str(manifest),
                       'PYTHONUNBUFFERED': '1'}
                print(f'Camera room endpoint connected; microphone={16000 if mic16 else 8000} Hz, '
                      'speaker=8000 Hz; local wake gating active on client startup.', flush=True)
                child = subprocess.Popen([config['client_python'], *client_arguments(config['device'])],
                                         env=env, start_new_session=True)
                # Keep the camera session alive with the client, and restart the
                # entire endpoint if the app exits rather than retain a dead URL.
                while child.poll() is None:
                    if session.launcher.poll() is not None:
                        raise AudioError('camera_app_exited')
                    time.sleep(0.5)
                if child.returncode:
                    raise AudioError('camera_room_client_exited')
            finally:
                if child is not None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=3)
                    # Even if the main client exited, close any remaining capture
                    # worker in its dedicated group.
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                session.close()
                print('Camera room endpoint stopped and temporary session removed.', flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('configure')
    setup.add_argument('--device', default='indoor-camera')
    setup.add_argument('--volume', type=int, choices=range(101), default=30)
    setup.add_argument('--confirm', action='store_true')
    setup.add_argument('--native-microphone16', action='store_true',
                       help='Opt into the commissioned microphone-only go2rtc patch; speaker stays 8 kHz')
    setup.add_argument('--state-dir', type=Path, default=STATE)
    start = sub.add_parser('run')
    start.add_argument('--state-dir', type=Path, default=STATE)
    args = parser.parse_args()
    configure(args) if args.command == 'configure' else run(args)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        print(str(exc) if isinstance(exc, AudioError) else 'camera_room_endpoint_failed', file=sys.stderr)
        raise SystemExit(2)
