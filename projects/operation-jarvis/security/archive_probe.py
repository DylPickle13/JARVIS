"""Experimental bounded, read-only H200 archive metadata probe. No media download."""
import json
import logging
import signal
from datetime import datetime, timedelta
import uuid
from zoneinfo import ZoneInfo

import security_cli as security
from pytapo import Tapo


class ReadOnlyTapo(Tapo):
    def isSupportingPresets(self):
        return False

    def executeFunction(self, method, params, retry=False):
        if method not in {'getDeviceInfo', 'getPairList', 'getGeneralDeviceList',
                          'searchDateWithVideo', 'searchVideoWithUTC'}:
            raise RuntimeError('unapproved_method')
        # Upstream otherwise disables cruise mode on one error code.
        return super().executeFunction(method, params, retry=True)


def main():
    logging.disable(logging.CRITICAL)
    hub = None
    stage = 'connect'
    def timeout(*args):
        raise TimeoutError()
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(40)
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
            print(json.dumps({'stage': stage, 'count': len(cameras),
                              'models': [c.get('device_model') for c in cameras]}))
            matches = [c for c in cameras if c.get('device_model') == 'C230']
            if len(matches) != 1:
                print(json.dumps({'result': 'camera_missing_or_ambiguous',
                                  'field_names': [list(c) for c in cameras]}))
                return
            camera = matches[0]
            stage = 'recording_dates'
            now = datetime.now(ZoneInfo('America/Toronto'))
            start_date = (now - timedelta(days=1)).strftime('%Y%m%d')
            end_date = (now + timedelta(days=1)).strftime('%Y%m%d')
            result = hub.executeFunction('searchDateWithVideo', {'playback': {
                'search_year_utility': {'channel': [0],
                    'child_device_id': camera['device_id'],
                    'child_device_mac': camera['mac'],
                    'start_date': start_date, 'end_date': end_date}}})
            dates = result.get('playback', {}).get('search_results')
            print(json.dumps({'stage': stage, 'start_date': start_date,
                              'end_date': end_date,
                              'result': 'read_succeeded' if isinstance(dates, list) else 'unexpected_shape',
                              'date_entry_count': len(dates) if isinstance(dates, list) else None}))
            stage = 'recording_clips'
            now = datetime.now(ZoneInfo('America/Toronto'))
            result = hub.executeFunction('searchVideoWithUTC', {'playback': {
                'search_video_with_utc': {'channel': 0,
                    'child_device_id': camera['device_id'],
                    'child_device_mac': camera['mac'],
                    'start_time': int((now - timedelta(hours=24)).timestamp()),
                    'end_time': int(now.timestamp()), 'start_index': 0, 'end_index': 19,
                    'player_id': uuid.uuid4().hex.upper()}}})
            clips = result.get('playback', {}).get('search_video_results')
            summaries = []
            if isinstance(clips, list):
                for item in clips:
                    if not isinstance(item, dict):
                        continue
                    for value in item.values():
                        if isinstance(value, dict):
                            summaries.append({key: value[key] for key in
                                              ('startTime', 'endTime') if type(value.get(key)) is int})
            print(json.dumps({'stage': stage,
                              'result': 'read_succeeded' if isinstance(clips, list) else 'unexpected_shape',
                              'entry_count': len(clips) if isinstance(clips, list) else None,
                              'clips': summaries}))
    except Exception as exc:
        print(json.dumps({'stage': stage, 'error_type': type(exc).__name__}))
    finally:
        if hub is not None:
            try:
                hub.close()
            except Exception:
                pass
        signal.alarm(0)


if __name__ == '__main__':
    main()
