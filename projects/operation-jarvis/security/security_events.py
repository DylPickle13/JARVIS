"""Staged D235 detection history. No delivery, scheduling or button inference."""
import asyncio
from contextlib import ExitStack
import hashlib
import json
import time

import security_cli as cli

MAX_EVENTS = 20


def add_parser(sub):
    parser = sub.add_parser('events', help='Staged D235 event history; notifications disabled')
    parser.add_argument('device')
    parser.add_argument('operation', choices=('status', 'history', 'preview'), default='status', nargs='?')
    parser.add_argument('--minutes', type=int, default=10, help='History window, 1–60 minutes')


def status():
    return {'result': 'read_succeeded', 'source': 'hub_detection_history',
            'delivery_enabled': False, 'background_listener': False,
            'physical_verification': 'pending', 'button_mapping': 'unverified',
            'motion_mapping': 'unverified', 'destination': 'not_configured'}


def normalize(response, start, end):
    """Only bounded timestamps/numeric type codes; never expose arbitrary text/IDs."""
    playback = response.get('playback') if isinstance(response, dict) else None
    rows = playback.get('search_detection_list') if isinstance(playback, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_EVENTS:
        raise cli.ControlError('invalid_event_response')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise cli.ControlError('invalid_event_response')
        began, ended = row.get('start_time'), row.get('end_time')
        if type(began) is not int or type(ended) is not int or not 0 < began <= ended:
            raise cli.ControlError('invalid_event_response')
        # Timestamp/timezone behavior is unverified; fail closed rather than
        # relabeling unrelated/old records as fresh activity.
        if ended < start or began > end or ended > end:
            raise cli.ControlError('event_time_unverified')
        code = row.get('event_type')
        if type(code) is not int or not 0 <= code <= 65535:
            code = None
        item = {'start_time': began, 'end_time': ended, 'type_code': code,
                'kind': 'unknown', 'verification': 'pending'}
        key = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        result.append({'event_key': key, **item})
    return sorted(result, key=lambda event: (event['start_time'], event['event_key']))


def preview(events):
    # There is deliberately no delivery branch until real types, timing, child
    # attribution and destination are commissioned. Never fabricate ring events.
    return [{'event_key': event['event_key'], 'decision': 'suppressed',
             'reason': 'source_and_mapping_unverified'} for event in events]


def run(entry, env_file, command='events', name=None, value=None, confirm=False):
    """Isolated read-only worker. Parent holds hub then doorbell locks."""
    from security_recording import archive_client, camera_from_hub
    if command != 'events' or entry.get('model') != 'D235' or not entry.get('host'):
        raise cli.ControlError('unsupported_command')
    if type(value) is not int or not 1 <= value <= 60:
        raise cli.ControlError('invalid_event_window')
    settings = cli.load_settings(env_file)
    if settings.missing:
        raise cli.ControlError(settings.missing)
    hub = None
    try:
        hub = archive_client(settings)  # authenticates and verifies H200 model
        camera = camera_from_hub(hub)  # exactly one D235; no first-device fallback
        end = int(time.time())
        start = end - value * 60
        response = hub.executeFunction('searchDetectionList', {'playback': {'search_detection_list': {
            'channel': 0, 'child_device_id': camera['device_id'], 'child_device_mac': camera['mac'],
            'start_time': start, 'end_time': end, 'start_index': 0, 'end_index': MAX_EVENTS - 1}}})
        events = normalize(response, start, end)
        rows = response['playback']['search_detection_list']
        return {**status(), 'events': events, 'window_start': start, 'window_end': end,
                'possibly_truncated': len(rows) == MAX_EVENTS,
                'completeness': 'not_assessed', 'child_attribution': 'unverified',
                'empty_does_not_prove_no_activity': True}
    finally:
        if hub is not None:
            hub.close()


def execute_events(args, adapter=None):
    adapter = adapter or cli
    if not 1 <= args.minutes <= 60:
        raise adapter.ControlError('invalid_event_window')
    entry = adapter.registry(args.registry).get(args.device)
    if not entry or entry.get('model') != 'D235' or not entry.get('host'):
        raise adapter.ControlError('direct_doorbell_required')
    if args.operation == 'status':
        return {**status(), 'device': args.device}
    from security_doorbell import execute
    try:
        with ExitStack() as locks:
            locks.enter_context(adapter.device_lock(entry['hub']))
            locks.enter_context(adapter.device_lock(args.device))
            result = asyncio.run(execute(args.env_file, entry=entry, command='events', value=args.minutes))
        if args.operation == 'preview':
            result['notification_preview'] = preview(result['events'])
        return {**result, 'device': args.device}
    except cli.ControlError as exc:
        raise adapter.ControlError(str(exc)) from None
