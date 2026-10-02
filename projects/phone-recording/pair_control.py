#!/usr/bin/env python3
"""Explicit USB/Wi-Fi two-phone control with verified post-stop collection."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import fcntl
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET
from inventory import DEFAULT_ADB

import android_transport as transport
TRANSPORTS = transport.config()
PHONES = transport.targets(TRANSPORTS)
from runtime_paths import ROOT, CAPTURE
UI = '/sdcard/phone-recording-pair-ui.xml'


def adb(phone, *args, timeout=15):
    endpoint = transport.ensure(phone, TRANSPORTS, PHONES)
    return subprocess.check_output([DEFAULT_ADB, '-s', endpoint, *args], text=True, timeout=timeout)


def parse_state(xml):
    nodes = list(ET.fromstring(xml).iter('node'))
    # Open Camera leaves underlying shutter nodes in settings hierarchies.
    if any(n.get('text', '').strip() for n in nodes):
        return 'unknown_or_overlay'
    for n in nodes:
        if n.get('resource-id') == 'net.sourceforge.opencamera:id/take_photo':
            return {'Start recording video': 'idle', 'Stop recording video': 'recording'}.get(n.get('content-desc'), 'unknown')
    return 'unknown'


def state(phone):
    for attempt in range(3):
        try:
            adb(phone, 'shell', 'rm', '-f', UI)
            adb(phone, 'shell', 'uiautomator', 'dump', UI)
            result = parse_state(adb(phone, 'shell', 'cat', UI))
            if result in ('idle', 'recording'):
                return result
        except (subprocess.SubprocessError, OSError, ET.ParseError, RuntimeError):
            pass
        if attempt < 2:
            time.sleep(.5)
    return 'unknown'


def parallel(fn, phones):
    def safe(p):
        try:
            return fn(p)
        except (subprocess.SubprocessError, OSError, RuntimeError):
            return 'command_error_outcome_uncertain'
    with ThreadPoolExecutor(max_workers=max(1,len(phones))) as pool:
        return dict(zip(phones, pool.map(safe, phones)))


def status():
    return parallel(state, list(PHONES))


def toggle(phone):
    adb(phone, 'shell', 'input', 'keyevent', 'KEYCODE_VOLUME_UP')
    return 'sent_once'


def change(action):
    before = status()
    if action == 'start' and any(s != 'idle' for s in before.values()):
        return {'ok': False, 'error': 'Start refused: both phones must be verified idle with settings closed', 'before': before}
    targets = list(PHONES) if action == 'start' else [p for p, s in before.items() if s == 'recording']
    commands = parallel(toggle, targets)
    after = status()
    expected = 'recording' if action == 'start' else 'idle'
    result = {'ok': all(s == expected for s in after.values()), 'action': action, 'before': before, 'commands': commands, 'after': after}
    if action == 'start' and not result['ok']:
        # Roll back only confirmed recordings started from an all-idle baseline.
        rollback = [p for p, s in after.items() if s == 'recording']
        result['rollback_commands'] = parallel(toggle, rollback)
        result['after_rollback'] = status()
        result['warning'] = 'Partial/uncertain start; inspect unknown phones manually. No automatic restart.'
    return result


def managed(action):
    from collect import begin, transfer
    if action == 'start':
        ready = status()
        if any(s != 'idle' for s in ready.values()):
            return {'ok': False, 'error': 'Both phones must be idle; no take started', 'states': ready}
        try:
            begin(ROOT, PHONES, adb)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            return {'ok': False, 'error': str(e)}
        return change('start')
    result = change('stop') if action == 'stop' else {'ok': all(s == 'idle' for s in status().values())}
    if result['ok']:
        result['collection'] = transfer(ROOT, PHONES, adb, DEFAULT_ADB, CAPTURE)
        result['ok'] = result['collection']['ok']
    else:
        result['collection'] = {'ok': False, 'error': 'Recording state unverified; transfer deferred'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'start', 'stop', 'collect', 'test', 'gui'])
    args = parser.parse_args()
    # Direct CLI/GUI must use the same three-camera engine as the dashboard.
    import os, sys
    interpreter = ROOT / '.sync-venv/bin/python'
    if not interpreter.exists():
        raise RuntimeError('Install requirements-sync.txt in the local .sync-venv first')
    if Path(sys.prefix) != ROOT / '.sync-venv':
        os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])
    from managed_control import status as camera_status, managed as camera_managed
    ROOT.mkdir(exist_ok=True)
    with (ROOT / '.pair-control.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        action = args.action
        if action == 'gui':
            from camera_config import CAMERAS, ROLES
            message = ', '.join(CAMERAS[r]['name'] for r in ROLES) + ': phone-local recording. Keep every enabled camera app open.'
            prompt = 'button returned of (display dialog ' + json.dumps(message) + ' with title "Phone Recording" buttons {"Cancel", "Stop record", "Start record"} default button "Start record" cancel button "Cancel")'
            button = subprocess.check_output(['osascript', '-e', prompt], text=True).strip()
            action = 'start' if button == 'Start record' else 'stop'
        if action == 'status':
            result = camera_status()
        elif action == 'test':
            result = {'host_start': datetime.datetime.now().astimezone().isoformat()}
            try:
                result['start'] = camera_managed('start')
                print(json.dumps(result), flush=True)
                if result['start']['ok']:
                    time.sleep(120)
            finally:
                # change(start) handles its own partial start rollback. Stop only
                # recordings belonging to this successful test, not preexisting ones.
                if result.get('start', {}).get('ok'):
                    result['stop'] = camera_managed('stop')
                result['host_end'] = datetime.datetime.now().astimezone().isoformat()
                (ROOT / 'pair-test-result.json').write_text(json.dumps(result, indent=2))
        else:
            result = camera_managed(action)
        print(json.dumps(result, indent=2))
        if args.action == 'gui':
            summary = json.dumps(result)
            subprocess.run(['osascript', '-e', 'on run argv\ndisplay dialog (item 1 of argv) with title "Phone Recording result" buttons {"OK"}\nend run', summary], check=True)


if __name__ == '__main__':
    main()
