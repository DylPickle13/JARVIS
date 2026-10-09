#!/usr/bin/env python3
"""Guarded wrapper for the private SDK fixture; used by the focus/Space monitor."""
import os
if os.environ.get('JARVIS_TEST_VERIFIED_RECOVERY_MAINTENANCE') != '1':
    raise SystemExit('Not authorized: requires a supervised idle verified-recovery maintenance window')

from pathlib import Path
import subprocess

if __name__ == '__main__':
    raise SystemExit(subprocess.run(['/opt/homebrew/bin/node', str(Path(__file__).with_suffix('.mjs'))], env=os.environ).returncode)
