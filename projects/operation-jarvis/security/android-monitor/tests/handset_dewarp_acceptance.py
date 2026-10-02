#!/usr/bin/env python3
"""Opt-in foreground lens test. Never wakes/unlocks or changes presence/camera settings.

Cycles all lens modes, requires advancing GPU/video/audio counters without RTSP
restart, and leaves the chosen mode. Optional screenshots stay in a private directory
outside the repository; they contain camera imagery, not public test fixtures.
"""
import argparse
from pathlib import Path
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

MODES = ('original', 'mild', 'medium', 'strong')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--confirm-viewer-and-audible-test', action='store_true')
    p.add_argument('--leave-mode', choices=MODES, default='original')
    p.add_argument('--capture-dir', type=Path)
    args = p.parse_args()
    if not args.confirm_viewer_and_audible_test:
        p.error('Explicit viewer/audible-test confirmation required.')
    os.umask(0o077)
    if args.capture_dir:
        root = Path(__file__).resolve().parents[5]
        destination = args.capture_dir.resolve()
        if destination == root or root in destination.parents:
            p.error('Camera screenshots must remain outside the repository.')
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        if any((destination / (mode+'.png')).exists() for mode in MODES):
            p.error('Capture directory already has test images; refusing overwrite.')

    def adb(*parts, binary=False):
        r = subprocess.run(['adb', '-s', args.serial, *parts], capture_output=True,
                           text=not binary, timeout=20)
        if r.returncode:
            raise RuntimeError('ADB operation failed; do not replay uncertain actions.')
        return r.stdout

    def require(ok, message):
        if not ok:
            raise RuntimeError(message)

    def state():
        text = adb('shell', 'dumpsys', 'activity', 'local.jarvis.monitor/.ViewerActivity')
        require('resumed=true activePlayer=true' in text and 'glActive=true' in text,
                'Active foreground GPU viewer required.')
        require('audioAvailable=true audioMuted=false audioFocus=true' in text,
                'Expected owner-selected audio-on default.')
        match = re.search(r'viewer lens=(\w+) lensFallback=false', text)
        require(match and match[1] in MODES, 'No healthy lens telemetry.')
        result = {'mode': match[1]}
        for key in ('opens', 'releases', 'displayed', 'glFrames', 'audioRendered'):
            value = re.search(r'\b'+key+r'=(\d+)', text)
            require(value, 'Missing numeric telemetry.')
            result[key] = int(value[1])
        return result

    def gate():
        require('mWakefulness=Awake' in adb('shell', 'dumpsys', 'power'), 'Phone must already be awake.')
        service = adb('shell', 'dumpsys', 'activity', 'service', 'local.jarvis.monitor/.MonitorService')
        require(all(v in service for v in ('enabled=true', 'pending=false', 'Connected over Wi-Fi / TLS — nearby')),
                'Enabled nearby helper with no pending action required.')
        lines = adb('shell', 'dumpsys', 'activity', 'activities').splitlines()
        require(any('mResumedActivity:' in line and 'local.jarvis.monitor/.ViewerActivity' in line for line in lines),
                'Viewer must remain foreground.')

    gate()
    initial = state()
    densities = re.findall(r'(?:Physical|Override) density: (\d+)', adb('shell', 'wm', 'density'))
    require(densities, 'Display density unavailable.')
    target_pixels = round(48 * int(densities[-1]) / 160)
    with tempfile.TemporaryDirectory(prefix='jarvis-dewarp-ui-') as folder:
        remote = '/sdcard/' + Path(folder).name + '.xml'
        local = Path(folder) / 'ui.xml'

        def tap_next():
            gate()
            before = state()
            local.unlink(missing_ok=True)
            adb('shell', 'rm', '-f', remote)
            require('dumped to:' in adb('shell', 'uiautomator', 'dump', remote), 'Fresh UI tree required.')
            adb('pull', remote, str(local))
            button = next((n for n in ET.parse(local).iter('node')
                           if n.get('content-desc') == 'Lens correction: '+before['mode']+'; tap to change' and
                           n.get('package') == 'local.jarvis.monitor'), None)
            require(button is not None and button.get('enabled') == 'true', 'Lens button unavailable.')
            require(button.get('class') == 'android.widget.ImageButton' and not button.get('text'),
                    'Expected a compact icon, not a labelled text button.')
            gate()
            x1,y1,x2,y2 = map(int, re.findall(r'\d+', button.get('bounds')))
            require(abs(x2-x1-target_pixels) <= 1 and abs(y2-y1-target_pixels) <= 1,
                    'Icon must retain its 48dp square touch target.')
            adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
            time.sleep(2.5)
            after = state()
            require(after['mode'] == MODES[(MODES.index(before['mode'])+1) % len(MODES)], 'Lens did not change once.')
            require(all(after[k] == initial[k] for k in ('opens','releases')), 'Lens toggle restarted playback.')
            require(all(after[k] > before[k] for k in ('displayed','glFrames','audioRendered')), 'Playback counters stalled.')

        try:
            for _ in MODES:
                gate()
                before = state()
                time.sleep(3)
                after = state()
                require(all(after[k] > before[k] for k in ('displayed','glFrames','audioRendered')), 'Counters stalled.')
                if args.capture_dir:
                    gate()
                    (destination / (after['mode']+'.png')).write_bytes(adb('exec-out', 'screencap', '-p', binary=True))
                print(f"PASS: {after['mode']}, GPU frames {before['glFrames']}->{after['glFrames']}, no restart.")
                tap_next()
            for _ in MODES:
                if state()['mode'] == args.leave_mode:
                    break
                tap_next()
            require(state()['mode'] == args.leave_mode, 'Final lens choice was not applied.')
            print('Left lens mode:', args.leave_mode)
            print('Geometry/visual quality and acoustic output require separate inspection.')
        finally:
            adb('shell', 'rm', '-f', remote)


if __name__ == '__main__':
    main()
