"""Single-Mac Wi-Fi runtime. No remote-host or USB fallback.

Capture and editing folders are separate local copies, NOT independent backups.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTURE = Path.home() / 'Movies/Phone Recordings Capture'
EDITING = Path.home() / 'Movies/Phone Recordings'
PYTHON = str(ROOT / '.sync-venv/bin/python')


def helper(name, *args):
    if name not in {'remote_jobs.py', 'export_verified_take.py', 'review_take.py'}:
        raise ValueError('Unknown controller helper')
    return [PYTHON, str(ROOT / name), *args]
