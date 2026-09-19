#!/usr/bin/env python3
"""Explicit candidate CLI: backend-only device writes, existing non-device actions.

Not selected by jarvis-cli or Pi tools until the approved fenced cutover. Missing
credentials/backend never select the legacy write path. No endpoint/key overrides.
"""
import importlib.util
from pathlib import Path
import sys


def main(argv=None):
    operation = Path(__file__).resolve().parent
    sys.path.insert(0, str(operation / 'jarvisd'))
    from jarvisd_core.control_cli import Router
    spec = importlib.util.spec_from_file_location('_jarvis_control_legacy', operation / 'jarvis.py')
    legacy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = legacy
    spec.loader.exec_module(legacy)
    return legacy.main(argv, command_router=Router(legacy))


if __name__ == '__main__':
    raise SystemExit(main())
