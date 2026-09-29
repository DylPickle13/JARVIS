#!/usr/bin/env python3
"""Explicit phone-only screen acceptance test. Never alters real presence.
Temporarily replaces ONLY the newly installed monitor relay with a TLS fixture;
restores its LaunchAgent in finally. Phone must already be enabled + plugged in.
"""
import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Server


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--confirm-phone-screen-test', action='store_true', required=True)
    p.add_argument('--serial', required=True)
    p.add_argument('--private-dir', type=Path, required=True)
    a = p.parse_args()
    root = a.private_dir
    config = json.loads((root/'server.json').read_text())
    label = 'com.jarvis.android-monitor'
    domain = 'gui/' + str(os.getuid())
    plist = Path.home()/'Library/LaunchAgents'/f'{label}.plist'
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(root/'server.crt', root/'server.key')
    state = {'version': 1, 'state': 'unknown', 'ageSeconds': None}
    def response(): return dict(state)
    def power(expected):
        text = subprocess.check_output(['adb', '-s', a.serial, 'shell', 'dumpsys', 'power'], text=True)
        actual = next(line.strip() for line in text.splitlines() if 'Display Power: state=' in line)
        print(actual, flush=True)
        if actual != 'Display Power: state=' + expected: raise AssertionError('Expected ' + expected)
    server = thread = None
    subprocess.run(['launchctl', 'bootout', domain + '/' + label], check=True)
    try:
        # launchctl removal can return before the old process releases its socket.
        for attempt in range(10):
            try:
                server = Server((config['bind'], config['port']), context, config['token'], response)
                break
            except OSError as exc:
                if exc.errno != 48 or attempt == 9: raise
                time.sleep(1)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        state.update(state='nearby', ageSeconds=1)
        time.sleep(8); power('ON')
        state.update(state='away', ageSeconds=1)
        time.sleep(14); power('OFF')
        state.update(state='unknown', ageSeconds=None)
        time.sleep(8); power('OFF')
        state.update(state='nearby', ageSeconds=99)  # stale must not wake
        time.sleep(8); power('OFF')
        state.update(state='nearby', ageSeconds=1)
        time.sleep(9); power('ON')
        text = subprocess.check_output(['adb', '-s', a.serial, 'shell', 'dumpsys', 'activity', 'activities'], text=True)
        line = next(x.strip() for x in text.splitlines() if 'mResumedActivity:' in x)
        if 'com.alexvas.dvr/.activity.LiveViewActivity' not in line:
            raise AssertionError('tinyCam live view not resumed (secure lock may need manual PIN).')
        print('tinyCam live view resumed; fresh away/nearby and unknown/stale gates passed.', flush=True)
    finally:
        if server:
            if thread: server.shutdown()
            server.server_close()
        if thread: thread.join(timeout=5)
        subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
        print('Production read-only presence relay restored.', flush=True)


if __name__ == '__main__': main()
