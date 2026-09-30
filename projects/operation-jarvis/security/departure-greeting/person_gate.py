"""Mandatory, fail-closed D235 person-event gate. Metadata only; no video.

Numeric type codes, UTC semantics and timely publication must be physically
commissioned for this source. Missing policy is UNVERIFIED, never sensor-only.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time

import departure
import runtime

MAX_ROWS = 20
MAX_WAIT = 2
SOURCE = 'h200_detection_history'


def default_policy():
    return {'version': 1, 'verified': False, 'source': SOURCE, 'person_code': None,
            'binding': None, 'timestamp_basis': 'unverified', 'verified_at': None}


def policy(root):
    value = runtime.read_json(root / 'person-gate.json', default_policy())
    if (set(value) != set(default_policy()) or type(value['version']) is not int
            or value['version'] != 1 or type(value['verified']) is not bool
            or value['source'] != SOURCE):
        raise runtime.TrialError('invalid_person_gate_policy')
    if value['verified']:
        if (type(value['person_code']) is not int or not 0 <= value['person_code'] <= 65535
                or type(value['binding']) is not str or not re.fullmatch('[0-9a-f]{64}', value['binding'])
                or value['timestamp_basis'] != 'unix_utc_seconds'
                or type(value['verified_at']) is not str):
            raise runtime.TrialError('invalid_person_gate_policy')
        try:
            at = datetime.fromisoformat(value['verified_at'])
            if at.utcoffset() is None:
                raise ValueError()
        except ValueError:
            raise runtime.TrialError('invalid_person_gate_policy') from None
    elif value != default_policy():
        raise runtime.TrialError('invalid_person_gate_policy')
    return value


def status(root):
    value = policy(root)
    return {'person_gate_required': True, 'person_gate_verified': value['verified'],
            'person_event_source': SOURCE, 'person_gate_max_wait_seconds': MAX_WAIT,
            'person_gate_state': 'commissioned' if value['verified'] else 'awaiting_physical_verification'}


async def read_one(reader, method, params):
    """One explicit approved getter: no SDK list paging or fallback requests."""
    if method not in {'getGeneralDeviceList', 'searchDetectionList'}:
        raise runtime.TrialError('unapproved_person_event_method')
    response = await reader.device.protocol.query({'multipleRequest': {'requests': [
        {'method': method, 'params': params}]}}, retry_count=0)
    wrapper = response.get('multipleRequest') if type(response) is dict else None
    rows = wrapper.get('responses') if type(wrapper) is dict else None
    if (type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict
            or rows[0].get('method') != method or type(rows[0].get('error_code')) is not int
            or rows[0]['error_code'] != 0 or type(rows[0].get('result')) is not dict):
        raise runtime.TrialError('invalid_person_event_response')
    return rows[0]['result']


def camera_binding(response, hub_info):
    section = response.get('general_camera_manage') if type(response) is dict else None
    rows = section.get('paired_general_device_list') if type(section) is dict else None
    if type(rows) is not list or len(rows) > 128 or any(type(row) is not dict for row in rows):
        raise runtime.TrialError('invalid_person_camera_list')
    cameras = [row for row in rows if row.get('device_model') == 'D235']
    if len(cameras) != 1:
        raise runtime.TrialError('person_camera_missing_or_ambiguous')
    camera = cameras[0]
    if type(hub_info) is not dict or hub_info.get('device_model') != 'H200':
        raise runtime.TrialError('person_hub_identity_invalid')
    ids = [hub_info[key] for key in ('dev_id', 'device_id') if key in hub_info]
    if not ids or any(type(identity) is not str for identity in ids) or len(set(ids)) != 1:
        raise runtime.TrialError('person_hub_identity_invalid')
    parts = [ids[0], hub_info.get('sw_version'), camera.get('device_id'), camera.get('mac')]
    if any(type(part) is not str or not part or len(part) > 256 for part in parts):
        raise runtime.TrialError('person_source_identity_invalid')
    # Firmware, when provided in hub camera metadata, participates in binding.
    for key in ('sw_version', 'firmware_version', 'fw_ver'):
        if key in camera:
            if type(camera[key]) is not str or not camera[key] or len(camera[key]) > 256:
                raise runtime.TrialError('person_source_identity_invalid')
            parts.append(camera[key])
    binding = hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()
    return {'device_id': camera['device_id'], 'mac': camera['mac']}, binding


async def bind(reader):
    """Identity metadata only, during connection setup, never in voice deadline."""
    with departure.cli.device_lock(reader.entries[0]):
        reader.phase = 'person_source_identity'
        async with asyncio.timeout(3):
            response = await read_one(reader, 'getGeneralDeviceList', {
                'general_camera_manage': {'paired_general_device_list': {}}})
        reader.person_camera, reader.person_binding = camera_binding(response, reader.hub_info)


def event_rows(response, query_start, query_end):
    section = response.get('playback') if type(response) is dict else None
    rows = section.get('search_detection_list') if type(section) is dict else None
    if type(rows) is not list or len(rows) >= MAX_ROWS:
        # A full page may be truncated; never page or guess which event is missing.
        raise runtime.TrialError('person_events_invalid_or_truncated')
    events = []
    for row in rows:
        if type(row) is not dict:
            raise runtime.TrialError('person_events_invalid_or_truncated')
        start, end, code = (row.get(key) for key in ('start_time', 'end_time', 'event_type'))
        if (type(start) is not int or type(end) is not int or type(code) is not int
                or not 0 < start <= end or not 0 <= code <= 65535
                or not query_start <= start <= end <= query_end):
            # Unknown ongoing-record schemas and device-clock errors are NOT fresh evidence.
            raise runtime.TrialError('person_event_schema_or_time_unverified')
        events.append({'start': start, 'end': end, 'code': code})
    return events


async def history(reader, start, end):
    camera = getattr(reader, 'person_camera', None)
    if not camera:
        raise runtime.TrialError('person_source_unbound')
    with departure.cli.device_lock(reader.entries[0]):
        reader.phase = 'person_event_read'
        response = await read_one(reader, 'searchDetectionList', {'playback': {'search_detection_list': {
            'channel': 0, 'child_device_id': camera['device_id'], 'child_device_mac': camera['mac'],
            'start_time': start, 'end_time': end, 'start_index': 0, 'end_index': MAX_ROWS - 1}}})
    return event_rows(response, start, end)


def event_key(binding, event):
    return hashlib.sha256(json.dumps([binding, event['start'], event['end'], event['code']],
        separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Result:
    confirmed: bool
    reason: str


async def confirm(root, reader, attempt, opened_at, expires, *, now=time.time, sleep=asyncio.sleep):
    value = policy(root)
    if not value['verified']:
        return Result(False, 'person_gate_unverified')
    if reader is None or getattr(reader, 'person_binding', None) != value['binding']:
        return Result(False, 'person_source_binding_mismatch')
    # Entire invocation is additionally bounded by the caller's 2-second timeout.
    for index in range(2):
        current = now()
        if not runtime.config(root)['enabled'] or not 0 <= current - opened_at < 6:
            return Result(False, 'person_event_expired')
        events = await history(reader, int(opened_at) - 1, int(current))
        checked = now()
        for event in events:
            # Strictly AFTER observed opening. Same-second records are ambiguous.
            # Exact commissioned code only: no guessed enums, bitmasks or motion fallback.
            if (event['code'] == value['person_code'] and opened_at < event['start']
                    and event['end'] <= checked < expires - 1.5):
                proof = {'version': 1, 'attempt': attempt, 'opened_at': opened_at, 'expires': expires,
                    'checked_at': checked, 'event_start': event['start'], 'event_end': event['end'],
                    'event_key': event_key(value['binding'], event), 'person_code': event['code'],
                    'binding': value['binding']}
                runtime.save_json(root / 'person-proof.json', proof)
                if valid_proof(root, attempt, expires, now=checked):
                    return Result(True, 'fresh_person_after_opening')
                return Result(False, 'person_proof_invalid')
        if index == 0:
            await sleep(0.25)
    return Result(False, 'no_fresh_person_after_opening')


def valid_proof(root, attempt, expires, *, now):
    value = policy(root)
    proof = runtime.read_json(root / 'person-proof.json')
    fields = {'version', 'attempt', 'opened_at', 'expires', 'checked_at', 'event_start',
              'event_end', 'event_key', 'person_code', 'binding'}
    if not value['verified'] or not proof or set(proof) != fields:
        return False
    if (type(proof['version']) is not int or proof['version'] != 1 or proof['attempt'] != attempt
            or proof['binding'] != value['binding'] or type(proof['person_code']) is not int
            or proof['person_code'] != value['person_code']):
        return False
    numbers = [proof[key] for key in ('opened_at', 'expires', 'checked_at')]
    if any(type(number) not in (int, float) or not math.isfinite(number) for number in numbers):
        return False
    if any(type(proof[key]) is not int for key in ('event_start', 'event_end')):
        return False
    if (proof['expires'] != expires or expires != proof['opened_at'] + 8
            or not proof['opened_at'] < proof['event_start'] <= proof['event_end']
            <= proof['checked_at'] <= now < expires - 1.5):
        return False
    event = {'start': proof['event_start'], 'end': proof['event_end'], 'code': proof['person_code']}
    return proof['event_key'] == event_key(value['binding'], event)


async def preview(args):
    """Explicit bounded metadata observation for commissioning; never grants speech."""
    from watcher import HubSession
    reader = HubSession(args, departure.validate_devices(args, departure.cli))
    events = {}
    read_count = 0
    deadline = time.monotonic() + args.seconds
    try:
        async with asyncio.timeout(args.seconds):
            await reader.connect()
            await bind(reader)
            while time.monotonic() < deadline:
                end = int(time.time())
                async with asyncio.timeout(2):
                    rows = await history(reader, end - 60, end)
                read_count += 1
                received = time.time()
                for event in rows:
                    key = event_key(reader.person_binding, event)
                    if key not in events:
                        if len(events) >= 64:
                            raise runtime.TrialError('person_preview_limit')
                        events[key] = {**event, 'first_seen_at': received}
                await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
    except TimeoutError:
        # A normal overall deadline is completion; an early read/setup timeout
        # is NOT evidence of an empty event history.
        if time.monotonic() < deadline:
            error = runtime.TrialError('person_preview_read_timeout')
            error.departure_phase = reader.phase
            raise error from None
    except Exception as exc:
        # Attribute contains one of our fixed phase names, never peer text.
        exc.departure_phase = reader.phase
        raise
    finally:
        await reader.close()
    return {'result': 'person_event_preview', 'delivery_enabled': False,
            'binding': getattr(reader, 'person_binding', None), 'events': list(events.values()),
            'read_count': read_count, 'source_response_verified': read_count > 0,
            'person_code_mapping': 'unverified', 'physical_verification': 'pending',
            'empty_does_not_prove_no_activity': True}
