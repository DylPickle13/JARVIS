"""One bounded H200 archive download attempt; no retries, priming or settings writes.

Experimental newer-firmware query/payload from pytapo issue 194. Saves only raw
TS in a private ignored directory; requires a finished notification for success.
"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import signal
import time
import uuid

from archive_probe import ReadOnlyTapo
import security_cli as security
from pytapo.media_stream.session import HttpMediaSession

MAX_BYTES = 12 * 1024 * 1024


def interval(start, end):
    now = int(time.time())
    if not (now - 86400 <= start < end <= now - 60 and end - start <= 10):
        raise ValueError('Require at most ten seconds within the past day, at least one minute old')


async def download(hub, camera, start, end, output):
    player = uuid.uuid4().hex.upper()
    media = HttpMediaSession(
        ip=hub.host, cloud_password=hub.cloudPassword,
        super_secret_key=hub.superSecretKey, encryptionMethod=hub.getEncryptionMethod(),
        port=8800, username='admin', window_size=50,
        query_params={'camera_mac': camera['mac'], 'type': 'download',
                      'playerId': player, 'media_type': 0})
    payload = {'type': 'request', 'seq': 1, 'params': {'method': 'get', 'download': {
        'audio_config': {'encode_type': 'OPUS', 'sample_rate': '16'},
        'dev_id': camera['device_id'], 'mac': camera['mac'], 'channels': [0],
        'client_id': 1, 'end_time': str(end), 'event_type': [], 'media_type': 0,
        'player_id': player, 'start_time': str(start)}}}
    count = 0
    finished = False
    stream = None
    try:
        async with asyncio.timeout(35):
            await media.start()
            stream = media.transceive(json.dumps(payload, separators=(',', ':')))
            with output.open('xb') as target:
                while True:
                    try:
                        response = await asyncio.wait_for(anext(stream), timeout=10)
                    except StopAsyncIteration:
                        break
                    if response.mimetype == 'video/mp2t':
                        data = response.plaintext
                        if count + len(data) > MAX_BYTES:
                            raise RuntimeError('size_limit')
                        target.write(data)
                        count += len(data)
                    elif response.mimetype == 'application/json':
                        message = json.loads(response.plaintext)
                        params = message.get('params', {})
                        if params.get('error_code', 0) != 0:
                            raise RuntimeError('stream_rejected')
                        if (message.get('type') == 'notification'
                                and params.get('event_type') == 'stream_status'
                                and params.get('status') == 'finished'):
                            finished = True
                            break
    finally:
        if stream is not None:
            await asyncio.wait_for(stream.aclose(), 3)
        await asyncio.wait_for(media.close(), 3)
        # Upstream close only handles fully started sessions; close partial auth too.
        if media._writer is not None:
            media._writer.close()
    return {'bytes': count, 'finished': finished, 'complete': finished and count > 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=int, required=True)
    parser.add_argument('--end', type=int, required=True)
    args = parser.parse_args()
    interval(args.start, args.end)
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    directory = Path(__file__).resolve().parent / 'private-archive'
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise RuntimeError('Archive directory must be private and non-symlink')
    output = directory / (uuid.uuid4().hex + '.partial.ts')
    hub = None
    stage = 'connect'
    def deadline(*_):
        raise TimeoutError()
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(55)
    try:
        with security.device_lock('hub'):
            cfg = security.load_settings(security.ROOT / '.env')
            hub = ReadOnlyTapo(cfg.host, 'admin', cfg.password, cfg.password,
                               isKLAP=False, retryStok=False,
                               printDebugInformation=False, printWarnInformation=False)
            stage = 'camera_list'
            result = hub.executeFunction('getGeneralDeviceList', {
                'general_camera_manage': {'paired_general_device_list': {}}})
            cameras = result['general_camera_manage']['paired_general_device_list']
            matches = [c for c in cameras if c.get('device_model') == 'C230']
            if len(matches) != 1:
                raise RuntimeError('camera_missing_or_ambiguous')
            stage = 'download'
            result = asyncio.run(download(hub, matches[0], args.start, args.end, output))
            if result['complete']:
                final = output.with_name(output.name.replace('.partial.ts', '.ts'))
                output.rename(final)
                output = final
            print(json.dumps({'stage': stage, **result, 'path': str(output)}))
            return 0 if result['complete'] else 2
    except Exception as exc:
        reason = 'nonce_missing' if 'Nonce is missing' in str(exc) else 'attempt_failed'
        print(json.dumps({'stage': stage, 'error_type': type(exc).__name__,
                          'reason': reason, 'bytes': output.stat().st_size if output.exists() else 0}))
        return 2
    finally:
        if hub is not None:
            try:
                hub.close()
            except Exception:
                pass
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
