#!/usr/bin/env python3
"""Camera PCM/playback worker for the existing room conversation state machine.

Only a supervisor-created owner-only loopback session file is accepted. No camera
credentials, network scans, microphone recordings or wake-policy changes here.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse

SECURITY = Path(__file__).resolve().parents[1] / 'security'
sys.path.insert(0, str(SECURITY))
from security_audio import (AudioError, CameraSession, prepare, read_json,
                            interruptible)
from security_cli import device_lock


def load_session(device):
    name = os.environ.get('JARVIS_ROOM_CAMERA_SESSION_FILE', '')
    if not name:
        raise AudioError('camera_session_required')
    data = read_json(Path(name))
    if not isinstance(data, dict) or data.get('device') != device:
        raise AudioError('camera_session_device_mismatch')
    for key, scheme in (('api', 'http'), ('rtsp', 'rtsp')):
        parsed = urllib.parse.urlsplit(data[key])
        if parsed.scheme != scheme or parsed.hostname != '127.0.0.1' or not parsed.port:
            raise AudioError('camera_session_must_be_loopback')
    if not isinstance(data.get('token'), str) or len(data['token']) < 20:
        raise AudioError('camera_session_token_required')
    if not 0 <= int(data['volume']) <= 100:
        raise AudioError('invalid_camera_gain')
    return data


def capture_command(data, rate, *, seconds=None, path=None):
    if rate not in (8000, 16000, 48000):
        raise AudioError('unsupported_camera_sample_rate')
    command = ['/opt/homebrew/bin/ffmpeg', '-nostdin', '-v', 'error',
               '-rtsp_transport', 'tcp', '-timeout', '5000000',
               '-fflags', 'nobuffer', '-flags', 'low_delay',
               '-probesize', '32768', '-analyzeduration', '1000000',
               '-i', data['rtsp'], '-vn', '-ac', '1', '-ar', str(rate)]
    if path is not None:
        if seconds is None or not 0 < seconds <= 120:
            raise AudioError('invalid_capture_duration')
        command += ['-t', str(seconds), '-y', str(path)]
    else:
        command += ['-f', 's16le', 'pipe:1']
    return command


def producer_ids(info):
    return {p['id'] for p in info.get('producers') or [] if 'id' in p}


def play(data, path, device):
    os.umask(0o077)
    directory = Path(os.environ['JARVIS_ROOM_CAMERA_SESSION_FILE']).parent
    with device_lock(device), interruptible(), tempfile.TemporaryDirectory(prefix='reply-', dir=directory) as name:
        tmp = Path(name)
        args = argparse.Namespace(audio_command='play', file=str(path), duration=None)
        session = CameraSession('', tmp, '', '', lambda: None)
        session.base, session.token = data['api'], data['token']
        try:
            file, seconds = prepare(args, tmp, int(data['volume']), lambda: None)
            before = producer_ids(session.request({'src': 'speaker'}))
            began = time.monotonic()
            playback = producer_ids(session.play(file)) - before
            if not playback and seconds > 2:
                raise AudioError('camera_playback_not_started')
            # The microphone is a persistent consumer. Watch only this reply's
            # producer IDs, not overall consumer count, to detect audio EOF.
            while playback & producer_ids(session.request({'src': 'speaker'}, timeout=0.4)):
                if time.monotonic() - began > seconds + 15:
                    raise AudioError('camera_playback_timeout')
                time.sleep(0.1)
            if time.monotonic() - began < max(0, seconds - 2):
                raise AudioError('camera_playback_ended_early')
            time.sleep(0.25)  # Small transport drain, cancellable by SIGTERM.
        finally:
            try:
                session.request({'dst': 'speaker', 'src': ''}, 'POST', timeout=0.25)
            except AudioError:
                pass
            # Do NOT close the shared app/camera microphone session.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('capture', 'record', 'playback'))
    parser.add_argument('--device', required=True)
    parser.add_argument('--rate', type=int, default=16000)
    parser.add_argument('--path', type=Path)
    parser.add_argument('--seconds', type=float)
    args = parser.parse_args()
    data = load_session(args.device)
    if args.operation == 'playback':
        if args.path is None:
            parser.error('playback requires --path')
        play(data, args.path, args.device)
    else:
        if args.operation == 'record' and args.path is None:
            parser.error('record requires --path')
        cmd = capture_command(data, args.rate,
                              path=args.path if args.operation == 'record' else None,
                              seconds=args.seconds)
        # Exec rather than wrapping ffmpeg: existing PCM watchdog/termination owns
        # the exact capture process and cannot leave an orphaned microphone.
        os.execv(cmd[0], cmd)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception:
        print('camera_audio_worker_failed', file=sys.stderr)
        raise SystemExit(2)
