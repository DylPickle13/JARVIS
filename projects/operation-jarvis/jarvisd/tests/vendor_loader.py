"""Load repository vendor wrappers without loading SDKs or live configuration."""
import importlib
import os
from pathlib import Path
import sys
import types
from unittest import mock


def load_vendor(kind, module):
    root = Path(os.environ.get("JARVIS_TEST_VENDOR_ROOT", str(Path(__file__).resolve().parents[2])))
    folder, package = {"plug": ("smart-plug", "smart_plug"), "purifier": ("air-purifier", "air_purifier")}[kind]
    alias = "_jarvis_test_" + package
    if alias not in sys.modules:
        parent = types.ModuleType(alias)
        parent.__path__ = [str(root / folder / package)]
        sys.modules[alias] = parent
    fake_kasa = types.ModuleType("kasa")
    fake_kasa.Discover = mock.Mock()
    fake_kasa.Discover.discover_single.side_effect = AssertionError("No SDK/device access in unit tests")
    fake_kasa.Discover.discover.side_effect = AssertionError("No SDK/device access in unit tests")
    with mock.patch.dict(sys.modules, {"kasa": fake_kasa}):
        return importlib.import_module(alias + "." + module)
