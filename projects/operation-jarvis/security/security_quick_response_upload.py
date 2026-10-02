"""Isolated experimental D235 new-response worker; NEVER run during tests/setup.

Authenticates identity, checks fresh native limits/list, then optionally performs
one explicitly confirmed native upload. All errors after reservation begins are
uncertain, journaled and never replayed. No playback or other device controls.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import sys

from security_cli import ControlError, Settings, load_settings, registry
from security_quick_response import (
    ROOT, RATE, MAX_SECONDS, CAPABILITY_REQUEST, LIST_REQUEST, Journal,
    label, limits, entries, check_new, verify_added, fingerprint, read_source, unknown,
)
from security_quick_response_transport import PCMATS, new_session


def load_media(request, directory):
    path = Path(request.get('media_path', ''))
    # Parent creates a private fixed-name output in this device's temporary
    # directory. No caller-controlled URL, stream route, codec or media RPC.
    if (not path.is_absolute() or path != path.resolve() or path.name != 'response.alaw'
            or path.parent.parent != directory or not path.parent.name.startswith('prepare-')):
        raise ControlError('invalid_native_audio_input')
    from security_audio import private_dir
    private_dir(directory)
    private_dir(path.parent)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ControlError('invalid_native_audio_input')
    raw = read_source(path, RATE * MAX_SECONDS)
    if (type(request.get('media_bytes')) is not int or request['media_bytes'] != len(raw)
            or request.get('media_sha256') != hashlib.sha256(raw).hexdigest()):
        raise ControlError('invalid_native_audio_input')
    return raw


def inventory(client):
    return (limits(client.executeFunction('getQuickRespCapability', CAPABILITY_REQUEST)),
            entries(client.executeFunction('getQuickRespList', LIST_REQUEST)))


async def upload(client, settings, entry, name, raw, before, journal, *, factory=new_session, sleep=asyncio.sleep):
    session = None
    pending = False
    record = {'phase': 'pending', 'name': name, 'codec': 'G711alaw', 'sample_rate': RATE,
              'audio_sha256': hashlib.sha256(raw).hexdigest(), 'audio_bytes': len(raw),
              'before_sha256': fingerprint(before),
              'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        async with asyncio.timeout(45):
            session = factory(entry['host'], settings.password, client.getEncryptionMethod())
            await session.start()  # Authentication only; no native audio reservation yet.
            if journal.blocked():
                raise ControlError('unresolved_native_upload_blocks_writes')
            # fsync the guard BEFORE the first potentially persistent request.
            journal.write(record)
            pending = True
            file_id = await session.open_new(name)
            if file_id in {row['id'] for row in before}:
                raise ControlError('native_upload_returned_existing_id')
            record['new_file_id'] = file_id
            journal.write(record)
            mux = PCMATS()
            for start in range(0, len(raw), 1024):
                await session.send_audio(mux.encode(raw[start:start + 1024]))
                await sleep(0.01)  # Bounded file upload pacing, as in the app sender.
            await session.finish()  # A socket EOF/notification is NOT sufficient.
            after = entries(client.executeFunction('getQuickRespList', LIST_REQUEST))
            verify_added(before, after, name, file_id)
            record.update(phase='verified', verified_at=datetime.now(timezone.utc).isoformat())
            journal.write(record)
            return {'result': 'quick_response_added', 'name': name,
                    'duration_seconds': len(raw) / RATE, 'codec': 'G711alaw', 'sample_rate': RATE,
                    'existing_entries': 'unchanged_in_readback',
                    'persistence_verification': 'device_list_readback_only',
                    'app_visibility': 'not_verified', 'playback': 'not_requested',
                    'physical_verification': 'not_assessed', 'automatic_retry': False}
    except BaseException:
        if not pending:
            raise
        record['phase'] = 'unknown'
        try:
            journal.write(record)
        except Exception:
            pass  # The prior durable pending guard remains blocking.
        return unknown()
    finally:
        if session is not None:
            try:
                await session.close()
            except (Exception, asyncio.CancelledError):
                pass


def run(request, env_file):
    command = request.get('command')
    alias = request.get('alias')
    if command not in ('status', 'add') or not isinstance(alias, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', alias):
        raise ControlError('invalid_arguments')
    allowed = {'alias', 'registry', 'entry_hash', 'command', 'confirm', 'experimental'}
    if command == 'add':
        allowed |= {'name', 'media_path', 'media_bytes', 'media_sha256'}
        if request.get('confirm') is not True:
            raise ControlError('confirmation_required')
        if request.get('experimental') is not True:
            raise ControlError('experimental_confirmation_required')
        label(request.get('name'))
    if set(request) != allowed:
        raise ControlError('invalid_arguments')
    configured = registry(request['registry'])
    entry = configured.get(alias)
    if (not entry or entry.get('model') != 'D235' or not entry.get('host') or not entry.get('hub')
            or request.get('entry_hash') != fingerprint(entry)):
        raise ControlError('direct_doorbell_required')
    Settings(host=entry['host'])
    from security_audio import private_dir
    directory = private_dir(private_dir(ROOT / '.quick-response-runtime') / alias)
    journal = Journal(directory / 'upload.json')
    if command == 'add' and journal.blocked():
        raise ControlError('unresolved_native_upload_blocks_writes')
    raw = load_media(request, directory) if command == 'add' else None
    settings = load_settings(env_file)
    if not settings.username or not settings.password:
        raise ControlError('missing_credentials')
    from security_doorbell_direct import make_client
    client = None
    try:
        client = make_client(entry['host'], settings)
        info = client.basicInfo.get('device_info', {}).get('basic_info', {})
        if info.get('device_model') != 'D235' or info.get('device_type') != 'SMART.TAPODOORBELL':
            raise ControlError('device_identity_mismatch')
        cap, before = inventory(client)
        if command == 'status':
            return {'result': 'read_succeeded', 'model': 'D235',
                    'scope': 'fresh_native_response_configuration', 'limits': cap.public(),
                    'responses': [{'name': row['name'], 'custom': row['read_only'] == '0',
                                   'duration_milliseconds': int(row['duration'])} for row in before],
                    'blocked_by_unresolved_upload': journal.blocked(),
                    'playback': 'not_requested', 'physical_verification': 'not_assessed'}
        check_new(request['name'], len(raw) / RATE, cap, before)
        return asyncio.run(upload(client, settings, entry, request['name'], raw, before, journal))
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


# Fixed public reasons only; never return SDK responses, identities or exception text.
REASONS = {
    'invalid_arguments', 'confirmation_required', 'experimental_confirmation_required',
    'response_name_requires_1_to_32_ascii_characters', 'invalid_response_name',
    'invalid_device_registry', 'direct_doorbell_required', 'missing_credentials',
    'device_identity_mismatch', 'invalid_quick_response_metadata',
    'custom_quick_responses_unavailable', 'response_exceeds_duration_limit',
    'response_name_already_exists', 'custom_response_storage_full',
    'private_upload_journal_invalid', 'unresolved_native_upload_blocks_writes',
    'invalid_native_audio_input', 'bounded_local_source_required',
    'private_audio_directory_required', 'doorbell_dependency_unavailable',
    'native_upload_encryption_unavailable', 'native_upload_invalid_response',
    'native_upload_connection_closed', 'native_upload_timeout', 'native_upload_rejected',
}


def main():
    logging.disable(logging.CRITICAL)
    previous = os.umask(0o077)
    try:
        if len(sys.argv) != 2:
            raise ControlError('invalid_arguments')
        value = sys.stdin.read(16385)
        if len(value) > 16384:
            raise ControlError('invalid_arguments')
        request = json.loads(value)
        if type(request) is not dict:
            raise ControlError('invalid_arguments')
        result = run(request, sys.argv[1])
        code = 3 if result.get('outcome') == 'unknown' else 0
    except BaseException as exc:
        reason = str(exc) if isinstance(exc, ControlError) and str(exc) in REASONS else 'native_response_preflight_failed'
        result, code = {'result': 'error', 'reason': reason, 'automatic_retry': False}, 2
    finally:
        os.umask(previous)
    print(json.dumps(result))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
