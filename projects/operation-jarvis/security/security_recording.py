"""D235 recording plans and bounded H200 archive operations.

No media upload, stream display, background recording, deletion or SD formatting.
Caller owns hub lock. Schedule writes and local clip downloads require approval.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from security_cli import ControlError, ROOT, load_settings

DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
MAX_CLIPS = 20


def timestamp(value):
    """Unix seconds or ISO timestamp with explicit zone; never assume local zone."""
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{1,12}', value):
        return int(value)
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError
        return int(date.timestamp())
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ControlError('invalid_timestamp') from None


def interval(value, *, clip=False, now=None):
    now = int(time.time()) if now is None else now
    if not isinstance(value, dict) or set(value) != {'start', 'end'}:
        raise ControlError('invalid_interval')
    start, end = timestamp(value['start']), timestamp(value['end'])
    if not (now - 86400 <= start < end <= now - 60):
        raise ControlError('interval_requires_past_day_and_60_seconds_old')
    if clip and end - start > 10:
        raise ControlError('clip_limit_10_seconds')
    return start, end


def schedule(value):
    if not isinstance(value, dict) or set(value) != set(DAYS):
        raise ControlError('invalid_weekly_schedule')
    result = {}
    for day in DAYS:
        slots = value[day]
        if not isinstance(slots, list) or len(slots) > 10:
            raise ControlError('invalid_weekly_schedule')
        previous_end = 0
        for slot in slots:
            if not isinstance(slot, str) or not re.fullmatch(r'\d{4}-\d{4}:[12]', slot):
                raise ControlError('invalid_weekly_schedule')
            start, end = slot[:4], slot[5:9]
            def minute(text):
                hours, minutes = int(text[:2]), int(text[2:])
                if minutes >= 60 or hours > 24 or (hours == 24 and minutes != 0):
                    raise ControlError('invalid_weekly_schedule')
                return hours * 60 + minutes
            a, b = minute(start), minute(end)
            if not previous_end <= a < b <= 1440:
                raise ControlError('invalid_weekly_schedule')
            previous_end = b
        result[day] = list(slots)
    return result


def normalize_plan(raw):
    try:
        days = {day: json.loads(raw[day]) if isinstance(raw[day], str) else raw[day] for day in DAYS}
        days = schedule(days)
        if raw.get('enabled') not in ('on', 'off'):
            raise ValueError
        enabled = raw['enabled'] == 'on'
    except (KeyError, TypeError, ValueError, ControlError):
        raise ControlError('record_plan_unavailable') from None
    mode = 'custom'
    for label, code in (('continuous', '1'), ('events', '2')):
        if all(slots == [f'0000-2400:{code}'] for slots in days.values()):
            mode = label
    return {'enabled': enabled, 'mode': mode if enabled else 'disabled', 'days': days}


def validate(command, name, value, confirm):
    if command == 'recording':
        if name not in ('status', 'continuous', 'events', 'schedule'):
            raise ControlError('unsupported_recording_mode')
        if name != 'status' and confirm is not True:
            raise ControlError('confirmation_required')
        if name == 'schedule':
            schedule(value)
    elif command in ('recordings', 'clip'):
        if command == 'clip' and confirm is not True:
            raise ControlError('confirmation_required')
        interval(value, clip=command == 'clip')
    else:
        raise ControlError('unsupported_command')


def plan_operation(client, mode, value):
    before = normalize_plan(client.getRecordPlan())
    power = client.getPowerMode().get('battery', {}).get('power', {}).get('mode')
    storage = client.getHubStorage().get('hub_manage', {}).get('hub_storage_info', {})
    summary = {'power_mode': power if power in ('wired_always_on', 'battery', 'wired') else None,
               'hub_storage_enabled': storage.get('enabled') == 'on' if storage.get('enabled') in ('on', 'off') else None,
               'hub_storage_status': storage.get('status') if storage.get('status') in ('online', 'offline') else 'unknown'}
    if mode == 'status':
        return {'result': 'read_succeeded', 'recording': before, **summary,
                'archive_playback': 'not_assessed'}
    desired = schedule(value) if mode == 'schedule' else {
        day: [f'0000-2400:{1 if mode == "continuous" else 2}'] for day in DAYS}
    if any(slot.endswith(':1') for slots in desired.values() for slot in slots) and power != 'wired_always_on':
        raise ControlError('continuous_requires_wired_always_on')
    if storage.get('enabled') != 'on' or storage.get('status') != 'online':
        raise ControlError('hub_storage_not_ready')
    if before['enabled'] and before['days'] == desired:
        return {'result': 'verified', 'changed': False, 'recording': before, **summary}
    try:
        client.setRecordPlan(True, **desired)
        after = normalize_plan(client.getRecordPlan())
        if not after['enabled'] or after['days'] != desired:
            return {'result': 'readback_mismatch', 'outcome': 'unknown'}
        return {'result': 'verified', 'changed': True, 'previous_recording': before,
                'recording': after, **summary, 'archive_playback': 'not_assessed'}
    except BaseException:
        raise ControlError('write_outcome_unknown') from None


def parse_clips(response, start, end):
    try:
        items = response['playback']['search_video_results']
        if not isinstance(items, list) or len(items) > MAX_CLIPS:
            raise ValueError
        clips = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError
            for key, value in item.items():
                if not re.fullmatch(r'search_video_results_\d+', key) or not isinstance(value, dict):
                    raise ValueError
                a, b = value.get('startTime'), value.get('endTime')
                if type(a) is not int or type(b) is not int or not a < b:
                    raise ValueError
                if a >= end or b <= start:
                    continue
                kind = value.get('video_type')
                clips.append({'start': a, 'end': b,
                    'start_iso': datetime.fromtimestamp(a, timezone.utc).isoformat(),
                    'end_iso': datetime.fromtimestamp(b, timezone.utc).isoformat(),
                    'recording_type': 'continuous' if kind in (1, '1') else 'event_or_other'})
        return clips
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise ControlError('invalid_archive_response') from None


def camera_from_hub(hub):
    response = hub.executeFunction('getGeneralDeviceList', {
        'general_camera_manage': {'paired_general_device_list': {}}})
    try:
        matches = [c for c in response['general_camera_manage']['paired_general_device_list']
                   if c.get('device_model') == 'D235']
        if len(matches) != 1:
            raise ControlError('doorbell_missing_or_ambiguous')
        camera = matches[0]
        if not all(isinstance(camera.get(k), str) and camera[k] for k in ('device_id', 'mac')):
            raise ValueError
        return camera
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ControlError('invalid_hub_camera_list') from None


def query_clips(hub, camera, start, end):
    response = hub.executeFunction('searchVideoWithUTC', {'playback': {'search_video_with_utc': {
        'channel': 0, 'child_device_id': camera['device_id'], 'child_device_mac': camera['mac'],
        'start_time': start, 'end_time': end, 'start_index': 0, 'end_index': MAX_CLIPS - 1,
        'player_id': uuid.uuid4().hex.upper()}}})
    return parse_clips(response, start, end)


def archive_client(settings):
    from pytapo import Tapo
    from pytapo.const import MAX_LOGIN_RETRIES
    from security_doorbell_direct import disable_transport_replays
    class Hub(Tapo):
        def isSupportingPresets(self):
            return False
        def executeFunction(self, method, params, retry=False):
            if method not in {'getDeviceInfo', 'getGeneralDeviceList', 'searchVideoWithUTC', 'searchDetectionList'}:
                raise ControlError('unapproved_method')
            return super().executeFunction(method, params, retry=True)
        def performRequest(self, requestData, loginRetryCount=0):
            return super().performRequest(requestData, loginRetryCount=MAX_LOGIN_RETRIES)
    hub = Hub(settings.host, 'admin', settings.password, settings.password,
              isKLAP=False, retryStok=False, printDebugInformation=False, printWarnInformation=False)
    try:
        disable_transport_replays(hub.transport)
        info = hub.basicInfo.get('device_info', {}).get('basic_info', {})
        if info.get('device_model') != 'H200':
            raise ControlError('device_identity_mismatch')
    except Exception:
        hub.close()
        raise
    return hub


def private_output():
    directory = ROOT / 'private-archive'
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ControlError('archive_directory_not_private')
    return directory / ('doorbell-' + uuid.uuid4().hex + '.partial.ts')


def verify_video(path):
    """Optional, local-only decoding. Never print tags, device metadata or frames."""
    result = {'video_decode_verified': False, 'audio_decode': 'not_assessed'}
    ffprobe, ffmpeg = shutil.which('ffprobe'), shutil.which('ffmpeg')
    if not ffprobe or not ffmpeg:
        return {**result, 'verification': 'decoder_unavailable'}
    try:
        probe = subprocess.run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-f', 'mpegts', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,width,height',
            '-of', 'json', str(path)], capture_output=True, text=True, timeout=8)
        if probe.returncode:
            return {**result, 'verification': 'probe_failed'}
        streams = json.loads(probe.stdout).get('streams', [])
        if not streams:
            return {**result, 'verification': 'video_missing'}
        stream = streams[0]
        if stream.get('codec_name') in ('hevc', 'h264'):
            result['video_codec'] = stream['codec_name']
        for field in ('width', 'height'):
            if type(stream.get(field)) is int:
                result[field] = stream[field]
        decoded = subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-nostdin',
            '-protocol_whitelist', 'file,pipe', '-f', 'mpegts', '-i', str(path), '-map', '0:v:0',
            '-t', '10', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=15)
        frames = [int(n) for n in re.findall(r'^frame=(\d+)$', decoded.stdout, re.MULTILINE)]
        result['video_decode_verified'] = decoded.returncode == 0 and bool(frames) and max(frames) > 0
        result['verification'] = 'video_decoded' if result['video_decode_verified'] else 'decode_failed'
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        result['verification'] = 'decode_unavailable_or_failed'
    return result


def archive_operation(env_file, command, value):
    start, end = interval(value, clip=command == 'clip')
    settings = load_settings(env_file)
    if settings.missing:
        raise ControlError(settings.missing)
    hub = None
    try:
        hub = archive_client(settings)
        camera = camera_from_hub(hub)
        clips = query_clips(hub, camera, start, end)
        if command == 'recordings':
            return {'result': 'read_succeeded', 'clips': clips,
                    'page_limit': MAX_CLIPS, 'pagination': 'first_page_only',
                    'possibly_truncated': True if len(clips) >= MAX_CLIPS else None,
                    'archive_playback': 'not_assessed', 'scope': 'hub_archive_index'}
        if not any(c['start'] <= start and c['end'] >= end for c in clips):
            raise ControlError('clip_not_covered_by_archive_index')
        from archive_download_probe import download
        output = private_output()
        os.umask(0o077)
        try:
            result = asyncio.run(download(hub, camera, start, end, output))
            if not result['complete']:
                raise ControlError('clip_download_incomplete')
            final = output.with_name(output.name.replace('.partial.ts', '.ts'))
            output.rename(final)
            return {'result': 'read_succeeded', 'path': str(final), 'bytes': result['bytes'],
                    'download_complete': True, **verify_video(final)}
        except Exception as exc:
            # Incomplete media is not a successful clip; retain no partial file.
            output.unlink(missing_ok=True)
            if isinstance(exc, ControlError):
                raise
            raise ControlError('clip_download_failed') from None
    finally:
        if hub is not None:
            try:
                hub.close()
            except Exception:
                pass


def run(entry, env_file, command, name, value, confirm):
    validate(command, name, value, confirm)
    if entry.get('model') != 'D235':
        raise ControlError('device_identity_mismatch')
    if command in ('recordings', 'clip'):
        return {'model': 'D235', **archive_operation(env_file, command, value)}
    from security_doorbell_direct import make_client
    settings = load_settings(env_file)
    if not settings.username or not settings.password:
        raise ControlError('missing_credentials')
    client = None
    try:
        client = make_client(entry['host'], settings, 'setRecordPlan' if name != 'status' else None)
        info = client.basicInfo.get('device_info', {}).get('basic_info', {})
        if info.get('device_model') != 'D235' or info.get('device_type') != 'SMART.TAPODOORBELL':
            raise ControlError('device_identity_mismatch')
        return {'model': 'D235', **plan_operation(client, name, value)}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
