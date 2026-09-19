#!/usr/bin/env python3
"""Explicit local-backend CLI entry; reads and unrelated actions are unchanged."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'jarvisd'))
import jarvis
from jarvisd_core.local_control import Router

if __name__ == '__main__':
    raise SystemExit(jarvis.main(command_router=Router(jarvis)))
