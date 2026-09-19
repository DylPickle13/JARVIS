"""Test-only file loader supporting checkout and copied artifact entry points."""
import importlib.util
from pathlib import Path
import sys


DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "jarvisd.py"


def load_daemon(name, source=DEFAULT_SOURCE):
    # Running jarvisd.py normally supplies this path automatically. Loading it
    # by spec in tests does not; never add path hacks to the production daemon.
    original = sys.path[:]
    try:
        sys.path.insert(0, str(source.parent))
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = original
