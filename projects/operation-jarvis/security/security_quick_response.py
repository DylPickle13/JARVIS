"""Experimental native D235 saved responses: offline preparation and new-only upload.

No playback, replacement, deletion, reordering, settings changes or automatic
retries. The isolated worker owns native upload; foreground talkback is separate.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unicodedata

from security_cli import ControlError

ROOT = Path(__file__).resolve().parent
RATE = 16000
CODEC = 'G722'
BYTE_RATE = 8000  # Fixed 64 kbit/s G.722: two 16 kHz samples per encoded byte.
AUDIO_CAPABILITY_REQUEST = {'audio_capability': {'name': ['device_sourcefile']}}
MAX_SECONDS = 60
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_TEXT_BYTES = 2048
MAX_ENTRIES = 64
MAX_FILE_ID = 2147483647
CAPABILITY_REQUEST = {'quick_response': {'name': ['capability']}}
LIST_REQUEST = {'quick_response': {'table': ['quick_resp_audio']}}
PHASES = {'pending', 'unknown', 'verified'}
METADATA_FIELDS = {
    'capability': frozenset({'shape', 'usr_def_audio_support', 'usr_def_audio_max_num',
                             'usr_def_audio_max_duration'}),
    'quick_resp_audio': frozenset({'shape', 'entry_shape', 'name', 'read_only', 'id',
                                   'index', 'duration', 'duplicate_id'}),
}


class MetadataError(ControlError):
    """Fixed diagnostic coordinates only; never retain device values or raw replies."""
    def __init__(self, section, field):
        super().__init__('invalid_quick_response_metadata')
        self.metadata_section = section
        self.metadata_field = field


def metadata_details(error):
    if not isinstance(error, MetadataError):
        return {}
    section, field = error.metadata_section, error.metadata_field
    if (type(section) is not str or type(field) is not str
            or field not in METADATA_FIELDS.get(section, ())):
        return {}
    return {'metadata_section': section, 'metadata_field': field}


def metadata_value(section, field, validator, *args):
    try:
        return validator(*args)
    except ControlError:
        raise MetadataError(section, field) from None


def label(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _().\-]{0,31}', value):
        raise ControlError('response_name_requires_1_to_32_ascii_characters')
    if value != value.strip():
        raise ControlError('invalid_response_name')
    return value


def number(value, maximum, *, minimum=0):
    if type(value) is str and re.fullmatch(r'\d{1,8}', value):
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ControlError('invalid_quick_response_metadata')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ControlError('invalid_quick_response_metadata')
    return value


def file_identifier(value):
    """Canonical comparison key; preserve raw inventory fields and strict session IDs."""
    if type(value) is int:
        value = str(number(value, MAX_FILE_ID))
    return identifier(value)


def normalized(value):
    return unicodedata.normalize('NFC', value).casefold()


def section(response, key):
    if type(response) is not dict:
        raise MetadataError(key, 'shape')
    module = response.get('quick_response', response)
    if type(module) is not dict or key not in module:
        raise MetadataError(key, 'shape')
    return module[key]


@dataclass(frozen=True)
class Limits:
    supported: bool
    max_custom: int
    max_seconds: int

    def public(self):
        return {'custom_audio_supported': self.supported,
                'max_custom_responses': self.max_custom,
                'max_duration_seconds': self.max_seconds,
                'uploader_max_duration_seconds': MAX_SECONDS,
                'uploader_codec': CODEC, 'uploader_sample_rate': RATE}


def limits(response):
    value = section(response, 'capability')
    if type(value) is not dict:
        raise MetadataError('capability', 'shape')
    if value.get('usr_def_audio_support') not in ('0', '1'):
        raise MetadataError('capability', 'usr_def_audio_support')
    return Limits(value['usr_def_audio_support'] == '1',
                  metadata_value('capability', 'usr_def_audio_max_num', number,
                                 value.get('usr_def_audio_max_num'), 32),
                  metadata_value('capability', 'usr_def_audio_max_duration', number,
                                 value.get('usr_def_audio_max_duration'), 300))


def check_audio_capability(response):
    """Require the file-upload profile actually advertised by this firmware."""
    module = response.get('audio_capability') if type(response) is dict else None
    value = module.get('device_sourcefile') if type(module) is dict else None
    if type(value) is not dict:
        raise ControlError('native_upload_audio_profile_unavailable')
    codecs, rates = value.get('encode_type'), value.get('sampling_rate')
    if (type(codecs) is not list or type(rates) is not list
            or not 1 <= len(codecs) <= 16 or not 1 <= len(rates) <= 16
            or any(type(v) is not str for v in codecs + rates)
            or CODEC not in codecs or str(RATE // 1000) not in rates):
        raise ControlError('native_upload_audio_profile_unavailable')


def entries(response):
    values = section(response, 'quick_resp_audio')
    if type(values) is not list or len(values) > MAX_ENTRIES:
        raise MetadataError('quick_resp_audio', 'shape')
    result = []
    for wrapper in values:
        if (type(wrapper) is not dict or len(wrapper) != 1
                or type(next(iter(wrapper), None)) is not str
                or not re.fullmatch(r'file_\d{1,3}', next(iter(wrapper), ''))):
            raise MetadataError('quick_resp_audio', 'entry_shape')
        item = next(iter(wrapper.values()))
        if type(item) is not dict:
            raise MetadataError('quick_resp_audio', 'entry_shape')
        name = item.get('name')
        if (not isinstance(name, str) or not name.strip() or len(name.encode('utf-8')) > 256
                or any(unicodedata.category(c).startswith('C') for c in name)):
            raise MetadataError('quick_resp_audio', 'name')
        if item.get('read_only') not in ('0', '1'):
            raise MetadataError('quick_resp_audio', 'read_only')
        metadata_value('quick_resp_audio', 'id', file_identifier, item.get('id'))
        metadata_value('quick_resp_audio', 'index', number, item.get('index'), MAX_ENTRIES)
        metadata_value('quick_resp_audio', 'duration', number, item.get('duration'), 300_000)
        # Retain all fields internally to detect changes to existing entries.
        result.append(dict(item))
    if len({file_identifier(r['id']) for r in result}) != len(result):
        raise MetadataError('quick_resp_audio', 'duplicate_id')
    return result


def check_new(name, seconds, cap, before):
    label(name)
    if not cap.supported or cap.max_seconds <= 0 or cap.max_custom <= 0:
        raise ControlError('custom_quick_responses_unavailable')
    if not 0 < seconds <= min(MAX_SECONDS, cap.max_seconds):
        raise ControlError('response_exceeds_duration_limit')
    if any(normalized(r['name']) == normalized(name) for r in before):
        raise ControlError('response_name_already_exists')
    if sum(r['read_only'] == '0' for r in before) >= cap.max_custom or len(before) >= MAX_ENTRIES:
        raise ControlError('custom_response_storage_full')


def verify_added(before, after, name, file_id):
    file_id = file_identifier(file_id)
    old = {file_identifier(r['id']): r for r in before}
    current = {file_identifier(r['id']): r for r in after}
    if (file_id in old or len(after) != len(before) + 1
            or len(old) != len(before) or len(current) != len(after)
            or any(fingerprint(current.get(key)) != fingerprint(row) for key, row in old.items())):
        raise ControlError('response_readback_mismatch')
    added = current.get(file_id)
    if (not added or added['name'] != name or added['read_only'] != '0'
            or sum(normalized(r['name']) == normalized(name) for r in after) != 1):
        raise ControlError('response_readback_mismatch')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Journal:
    """Durable pending-before-write guard, private and never an automatic retry queue."""
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or not 0 < info.st_size <= 16384):
                raise ValueError
            with os.fdopen(fd) as source:
                fd = None
                value = json.loads(source.read(16385))
            if type(value) is not dict or value.get('phase') not in PHASES:
                raise ValueError
            return value
        except (ValueError, OSError):
            raise ControlError('private_upload_journal_invalid') from None
        finally:
            if fd is not None:
                os.close(fd)

    def blocked(self):
        value = self.read()
        return value is not None and value['phase'] != 'verified'

    def write(self, value):
        from security_audio import private_dir
        private_dir(self.path.parent)
        if value.get('phase') not in PHASES:
            raise ControlError('private_upload_journal_invalid')
        fd, name = tempfile.mkstemp(prefix='.journal-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(value, out, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)


def unknown():
    return {'result': 'write_outcome_unknown', 'outcome': 'unknown',
            'automatic_retry': False, 'reason': 'native_response_upload_outcome_unknown',
            'physical_verification': 'not_assessed'}


def add_parser(sub):
    parser = sub.add_parser('quick-response', help='Experimental native saved D235 responses; no playback')
    commands = parser.add_subparsers(dest='response_command', required=True)
    for command in ('status', 'prepare', 'add'):
        p = commands.add_parser(command)
        p.add_argument('device')
        if command != 'status':
            p.add_argument('--name', required=True, help='New list label, 1–32 ASCII characters')
            source = p.add_mutually_exclusive_group(required=True)
            source.add_argument('--file', help='Local audio file; never a URL or playlist')
            source.add_argument('--text', help='JARVIS speech; visible in shell history; prefer --text-file')
            source.add_argument('--text-file', help='Private UTF-8 file, or - for stdin; at most 2048 bytes')
            from security_audio import percentage
            p.add_argument('--gain', type=percentage, default=100, help='Stored digital gain 0–100; no hardware setting change')
        if command == 'add':
            p.add_argument('--confirm', action='store_true', help='Approve creation of ONE persistent native response')
            p.add_argument('--experimental', action='store_true', help='Explicit opt-in to this uncommissioned protocol')


def read_source(path, maximum):
    # Fixed local input; never block on a FIFO or allow an unbounded source.
    try:
        resolved = Path(path).expanduser().resolve()
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
                raise ValueError
            data = source.read(maximum + 1)
        if not 0 < len(data) <= maximum:
            raise ValueError
        return data
    except (OSError, ValueError):
        raise ControlError('bounded_local_source_required') from None


def run_local(command, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ControlError('response_preparation_timeout')
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        process.wait(timeout=remaining)
        if process.returncode:
            raise ControlError('response_preparation_failed')
    except subprocess.TimeoutExpired:
        raise ControlError('response_preparation_timeout') from None
    finally:
        if process.poll() is None:
            import signal
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)


def prepare(args, tmp):
    label(args.name)
    deadline = time.monotonic() + 35
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ControlError('ffmpeg_unavailable')
    source = tmp / 'input.media'
    if args.file is not None:
        source.write_bytes(read_source(args.file, MAX_INPUT_BYTES))
    else:
        if args.text is not None:
            text = args.text
            if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_TEXT_BYTES:
                raise ControlError('bounded_speech_required')
        else:
            try:
                if args.text_file == '-':
                    import sys
                    raw = sys.stdin.buffer.read(MAX_TEXT_BYTES + 1)
                else:
                    raw = read_source(args.text_file, MAX_TEXT_BYTES)
                text = raw.decode('utf-8')
            except (UnicodeError, AttributeError):
                raise ControlError('bounded_speech_required') from None
            if len(raw) > MAX_TEXT_BYTES:
                raise ControlError('bounded_speech_required')
        if not text.strip() or '\x00' in text:
            raise ControlError('bounded_speech_required')
        python = ROOT.parent / '.venv/bin/python'
        if not python.is_file():
            raise ControlError('jarvis_voice_environment_unavailable')
        speech = tmp / 'speech.txt'
        speech.write_text(text, encoding='utf-8')
        run_local([str(python), str(ROOT / 'security_tts.py'), str(speech), str(source)], deadline)
    output = tmp / 'response.g722'
    run_local([ffmpeg, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe',
               '-format_whitelist', 'wav,aiff,mp3,mov,flac,ogg,aac,matroska,webm',
               '-i', str(source), '-map', '0:a:0', '-vn', '-af', f'volume={args.gain / 100}',
               '-ar', str(RATE), '-ac', '1', '-t', str(MAX_SECONDS + 1),
               '-c:a', 'g722', '-b:a', '64k', '-f', 'g722', str(output)], deadline)
    raw = read_source(output, (MAX_SECONDS + 1) * BYTE_RATE)
    if len(raw) > MAX_SECONDS * BYTE_RATE:
        raise ControlError('response_exceeds_local_duration_limit')
    return output, len(raw), hashlib.sha256(raw).hexdigest()


async def launch_worker(request, env_file, journal):
    interpreter = ROOT / '.venv-archive/bin/python'
    if not interpreter.is_file():
        raise ControlError('doorbell_dependency_unavailable')
    process = await asyncio.create_subprocess_exec(
        str(interpreter), str(ROOT / 'security_quick_response_upload.py'), str(Path(env_file).resolve()),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        # Join the CLI's process group so group termination also stops the
        # worker; the parent separately kills/reaps it on failure or timeout.
        start_new_session=False)
    try:
        output, _ = await asyncio.wait_for(process.communicate(json.dumps(request).encode()), 75)
        if len(output) > 65536:
            raise ValueError
        result = json.loads(output)
        if type(result) is not dict or result.get('result') not in {
                'read_succeeded', 'quick_response_added', 'write_outcome_unknown', 'error'}:
            raise ValueError
        return result
    except BaseException:
        # Reap BEFORE inspecting the durable guard: otherwise a still-running
        # worker could begin its write between the inspection and termination.
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
        if request['command'] == 'add':
            try:
                blocked = journal.blocked()
            except ControlError:
                blocked = True
            if blocked:
                return unknown()
        raise
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()


def execute_quick_response(args, adapter=None):
    # The launcher executes security_cli as __main__; translate our exception
    # type to the caller's rather than leaking it into generic CLI error handling.
    if adapter is None:
        import security_cli as adapter
    try:
        return _execute_quick_response(args, adapter)
    except ControlError as exc:
        raise adapter.ControlError(str(exc)) from None


def _execute_quick_response(args, adapter):
    if args.response_command == 'add':
        if getattr(args, 'confirm', False) is not True:
            raise ControlError('confirmation_required')
        if getattr(args, 'experimental', False) is not True:
            raise ControlError('experimental_confirmation_required')
    configured = adapter.registry(args.registry)
    entry = configured.get(args.device)
    if not entry or entry.get('model') != 'D235' or not entry.get('host') or not entry.get('hub'):
        raise ControlError('direct_doorbell_required')
    from security_audio import private_dir, interruptible
    previous = os.umask(0o077)
    try:
        directory = private_dir(private_dir(ROOT / '.quick-response-runtime') / args.device)
        journal = Journal(directory / 'upload.json')
        request = {'alias': args.device, 'registry': str(Path(args.registry).resolve()),
                   'entry_hash': fingerprint(entry), 'command': args.response_command,
                   'confirm': getattr(args, 'confirm', False),
                   'experimental': getattr(args, 'experimental', False)}
        with interruptible(), tempfile.TemporaryDirectory(prefix='prepare-', dir=directory) as value:
            if args.response_command != 'status':
                path, count, digest = prepare(args, Path(value))
                if args.response_command == 'prepare':
                    return {'result': 'quick_response_prepared', 'device': args.device,
                            'name': args.name, 'codec': CODEC, 'sample_rate': RATE,
                            'duration_seconds': count / BYTE_RATE, 'gain': args.gain,
                            'scope': 'offline_only_device_limits_not_checked'}
                request.update(name=args.name, media_path=str(path), media_bytes=count, media_sha256=digest)
            with ExitStack() as locks:
                locks.enter_context(adapter.device_lock(entry['hub']))
                locks.enter_context(adapter.device_lock(args.device))
                result = asyncio.run(launch_worker(request, args.env_file, journal))
            return {'device': args.device, **result}
    finally:
        os.umask(previous)
