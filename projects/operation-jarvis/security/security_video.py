"""Bounded local D235 video; no cloud, audio output, or persistent service."""
import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import uuid

import security_audio as audio
import security_cli as cli


def add_parser(sub):
    for command in ('snapshot', 'live'):
        p = sub.add_parser(command, help='Private local D235 video (explicit approval required)')
        p.add_argument('device')
        p.add_argument('--confirm', action='store_true')
        p.add_argument('--quality', choices=('low', 'hd'), default='hd',
                       help='low: existing H264 preview; hd: dedicated HEVC bridge')
        if command == 'live':
            p.add_argument('--seconds', type=int, default=30, help='Viewer lifetime, 1–120 seconds')
            p.add_argument('--verify-only', action='store_true', help='Decode locally without displaying or saving video')


def run_bounded(command, seconds, *, timeout_expected=False):
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        try:
            code = proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            if timeout_expected:
                return  # Live RTSP may not send EOF; always reap in finally.
            raise cli.ControlError('video_timeout') from None
        if code:
            raise cli.ControlError('video_transport_failed')
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)


def execute_video(args, adapter=None):
    try:
        return _execute_video(args)
    except cli.ControlError as exc:
        # CLI can be running as __main__, with its own exception class.
        if adapter is not None:
            raise adapter.ControlError(str(exc)) from None
        raise


def _execute_video(args):
    # Confirmation and bounds before credentials, locks or any networking.
    if not args.confirm:
        raise cli.ControlError('confirmation_required')
    if args.command not in ('live', 'snapshot'):
        raise cli.ControlError('unsupported_video_command')
    quality = getattr(args, 'quality', 'hd')
    if quality not in ('low', 'hd'):
        raise cli.ControlError('invalid_video_quality')
    seconds = getattr(args, 'seconds', 30)
    if type(seconds) is not int or not 1 <= seconds <= 120:
        raise cli.ControlError('invalid_video_duration')
    entry = cli.registry(args.registry).get(args.device)
    if not entry or entry.get('model') != 'D235' or not entry.get('host'):
        raise cli.ControlError('direct_doorbell_required')
    ffmpeg = shutil.which('ffmpeg')
    ffplay = shutil.which('ffplay')
    verify = getattr(args, 'verify_only', False)
    if not ffmpeg or (args.command == 'live' and not verify and not ffplay):
        raise cli.ControlError('video_tool_unavailable')
    settings = cli.load_settings(args.env_file)
    old_umask = os.umask(0o077)
    try:
        runtime = audio.private_dir(cli.ROOT / '.video-runtime')
        with ExitStack() as locks, audio.interruptible():
            locks.enter_context(cli.device_lock(entry['hub']))
            locks.enter_context(cli.device_lock(args.device))
            asyncio.run(asyncio.wait_for(audio.identify_doorbell(entry, args.env_file), 50))
            with tempfile.TemporaryDirectory(prefix='video-', dir=runtime) as name:
                tmp = Path(name)
                app = (cli.ROOT / 'private-notes/audio-poc/hd-video/JARVIS Doorbell Video.app'
                       if quality == 'hd' else audio.MIC16_APP)
                session = audio.CameraSession(app, tmp, entry['host'], settings.password, lambda: None)
                try:
                    session.start(video_only=True, video_quality=quality)
                    source = ['-rtsp_transport', 'tcp', '-timeout', '10000000', '-i', session.rtsp_video_url]
                    if args.command == 'snapshot':
                        frame = tmp / 'frame.jpg'
                        run_bounded([ffmpeg, '-nostdin', '-v', 'error', *source,
                                     '-map', '0:v:0', '-an', '-frames:v', '1', '-update', '1',
                                     '-q:v', '2', '-n', str(frame)], 25)
                        if not frame.is_file() or frame.stat().st_size == 0:
                            raise cli.ControlError('empty_video_frame')
                        directory = audio.private_dir(cli.ROOT / 'private-snapshots')
                        output = directory / ('doorbell-' + uuid.uuid4().hex + '.jpg')
                        with output.open('xb') as dst:
                            try:
                                with frame.open('rb') as src:
                                    shutil.copyfileobj(src, dst)
                            except BaseException:
                                output.unlink(missing_ok=True)
                                raise
                        return {'result': 'snapshot_saved', 'device': args.device,
                                'path': str(output), 'bytes': output.stat().st_size, 'quality': quality,
                                'audio': 'excluded', 'displayed': False}
                    if verify:
                        # Decode at least one frame; a successful empty EOF is not proof.
                        progress = tmp / 'progress.txt'
                        run_bounded([ffmpeg, '-nostdin', '-v', 'error', *source, '-map', '0:v:0',
                                     '-an', '-t', str(seconds), '-progress', str(progress),
                                     '-f', 'null', '-'], seconds + 25)
                        frames = [int(line.split('=', 1)[1]) for line in progress.read_text().splitlines()
                                  if line.startswith('frame=')]
                        if not frames or max(frames) <= 0:
                            raise cli.ControlError('empty_video_stream')
                        return {'result': 'live_video_decode_verified', 'device': args.device,
                                'decoded_frames': max(frames), 'quality': quality,
                                'audio': 'excluded', 'displayed': False}
                    # Viewer shows video locally only. No microphone/speaker output or recording.
                    run_bounded([ffplay, '-v', 'error', '-an', '-autoexit', '-t', str(seconds),
                                 '-window_title', 'JARVIS front door (local)', *source], seconds, timeout_expected=True)
                    return {'result': 'live_view_closed', 'device': args.device,
                            'quality': quality, 'audio': 'excluded', 'physical_verification': 'not_assessed'}
                finally:
                    session.close()
    except audio.AudioError as exc:
        raise cli.ControlError(str(exc)) from None
    except (OSError, ValueError, TimeoutError):
        raise cli.ControlError('video_operation_failed') from None
    finally:
        os.umask(old_umask)
