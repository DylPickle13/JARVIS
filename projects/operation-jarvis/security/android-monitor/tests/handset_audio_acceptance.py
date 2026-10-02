#!/usr/bin/env python3
"""Opt-in brief listen/mute check on an already-awake, nearby native viewer.

Optional --confirm-lifecycle-test also backgrounds playback into its own helper
and reopens it to verify the owner's audio-on default. Never wakes the phone, changes system
volume, opens another app, records media,
changes presence, or unmutes without --confirm-audible-test. Ends muted unless
--leave-audio-on is explicitly supplied. Rendering
counters are not proof of acoustic output; the owner must verify audibility.
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
    p.add_argument('--confirm-audible-test', action='store_true')
    p.add_argument('--confirm-lifecycle-test', action='store_true')
    p.add_argument('--leave-audio-on', action='store_true')
    args = p.parse_args()
    if not args.confirm_audible_test:
        p.error('Explicit audible-test confirmation required.')
    if ':' in args.serial:
        p.error('Authorized USB ADB required.')

    def adb(*parts):
        r = subprocess.run(['adb', '-s', args.serial, *parts], capture_output=True, text=True, timeout=15)
        if r.returncode:
            raise RuntimeError('ADB operation failed; inspect before retrying.')
        return r.stdout

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def state():
        return adb('shell', 'dumpsys', 'activity', 'local.jarvis.monitor/.ViewerActivity')

    def eligible(require_nearby=True):
        if require_nearby:
            service = adb('shell', 'dumpsys', 'activity', 'service', 'local.jarvis.monitor/.MonitorService')
            require(all(s in service for s in ('enabled=true', 'pending=false', 'nativePlayer=true',
                                              'Connected over Wi-Fi / TLS — nearby')),
                    'Enabled helper, nearby status and no pending action required; no forced wake.')
        require('mWakefulness=Awake' in adb('shell', 'dumpsys', 'power'), 'Phone is not awake.')
        require('resumed=true activePlayer=true' in state(), 'Viewer is not foreground/active.')
        activities = adb('shell', 'dumpsys', 'activity', 'activities')
        require(any('mResumedActivity:' in line and 'local.jarvis.monitor/.ViewerActivity' in line
                    for line in activities.splitlines()), 'Another activity is foreground; refusing taps.')

    def value(text, name):
        m = re.search(r'\b' + re.escape(name) + r'=(\d+)', text)
        require(m is not None, 'Missing numeric player telemetry.')
        return int(m[1])

    eligible()
    initial = state()
    require('audioAvailable=true audioMuted=false audioFocus=true' in initial and 'audioVolume=1.0' in initial,
            'A supported audio track playing by default is required.')
    with tempfile.TemporaryDirectory(prefix='jarvis-audio-acceptance-') as directory:
        remote = '/sdcard/' + Path(directory).name + '.xml'
        local = Path(directory) / 'ui.xml'

        def tap(description):
            require_nearby = description == 'Unmute camera audio'
            eligible(require_nearby)
            local.unlink(missing_ok=True)
            adb('shell', 'rm', '-f', remote)
            require('dumped to:' in adb('shell', 'uiautomator', 'dump', remote), 'No fresh UI hierarchy.')
            adb('pull', remote, str(local))
            matches = [n for n in ET.parse(local).iter('node')
                       if n.get('package') == 'local.jarvis.monitor' and n.get('content-desc') == description
                       and n.get('enabled') == 'true' and n.get('clickable') == 'true']
            require(len(matches) == 1, 'Expected exactly one enabled audio button.')
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', matches[0].get('bounds')))
            eligible(require_nearby)  # Recheck after UI collection, not only before it.
            adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))

        try:
            tap('Mute camera audio')
            require('audioMuted=true audioFocus=false' in state(), 'Initial mute did not release focus.')
            tap('Unmute camera audio')
            time.sleep(1)
            listening = state()
            require('audioAvailable=true audioMuted=false audioFocus=true' in listening,
                    'Audio did not enter explicit listening mode.')
            require('audioVolume=1.0' in listening, 'Player volume was not enabled.')
            time.sleep(4)
            advancing = state()
            require(value(advancing, 'audioRendered') > value(listening, 'audioRendered'),
                    'Audio output buffers did not advance.')
            require(value(advancing, 'displayed') > value(listening, 'displayed'),
                    'Video frames did not advance while listening.')
            require(value(advancing, 'opens') == value(initial, 'opens'), 'Unmute restarted the RTSP session.')
            tap('Mute camera audio')
            time.sleep(1)
            muted = state()
            require('audioMuted=true audioFocus=false' in muted and 'audioVolume=0.0' in muted,
                    'Mute did not silence the player and release focus.')
            require(value(muted, 'opens') == value(initial, 'opens'), 'Mute restarted the RTSP session.')
            print('PASS: explicit unmute, audio/video counters advance, mute releases focus; no RTSP restart.')
            if args.confirm_lifecycle_test:
                tap('Unmute camera audio')
                require('audioMuted=false audioFocus=true' in state(), 'No listening consent to reset.')
                eligible()
                adb('shell', 'am', 'start', '-n', 'local.jarvis.monitor/.MainActivity')
                time.sleep(1)
                paused = state()
                require('resumed=false activePlayer=false' in paused and
                        'audioMuted=true audioFocus=false' in paused and 'audioVolume=0.0' in paused,
                        'Backgrounding did not release player, consent and focus.')
                require(value(paused, 'opens') == value(paused, 'releases'), 'Player resource imbalance.')
                local.unlink(missing_ok=True)
                adb('shell', 'rm', '-f', remote)
                require('dumped to:' in adb('shell', 'uiautomator', 'dump', remote), 'No fresh helper UI.')
                adb('pull', remote, str(local))
                def open_buttons():
                    return [n for n in ET.parse(local).iter('node')
                            if n.get('package') == 'local.jarvis.monitor' and
                            n.get('text') == 'Open camera viewer' and n.get('enabled') == 'true']
                buttons = open_buttons()
                if not buttons:
                    scrolls = [n for n in ET.parse(local).iter('node')
                               if n.get('package') == 'local.jarvis.monitor' and
                               n.get('class') == 'android.widget.ScrollView']
                    require(len(scrolls) == 1, 'Helper scroll view unavailable.')
                    x1, y1, x2, y2 = map(int, re.findall(r'\d+', scrolls[0].get('bounds')))
                    adb('shell', 'input', 'swipe', str((x1+x2)//2), str(y2-160),
                        str((x1+x2)//2), str(y1+220), '500')
                    time.sleep(1)
                    local.unlink(missing_ok=True)
                    adb('shell', 'rm', '-f', remote)
                    require('dumped to:' in adb('shell', 'uiautomator', 'dump', remote), 'No fresh scrolled UI.')
                    adb('pull', remote, str(local))
                    buttons = open_buttons()
                require(len(buttons) == 1, 'Helper Open button unavailable; refusing guessed tap.')
                activities = adb('shell', 'dumpsys', 'activity', 'activities')
                require(any('mResumedActivity:' in line and 'local.jarvis.monitor/.MainActivity' in line
                            for line in activities.splitlines()), 'Helper no longer foreground.')
                service = adb('shell', 'dumpsys', 'activity', 'service', 'local.jarvis.monitor/.MonitorService')
                require('Connected over Wi-Fi / TLS — nearby' in service and 'pending=false' in service,
                        'No nearby status; leaving playback paused.')
                require('mWakefulness=Awake' in adb('shell', 'dumpsys', 'power'), 'Phone slept; no forced wake.')
                x1, y1, x2, y2 = map(int, re.findall(r'\d+', buttons[0].get('bounds')))
                adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
                time.sleep(6)
                returned = state()
                require('resumed=true activePlayer=true' in returned and
                        'audioMuted=false audioFocus=true' in returned and 'audioVolume=1.0' in returned,
                        'Returning viewer did not restore the audio-on default.')
                require(value(returned, 'displayed') > 0, 'No rendered video after return.')
                print('PASS: leaving releases audio/player; returning defaults to audio on.')
            print('Acoustic output is not measured; owner listening confirmation remains separate.')
        finally:
            # Read after any uncertain operation. Never blindly repeat a toggle.
            try:
                current = state()
                if args.leave_audio_on:
                    if 'resumed=true activePlayer=true' in current and 'audioMuted=true' in current:
                        tap('Unmute camera audio')  # Still requires nearby/foreground; never forces wake.
                        require('audioMuted=false audioFocus=true' in state(), 'Could not verify final audio-on.')
                elif 'audioMuted=false' in current:
                    tap('Mute camera audio')
                    require('audioMuted=true audioFocus=false' in state(), 'Could not verify final mute.')
            finally:
                adb('shell', 'rm', '-f', remote)


if __name__ == '__main__':
    main()
