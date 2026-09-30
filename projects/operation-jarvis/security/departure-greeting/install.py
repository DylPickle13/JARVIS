"""Explicit install of the departure trial only. No immediate playback/test."""
import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import wave

import departure
import person_gate
import runtime
import security_audio as audio

LABEL = 'com.jarvis.departure-greeting'


def install():
    parser = argparse.ArgumentParser(description='Install outdoor departure trial; no immediate speech.')
    parser.add_argument('--enable-trial', action='store_true', required=True)
    parser.add_argument('--confirm', action='store_true', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root = runtime.private_dir(runtime.ROOT)
    plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    if plist.exists() or (root / 'config.json').exists() or (root / 'state.json').exists():
        raise runtime.TrialError('existing_installation_requires_review')
    interpreter = departure.SECURITY_ROOT / '.venv-313/bin/python'
    voice_python = departure.SECURITY_ROOT.parent / '.venv/bin/python'
    ffmpeg = shutil.which('ffmpeg')
    if (not interpreter.is_file() or not voice_python.is_file() or not ffmpeg
            or not (audio.APP / 'Contents/MacOS/go2rtc').is_file()):
        raise runtime.TrialError('trial_dependency_unavailable')
    opts = departure.parser().parse_args(['observe'])
    entries = departure.validate_devices(opts, departure.cli)
    devices = departure.cli.registry(opts.registry)
    bell = devices.get('front-doorbell')
    if (not bell or bell.get('model') != 'D235' or not bell.get('host')
            or bell.get('hub') != entries[0]):
        raise runtime.TrialError('outdoor_doorbell_required')
    # Offline synthesis only: cached model; never contacts/plays on a camera.
    text = root / 'phrase.txt'
    text.write_text(runtime.PHRASE, encoding='utf-8')
    try:
        result = subprocess.run([str(voice_python), str(departure.SECURITY_ROOT / 'security_tts.py'),
            str(text), str(root / 'phrase.wav')], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=45)
    finally:
        text.unlink(missing_ok=True)
    if result.returncode:
        raise runtime.TrialError('cached_voice_unavailable')
    with wave.open(str(root / 'phrase.wav')) as wav:
        seconds = wav.getnframes() / wav.getframerate()
    if not 0 < seconds <= 4.5:
        raise runtime.TrialError('phrase_duration_invalid')
    runtime.save_json(root / 'phrase.json', {'phrase': runtime.PHRASE,
        'sha256': hashlib.sha256((root / 'phrase.wav').read_bytes()).hexdigest(),
        'seconds': seconds})
    runtime.save_json(root / 'config.json', {'version': 1, 'enabled': True,
        'motion_device': 'motion-sensor', 'door_device': 'door-sensor',
        'speaker_device': 'front-doorbell', 'volume': 60})
    runtime.save_json(root / 'state.json', runtime.default_state())
    runtime.save_json(root / 'person-gate.json', person_gate.default_policy())
    spec = {'Label': LABEL,
        'ProgramArguments': [str(interpreter), str(Path(__file__).with_name('watcher.py').resolve())],
        'WorkingDirectory': str(Path(__file__).resolve().parent),
        'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 30,
        'LimitLoadToSessionType': 'Aqua', 'Umask': 63,
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StandardOutPath': str(root / 'watcher.log'),
        'StandardErrorPath': str(root / 'watcher-error.log')}
    plist.parent.mkdir(parents=True, exist_ok=True)
    with plist.open('xb') as output:
        plistlib.dump(spec, output)
    result = subprocess.run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(plist)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        # Do not leave a failing installation claiming delivery is enabled.
        value = runtime.config(root)
        value['enabled'] = False
        runtime.save_json(root / 'config.json', value)
        raise runtime.TrialError('trial_bootstrap_failed')
    print('Departure trial installed; mandatory person-event commissioning required before speech. No immediate speech sent.')


if __name__ == '__main__':
    try:
        install()
    except Exception:
        print('Departure trial installation failed; inspect private state before retrying.', file=sys.stderr)
        raise SystemExit(2)
