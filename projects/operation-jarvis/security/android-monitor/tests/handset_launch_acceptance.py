#!/usr/bin/env python3
"""Opt-in, phone-only sleep/wake and tinyCam task-reuse regression test.

Does not change presence, pairing, enabled preferences, camera settings, or host
services. Requires the enabled helper, external power, fresh nearby status, and
an existing single tinyCam live-view activity. Video liveness is checked separately.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--confirm-phone-screen-test', action='store_true')
    parser.add_argument('--cycles', type=int, choices=range(1, 6), default=2)
    args = parser.parse_args()
    if not args.confirm_phone_screen_test:
        parser.error('Explicit --confirm-phone-screen-test is required.')

    def adb(*parts):
        result = subprocess.run(['adb', '-s', args.serial, *parts],
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError('ADB operation failed; do not replay a screen action.')
        return result.stdout

    def live_views():
        lines = adb('shell', 'dumpsys', 'activity', 'activities').splitlines()
        return sum(line.count('com.alexvas.dvr/.activity.LiveViewActivity')
                   for line in lines if 'Activities=[' in line)

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    battery = adb('shell', 'dumpsys', 'battery')
    require(re.search(r'(?:AC|USB|Wireless) powered: true', battery),
            'External power is required.')
    require(live_views() == 1, 'Start with exactly one tinyCam live-view activity.')

    with tempfile.TemporaryDirectory(prefix='jarvis-launch-acceptance-') as directory:
        remote = '/sdcard/' + Path(directory).name + '.xml'
        local = Path(directory) / 'ui.xml'

        def hierarchy():
            # Never reuse a previous successful dump after a null/idle error.
            local.unlink(missing_ok=True)
            adb('shell', 'rm', '-f', remote)
            output = adb('shell', 'uiautomator', 'dump', remote)
            require('dumped to:' in output, 'No fresh UI hierarchy; test stopped.')
            adb('pull', remote, str(local))
            return list(ET.parse(local).iter('node'))

        def bounds(node):
            numbers = list(map(int, re.findall(r'\d+', node.get('bounds', ''))))
            require(len(numbers) == 4, 'UI bounds are unavailable.')
            return numbers

        try:
            for cycle in range(1, args.cycles + 1):
                adb('shell', 'input', 'keyevent', '224')
                adb('shell', 'am', 'start', '-n', 'local.jarvis.monitor/.MainActivity')
                time.sleep(1)
                nodes = hierarchy()
                status = next((n.get('text', '') for n in nodes
                               if n.get('text', '').startswith('Enabled\n')), '')
                require('Connected over Wi-Fi / TLS — nearby' in status
                        and 'interrupted action' not in status,
                        'Fresh nearby status and no pending-action error are required.')
                label = 'Test: sleep then wake in 8 seconds'
                button = next((n for n in nodes if n.get('text') == label), None)
                if button is None:
                    scroll = next((n for n in nodes
                                   if n.get('class') == 'android.widget.ScrollView'), None)
                    require(scroll is not None, 'Helper scroll view unavailable.')
                    x1, y1, x2, y2 = bounds(scroll)
                    x = (x1 + x2) // 2
                    adb('shell', 'input', 'swipe', str(x), str(y2 - 160),
                        str(x), str(y1 + 220), '500')
                    time.sleep(1)
                    button = next((n for n in hierarchy() if n.get('text') == label), None)
                require(button is not None and button.get('enabled') == 'true',
                        'Sleep/wake test button is unavailable.')
                x1, y1, x2, y2 = bounds(button)
                # Exactly one action dispatch. An uncertain result stops the test.
                adb('shell', 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
                time.sleep(2)
                require('mWakefulness=Asleep' in adb('shell', 'dumpsys', 'power'),
                        'Phone did not enter sleep.')
                time.sleep(9)
                require('mWakefulness=Awake' in adb('shell', 'dumpsys', 'power'),
                        'Phone did not automatically wake.')
                require('com.alexvas.dvr/com.alexvas.dvr.activity.LiveViewActivity'
                        in adb('shell', 'dumpsys', 'window'), 'tinyCam did not regain focus.')
                require(live_views() == 1, 'Wake stacked another tinyCam live-view activity.')
                print(f'Cycle {cycle}: slept, automatically woke, reused one live view.')
        finally:
            adb('shell', 'rm', '-f', remote)


if __name__ == '__main__':
    main()
