#!/usr/bin/env python3
"""Opt-in live voice-filter A/B, mute-safety and CPU-cost check. No recording or forced wake.

Requires an already-nearby, awake viewer, Voice focus and audio on. Leaves Voice focus
and audio on after success. Stops on uncertainty; never automatically replays a tap.
CPU metrics cover the PCM processor, not the entire player or an isolated thermal test.
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
    p.add_argument('--confirm-audible-filter-test', action='store_true')
    p.add_argument('--leave-original', action='store_true', help='For a subsequent saved-choice lifecycle test.')
    args = p.parse_args()
    if ':' in args.serial or not args.confirm_audible_filter_test:
        p.error('USB serial and explicit audible-filter-test confirmation required.')

    def require(ok, message):
        if not ok:
            raise RuntimeError(message)

    def adb(*parts):
        return subprocess.check_output(['adb', '-s', args.serial, *parts], text=True, timeout=20)

    def state():
        return adb('shell', 'dumpsys', 'activity', 'local.jarvis.monitor/.ViewerActivity')

    def value(s, key):
        match = re.search(r'\b'+key+r'=(\d+)', s)
        require(match, 'Missing numeric viewer telemetry.')
        return int(match[1])

    def gate():
        helper = adb('shell', 'dumpsys', 'activity', 'service', 'local.jarvis.monitor/.MonitorService')
        require(all(v in helper for v in ('enabled=true', 'pending=false', 'Connected over Wi-Fi / TLS — nearby')),
                'Enabled, nearby helper with no pending action required.')
        require('mWakefulness=Awake' in adb('shell', 'dumpsys', 'power'), 'Not awake; never force wake.')
        require(any('mResumedActivity:' in l and 'local.jarvis.monitor/.ViewerActivity' in l
                    for l in adb('shell', 'dumpsys', 'activity', 'activities').splitlines()), 'Viewer not foreground.')
        require('resumed=true activePlayer=true' in state(), 'Viewer not active.')

    gate()
    initial = state()
    require('voiceFocus=true voiceSupported=true' in initial and
            'audioAvailable=true audioMuted=false audioFocus=true' in initial, 'Initial Voice focus/audio-on required.')
    opens = value(initial, 'opens')
    with tempfile.TemporaryDirectory(prefix='jarvis-voice-ui-') as directory:
        local = Path(directory)/'ui.xml'
        remote = '/sdcard/'+Path(directory).name+'.xml'

        def tap(description):
            gate(); local.unlink(missing_ok=True); adb('shell', 'rm', '-f', remote)
            require('dumped to:' in adb('shell', 'uiautomator', 'dump', remote), 'Fresh UI unavailable.')
            adb('pull', remote, str(local))
            nodes = [n for n in ET.parse(local).iter('node') if n.get('package') == 'local.jarvis.monitor'
                     and n.get('content-desc') == description and n.get('enabled') == 'true' and n.get('clickable') == 'true']
            require(len(nodes) == 1, 'Expected one accessible control; no guessed tap.')
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', nodes[0].get('bounds')))
            density = re.search(r'(?:Override|Physical) density: (\d+)', adb('shell', 'wm', 'density'))
            require(density and min(x2-x1, y2-y1) >= 48*int(density[1])/160-1, 'Touch target too small.')
            gate(); adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
            time.sleep(.3)

        def verify(focus, muted=False):
            s = state()
            require('voiceFocus='+str(focus).lower()+' voiceSupported=true' in s, 'Filter readback mismatch.')
            require('audioMuted='+str(muted).lower()+' audioFocus='+str(not muted).lower() in s, 'Mute/focus changed unexpectedly.')
            require('audioVolume='+('0.0' if muted else '1.0') in s, 'Volume mismatch.')
            require(value(s, 'opens') == opens and 'retryPending=false' in s, 'Unexpected RTSP restart/retry.')
            return s

        def measure(focus):
            time.sleep(1)  # Finish the 64 ms mode transition before sampling.
            before = verify(focus); time.sleep(20); gate(); after = verify(focus)
            samples = value(after, 'voiceSamples')-value(before, 'voiceSamples')
            cpu = value(after, 'voiceCpuUs')-value(before, 'voiceCpuUs')
            require(samples>80000 and cpu>0, 'PCM processor did not advance.')
            require(value(after, 'displayed')>value(before, 'displayed') and
                    value(after, 'audioRendered')>value(before, 'audioRendered'), 'Audio/video did not advance.')
            percent = cpu/(samples/8000*1000000)*100
            print(f'{"Voice focus" if focus else "Original"}: {percent:.2f}% of one CPU core per audio second; {samples} samples.')
            require(percent<10, 'Processor exceeded conservative live CPU budget; inspect before leaving enabled.')

        try:
            tap('Audio filter: Voice focus; tap to change'); verify(False); measure(False)
            tap('Mute camera audio'); verify(False, True)
            tap('Audio filter: Original; tap to change'); verify(True, True)
            tap('Audio filter: Voice focus; tap to change'); verify(False, True)
            tap('Unmute camera audio'); verify(False)
            tap('Audio filter: Original; tap to change'); verify(True); measure(True)
            if args.leave_original:
                tap('Audio filter: Voice focus; tap to change'); verify(False)
            print('PASS: both modes, muted filter toggles, 48dp targets, continuing PCM/audio/video; no RTSP restart.')
            print('Acoustic quality and physical A/V synchronisation require owner listening/viewing; not measured.')
        finally:
            adb('shell', 'rm', '-f', remote)


if __name__ == '__main__':
    main()
