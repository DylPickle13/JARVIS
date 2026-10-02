"""Narrow native saved-audio transport. No preview, talk, playback or arbitrary RPC.

Only pytapo's pinned authenticated handshake/AES helper is reused. Its generic
transceive/router is NOT used: native upload needs distinct finish/session rules.
The MPEG-TS encoder is independent and emits G.722 (Tapo stream type 0x93), with
90 kHz PTS/PCR, as observed in the Android custom-response sender.
"""
from __future__ import annotations

import asyncio
import json
import re
import struct

from security_cli import ControlError
from security_quick_response import RATE, CODEC, BYTE_RATE, file_identifier, identifier, label, number

MAX_BODY = 65536
MAX_HEADERS = 16384


def crc32_mpeg(data):
    crc = 0xFFFFFFFF
    for value in data:
        crc ^= value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & 0xFFFFFFFF
    return struct.pack('>I', crc)


def pts(value):
    value &= (1 << 33) - 1
    return bytes((0x21 | ((value >> 29) & 14), (value >> 22) & 255,
                  1 | ((value >> 14) & 254), (value >> 7) & 255,
                  1 | ((value << 1) & 254)))


class PCMATS:
    """Packetize 64 kbit/s G.722; timestamps track encoded bytes, not PCM samples."""
    PMT_PID = 0x42
    AUDIO_PID = 0x44

    def __init__(self):
        self.counters = {}
        self.encoded_bytes = 0

    def packetize(self, pid, data, *, pcr=None):
        output = bytearray()
        first = True
        while data:
            adaptation = b''
            capacity = 184
            if first and pcr is not None:
                value = pcr & ((1 << 33) - 1)
                adaptation = bytes((0x10, (value >> 25) & 255, (value >> 17) & 255,
                                    (value >> 9) & 255, (value >> 1) & 255,
                                    ((value & 1) << 7) | 0x7E, 0))
                capacity -= 1 + len(adaptation)
            take = min(capacity, len(data))
            if take < capacity:
                # Adaptation length excludes its own byte. A zero-length field
                # is valid for exactly 183 payload bytes.
                size = 183 - take
                if not adaptation and size:
                    adaptation = b'\x00'
                adaptation += b'\xff' * (size - len(adaptation))
                adapted = True
            else:
                adapted = bool(adaptation)
            count = self.counters.get(pid, 0)
            self.counters[pid] = (count + 1) & 15
            output.extend(bytes((0x47, (0x40 if first else 0) | (pid >> 8), pid & 255,
                                 (0x30 if adapted else 0x10) | count)))
            if adapted:
                output.extend(bytes((len(adaptation),)) + adaptation)
            output.extend(data[:take])
            data = data[take:]
            first = False
        return bytes(output)

    def tables(self):
        pat = bytes.fromhex('00b00d0001c100000001') + struct.pack('>H', 0xE000 | self.PMT_PID)
        pmt = (bytes.fromhex('02b0120001c10000') + struct.pack('>H', 0xE000 | self.AUDIO_PID)
               + bytes.fromhex('f00093') + struct.pack('>H', 0xE000 | self.AUDIO_PID)
               + bytes.fromhex('8000'))  # Tapo repurposes reserved ES bits: rate index 8 = 16 kHz.
        # PSI payload includes a pointer field; pad with legal PSI stuffing,
        # rather than PES adaptation fields.
        result = bytearray()
        for pid, section in ((0, pat), (self.PMT_PID, pmt)):
            body = b'\x00' + section + crc32_mpeg(section)
            count = self.counters.get(pid, 0)
            self.counters[pid] = (count + 1) & 15
            result.extend(bytes((0x47, 0x40 | (pid >> 8), pid & 255, 0x10 | count)))
            result.extend(body + b'\xff' * (184 - len(body)))
        return bytes(result)

    def encode(self, raw):
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 1024:
            raise ControlError('invalid_native_audio_chunk')
        timestamp = self.encoded_bytes * 90000 // BYTE_RATE
        header = b'\x00\x00\x01\xc0' + struct.pack('>H', len(raw) + 8) + b'\x80\x80\x05' + pts(timestamp)
        self.encoded_bytes += len(raw)  # G.722: one byte per two 16 kHz samples.
        return self.tables() + self.packetize(self.AUDIO_PID, header + raw, pcr=timestamp)


def headers(block):
    if len(block) > MAX_HEADERS:
        raise ControlError('native_upload_invalid_response')
    result = {}
    try:
        for line in block.decode('ascii').strip().split('\r\n'):
            key, value = line.split(':', 1)
            key = key.strip().lower()
            if not re.fullmatch(r'[a-z0-9-]+', key) or key in result:
                raise ValueError
            result[key] = value.strip()
        if any(k in result for k in ('x-data-hmac', 'x-nonce')):
            raise ValueError  # New authenticated-media variants need review.
        if result.get('content-type') != 'application/json':
            raise ValueError  # Never acquire or decode camera audio/video.
        length = number(result.get('content-length'), MAX_BODY, minimum=1)
        encrypted = result.get('x-if-encrypt', '0')
        if encrypted not in ('0', '1'):
            raise ValueError
        return result, length, encrypted == '1'
    except (ValueError, UnicodeError):
        raise ControlError('native_upload_invalid_response') from None


class NativeUploadSession:
    """One authenticated connection, one new response, one explicit finish."""
    def __init__(self, transport):
        self.transport = transport
        self.queue = asyncio.Queue(32)
        self.seq = 0
        self.session_id = None
        self.file_id = None
        self.processed = 0
        self.finished = False
        # The pinned base starts this reader after authentication. No SDK
        # download ACKs, queue migration or automatic stream-complete guesses.
        self.transport._device_response_handler_loop = self.read_loop

    async def start(self):
        await asyncio.wait_for(self.transport.start(), 10)
        exchange = self.transport._key_exchange
        if (not isinstance(exchange, str) or not re.search(r'\busername="admin"', exchange)
                or self.transport._aes is None):
            raise ControlError('native_upload_encryption_unavailable')
        match = re.search(r'\bencrypt_type="([^"]+)"', exchange)
        if match and match[1] not in ('1', '3'):
            raise ControlError('native_upload_encryption_unavailable')
        boundary = self.transport._device_boundary
        if not isinstance(boundary, bytes) or not re.fullmatch(rb'[-A-Za-z0-9_]{1,100}', boundary):
            raise ControlError('native_upload_invalid_response')

    async def read_loop(self):
        while self.transport._started:
            skipped = await self.transport._reader.readuntil(self.transport._device_boundary)
            if len(skipped) > MAX_HEADERS:
                raise ControlError('native_upload_invalid_response')
            block = await self.transport._reader.readuntil(b'\r\n\r\n')
            fields, length, encrypted = headers(block)
            data = await self.transport._reader.readexactly(length)
            if encrypted:
                data = self.transport._aes.decrypt(data)
            value = json.loads(data)
            if type(value) is not dict or value.get('type') not in ('response', 'notification', 'error'):
                raise ControlError('native_upload_invalid_response')
            sid = fields.get('x-session-id')
            if sid is not None and self.session_id is not None and sid != self.session_id:
                raise ControlError('native_upload_invalid_response')
            self.queue.put_nowait(value)

    async def next_message(self):
        task = self.transport._response_handler_task
        get = asyncio.create_task(self.queue.get())
        try:
            done, _ = await asyncio.wait((task, get), timeout=8, return_when=asyncio.FIRST_COMPLETED)
            if get in done:
                return get.result()
            if task in done:
                task.result()
                raise ControlError('native_upload_connection_closed')
            raise ControlError('native_upload_timeout')
        finally:
            if not get.done():
                get.cancel()
                await asyncio.gather(get, return_exceptions=True)

    def notification(self, value):
        if value.get('type') == 'error':
            raise ControlError('native_upload_rejected')
        if value.get('type') != 'notification' or type(value.get('params')) is not dict:
            raise ControlError('native_upload_invalid_response')
        info = value['params']
        event = info.get('event_type')
        if event == 'stream_sequence':
            if self.file_id is None or file_identifier(info.get('audio_file_id')) != self.file_id:
                raise ControlError('native_upload_invalid_response')
            processed = number(info.get('processed_len'), 16 * 1024 * 1024)
            if processed < self.processed:
                raise ControlError('native_upload_invalid_response')
            self.processed = processed
        elif event not in ('stream_status', 'stream_finish'):
            raise ControlError('native_upload_invalid_response')
        else:
            # A notification (including "finished") NEVER replaces the explicit
            # zero-error finish response. Unsolicited completion is not success.
            raise ControlError('native_upload_unexpected_completion')

    async def send_part(self, body, mimetype, *, session=None, encrypt=False):
        if self.finished or not self.transport._started:
            raise ControlError('native_upload_invalid_state')
        if session is not None:
            identifier(session)
        if encrypt:
            body = self.transport._aes.encrypt(body)
        fields = {b'Content-Type': mimetype.encode(), b'Content-Length': str(len(body)).encode(),
                  b'X-If-Encrypt': b'1' if encrypt else b'0'}
        if session is not None:
            fields[b'X-Session-Id'] = session.encode()
        await asyncio.wait_for(self.transport._send_http_request(
            b'--' + self.transport.client_boundary, fields), 5)
        self.transport._writer.write(body + b'\r\n')
        await asyncio.wait_for(self.transport._writer.drain(), 5)

    async def request(self, params, *, session=None):
        if (self.seq == 0 and session is None and type(params) is dict
                and set(params) == {'method', 'usr_def_audio'} and params['method'] == 'get'
                and type(params['usr_def_audio']) is dict
                and set(params['usr_def_audio']) == {'name', 'type', 'audio_config'}
                and params['usr_def_audio']['type'] == 'quick_response'
                and params['usr_def_audio']['audio_config'] == {
                    'sample_rate': str(RATE // 1000), 'encode_type': CODEC}):
            label(params['usr_def_audio']['name'])
        elif not (self.session_id is not None and session == self.session_id
                  and params == {'method': 'do', 'finish': 'null'}):
            raise ControlError('unapproved_native_upload_method')
        self.seq += 1
        sequence = self.seq
        body = json.dumps({'type': 'request', 'seq': sequence, 'params': params}, separators=(',', ':')).encode()
        await self.send_part(body, 'application/json', session=session)
        while True:
            message = await self.next_message()
            if message.get('type') != 'response':
                self.notification(message)
                continue
            if type(message.get('seq')) is not int or message['seq'] != sequence:
                raise ControlError('native_upload_invalid_response')
            value = message.get('params')
            if type(value) is not dict or type(value.get('error_code')) is not int:
                raise ControlError('native_upload_invalid_response')
            if value['error_code'] != 0:
                raise ControlError('native_upload_rejected')
            return value

    async def open_new(self, name):
        label(name)
        if self.seq or self.session_id is not None:
            raise ControlError('native_upload_invalid_state')
        value = await self.request({'method': 'get', 'usr_def_audio': {
            'name': name, 'type': 'quick_response',
            'audio_config': {'sample_rate': str(RATE // 1000), 'encode_type': CODEC}}})
        self.session_id = identifier(value.get('session_id'))
        self.file_id = file_identifier(value.get('audio_file_id'))
        number(value.get('index'), 64)
        return self.file_id

    async def send_audio(self, body):
        if self.session_id is None or not body or len(body) > 16384 or len(body) % 188:
            raise ControlError('native_upload_invalid_state')
        # Require negotiated AES; there is no plaintext-audio compatibility retry.
        await self.send_part(body, 'audio/mp2t', session=self.session_id, encrypt=True)
        while not self.queue.empty():
            self.notification(self.queue.get_nowait())
        task = self.transport._response_handler_task
        if task.done():
            task.result()
            raise ControlError('native_upload_connection_closed')

    async def finish(self):
        if self.session_id is None or self.finished:
            raise ControlError('native_upload_invalid_state')
        value = await self.request({'method': 'do', 'finish': 'null'}, session=self.session_id)
        if file_identifier(value.get('audio_file_id', self.file_id)) != self.file_id:
            raise ControlError('native_upload_invalid_response')
        self.finished = True

    async def close(self):
        # No stop/delete/recovery RPC on cleanup: an interrupted reservation may
        # persist and is deliberately treated as unknown by the durable guard.
        try:
            await asyncio.wait_for(self.transport.close(), 3)
        finally:
            writer = self.transport._writer
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 2)
                except (Exception, asyncio.CancelledError):
                    pass


def new_session(host, password, encryption_method):
    from importlib.metadata import version
    if version('pytapo') != '3.4.19' or encryption_method not in ('md5', 'sha256'):
        raise ControlError('doorbell_dependency_unavailable')
    from pytapo.media_stream.session import HttpMediaSession
    return NativeUploadSession(HttpMediaSession(host, password, '', encryption_method,
                                               window_size=500, port=8800, query_params={}))
