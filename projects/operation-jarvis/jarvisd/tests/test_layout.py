"""Relocation contracts; imports use a synthetic checkout, never live config."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from daemon_loader import load_daemon


DAEMON_DIR = Path(__file__).resolve().parents[1]


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "checkout"
        self.operation = self.root / "projects" / "operation-jarvis"
        self.source = self.operation / "jarvisd" / "jarvisd.py"
        self.source.parent.mkdir(parents=True)
        shutil.copyfile(DAEMON_DIR / "jarvisd.py", self.source)
        shutil.copyfile(DAEMON_DIR / "device-worker.py", self.source.parent / "device-worker.py")
        shutil.copytree(DAEMON_DIR / "jarvisd_core", self.source.parent / "jarvisd_core")
        (self.operation / "jarvis-cli").touch()
        (self.root / ".pi").mkdir()
        (self.root / ".env").write_text("# Synthetic test configuration only.\n")

    def load(self, overrides=None, source=None):
        # No collectors, HTTP server, or persistent event store start on import.
        # Configuration lives in the temporary checkout; no host credentials.
        with mock.patch.dict(os.environ, overrides or {}, clear=True):
            return load_daemon("layout_test_daemon", source or self.source)

    def test_checkout_defaults_resolve_outside_the_app(self):
        daemon = self.load()
        self.assertEqual(daemon.OPERATION_ROOT, self.operation)
        self.assertEqual(daemon.PROJECT_ROOT, self.root)
        self.assertEqual(daemon.JARVIS_ROOT, self.root)
        self.assertEqual(daemon.JARVIS_CLI, self.operation / "jarvis-cli")
        self.assertEqual(daemon.DEVICE_WORKER, self.source.parent / "device-worker.py")
        self.assertEqual(daemon.SERVICES_FILE, self.source.parent / "services.json")
        self.assertEqual(daemon.EVENTS_FILE, self.source.parent / "logs" / "events.jsonl")
        self.assertEqual(daemon.LOG_FILE, self.source.parent / "logs" / "jarvisd.log")
        self.assertEqual(daemon.SIGNING_RENEWAL_SCRIPT,
                         self.operation / "jarvis-app" / "scripts" / "renew-free-signing.sh")
        self.assertEqual(daemon.SCHEDULER_RUNNER, self.root / ".pi" / "scheduler" / "runner.py")
        self.assertEqual(daemon.CODEX_QUOTAS_SCRIPT, self.operation / "quotas" / "quotas.py")
        self.assertEqual(daemon.PORT, 8790)

    def test_entry_import_does_not_touch_existing_event_history(self):
        path = self.source.parent / "logs" / "events.jsonl"
        path.parent.mkdir()
        original = b'{"seq":9,"summary":"retained"}\nmalformed historical line\n'
        path.write_bytes(original)
        daemon = self.load()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(daemon.EVENTS.list(), [])

    def test_copied_core_package_loads_without_checkout_or_working_directory(self):
        code = '''
import runpy, sys
from pathlib import Path
source = Path(sys.argv[1])
sys.path.insert(0, str(source.parent))
module = runpy.run_path(str(source))
import jarvisd_core
assert Path(jarvisd_core.__file__).parent == source.parent / 'jarvisd_core'
assert module['EVENTS'].list() == []
assert not (source.parent / 'logs').exists()
print('copied package import: OK')
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(self.source)],
                                cwd=self.temp.name, env={}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("copied package import: OK", result.stdout)

    def test_operation_fallback_is_immediate_parent(self):
        (self.operation / "jarvis-cli").unlink()
        self.assertEqual(self.load().OPERATION_ROOT, self.operation)

    def test_frozen_artifact_uses_explicit_roots_for_app_helper(self):
        artifact = Path(self.temp.name) / "artifact" / "jarvisd" / "jarvisd.py"
        artifact.parent.mkdir(parents=True)
        shutil.copyfile(self.source, artifact)
        shutil.copyfile(DAEMON_DIR / "device-worker.py", artifact.parent / "device-worker.py")
        shutil.copytree(DAEMON_DIR / "jarvisd_core", artifact.parent / "jarvisd_core")
        daemon = self.load({
            "JARVISD_OPERATION_ROOT": str(self.operation),
            "JARVISD_PROJECT_ROOT": str(self.root),
        }, source=artifact)
        self.assertEqual(daemon.JARVIS_ROOT, self.root)
        self.assertEqual(daemon.JARVIS_CLI, self.operation / "jarvis-cli")
        self.assertEqual(daemon.DEVICE_WORKER, (artifact.parent / "device-worker.py").resolve())
        self.assertEqual(daemon.SIGNING_RENEWAL_SCRIPT,
                         self.operation / "jarvis-app" / "scripts" / "renew-free-signing.sh")

    def test_runtime_and_helper_overrides_remain_supported(self):
        overrides = {
            "JARVISD_SERVICES_FILE": str(self.root / "private" / "services.json"),
            "JARVISD_EVENTS_FILE": str(self.root / "private" / "events.jsonl"),
            "JARVISD_LOG_FILE": str(self.root / "private" / "daemon.log"),
            "JARVISD_SIGNING_RENEWAL_SCRIPT": str(self.root / "custom" / "renew.sh"),
            "JARVISD_JARVIS_ROOT": str(self.root / "runtime"),
        }
        daemon = self.load(overrides)
        for env, attribute in (
            ("JARVISD_SERVICES_FILE", "SERVICES_FILE"),
            ("JARVISD_EVENTS_FILE", "EVENTS_FILE"),
            ("JARVISD_LOG_FILE", "LOG_FILE"),
            ("JARVISD_SIGNING_RENEWAL_SCRIPT", "SIGNING_RENEWAL_SCRIPT"),
            ("JARVISD_JARVIS_ROOT", "JARVIS_ROOT"),
        ):
            self.assertEqual(getattr(daemon, attribute), Path(overrides[env]))

    def test_launchagents_share_new_directory_and_preserve_labels(self):
        for label, script in (
            ("com.operation-jarvis.jarvisd", "jarvisd.py"),
            ("com.operation-jarvis.jarvisd-resurrector", "resurrector.sh"),
        ):
            with self.subTest(label=label):
                path = DAEMON_DIR / "launchd" / f"{label}.plist"
                data = plistlib.loads(path.read_bytes())
                directory = Path(data["WorkingDirectory"])
                self.assertEqual(directory.parts[-2:], ("operation-jarvis", "jarvisd"))
                self.assertEqual(data["Label"], label)
                self.assertEqual(Path(data["ProgramArguments"][1]), directory / script)
                for key in ("StandardOutPath", "StandardErrorPath"):
                    self.assertEqual(Path(data[key]).parent, directory / "logs")
                self.assertNotIn("jarvis-app/jarvisd", path.read_text())

    def test_app_helper_and_verifier_use_sibling_backend(self):
        operation = DAEMON_DIR.parent
        self.assertTrue((operation / "jarvis-app" / "scripts" / "renew-free-signing.sh").is_file())
        self.assertTrue((operation / "jarvis-app" / "scripts" / "jarvis-mobile-vscode-restart.py").is_file())
        verifier = (operation / "jarvis-app" / "scripts" / "verify-jarvis-app.sh").read_text()
        self.assertIn("../jarvisd/verify.sh", verifier)
        self.assertNotIn("Path('jarvisd/", verifier)


if __name__ == "__main__":
    unittest.main()
