"""Explicit C230 24/7 recording setup; run in .venv-archive with --confirm.
Only changes the weekly recording plan, not audio, detection, or storage settings.
"""
import argparse
import json
import logging
import signal
from pytapo import Tapo
import security_cli as security

DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


class Camera(Tapo):
    def isSupportingPresets(self):
        return False

    def executeFunction(self, method, params, retry=False):
        if method not in {'getDeviceInfo', 'getRecordPlan', 'getHubStorage', 'setRecordPlan'}:
            raise RuntimeError('unapproved_method')
        # Prevent upstream's cruise-disable fallback on errors.
        return super().executeFunction(method, params, retry=True)


def continuous(plan):
    return plan.get('enabled') == 'on' and all(
        json.loads(plan.get(day, 'null')) == ['0000-2400:1'] for day in DAYS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', action='store_true', required=True)
    parser.parse_args()
    logging.disable(logging.CRITICAL)
    camera = None
    write_started = False
    def timeout(*args):
        raise TimeoutError()
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(40)
    try:
        with security.device_lock('indoor-camera'):
            cfg = security.load_settings(security.ROOT / '.env')
            entry = security.registry()['indoor-camera']
            camera = Camera(entry['host'], 'admin', cfg.password, cfg.password,
                            isKLAP=False, retryStok=False, printWarnInformation=False)
            info = camera.basicInfo.get('device_info', {}).get('basic_info', {})
            if info.get('device_model') != 'C230':
                raise RuntimeError('wrong_device')
            storage = camera.getHubStorage()['hub_manage']['hub_storage_info']
            if storage.get('enabled') != 'on' or storage.get('status') != 'online':
                raise RuntimeError('hub_storage_not_ready')
            before = camera.getRecordPlan()
            print(json.dumps({'previous_record_plan': before}), flush=True)
            if not continuous(before):
                write_started = True
                camera.setRecordPlan(True, **{day: ['0000-2400:1'] for day in DAYS})
            after = camera.getRecordPlan()
            if not continuous(after):
                raise RuntimeError('readback_mismatch')
            print(json.dumps({'result': 'verified', 'record_plan': after,
                              'archive_playback': 'not_assessed'}))
            return 0
    except Exception as exc:
        print(json.dumps({'result': 'write_outcome_unknown' if write_started else 'read_failed',
                          'error_type': type(exc).__name__}))
        return 3 if write_started else 2
    finally:
        if camera is not None:
            try:
                camera.close()
            except Exception:
                pass
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
