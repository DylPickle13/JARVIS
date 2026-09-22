#!/usr/bin/env python3
"""Offline verification entry point. Never installs, deploys, or runs live tests.

Existing interpreters only. Missing dependencies fail explicitly. Swift package
checks are optional and do not regenerate the Xcode project or install an app.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('backend', 'plugs', 'security', 'voice', 'presence', 'audio', 'sdk', 'swift')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', action='append', choices=SUITES)
    parser.add_argument('--python', type=Path, default=ROOT / '.venv/bin/python')
    parser.add_argument('--kasa-python', type=Path, default=ROOT / 'smart-plug/.venv/bin/python')
    parser.add_argument('--security-python', type=Path, default=ROOT / 'security/.venv-313/bin/python')
    parser.add_argument('--vesync-python', type=Path, default=ROOT / 'air-purifier/.venv/bin/python')
    args = parser.parse_args()
    python = str(args.python.absolute())
    kasa = str(args.kasa_python.absolute())
    security = str(args.security_python.absolute())
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'JARVIS_LIVE_TESTS': '0',
           'PYTHON': python, 'JARVIS_TEST_KASA_PYTHON': kasa,
           'JARVIS_TEST_VESYNC_PYTHON': str(args.vesync_python.absolute()),
           'JARVIS_TEST_VENDOR_ROOT': str(ROOT)}
    with tempfile.TemporaryDirectory(prefix='jarvis-offline-') as scratch:
        jobs = {
            'backend': (['bash', 'verify.sh'], ROOT / 'jarvisd'),
            'plugs': ([kasa, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], ROOT / 'smart-plug'),
            'security': ([security, '-B', '-m', 'unittest', 'test_read_recovery', 'test_security_cli', '-v'], ROOT / 'security'),
            'voice': ([python, '-B', '-m', 'unittest', 'discover', '-p', 'test_*.py', '-v'], ROOT / 'voice'),
            'presence': ([python, '-B', '-m', 'unittest', 'test_presence', 'test_pi_presence', '-v'], ROOT / 'presence'),
            'audio': ([python, '-B', '-m', 'unittest', 'test_source_layout', 'test_shared_room_session', 'test_shared_room_wake', '-v'], ROOT / 'room-audio'),
            'sdk': (['bash', '-c', 'bash verify-kasa-sdk.sh && bash verify-vesync-sdk.sh && bash verify-delegation-sdk.sh'], ROOT / 'jarvisd'),
            'swift': (['swift', 'test', '--scratch-path', scratch + '/swift'], ROOT / 'jarvis-app/JARVISKit'),
        }
        failed = []
        for suite in args.suite or SUITES[:-1]:
            command, cwd = jobs[suite]
            print(f'\n=== {suite} (offline) ===', flush=True)
            try:
                result = subprocess.run(command, cwd=cwd, env=env, timeout=600)
                if result.returncode:
                    failed.append(suite)
            except (OSError, subprocess.TimeoutExpired):
                print(f'{suite}: interpreter/dependency unavailable or deadline exceeded', flush=True)
                failed.append(suite)
        if failed:
            print('FAILED: ' + ', '.join(failed))
            return 1
        print('Selected offline suites passed. No live/device acceptance performed.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
