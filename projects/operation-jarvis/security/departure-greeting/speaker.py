"""One reserved outdoor-doorbell farewell. No retry, loop, or text input."""
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

import departure
import person_gate
import runtime
import security_audio as audio


class Expired(Exception):
    pass


def quoted_playback_path(file):
    """go2rtc v1.9.14 interpolates this into a QuoteSplit command string.

    Its parser is not POSIX shell escaping: use one double-quoted argument.
    The HTTP API separately rejects whitespace, including inside quotes.
    Reject URL/argv delimiters too; never bypass the API's security validation.
    """
    path = str(file)
    if (not Path(path).is_absolute()
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in path)
            or any(char in path for char in ('"', '#', '?'))):
        raise ValueError('unsupported_playback_path')
    return '"' + path + '"'


def play_once(root, request, *, clock=time.time):
    """Reuse identity/locks/approved app/codec/padding, with pre-play expiry."""
    journal = runtime.Journal(root)
    value = runtime.config(root)
    attempt = request.get('attempt')
    expires = request.get('expires')
    if (type(attempt) is not str or journal.state['pending'] != attempt
            or type(expires) not in (int, float) or not 0 < expires - clock() <= person_gate.VOICE_ONSET_SECONDS):
        return 'expired_before_play'
    if (not value['enabled'] or journal.state['fault'] is not None
            or not person_gate.valid_proof(root, attempt, expires, now=clock())):
        return 'failed_before_play'
    devices = departure.cli.registry(departure.SECURITY_ROOT / 'devices.json')
    speaker = devices.get(value['speaker_device'])
    motion = devices.get(value['motion_device'])
    if (not speaker or speaker.get('model') != 'D235' or not speaker.get('host')
            or not motion or speaker.get('hub') != motion.get('hub')):
        return 'failed_before_play'
    meta = runtime.read_json(root / 'phrase.json')
    source = root / 'phrase.wav'
    if (not meta or meta.get('phrase') != runtime.PHRASE or source.is_symlink()
            or not source.is_file() or source.stat().st_mode & 0o077 or source.stat().st_uid != os.getuid()
            or source.stat().st_size > 1024 * 1024
            or hashlib.sha256(source.read_bytes()).hexdigest() != meta.get('sha256')):
        return 'failed_before_play'
    attempted = False
    stage = 'identity'
    def diagnose(exc):
        # Fixed labels only: no exception text, URLs, credentials or media.
        safe_types = {'TimeoutError', 'OSError', 'AudioError', 'Expired'}
        reasons = {'camera_audio_transport_failed', 'audio_ended_early',
                   'audio_completion_timeout', 'camera_audio_app_failed',
                   'camera_audio_start_timeout', 'camera_speaker_codec_unavailable'}
        reason = str(exc) if isinstance(exc, audio.AudioError) and str(exc) in reasons else 'unclassified'
        try:
            runtime.save_json(root / 'speaker-diagnostic.json', {
                'attempt': attempt, 'stage': stage, 'playback_attempted': attempted,
                'error_type': type(exc).__name__ if type(exc).__name__ in safe_types else 'other',
                'reason': reason, 'observed_at': clock()})
        except Exception:
            pass  # Diagnostic failure must never change delivery/retry semantics.
    session = None
    def check():
        if not attempted and (clock() > expires or not runtime.config(root)['enabled']
                or not person_gate.valid_proof(root, attempt, expires, now=clock())):
            raise Expired()
    class DeadlineSession(audio.CameraSession):
        closing = False
        def request(self, params, method='GET', timeout=5):
            if not attempted and not self.closing:
                check()
                timeout = min(timeout, max(0.05, expires - clock()))
            elif attempted and not self.closing:
                timeout = min(timeout, 2)
            return super().request(params, method, timeout)
        def play(self, file):
            nonlocal attempted, stage
            check()
            # Leading silence is 1.5 s; the voice must begin before expiry.
            if clock() + person_gate.LEADING_SILENCE_SECONDS > expires:
                raise Expired()
            source = quoted_playback_path(file)
            # Durable marker BEFORE the possibly audible request. Parent regards
            # malformed/missing results or worker death as unknown, never retry.
            runtime.save_json(root / 'playback.json', {'attempt': attempt, 'started': True})
            attempted = True
            stage = 'play_request'
            result = super().play(source)
            stage = 'completion_monitor'
            return result
        def close(self):
            self.closing = True
            return super().close()
    try:
        with departure.cli.device_lock(speaker['hub']), departure.cli.device_lock(value['speaker_device']), audio.interruptible():
            check()
            # No 50-second identity wait for an expired doorstep greeting.
            async def identify():
                async with asyncio.timeout(max(0.05, expires - clock())):
                    await audio.identify_doorbell(speaker, departure.SECURITY_ROOT / '.env')
            asyncio.run(identify())
            check()
            settings = departure.cli.load_settings(departure.SECURITY_ROOT / '.env')
            args = departure.cli.parser().parse_args(['audio', 'play', value['speaker_device'], str(source),
                '--volume', str(value['volume']), '--duration', '8', '--confirm'])
            args.doorbell_padding = True
            # go2rtc's HTTP source validator rejects ALL whitespace, even
            # inside quotes. Persistent runtime is in Application Support;
            # use an isolated OS scratch directory (0700) for this session.
            with tempfile.TemporaryDirectory(prefix='jarvis-departure-') as temporary:
                tmp = runtime.private_dir(Path(temporary))
                quoted_playback_path(tmp / 'playback.wav')  # Fail before any session/send.
                stage = 'prepare'
                file, seconds = audio.prepare(args, tmp, value['volume'], check)
                session = DeadlineSession(args.app, tmp, speaker['host'], settings.password, check)
                try:
                    stage = 'session_start'
                    session.start()
                    check()
                    result, plays = audio.playback_loop(session, file, seconds, False, 8, check)
                    return 'completed' if result == 'completed' and plays == 1 else 'unknown'
                finally:
                    session.close()
                    session = None
    except (Expired, TimeoutError) as exc:
        diagnose(exc)
        return 'unknown' if attempted else 'expired_before_play'
    except BaseException as exc:
        diagnose(exc)
        return 'unknown' if attempted else 'failed_before_play'


def main():
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    outcome = 'unknown'
    try:
        if len(sys.argv) != 2:
            raise runtime.TrialError('invalid_worker_arguments')
        root = runtime.private_dir(Path(sys.argv[1]))
        request = json.loads(sys.stdin.read(4097))
        if type(request) is not dict or set(request) != {'attempt', 'expires'}:
            raise runtime.TrialError('invalid_worker_request')
        outcome = play_once(root, request)
    except Exception:
        pass
    print(json.dumps({'outcome': outcome}))
    return 0 if outcome != 'unknown' else 3


if __name__ == '__main__':
    raise SystemExit(main())
