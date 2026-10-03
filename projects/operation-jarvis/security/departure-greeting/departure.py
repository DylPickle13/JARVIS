"""Departure-only detector, bounded silent observation, and trial status.

Hub snapshots cannot establish radio freshness or prove actual departure.
The separately opted-in watcher/speaker applies durable delivery safeguards.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import sys
import time

# Standalone subproject; reuse existing read-only registry/identity/lock helpers.
SECURITY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SECURITY_ROOT))
import security_cli as cli

MAX_SECONDS = 300


def parser():
    parser = cli.Parser(description='Departure-only trial status and bounded silent observation.')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--confirm', action='store_true', help='Required to disable the trial')
    parser.add_argument('--env-file', default=str(SECURITY_ROOT / '.env'))
    parser.add_argument('--registry', default=str(SECURITY_ROOT / 'devices.json'))
    parser.add_argument('operation', choices=('status', 'observe', 'person-preview', 'disable'), nargs='?', default='status')
    parser.add_argument('--motion-device', default='motion-sensor')
    parser.add_argument('--door-device', default='door-sensor')
    parser.add_argument('--seconds', type=int, default=60, help='Bounded observation, 10–300 seconds')
    parser.add_argument('--interval', type=int, default=2, help='Delay after each read, 2–5 seconds')
    return parser


def status():
    import runtime
    return {'result': 'departure_staged', 'mode': 'silent', 'delivery_enabled': False,
            'background_listener': False, 'arrival_enabled': False,
            'phrase': runtime.PHRASE, 'motion_window_seconds': 20,
            'cooldown_seconds': 120, 'minimum_motion_lead_seconds': 0.5,
            'maximum_sample_gap_seconds': 8, 'maximum_read_seconds': 2,
            'active_hours': '24/7', 'quiet_hours': None, 'person_gate_required': True,
            'person_gate_verified': False,
            'source': 'hub_reported_snapshot', 'radio_freshness': 'unknown',
            'physical_verification': 'pending', 'departure_verification': 'heuristic_only'}


@dataclass(frozen=True)
class Sample:
    tick: float
    observed_at: datetime
    motion: bool | None
    door_open: bool | None
    read_seconds: float = 0

    def __post_init__(self):
        if (type(self.tick) not in (int, float) or not math.isfinite(self.tick)
                or self.tick < 0 or type(self.read_seconds) not in (int, float)
                or not math.isfinite(self.read_seconds) or self.read_seconds < 0
                or not isinstance(self.observed_at, datetime)
                or self.observed_at.utcoffset() is None
                or (self.motion is not None and type(self.motion) is not bool)
                or (self.door_open is not None and type(self.door_open) is not bool)):
            raise ValueError('invalid_departure_sample')


class DepartureDetector:
    """Consecutive paired snapshots only; initial/recovery samples are baselines.

    A clear->motion edge while the door is closed may arm one candidate. A later
    closed->open edge consumes it. Explicit same-sample mode also accepts both
    rising edges together, without claiming their order or excluding arrivals. Unknown,
    slow, missed, duplicated, or clock-discontinuous samples break continuity.
    A door opening consumes the motion even if suppressed. Motion while the door
    is open is not carried into a later session. No inferred resident identity.
    """
    def __init__(self, *, allow_simultaneous=False, require_close=False):
        self.allow_simultaneous = allow_simultaneous
        self.require_close = require_close
        self.awaiting_close = False
        self.previous = None
        self.motion_tick = None
        self.last_candidate_tick = None

    def reset(self):
        self.awaiting_close = False
        self.previous = None
        self.motion_tick = None
        # Keep cooldown through outages. New processes never restore motion.

    @staticmethod
    def decision(reason, candidate=False):
        return {'decision': 'candidate' if candidate else 'suppressed', 'reason': reason,
                'delivery': 'disabled', 'departure_verified': False}

    def accept(self, sample: Sample):
        old = self.previous
        if sample.motion is None or sample.door_open is None:
            self.reset()
            return self.decision('unknown_sensor_state')
        if sample.read_seconds > 2:
            self.reset()
            return self.decision('slow_read')
        if old is not None:
            gap = sample.tick - old.tick
            wall_gap = (sample.observed_at - old.observed_at).total_seconds()
            if gap <= 0 or gap > 8 or abs(wall_gap - gap) > 2:
                self.reset()
                return self.decision('observation_discontinuity')
        self.previous = sample
        if old is None:
            return self.decision('baseline')
        motion_edge = old.motion is False and sample.motion is True
        opening = old.door_open is False and sample.door_open is True
        closing = old.door_open is True and sample.door_open is False
        if closing and self.require_close:
            qualified = self.awaiting_close
            self.awaiting_close = False
            self.motion_tick = None
            if not qualified:
                return self.decision('close_without_qualified_opening')
            if (self.last_candidate_tick is not None
                    and sample.tick - self.last_candidate_tick < 120):
                return self.decision('cooldown')
            self.last_candidate_tick = sample.tick
            return self.decision('qualified_opening_then_close', candidate=True)
        if opening:
            self.awaiting_close = False
            armed = self.motion_tick
            self.motion_tick = None
            simultaneous = motion_edge and self.allow_simultaneous
            if motion_edge and not simultaneous:
                return self.decision('simultaneous_changes')
            if not simultaneous and (armed is None or not 0.5 <= sample.tick - armed <= 20):
                return self.decision('no_recent_indoor_motion_edge')
            if self.require_close:
                # Volatile only, no open-duration timeout. Continuity checks above
                # still discard any opening spanning a sensor interruption.
                self.awaiting_close = True
                return self.decision('qualified_opening_waiting_for_close')
            # This is a household/session cooldown, not a per-person counter.
            if (self.last_candidate_tick is not None
                    and sample.tick - self.last_candidate_tick < 120):
                return self.decision('cooldown')
            self.last_candidate_tick = sample.tick
            return self.decision('same_sample_motion_and_opening' if simultaneous
                                 else 'motion_before_door_open', candidate=True)
        if sample.door_open:
            self.motion_tick = None
        elif motion_edge and old.door_open is False:
            self.motion_tick = sample.tick
        # Opening then foyer motion (arrival) is deliberately never a candidate.
        return self.decision('no_departure_sequence')


def validate_devices(args, adapter):
    devices = adapter.registry(args.registry)
    motion, door = devices.get(args.motion_device), devices.get(args.door_device)
    if (not motion or not door or motion.get('model') != 'T100'
            or door.get('model') != 'T110' or not motion.get('hub')
            or motion.get('hub') != door.get('hub')):
        raise adapter.ControlError('departure_sensor_pair_required')
    hub_alias = motion['hub']
    hub = devices.get(hub_alias)
    if not hub or hub.get('model') != 'H200':
        raise adapter.ControlError('departure_hub_required')
    return hub_alias, hub, motion, door


def child_rows(response, adapter):
    payload = response.get('getChildDeviceList') if type(response) is dict else None
    children = payload.get('child_device_list') if type(payload) is dict else None
    if type(children) is not list or len(children) > 128 or any(type(row) is not dict for row in children):
        raise adapter.ControlError('invalid_departure_snapshot')
    return children


def child_model(row):
    models = [row[key] for key in ('model', 'device_model') if key in row]
    if not models or any(type(value) is not str for value in models):
        return None
    models = [value.partition('(')[0].strip() for value in models]
    return models[0] if len(set(models)) == 1 else None


def select_child_ids(response, motion, door, adapter):
    """Same registry-name/model match as SDK selection, without cloud-state init.

    Tapo child nicknames are base64 UTF-8, as in the pinned SDK alias property.
    Do not choose by model alone, list order, strongest RSSI, or first child.
    """
    rows = child_rows(response, adapter)
    identities = []
    for entry in (motion, door):
        matches = []
        for row in rows:
            if child_model(row) != entry['model']:
                continue
            nickname = row.get('nickname')
            if type(nickname) is not str or len(nickname) > 1024:
                continue
            try:
                name = base64.b64decode(nickname, validate=True).decode('utf-8')
            except (ValueError, binascii.Error, UnicodeError):
                continue
            if name == entry['name']:
                matches.append(row)
        if len(matches) != 1:
            raise adapter.ControlError('sensor_missing_or_ambiguous')
        identity = matches[0].get('device_id')
        if type(identity) is not str or not identity or len(identity) > 256:
            raise adapter.ControlError('departure_sensor_identity_invalid')
        identities.append(identity)
    if identities[0] == identities[1]:
        raise adapter.ControlError('departure_sensor_identity_invalid')
    return tuple(identities)


def paired_states(response, motion_id, door_id, adapter):
    """Sanitize one child-list getter; IDs/model/schema are never inferred."""
    children = child_rows(response, adapter)
    states = []
    for identity, model, field in ((motion_id, 'T100', 'detected'), (door_id, 'T110', 'open')):
        matches = [row for row in children if row.get('device_id') == identity]
        if len(matches) != 1 or child_model(matches[0]) != model:
            raise adapter.ControlError('departure_sensor_missing_or_changed')
        value = matches[0].get(field)
        states.append(value if type(value) is bool else None)
    return tuple(states)


def owned_http_client(device):
    """Supported per-device SDK option; no stale pooled sockets or global patch."""
    import aiohttp
    client = aiohttp.ClientSession(connector=aiohttp.TCPConnector(force_close=True),
        cookie_jar=aiohttp.CookieJar(unsafe=True, quote_cookie=False),
        headers={'Connection': 'close'})
    device.config.http_client = client
    return client


async def observe(args, adapter, entries, *, clock=time.monotonic,
                  wall_clock=lambda: datetime.now(timezone.utc), sleep=asyncio.sleep):
    """Explicit, bounded read session; sanitized rows returned, never saved.

    One identity-checked H200 connection and one shared hub lock. No concurrent
    reads, SDK request replay, catch-up loop, retained state, media, or audio.
    """
    from kasa import Discover
    hub_alias, hub_entry, motion_entry, door_entry = entries
    device = None
    http_client = None
    detector = DepartureDetector()
    rows = []
    settings = adapter.load_settings(args.env_file)
    if settings.missing:
        raise adapter.ControlError(settings.missing)
    host = settings.host if hub_entry['host'] == '@hub' else hub_entry['host']
    deadline = clock() + args.seconds
    try:
        with adapter.device_lock(hub_alias):
            # Deadline includes setup and reads; cleanup has its own short bound.
            async with asyncio.timeout(args.seconds):
                device = await Discover.discover_single(host, username=settings.username,
                    password=settings.password, discovery_timeout=3, timeout=5)
                if (device is None or device.model != 'H200'
                        or device.device_type.value != 'hub'):
                    raise adapter.ControlError('device_identity_mismatch')
                http_client = owned_http_client(device)
                original = device.protocol.query
                async def once(request, *positional, **kwargs):
                    kwargs['retry_count'] = 0
                    return await original(request, *positional, **kwargs)
                device.protocol.query = once
                adapter.install_empty_child_lists_compat(device.protocol)
                response = await device.protocol.query({'getDeviceInfo': {
                    'device_info': {'name': ['basic_info']}}})
                if response['getDeviceInfo']['device_info']['basic_info'].get('device_model') != 'H200':
                    raise adapter.ControlError('device_identity_mismatch')
                response = await device.protocol.query({'getChildDeviceList': {
                    'childControl': {'start_index': 0}}})
                motion_id, door_id = select_child_ids(response, motion_entry, door_entry, adapter)
                while clock() < deadline:
                    began = clock()
                    # One explicit getter contains BOTH sensor snapshots. Never
                    # compare sequential CLI reads or relabel SDK cache as fresh.
                    response = await device.protocol.query({'getChildDeviceList': {
                        'childControl': {'start_index': 0}}})
                    motion, door_open = paired_states(response, motion_id, door_id, adapter)
                    tick = clock()
                    if tick >= deadline:
                        break
                    sample = Sample(tick, wall_clock(), motion, door_open, tick - began)
                    rows.append({'observed_at': sample.observed_at.isoformat(),
                        'motion': sample.motion, 'door_open': sample.door_open,
                        'read_seconds': round(sample.read_seconds, 3),
                        **detector.accept(sample)})
                    await sleep(min(args.interval, max(0, deadline - clock())))
    except TimeoutError:
        # Deadline is normal termination; do not replay a hung request.
        detector.reset()
        return {**status(), 'result': 'departure_observed',
                'end_reason': 'deadline' if clock() >= deadline else 'read_timeout',
                'observations': rows, 'completeness': 'not_assessed'}
    finally:
        if device is not None:
            try:
                await asyncio.wait_for(device.disconnect(), 2)
            except Exception:
                pass
        if http_client is not None:
            await http_client.close()
    return {**status(), 'result': 'departure_observed', 'end_reason': 'completed',
            'observations': rows, 'completeness': 'not_assessed'}


def execute_departure(args, adapter=None):
    adapter = adapter or cli
    if not 10 <= args.seconds <= MAX_SECONDS or not 2 <= args.interval <= 5:
        raise adapter.ControlError('invalid_departure_window')
    if args.operation in ('status', 'disable'):
        import runtime
        if args.operation == 'disable':
            if not args.confirm:
                raise adapter.ControlError('confirmation_required')
            root = runtime.private_dir(runtime.ROOT)
            value = runtime.config(root)
            value['enabled'] = False
            runtime.save_json(root / 'config.json', value)
        installed = runtime.installed_status(runtime.ROOT)
        return {**status(), **installed,
                'result': 'departure_trial_status' if installed['installed'] else 'departure_staged',
                'mode': 'audible_trial' if installed['enabled'] else 'silent',
                'background_listener': installed['running'],
                'quiet_hours_active': False}
    if args.operation == 'person-preview':
        import person_gate
        if args.seconds > 60:
            raise adapter.ControlError('invalid_person_preview_window')
        return asyncio.run(person_gate.preview(args))
    entries = validate_devices(args, adapter)
    return asyncio.run(observe(args, adapter, entries))


def main(argv=None):
    logging.disable(logging.CRITICAL)
    try:
        args = parser().parse_args(argv)
        result = execute_departure(args)
        code = 0
    except cli.ControlError as exc:
        result, code = {'result': 'error', 'reason': str(exc)}, 2
    except KeyboardInterrupt:
        result, code = {'result': 'cancelled'}, 130
    except Exception as exc:
        # Never print exceptions, raw payloads, credential paths, or identifiers.
        reason = {'AuthenticationError': 'authentication_failed',
                  'OSError': 'network_or_local_io_error',
                  'ModuleNotFoundError': 'dependency_unavailable',
                  'PrivateEnvError': 'private_credentials_unavailable'}.get(
                      type(exc).__name__, 'observation_failed')
        result, code = {'result': 'error', 'reason': reason}, 2
        phase = getattr(exc, 'departure_phase', None)
        if phase in {'discovery', 'identity', 'initial_state', 'person_source_identity', 'person_event_read'}:
            result['stage'] = phase
            allowed = {'TrialError', 'ControlError', 'TimeoutError', 'DeviceError', 'AuthenticationError',
                       '_ConnectionError', '_RetryableError', 'KasaException', 'KeyError'}
            result['error_type'] = type(exc).__name__ if type(exc).__name__ in allowed else 'other'
    result['security_assessment'] = 'not_assessed'
    print(json.dumps(result, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
