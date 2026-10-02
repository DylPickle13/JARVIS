"""Bounded LG-only local-recording proof; run explicitly on mac-mini-16.
Does not transfer/delete clips. Unknown recording state requires manual inspection.
"""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import datetime
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET
from inventory import DEFAULT_ADB

SERIAL = 'LGH873bb5b4b79'
UI = '/sdcard/opencamera-proof-ui.xml'


def adb(*args):
    return subprocess.check_output([DEFAULT_ADB, '-s', SERIAL, *args], text=True, timeout=15)


def state():
    # Retry observations only: LG accessibility sometimes returns a null root.
    # Never retry the recording toggle based on a failed observation.
    for attempt in range(3):
        try:
            adb('shell', 'rm', '-f', UI)
            adb('shell', 'uiautomator', 'dump', UI)
            root = ET.fromstring(adb('shell', 'cat', UI))
            for n in root.iter('node'):
                if n.get('resource-id') == 'net.sourceforge.opencamera:id/take_photo':
                    return n.get('content-desc')
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ET.ParseError):
            pass
        if attempt < 2:
            time.sleep(0.5)
    return 'unknown'


def clips():
    # Only this app's output directory, not the personal camera roll.
    result = subprocess.run([DEFAULT_ADB, '-s', SERIAL, 'shell', 'ls', '-1', '/sdcard/DCIM/OpenCamera'], capture_output=True, text=True, timeout=15)
    if result.returncode and 'No such file or directory' not in result.stderr + result.stdout:
        raise RuntimeError('Cannot inspect app output directory')
    return sorted(n for n in result.stdout.splitlines() if n.endswith('.mp4') and '/' not in n)


def main():
    log = {'host_start': datetime.datetime.now().astimezone().isoformat(), 'before': clips()}
    assert state() == 'Start recording video', 'Phone is not verified idle in video mode'
    start = time.monotonic()
    attempted = False
    try:
        attempted = True
        adb('shell', 'input', 'keyevent', 'KEYCODE_VOLUME_UP')
        log['after_start'] = state()
        assert log['after_start'] == 'Stop recording video', 'Start unverified; no blind retry'
        print('CONFIRMED RECORDING', log['host_start'], flush=True)
        time.sleep(max(0, 120 - (time.monotonic() - start)))
    finally:
        if attempted:
            current = state()
            if current == 'Stop recording video':
                adb('shell', 'input', 'keyevent', 'KEYCODE_VOLUME_UP')
                current = state()
            log['final_state'] = current
            log['host_stop'] = datetime.datetime.now().astimezone().isoformat()
            log['new_clips'] = sorted(set(clips()) - set(log['before']))
            p = Path.home() / 'phone-recording/lg-usb-test-result.json'
            p.write_text(json.dumps(log, indent=2))
            print(json.dumps(log, indent=2), flush=True)
            assert current == 'Start recording video', 'Stop unverified: inspect phone manually'


if __name__ == '__main__':
    main()
