#!/usr/bin/env python3
"""Opt-in native viewer lifecycle/sleep-wake test; no presence or camera changes.

Leaves the viewer playing with audio on for observation; explicit audible-test
confirmation is required for the v1.6.1 default. With --confirm-temporary-wake the owner
explicitly permits the built-in phone-only screen test even when presence is away.
Otherwise fresh nearby status is required. Never acknowledges pending errors.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--confirm-phone-viewer-test', action='store_true')
    p.add_argument('--confirm-audible-test', action='store_true')
    p.add_argument('--confirm-temporary-wake', action='store_true')
    p.add_argument('--cycles', type=int, choices=range(1, 6), default=3)
    args = p.parse_args()
    if not args.confirm_phone_viewer_test or not args.confirm_audible_test:
        p.error('Explicit phone-test and audible-test confirmation required.')

    def adb(*parts):
        r = subprocess.run(['adb', '-s', args.serial, *parts], capture_output=True, text=True, timeout=15)
        if r.returncode:
            raise RuntimeError('ADB test operation failed; do not replay uncertain actions.')
        return r.stdout

    def require(ok, message):
        if not ok:
            raise RuntimeError(message)

    def viewer():
        return adb('shell', 'dumpsys', 'activity', 'local.jarvis.monitor/.ViewerActivity')

    def frames():
        match = re.search(r'viewer decoded=\d+ displayed=(\d+)', viewer())
        require(match, 'No player frame telemetry.')
        return int(match[1])

    lens = re.search(r'viewer lens=(\w+) lensFallback=false glActive=true', viewer())
    require(lens, 'Active GPU viewer required for lens lifecycle acceptance.')
    expected_lens = lens[1]
    voice = re.search(r'viewer voiceFocus=(true|false) voiceSupported=true', viewer())
    expected_voice = voice[1] if voice else None

    require(re.search(r'(?:AC|USB|Wireless) powered: true', adb('shell', 'dumpsys', 'battery')),
            'External power required.')
    with tempfile.TemporaryDirectory(prefix='jarvis-viewer-acceptance-') as directory:
        remote = '/sdcard/' + Path(directory).name + '.xml'
        local = Path(directory) / 'ui.xml'

        def hierarchy():
            local.unlink(missing_ok=True)
            adb('shell', 'rm', '-f', remote)
            require('dumped to:' in adb('shell', 'uiautomator', 'dump', remote), 'No fresh UI tree.')
            adb('pull', remote, str(local))
            return list(ET.parse(local).iter('node'))

        try:
            for cycle in range(1, args.cycles + 1):
                service = adb('shell', 'dumpsys', 'activity', 'service', 'local.jarvis.monitor/.MonitorService')
                # The 15-second self-test hold can outlast frame/UI checks. Only
                # wait for that explicit status to clear; never bypass an away/error gate.
                for _ in range(10):
                    if 'status=Screen test: sleep, then wake after 8 seconds' not in service:
                        break
                    time.sleep(1)
                    service = adb('shell', 'dumpsys', 'activity', 'service', 'local.jarvis.monitor/.MonitorService')
                require('enabled=true' in service and 'pending=false' in service and 'nativePlayer=true' in service,
                        'Enabled native helper with no pending action is required.')
                require(args.confirm_temporary_wake or 'Connected over Wi-Fi / TLS — nearby' in service,
                        'Fresh nearby status required unless temporary test wake is explicitly confirmed.')
                if args.confirm_temporary_wake:
                    adb('shell', 'input', 'keyevent', '224')
                else:
                    require('mWakefulness=Awake' in adb('shell', 'dumpsys', 'power'),
                            'Already-awake handset required; no forced wake.')
                adb('shell', 'am', 'start', '-n', 'local.jarvis.monitor/.MainActivity')
                time.sleep(1)
                state = viewer()
                require('activePlayer=false' in state, 'Player did not release when backgrounded.')
                require('glActive=false glFrames=0' in state, 'GPU resources retained when backgrounded.')
                if expected_voice is not None:
                    require('voiceSupported=false voiceSamples=0 voiceOutput=0 voiceCpuUs=0' in state,
                            'Backgrounding retained the voice processor.')
                require('audioMuted=true audioFocus=false' in state and 'audioVolume=0.0' in state,
                        'Backgrounded viewer retained audio consent/focus/volume.')
                counts = re.search(r'viewer opens=(\d+) releases=(\d+)', state)
                require(counts and counts[1] == counts[2], 'Playback resources not fully released.')
                nodes = hierarchy()
                label = 'Test: sleep then wake in 8 seconds'
                button = next((n for n in nodes if n.get('text') == label), None)
                if button is None:
                    scroll = next(n for n in nodes if n.get('class') == 'android.widget.ScrollView')
                    x1, y1, x2, y2 = map(int, re.findall(r'\d+', scroll.get('bounds')))
                    x = (x1+x2)//2
                    adb('shell', 'input', 'swipe', str(x), str(y2-160), str(x), str(y1+220), '500')
                    time.sleep(1)
                    button = next((n for n in hierarchy() if n.get('text') == label), None)
                require(button is not None and button.get('enabled') == 'true', 'Screen-test button unavailable.')
                x1,y1,x2,y2 = map(int,re.findall(r'\d+',button.get('bounds')))
                adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
                time.sleep(2)
                require('mWakefulness=Asleep' in adb('shell','dumpsys','power'), 'Screen did not sleep.')
                time.sleep(10)
                require('mWakefulness=Awake' in adb('shell','dumpsys','power'), 'Screen did not automatically wake.')
                lines = adb('shell','dumpsys','activity','activities').splitlines()
                count = sum(l.count('local.jarvis.monitor/.ViewerActivity') for l in lines if 'Activities=[' in l)
                require(count == 1, 'Expected exactly one native viewer activity.')
                gpu_first = re.search(r'glFrames=(\d+)', viewer())
                require(gpu_first, 'No GPU frame telemetry after wake.')
                first = frames(); time.sleep(3); second = frames()
                current = viewer()
                require('viewer lens='+expected_lens+' lensFallback=false glActive=true' in current,
                        'Lens choice/GPU rendering did not survive sleep/wake.')
                if expected_voice is not None:
                    require('viewer voiceFocus='+expected_voice+' voiceSupported=true' in current,
                            'Saved audio filter choice did not survive sleep/wake.')
                    require(int(re.search(r'voiceSamples=(\d+)', current)[1]) > 0,
                            'Voice processor did not resume consuming PCM.')
                gpu_second = re.search(r'glFrames=(\d+)', current)
                require(gpu_second and int(gpu_second[1]) > int(gpu_first[1]) > 0,
                        'GPU frames did not advance after wake.')
                require(second > first > 0, 'Rendered frames did not advance after wake.')
                require('audioAvailable=true audioMuted=false audioFocus=true' in viewer(),
                        'Wake did not restore the audio-on default.')
                print(f'Cycle {cycle}: released player/GPU, slept, auto-woke, lens={expected_lens}, frames {first}->{second}.')
        finally:
            adb('shell', 'rm', '-f', remote)


if __name__ == '__main__':
    main()
