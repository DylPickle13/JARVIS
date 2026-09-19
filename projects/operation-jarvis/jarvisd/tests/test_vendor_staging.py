"""Build-only SDK fence patches; never edits/imports live vendor packages."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from test_jarvisd import jarvisd as daemon
from jarvisd_core import vendor_fence

SPEC = importlib.util.spec_from_file_location('_fenced_vendor_staging', Path(daemon.__file__).parent / 'stage-fenced-vendors.py')
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = Path(os.environ.get('JARVIS_TEST_VENDOR_ROOT', str(Path(daemon.__file__).parent.parent)))

    def test_private_new_stage_uses_identical_helper_and_preserves_source(self):
        before = {name: (self.source / name).read_bytes() for name in staging.BASELINES}
        output = self.root / 'stage'
        manifest = staging.stage(self.source, output)
        self.assertGreater(len(manifest), 2)
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        helper = Path(vendor_fence.__file__).read_bytes()
        for package in ('smart-plug/smart_plug', 'air-purifier/air_purifier'):
            self.assertEqual((output / package / 'vendor_fence.py').read_bytes(), helper)
        for name, raw in before.items():
            self.assertEqual((self.source / name).read_bytes(), raw)
            self.assertNotEqual((output / name).read_bytes(), raw)
        self.assertFalse(any(p.name in ('.env', '.venv', 'plugs.json') for p in output.rglob('*')))

    def test_existing_or_live_tree_destinations_are_refused(self):
        output = self.root / 'existing'; output.mkdir()
        for destination in (output, self.source / 'not-created-fenced-build'):
            with self.assertRaises(ValueError):
                staging.stage(self.source, destination)
        self.assertEqual(list(output.iterdir()), [])
        self.assertFalse((self.source / 'not-created-fenced-build').exists())

    def test_symlink_parent_cannot_hide_live_tree_destination(self):
        alias = self.root / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            staging.stage(self.source, alias / 'not-created-fenced-build')
        self.assertFalse((self.source / 'not-created-fenced-build').exists())

    def test_input_drift_fails_before_creating_output(self):
        source = self.root / 'source'; source.mkdir()
        for relative in staging.BASELINES:
            target = source / relative; target.parent.mkdir(parents=True)
            shutil.copy2(self.source / relative, target)
        path = source / next(iter(staging.BASELINES)); path.write_bytes(path.read_bytes() + b'\n# drift\n')
        with self.assertRaises(ValueError):
            staging.stage(source, self.root / 'stage')
        self.assertFalse((self.root / 'stage').exists())
