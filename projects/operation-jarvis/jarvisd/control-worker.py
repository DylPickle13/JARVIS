#!/usr/bin/env python3
"""Explicit ownership-fenced worker candidate, not the legacy worker default."""
from jarvisd_core.control_worker import main

if __name__ == '__main__':
    raise SystemExit(main())
