#!/usr/bin/env python3
"""Monitor focus during fixture actions; optional disposable non-automation window."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading

SCRIPT = '''tell application "System Events" to set a to bundle identifier of first application process whose frontmost is true
tell application "Google Chrome" to return a & ":" & (id of front window as text) & ":" & (id of active tab of front window as text)'''


def applescript(script):
    return subprocess.check_output(['/usr/bin/osascript', '-e', script], text=True, stderr=subprocess.PIPE, timeout=10).strip()


def foreground():
    return applescript(SCRIPT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture-window', action='store_true', help='Use a disposable blank window instead of a personal window')
    args = parser.parse_args()
    original = foreground().split(':')
    sentinel = None
    try:
        if args.fixture_window:
            sentinel = int(applescript('tell application "Google Chrome"\nset w to make new window\nreturn id of w\nend tell'))
        before = foreground()
        meta = json.loads((Path.home()/'.jarvis/extension-window.json').read_text())
        assert before.split(':')[1] != str(meta['windowId']), 'Requires a non-automation Chrome window in front; use --fixture-window'
        if sentinel is not None:
            assert before.split(':')[1] == str(sentinel)
        samples, errors, stop = [], [], threading.Event()

        def monitor():
            while not stop.is_set():
                try:
                    samples.append(foreground())
                except Exception:
                    errors.append('Foreground sample failed')
                stop.wait(.08)

        thread = threading.Thread(target=monitor)
        thread.start()
        try:
            result = subprocess.run(['python3', str(Path(__file__).with_name('test-extension-live.py'))], env={**os.environ, 'JARVIS_TEST_BROWSER_URL': os.environ.get('JARVIS_TEST_BROWSER_URL', 'http://127.0.0.1:17323')})
        finally:
            stop.set()
            thread.join()
        assert result.returncode == 0, 'Live tests failed'
        assert not errors, errors
        assert samples and all(sample == before for sample in samples), 'Foreground changed during test'
        assert foreground() == before, 'Foreground changed after test'
        print(f'PASS: foreground app, non-automation window and selected tab unchanged across {len(samples)} samples')
    finally:
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
