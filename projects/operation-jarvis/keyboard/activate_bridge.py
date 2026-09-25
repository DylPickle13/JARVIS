#!/usr/bin/env python3
"""Explicit post-install cutover. No installation, acknowledgment, or manual HID write."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile

import bridge_client
import cycle

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true', required=True)
    parser.add_argument('--bootstrap-watcher', action='store_true',
                        help='After a deliberate bootout, bootstrap its existing plist instead of restarting')
    args = parser.parse_args()
    os.umask(0o077)
    # Shared lock prevents a watcher command racing the backend switch.
    store = cycle.Store(cycle.RUNTIME)
    with os.fdopen(store.open_private('cycle.lock', os.O_RDWR | os.O_CREAT), 'r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        local = cycle.validate_state(store.load('state.json', cycle.initial()))
        if local['pending']:
            raise SystemExit('Local uncertain write remains blocked; explicit acknowledgment required')
        response = bridge_client.request('status')
        if (response.get('pending') is not False or response.get('lighting_readback') is not False
                or response.get('device_available') is not True):
            raise SystemExit('Bridge is not ready; no backend switch made')
        fd, name = tempfile.mkstemp(dir=ROOT, prefix='.transport-')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump({'backend': 'karabiner'}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, ROOT / 'transport.json')
        finally:
            if os.path.exists(name): os.unlink(name)
    # KeepAlive restarts the single registered watcher; don't launch a second one.
    target = f'gui/{os.getuid()}/com.jarvis.ajazz-keyboard-watch'
    command = (['launchctl', 'bootstrap', f'gui/{os.getuid()}',
                str(Path.home() / 'Library/LaunchAgents/com.jarvis.ajazz-keyboard-watch.plist')]
               if args.bootstrap_watcher else ['launchctl', 'kill', 'SIGTERM', target])
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit('Backend switched, but watcher restart failed; inspect before retrying')
    print('Karabiner backend selected; watcher restarting with original persisted safety state.')


if __name__ == '__main__':
    main()
