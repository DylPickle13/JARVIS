#!/usr/bin/env python3
"""Explicit scheduler-owned start/stop of the existing presence watcher.

No installation, plist replacement, display/device commands, or uncertainty
acknowledgement. Preserve the installed Python runtime and all controller state.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time

import cycle

ROOT = Path(__file__).resolve().parent
LABEL = 'com.jarvis.ajazz-keyboard-watch'
PLIST = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'


class ControlError(RuntimeError):
    pass


def command(*args):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True,
                          text=True, timeout=5)


def checked(*args):
    result = command(*args)
    if result.returncode:
        raise ControlError('Controller command failed; inspect its state before retrying.')
    return result.stdout


def status(service):
    result = command('print', service)
    if result.returncode:
        if 'Could not find service' in result.stderr or 'Could not find service' in result.stdout:
            return None
        raise ControlError('Controller status unavailable; no lifecycle change attempted.')
    if str(ROOT / 'watch.py') not in result.stdout or '--watch' not in result.stdout:
        raise ControlError('Controller identity mismatch; refusing lifecycle changes.')
    match = re.search(r'^\s*pid = (\d+)\s*$', result.stdout, re.M)
    return {'pid': int(match.group(1)) if match else None}


def disabled(domain):
    output = checked('print-disabled', domain)
    match = re.search(r'"' + re.escape(LABEL) + r'"\s*=>\s*(disabled|enabled|true|false)\b', output)
    return bool(match and match.group(1) in ('disabled', 'true'))


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def validate_installation():
    with PLIST.open('rb') as handle:
        definition = plistlib.load(handle)
    args = definition.get('ProgramArguments', [])
    if (definition.get('Label') != LABEL or len(args) != 3
            or not isinstance(args[0], str) or not Path(args[0]).is_absolute()
            or not Path(args[0]).is_file()
            or args[1:] != [str(ROOT / 'watch.py'), '--watch']):
        raise ControlError('Installed controller identity mismatch; refusing lifecycle changes.')


def control(enabled):
    if sys.platform != 'darwin':
        raise ControlError('Computer presence lifecycle requires its macOS owner host.')
    validate_installation()
    domain = f'gui/{os.getuid()}'
    service = f'{domain}/{LABEL}'
    store = cycle.Store(cycle.RUNTIME)
    with os.fdopen(store.open_private('control.lock', os.O_RDWR | os.O_CREAT), 'r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ControlError('Another controller lifecycle change is in progress.') from None
        current = status(service)
        if enabled:
            if current is not None and current['pid'] is None:
                raise ControlError('Controller is registered but not running; inspect before retrying.')
            checked('enable', service)
            if current is None:
                checked('bootstrap', domain, str(PLIST))  # Exactly one start; no kickstart/replay.
            deadline = time.monotonic() + 5
            while True:
                current = status(service)
                if current is not None and current['pid'] is not None:
                    break
                if time.monotonic() >= deadline:
                    raise ControlError('Controller start not verified; inspect before retrying.')
                time.sleep(0.1)
            if disabled(domain):
                raise ControlError('Controller enable not verified; inspect before retrying.')
            return 'running'
        # Prevent restart at login before unloading. Never wake/unlock or alter outputs.
        checked('disable', service)
        if current is not None:
            checked('bootout', service)
            pid = current['pid']
            deadline = time.monotonic() + 10
            while pid is not None and alive(pid):
                if time.monotonic() >= deadline:
                    raise ControlError('Controller process has not exited; stop not verified.')
                time.sleep(0.1)
        if status(service) is not None or not disabled(domain):
            raise ControlError('Controller stop not verified; inspect before retrying.')
        return 'stopped'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('enable', 'disable'))
    args = parser.parse_args()
    try:
        state = control(args.action == 'enable')
    except Exception as exc:
        message = str(exc) if isinstance(exc, ControlError) else 'Controller lifecycle failed; inspect before retrying.'
        print(json.dumps({'ok': False, 'error': message}))
        return 1
    print(json.dumps({'ok': True, 'controller': state}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
