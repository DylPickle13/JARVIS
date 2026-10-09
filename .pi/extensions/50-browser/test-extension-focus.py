#!/usr/bin/env python3
"""Monitor focus during fixture actions; optional disposable non-automation window."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import tempfile

SCRIPT = '''tell application "System Events" to set a to bundle identifier of first application process whose frontmost is true
tell application "Google Chrome" to return a & ":" & (id of front window as text) & ":" & (id of active tab of front window as text)'''


def applescript(script):
    return subprocess.check_output(['/usr/bin/osascript', '-e', script], text=True, stderr=subprocess.PIPE, timeout=10).strip()


def foreground():
    return applescript(SCRIPT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture-window', action='store_true', help='Use a disposable blank window instead of a personal window')
    parser.add_argument('--spaces', action='store_true', help='Also sample every display\'s active Space using a read-only private macOS API')
    parser.add_argument('--script', choices=['test-extension-live.py','test-multi-session-live.py','test-window-tab-recovery.py','test-action-reliability-live.py','test-verified-recovery-live.py'], default='test-extension-live.py')
    args = parser.parse_args()
    if args.spaces and args.script == 'test-window-tab-recovery.py' and os.environ.get('JARVIS_TEST_BACKGROUND_RECOVERY') != '1':
        parser.error('Space tests require JARVIS_TEST_BACKGROUND_RECOVERY=1; external-tab setup itself may show Chrome')
    if args.script == 'test-action-reliability-live.py' and os.environ.get('JARVIS_TEST_RELIABILITY_MAINTENANCE') != '1':
        parser.error('Reliability live tests require explicit JARVIS_TEST_RELIABILITY_MAINTENANCE=1')
    if args.script == 'test-verified-recovery-live.py' and os.environ.get('JARVIS_TEST_VERIFIED_RECOVERY_MAINTENANCE') != '1':
        parser.error('Verified recovery checks require explicit JARVIS_TEST_VERIFIED_RECOVERY_MAINTENANCE=1')
    original = foreground().split(':')
    sentinel, temporary, space_binary = None, None, None
    def snapshot():
        spaces = subprocess.check_output([str(space_binary)], text=True, timeout=5).strip() if space_binary else ''
        return foreground(), spaces
    try:
        if args.spaces:
            temporary = tempfile.TemporaryDirectory(prefix='jarvis-focus-')
            space_binary = Path(temporary.name)/'space-snapshot'
            subprocess.run(['swiftc',str(Path(__file__).with_name('test-space-snapshot.swift')),'-o',str(space_binary)],check=True,timeout=60)
        if args.fixture_window:
            sentinel = int(applescript('tell application "Google Chrome"\nset w to make new window\nreturn id of w\nend tell'))
        before = snapshot()
        meta = json.loads((Path.home()/'.jarvis/extension-window.json').read_text())
        assert before[0].split(':')[1] != str(meta['windowId']), 'Requires a non-automation Chrome window in front; use --fixture-window'
        if sentinel is not None:
            assert before[0].split(':')[1] == str(sentinel)
        samples, errors, stop = [], [], threading.Event()

        def monitor():
            while not stop.is_set():
                try:
                    samples.append(snapshot())
                except Exception:
                    errors.append('Foreground/Space sample failed')
                stop.wait(.08)

        thread = threading.Thread(target=monitor)
        thread.start()
        try:
            result = subprocess.run(['python3', str(Path(__file__).with_name(args.script))], env={**os.environ, 'JARVIS_TEST_BROWSER_URL': os.environ.get('JARVIS_TEST_BROWSER_URL', 'http://127.0.0.1:17323')})
        finally:
            stop.set()
            thread.join()
        after = snapshot()
        report = Path(__file__).resolve().parents[2]/'runtime/browser-extension-review/focus-last-report.json'
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps({'script':args.script,'returncode':result.returncode,'before':before,'after':after,'samples':samples,'errors':errors},indent=2))
        assert result.returncode == 0, 'Live tests failed'
        assert not errors, errors
        assert samples and all(sample == before for sample in samples), 'Foreground or active Space changed during test'
        assert after == before, 'Foreground or active Space changed after test'
        extra = ' and every display\'s active Space' if args.spaces else ''
        print(f'PASS: foreground app, non-automation window/tab{extra} unchanged across {len(samples)} samples')
    finally:
        if temporary is not None:
            temporary.cleanup()
        if sentinel is not None:
            applescript(f'''tell application "Google Chrome"
              close (first window whose id is {sentinel})
              try
                set index of (first window whose id is {int(original[1])}) to 1
              end try
            end tell''')
            # Restore an app activated by creating the fixture window, but never
            # override a different app the user switched to during the test.
            if foreground().split(':')[0] == 'com.google.Chrome' and original[0] != 'com.google.Chrome':
                subprocess.run(['/usr/bin/osascript', '-e', 'on run argv\ntell application id (item 1 of argv) to activate\nend run', '--', original[0]], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    main()
