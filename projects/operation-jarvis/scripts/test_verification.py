"""Offline verification contracts; no real suites or endpoints invoked here."""
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import verify_docs

SPEC = importlib.util.spec_from_file_location('verify_offline', Path(__file__).with_name('verify-offline.py'))
offline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offline)


class DocumentationTests(unittest.TestCase):
    def test_source_documentation_has_no_missing_local_targets(self):
        missing = verify_docs.missing_targets(verify_docs.markdown_files(verify_docs.ROOT))
        self.assertEqual(missing, [], '\n'.join(f'{p}:{n}: {t}' for p, n, t in missing))

    def test_links_fragments_titles_images_and_url_escaped_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'with space.md').write_text('# Target')
            doc = root / 'README.md'
            doc.write_text('[ok](with%20space.md#target "Title")\n'
                           '[angle](<with space.md>)\n'
                           '[external](https://example.com/absent)\n'
                           '[anchor](#missing)\n'
                           '![missing](image.png)\n')
            self.assertEqual(verify_docs.missing_targets([doc]), [(doc, 5, 'image.png')])

    def test_examples_in_both_fence_types_are_not_links(self):
        with tempfile.TemporaryDirectory() as directory:
            doc = Path(directory) / 'README.md'
            doc.write_text('```md\n[x](missing)\n~~~\n```\n'
                           '~~~~\n[x](missing)\n~~~\n~~~~\n[x](real-missing)\n')
            self.assertEqual(verify_docs.missing_targets([doc]), [(doc, 9, 'real-missing')])

    def test_private_and_generated_trees_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('.venv', 'data', 'build', 'docs'):
                (root / name).mkdir()
                (root / name / 'README.md').write_text('')
            self.assertEqual(list(verify_docs.markdown_files(root)), [root / 'docs/README.md'])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        redirect = patch('sys.stdout', self.output)
        redirect.start()
        self.addCleanup(redirect.stop)

    def test_default_covers_all_non_swift_suites_without_live_tests(self):
        with patch('sys.argv', ['verify-offline.py']), \
                patch.dict('os.environ', {'JARVIS_LIVE_TESTS': '1'}), \
                patch.object(offline.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(offline.main(), 0)
        self.assertEqual(run.call_count, len(offline.SUITES) - 1)
        for invocation in run.call_args_list:
            self.assertEqual(invocation.kwargs['env']['JARVIS_LIVE_TESTS'], '0')
            self.assertEqual(invocation.kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertEqual(invocation.kwargs['timeout'], 600)
        self.assertTrue({'purifier', 'keyboard', 'terminal', 'android-monitor', 'departure', 'docs'} <= set(offline.SUITES))

    def test_missing_interpreter_is_a_failure_not_a_skip(self):
        with patch('sys.argv', ['verify-offline.py', '--suite', 'voice']), \
                patch.object(offline.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(offline.main(), 1)

    def test_failed_suite_does_not_prevent_other_checks(self):
        with patch('sys.argv', ['verify-offline.py', '--suite', 'voice', '--suite', 'docs']), \
                patch.object(offline.subprocess, 'run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as run:
            self.assertEqual(offline.main(), 1)
        self.assertEqual(run.call_count, 2)
