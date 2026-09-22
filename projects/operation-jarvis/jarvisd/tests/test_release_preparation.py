import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/prepare-jarvisd-release.py'
spec = importlib.util.spec_from_file_location('release_preparation', SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        (self.repo / 'source.py').write_text('value = 1\n')
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), '-c', 'user.name=Fixture',
                                       '-c', 'user.email=fixture@example.invalid', *args], stderr=subprocess.DEVNULL)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture', '--no-gpg-sign')

    def test_exact_committed_tree_and_private_manifest_without_activation(self):
        (self.repo / 'source.py').write_text('uncommitted = True\n')
        output = self.root / 'release'
        manifest = release.prepare(self.repo, 'HEAD', output, [('test', sys.executable)])
        self.assertEqual((output / 'source/source.py').read_text(), 'value = 1\n')
        self.assertEqual(manifest['files']['source.py'], hashlib.sha256(b'value = 1\n').hexdigest())
        self.assertEqual(manifest['verification'], 'not_run')
        self.assertEqual(manifest['activation'], 'not_performed')
        self.assertIn('dependencies', manifest['runtimeMetadata']['test'])
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertEqual((output / 'source-manifest.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.repo / 'source.py').read_text(), 'uncommitted = True\n')
        with self.assertRaises(ValueError):
            release.prepare(self.repo, 'HEAD', output)
        with self.assertRaises(ValueError):
            release.prepare(self.repo, 'HEAD', self.repo / 'nested')

    def test_tracked_private_material_rejected_before_output(self):
        (self.repo / '.env').write_text('synthetic fixture only')
        self.commit()
        with self.assertRaises(ValueError):
            release.prepare(self.repo, 'HEAD', self.root / 'release')
        self.assertFalse((self.root / 'release').exists())

    def test_tracked_symlink_rejected(self):
        (self.repo / 'link').symlink_to('source.py')
        self.commit()
        with self.assertRaises(ValueError):
            release.prepare(self.repo, 'HEAD', self.root / 'release')
