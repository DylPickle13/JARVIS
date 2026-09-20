"""Bounded D235 worker: legacy hub reads or direct, gated settings adapter.

Uses the existing isolated archive environment (pytapo). Parent owns the hub
lock. Credentials stay in the env file; private routing data travels over stdin.
Media acquisition is limited to explicit, confirmed short archive downloads.
No audible actions, background service or arbitrary RPC.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent

# Documented product features, NOT a claim of working local API endpoints.
UNVERIFIED = (
    'live_video', 'rtsp', 'two_way_audio', 'quick_responses', 'button_events',
    'chime_pairing', 'chime_ring', 'chime_volume', 'chime_schedule',
    'motion_detection', 'person_detection', 'vehicle_detection', 'pet_detection',
    'package_detection', 'spotlight', 'night_vision', 'privacy',
    'battery_status', 'power_mode', 'recording_policy', 'recording_playback',
    'recording_download', 'phone_notifications',
)


def summarize(response):
    """Strict selection and explicit scalar allowlist; no raw identifiers escape."""
    from security_cli import ControlError
    try:
        cameras = response['general_camera_manage']['paired_general_device_list']
        if not isinstance(cameras, list) or not all(isinstance(c, dict) for c in cameras):
            raise ValueError
        matches = [c for c in cameras if c.get('device_model') == 'D235']
    except (KeyError, TypeError, ValueError):
        raise ControlError('invalid_hub_camera_list') from None
    if len(matches) != 1:
        raise ControlError('doorbell_missing_or_ambiguous')
    camera = matches[0]
    features = {}
    for name in ('hub_storage_enabled', 'plan_24h_record', 'wifi_backup_enabled'):
        value = camera.get(name)
        features[name] = {'value': value if type(value) is bool else None,
                          'status': 'observed' if type(value) is bool else 'unknown',
                          'writable': False}
    mode = camera.get('network_mode')
    features['network_mode'] = {
        'value': mode if mode in ('wireless', 'wired') else None,
        'writable': False,
        'meaning': 'network_connection_not_electrical_power_mode',
    }
    return {
        'result': 'read_succeeded', 'model': 'D235',
        'observation_scope': 'hub_reported_snapshot',
        'doorbell_reachability': 'not_assessed',
        'hardware': None, 'firmware': None,
        'features': features,
        'capabilities': {
            'hub_metadata': {'support': 'verified_read_only'},
            **{name: {'support': 'not_verified', 'enabled_in_cli': False}
               for name in UNVERIFIED},
        },
    }


def read_hub(env_file):
    from security_cli import ControlError, load_settings
    from pytapo import Tapo

    class Reader(Tapo):
        def isSupportingPresets(self):
            return False

        def executeFunction(self, method, params, retry=False):
            if method not in {'getDeviceInfo', 'getGeneralDeviceList'}:
                raise ControlError('unapproved_method')
            # Prevent upstream's fallback that can disable cruise mode.
            return super().executeFunction(method, params, retry=True)

    settings = load_settings(env_file)
    if settings.missing:
        raise ControlError(settings.missing)
    hub = None
    try:
        hub = Reader(settings.host, 'admin', settings.password, settings.password,
                     isKLAP=False, retryStok=False,
                     printDebugInformation=False, printWarnInformation=False)
        info = hub.basicInfo.get('device_info', {}).get('basic_info', {})
        if info.get('device_model') != 'H200':
            raise ControlError('device_identity_mismatch')
        return summarize(hub.executeFunction('getGeneralDeviceList', {
            'general_camera_manage': {'paired_general_device_list': {}}}))
    finally:
        if hub is not None:
            hub.close()


async def execute(env_file, *, entry=None, command='status', name=None, value=None, confirm=False):
    """Caller holds hub lock; worker is killed/reaped on timeout/cancellation."""
    from security_cli import ControlError
    writing = command in ('set', 'privacy') or (command == 'recording' and name != 'status')
    interpreter = ROOT / '.venv-archive/bin/python'
    if not interpreter.is_file():
        raise ControlError('doorbell_dependency_unavailable')
    process = await asyncio.create_subprocess_exec(
        str(interpreter), str(Path(__file__).resolve()), str(Path(env_file).resolve()),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        request = json.dumps({'entry': entry, 'command': command, 'name': name,
                              'value': value, 'confirm': confirm}).encode()
        try:
            output, _ = await asyncio.wait_for(process.communicate(request), timeout=90 if command == 'clip' else 45)
        except (TimeoutError, asyncio.CancelledError):
            if writing:
                raise ControlError('write_outcome_unknown') from None
            raise
        if len(output) > 65536:
            raise ControlError('write_outcome_unknown' if writing
                               else 'doorbell_invalid_response')
        result = json.loads(output)
        if process.returncode or result.get('result') not in ('read_succeeded', 'verified', 'readback_mismatch'):
            reason = result.get('reason')
            if reason not in {'doorbell_missing_or_ambiguous', 'device_identity_mismatch',
                              'invalid_hub_camera_list', 'doorbell_dependency_unavailable',
                              'write_outcome_unknown', 'feature_unavailable', 'confirmation_required',
                              'unsupported_setting', 'unsupported_command', 'expected_on_or_off',
                              'number_out_of_range', 'invalid_feature_value',
                              'record_plan_unavailable', 'continuous_requires_wired_always_on',
                              'hub_storage_not_ready', 'invalid_weekly_schedule',
                              'invalid_archive_response', 'archive_directory_not_private',
                              'invalid_event_response', 'invalid_event_window', 'event_time_unverified',
                              'clip_not_covered_by_archive_index', 'clip_download_incomplete',
                              'clip_download_failed', 'invalid_interval', 'invalid_timestamp',
                              'interval_requires_past_day_and_60_seconds_old', 'clip_limit_10_seconds'}:
                reason = 'doorbell_read_failed'
            raise ControlError(reason)
        return result
    except (ValueError, TypeError, AttributeError, OSError):
        raise ControlError('write_outcome_unknown' if writing
                           else 'doorbell_invalid_response') from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


def main():
    import logging
    from security_cli import ControlError
    logging.disable(logging.CRITICAL)
    try:
        if len(sys.argv) != 2:
            raise ControlError('invalid_arguments')
        request = json.loads(sys.stdin.read(16384))
        if request.get('entry') is not None:
            if request.get('command') == 'events':
                from security_events import run
            elif request.get('command') in ('recording', 'recordings', 'clip'):
                from security_recording import run
            else:
                from security_doorbell_direct import run
            result = run(request['entry'], sys.argv[1], request.get('command', 'status'),
                         request.get('name'), request.get('value'), request.get('confirm', False))
        else:
            if request.get('command', 'status') not in ('status', 'capabilities'):
                raise ControlError('unsupported_command')
            result = read_hub(sys.argv[1])
        code = 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ControlError) else (
            'doorbell_dependency_unavailable' if isinstance(exc, ModuleNotFoundError)
            else 'doorbell_read_failed')
        result, code = {'result': 'error', 'reason': reason}, 2
    print(json.dumps(result))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
