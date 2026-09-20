"""Foreground, owner-approved C230/D235 speaker audio. No daemon or backend routes.

Volume is digital gain, not a persistent camera speaker setting. Runtime metadata
contains no speech, media paths, LAN addresses or credentials. Media and local API
credentials exist only in an owner-only temporary directory for the session.
"""
import asyncio
from contextlib import contextmanager, ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

ROOT = Path(__file__).resolve().parent
MIC16_APP = ROOT / 'private-notes/audio-poc/native16/JARVIS Camera Audio 16k.app'
APP = MIC16_APP  # One approved bundle for room audio and standalone playback.
DEFAULT_VOLUME = 30


class AudioError(Exception):
    pass


class Stopped(Exception):
    pass


def percentage(value):
    value = int(value)
    if not 0 <= value <= 100:
        raise ValueError('volume_must_be_0_to_100')
    return value


def duration_arg(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('duration_must_be_positive')
    return value


def add_parser(sub):
    p = sub.add_parser('audio', help='C230/D235 speech, files, volume, status and stop')
    commands = p.add_subparsers(dest='audio_command', required=True)
    for name in ('speak', 'play', 'status', 'stop', 'volume'):
        s = commands.add_parser(name)
        s.add_argument('device')
        if name == 'speak':
            source = s.add_mutually_exclusive_group(required=True)
            source.add_argument('--text', help='Speech text (visible in shell history); prefer --text-file')
            source.add_argument('--text-file', help='UTF-8 local file, or - for stdin')
            s.add_argument('--voice', default='jarvis', help='jarvis (Piper default), or installed macOS say voice')
        if name == 'play':
            s.add_argument('file', help='Local audio file; URLs and playlists are not supported')
        if name in ('speak', 'play'):
            s.add_argument('--volume', type=percentage, help='Digital gain 0–100 percent; defaults to saved value or 30')
            s.add_argument('--duration', type=duration_arg, help='Optional playback limit in seconds; default: no limit')
            s.add_argument('--loop', action='store_true', help='Repeat until stopped; small gap between repetitions')
            s.add_argument('--app', default=str(APP), help='Permission-approved go2rtc macOS app bundle')
        if name == 'volume':
            s.add_argument('level', nargs='?', type=percentage, help='Save gain for FUTURE sessions; omit to read')
        if name in ('speak', 'play', 'stop', 'volume'):
            s.add_argument('--confirm', action='store_true', help='Explicit approval for playback/control')


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise AudioError('private_audio_directory_required')
    return path


def read_json(path, default=None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return default
    with os.fdopen(fd) as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise AudioError('private_audio_file_required')
        return json.load(f)


def save_json(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def local_file(value):
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise AudioError('local_media_file_required')
    return path


def load_text(args):
    if args.text is not None:
        text = args.text
    elif args.text_file == '-':
        import sys
        text = sys.stdin.read()
    else:
        text = local_file(args.text_file).read_text(encoding='utf-8')
    if not text.strip() or '\x00' in text:
        raise AudioError('nonempty_speech_required')
    return text


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def identify(host, settings):
    from kasa import Discover
    dev = None
    try:
        dev = await Discover.discover_single(host, username=settings.username,
                                            password=settings.password,
                                            discovery_timeout=5, timeout=5)
        if dev is None or dev.model != 'C230':
            raise AudioError('audio_identity_mismatch')
    finally:
        if dev is not None:
            await asyncio.wait_for(dev.disconnect(), 2)


async def identify_doorbell(entry, env_file):
    # D235 discovery is unreliable; use the isolated, read-only HTTPS adapter.
    from security_doorbell import execute
    result = await execute(env_file, entry=entry, command='identity')
    if result.get('model') != 'D235' or result.get('doorbell_reachability') != 'authenticated':
        raise AudioError('audio_identity_mismatch')


@contextmanager
def interruptible():
    old = signal.getsignal(signal.SIGTERM)
    def stop_signal(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_signal)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, old)


def run_child(command, check_stop):
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        while proc.poll() is None:
            check_stop()
            # Wake immediately on completion rather than sleeping out a polling
            # interval. Keep cancellation checks bounded for long synthesis.
            try:
                proc.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        if proc.returncode:
            raise AudioError('audio_preparation_failed')
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)


def prepare(args, tmp, volume, check_stop):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise AudioError('ffmpeg_unavailable')
    if args.audio_command == 'speak':
        text = load_text(args)
        (tmp / 'speech.txt').write_text(text, encoding='utf-8')
        if args.voice == 'jarvis':
            python = ROOT.parent / '.venv/bin/python'
            if not python.exists():
                raise AudioError('jarvis_voice_environment_unavailable')
            source = tmp / 'voice.wav'
            run_child([str(python), str(ROOT/'security_tts.py'), str(tmp/'speech.txt'), str(source)], check_stop)
        else:
            source = tmp / 'voice.aiff'
            run_child(['/usr/bin/say', '-v', args.voice, '-f', str(tmp/'speech.txt'), '-o', str(source)], check_stop)
    else:
        source = local_file(args.file)
    # Restrict demuxers and protocols: local media cannot cause network fetches or
    # execute playlist/concat indirections. Copy input to a fixed safe filename.
    safe_source = tmp / 'input.media'
    with source.open('rb') as src, safe_source.open('wb') as dst:
        while block := src.read(1024 * 1024):
            check_stop()
            dst.write(block)
    output = tmp / 'playback.wav'
    command = [ffmpeg, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe',
               '-format_whitelist', 'wav,aiff,mp3,mov,flac,ogg,aac,matroska,webm',
               '-i', str(safe_source), '-map', '0:a:0', '-vn', '-af',
               f'volume={volume/100}' + (',adelay=1500:all=1,apad=pad_dur=2'
                                        if getattr(args, 'doorbell_padding', False) else ''),
               '-ar', str(getattr(args, 'sample_rate', 8000)), '-ac', '1', '-c:a', 'pcm_s16le']
    if args.duration is not None:
        command += ['-t', str(args.duration)]
    run_child(command + [str(output)], check_stop)
    with wave.open(str(output)) as wav:
        seconds = wav.getnframes() / wav.getframerate()
    if not math.isfinite(seconds) or seconds <= 0:
        raise AudioError('empty_audio')
    return output, seconds


class CameraSession:
    def __init__(self, app, tmp, host, password, check_stop, *, microphone16=False):
        self.app = Path(app).expanduser().resolve()
        self.tmp = tmp
        self.host = host
        self.password = password
        self.microphone16 = microphone16
        self.codec = 'pcma'  # Speaker stays on the physically verified 8 kHz path.
        self.check_stop = check_stop
        self.launcher = None
        self.base = None
        self.token = secrets.token_urlsafe(32)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, params, method='GET', timeout=5):
        import base64
        url = self.base + '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method=method)
        auth = base64.b64encode(('audio:' + self.token).encode()).decode()
        req.add_header('Authorization', 'Basic ' + auth)
        try:
            with self.opener.open(req, timeout=timeout) as res:
                raw = res.read(1024 * 1024)
            return json.loads(raw) if raw else {}
        except Exception:
            # Never return raw go2rtc diagnostics (may contain credential URLs).
            raise AudioError('camera_audio_transport_failed') from None

    def start(self, *, video_only=False, video_quality='low'):
        if not (self.app / 'Contents/MacOS/go2rtc').is_file():
            raise AudioError('approved_go2rtc_app_unavailable')
        api_port, rtsp_port = port(), port()
        while rtsp_port == api_port:
            rtsp_port = port()
        digest = hashlib.sha256(self.password.encode()).hexdigest().upper()
        config = (f'api:\n  listen: "127.0.0.1:{api_port}"\n  username: audio\n  password: {self.token}\n'
                  f'rtsp:\n  listen: "127.0.0.1:{rtsp_port}"\n'
                  'webrtc:\n  listen: ""\n  ice_servers: []\n'
                  'ffmpeg:\n  bin: ' + json.dumps(shutil.which('ffmpeg')) + '\n'
                  'log:\n  level: error\nstreams:\n  speaker: '
                  + json.dumps(f'tapo://admin:{digest}@{self.host}' + (('?subtype=0&video=h265' if video_quality == 'hd' else '?subtype=1') if video_only else
                      '?audio=mic16' if self.microphone16 else '')) + '\n')
        (self.tmp / 'go2rtc.yaml').write_text(config)
        self.base = f'http://127.0.0.1:{api_port}/api/streams'
        self.rtsp_audio_url = f'rtsp://127.0.0.1:{rtsp_port}/speaker?audio=' + ('pcmu' if self.microphone16 else 'pcma')
        self.launcher = subprocess.Popen(['/usr/bin/open', '-n', '-W', str(self.app), '--args',
                                         '-config', str(self.tmp/'go2rtc.yaml')],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        start_new_session=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.check_stop()
            if self.launcher.poll() is not None:
                raise AudioError('camera_audio_app_failed')
            try:
                self.request({}, timeout=0.5)
                break
            except AudioError:
                time.sleep(0.1)
        else:
            raise AudioError('camera_audio_start_timeout')
        info = self.request({'src': 'speaker', 'video' if video_only else 'audio': 'all'}, timeout=15)
        medias = [m for p in info.get('producers') or [] for m in p.get('medias') or []]
        if video_only:
            if not any('video, recvonly,' in m for m in medias):
                raise AudioError('camera_video_codec_unavailable')
            self.rtsp_video_url = f'rtsp://127.0.0.1:{rtsp_port}/speaker?video'
            return
        expected = 'audio, sendonly, PCMA/8000'
        if not any(expected in m for m in medias):
            raise AudioError('camera_speaker_codec_unavailable')
        if self.microphone16 and not any('audio, recvonly, PCMU/16000' in m for m in medias):
            raise AudioError('camera_native_microphone_unavailable')

    def play(self, file):
        return self.request({'dst': 'speaker', 'src': f'ffmpeg:{file}#audio={self.codec}#input=file'}, 'POST', 15)

    def busy(self):
        return bool(self.request({'src': 'speaker'}).get('consumers'))

    def close(self):
        if self.base:
            try:
                self.request({'dst': 'speaker', 'src': ''}, 'POST', 2)
            except AudioError:
                pass
        # LaunchServices app is not a child of `open`. Match exact executable AND
        # our unique configuration path; never kill unrelated camera sessions.
        rows = subprocess.run(['/bin/ps', '-axo', 'pid=,command='], capture_output=True,
                              text=True, timeout=3).stdout.splitlines()
        pids = []
        for row in rows:
            if ((str(self.app/'Contents/MacOS/go2rtc') in row and str(self.tmp/'go2rtc.yaml') in row)
                    or ('ffmpeg' in row and str(self.tmp/'playback.wav') in row)):
                pids.append(int(row.strip().split(None, 1)[0]))
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        for pid in pids:
            if alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.launcher is not None:
            if self.launcher.poll() is None:
                self.launcher.terminate()
            try:
                self.launcher.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.launcher.kill()
                self.launcher.wait(timeout=3)


def playback_loop(session, file, seconds, repeat, limit, check_stop, clock=time.monotonic, sleep=time.sleep):
    start = clock()
    plays = 0
    while True:
        check_stop()
        if limit is not None and clock() - start >= limit:
            return 'duration_reached', plays
        began = clock()
        session.play(file)
        plays += 1
        while True:
            check_stop()
            elapsed = clock() - start
            if limit is not None and elapsed >= limit:
                return 'duration_reached', plays
            if not session.busy():
                if clock() - began < max(0, seconds - 2):
                    raise AudioError('audio_ended_early')
                break
            # No arbitrary maximum: watchdog scales with actual file duration.
            if clock() - began > seconds + 30:
                raise AudioError('audio_completion_timeout')
            sleep(0.2)
        if not repeat:
            return 'completed', plays


def execute_audio(args, adapter=None):
    # Use the caller's module even when security_cli runs as __main__.
    if adapter is None:
        import security_cli as adapter
    registry, load_settings = adapter.registry, adapter.load_settings
    device_lock, ControlError = adapter.device_lock, adapter.ControlError
    entry = registry(args.registry).get(args.device)
    if (not entry or entry.get('model') not in ('C230', 'D235')
            or not entry.get('host') or entry.get('host') == '@hub'
            or (entry.get('model') == 'D235' and not entry.get('hub'))):
        raise ControlError('audio_model_not_commissioned')
    operation = args.audio_command
    if operation in ('speak', 'play', 'stop') or (operation == 'volume' and args.level is not None):
        if not args.confirm:
            raise ControlError('confirmation_required')
    previous_umask = os.umask(0o077)
    try:
        runtime = private_dir(ROOT / '.audio-runtime')
        directory = private_dir(runtime / args.device)
        state_path, stop_path = directory/'state.json', directory/'stop.json'
        settings_dir = private_dir(ROOT / '.audio-settings')
        volume_path = settings_dir / (args.device + '.json')
        saved = read_json(volume_path, {'volume': DEFAULT_VOLUME})
        default_volume = percentage(saved['volume'])
        if operation == 'volume':
            if args.level is not None:
                save_json(volume_path, {'volume': args.level})
            return {'result': 'audio_volume', 'volume': default_volume if args.level is None else args.level,
                    'scope': 'digital_gain_future_sessions', 'device': args.device}
        if operation in ('status', 'stop'):
            state = read_json(state_path)
            if not state or not alive(state.get('pid')):
                return {'result': 'audio_idle', 'device': args.device, 'default_volume': default_volume}
            if operation == 'stop':
                save_json(stop_path, {'session': state['session']})
                return {'result': 'audio_stop_requested', 'device': args.device}
            return {'result': 'audio_status', 'device': args.device,
                    **{k: state[k] for k in ('phase', 'volume', 'voice', 'loop', 'duration_limit', 'media_seconds') if k in state}}
        volume = default_volume if args.volume is None else args.volume
        settings = load_settings(args.env_file)
        # Fail input validation before contacting the camera.
        if operation == 'play':
            local_file(args.file)
        else:
            args.text = load_text(args)
        with ExitStack() as locks, interruptible():
            # Match the doorbell adapter's hub-first locking order.
            if entry['model'] == 'D235':
                locks.enter_context(device_lock(entry['hub']))
            locks.enter_context(device_lock(args.device))
            session_id = secrets.token_hex(16)
            state = {'pid': os.getpid(), 'session': session_id, 'phase': 'identifying',
                     'volume': volume, 'voice': args.voice if operation == 'speak' else None,
                     'loop': args.loop, 'duration_limit': args.duration}
            def update(phase):
                state['phase'] = phase
                save_json(state_path, state)
            def check_stop():
                request = read_json(stop_path, {})
                if request.get('session') == session_id:
                    raise Stopped
            update('identifying')
            started = False
            try:
                with tempfile.TemporaryDirectory(prefix='session-', dir=directory) as name:
                    tmp = Path(name)
                    if entry['model'] == 'D235':
                        asyncio.run(asyncio.wait_for(identify_doorbell(entry, args.env_file), 50))
                    else:
                        asyncio.run(asyncio.wait_for(identify(entry['host'], settings), 18))
                    check_stop()
                    update('preparing')
                    args.doorbell_padding = entry['model'] == 'D235'
                    file, seconds = prepare(args, tmp, volume, check_stop)
                    state['media_seconds'] = round(seconds, 3)
                    session = CameraSession(args.app, tmp, entry['host'], settings.password, check_stop)
                    try:
                        update('connecting')
                        session.start()
                        check_stop()
                        update('playing')
                        started = True
                        outcome, plays = playback_loop(session, file, seconds, args.loop, args.duration, check_stop)
                        return {'result': 'audio_' + outcome, 'device': args.device, 'volume': volume,
                                'voice': state['voice'], 'plays': plays, 'media_seconds': round(seconds, 3),
                                'physical_verification': 'not_assessed'}
                    finally:
                        session.close()
            except Stopped:
                return {'result': 'audio_stopped', 'device': args.device}
            except KeyboardInterrupt:
                raise
            except Exception:
                if started:
                    return {'result': 'error', 'reason': 'audio_playback_outcome_unknown', 'outcome': 'unknown'}
                raise
            finally:
                state_path.unlink(missing_ok=True)
                stop_path.unlink(missing_ok=True)
    except AudioError as exc:
        raise ControlError(str(exc)) from None
    finally:
        os.umask(previous_umask)
