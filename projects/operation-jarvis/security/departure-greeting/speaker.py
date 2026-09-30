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
            nonlocal attempted
            check()
            # Leading silence is 1.5 s; the voice must begin before expiry.
            if clock() + person_gate.LEADING_SILENCE_SECONDS > expires:
                raise Expired()
            # Durable marker BEFORE the possibly audible request. Parent regards
            # malformed/missing results or worker death as unknown, never retry.
            runtime.save_json(root / 'playback.json', {'attempt': attempt, 'started': True})
            attempted = True
            return super().play(file)
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
            with tempfile.TemporaryDirectory(prefix='play-', dir=root) as temporary:
                tmp = Path(temporary)
                file, seconds = audio.prepare(args, tmp, value['volume'], check)
                session = DeadlineSession(args.app, tmp, speaker['host'], settings.password, check)
                try:
                    session.start()
                    check()
                    result, plays = audio.playback_loop(session, file, seconds, False, 8, check)
                    return 'completed' if result == 'completed' and plays == 1 else 'unknown'
                finally:
                    session.close()
                    session = None
    except (Expired, TimeoutError):
        return 'unknown' if attempted else 'expired_before_play'
    except BaseException:
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
