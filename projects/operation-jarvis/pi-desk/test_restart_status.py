import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import desktop
import restart_status as progress


class RestartStatusTests(unittest.TestCase):
    def test_summary_keeps_busy_slots_visible(self):
        progress = self.busy_progress()
        self.assertEqual(progress.summary(), '8/10 ready · Waiting for idle: 1, 3')
        progress.update('slot 1: restarting conversation.jsonl')
        self.assertEqual(progress.summary(),
                         '8/10 ready · Waiting for idle: 3 · Restarting: 1')
        progress.update('slot 1: did not become ready: timeout')
        self.assertEqual(progress.summary(),
                         '8/10 ready · Waiting for idle: 3 · Failed: 1')
        progress.update('slot 3: ready (PID 1->2, conversation.jsonl)')
        self.assertEqual(progress.summary(), '9/10 ready · Failed: 1')

    @staticmethod
    def busy_progress():
        tracker = progress.Progress()
        for slot in range(1, 11):
            tracker.update(f'slot {slot}: queued; waiting for idle (up to 30 minutes)')
        for slot in (2, 4, 5, 6, 7, 8, 9, 10):
            tracker.update(f'slot {slot}: ready (PID 1->2, conversation.jsonl)')
        return tracker

    def test_existing_worker_log_is_summarized(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(progress, 'STATE', Path(directory)):
            lines = [f'slot {slot}: queued; waiting for idle' for slot in range(1, 11)]
            lines += [f'slot {slot}: ready (PID 1->2)' for slot in (2, 4, 5, 6, 7, 8, 9, 10)]
            (Path(directory) / 'restart.log').write_text('\n'.join(lines))
            progress.publish(lines[-1])
            self.assertIn('8/10 ready · Waiting for idle: 1, 3', progress.status_line())
            progress.publish('Failed: connection lost')
            self.assertIn('Failed: connection lost', progress.status_line())

    def test_headers_have_no_f12(self):
        self.assertNotIn('F12', desktop.selector({}))
        for width in (30, 80, 120, 184):
            self.assertNotIn('F12', desktop.responsive_selector({}, width, 3, 1))

    def test_progress_escaped_and_expires(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(progress, 'STATE', Path(directory)):
            self.assertEqual(progress.status_line(), '')
            progress.publish('slot 1: waiting #(unsafe)')
            self.assertIn('waiting ##(unsafe)', progress.status_line())
            with patch.object(progress.time, 'time', return_value=progress.time.time() + 61):
                self.assertEqual(progress.status_line(), '')

    def test_background_output_success_and_failure(self):
        for code in (0, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory, \
                    patch.object(progress, 'STATE', Path(directory)), \
                    patch.object(progress, 'load') as backend, \
                    patch.object(progress.subprocess, 'Popen') as spawn:
                backend.return_value.restart.return_value = ['helper']
                spawn.return_value = Mock(stdout=io.StringIO('slot 1: queued; waiting for idle\n'),
                                          wait=Mock(return_value=code))
                self.assertEqual(progress.run(), code)
                self.assertIn('Complete' if code == 0 else 'Failed', progress.status_line())
                self.assertIn('waiting for idle', (Path(directory) / 'restart.log').read_text())
                spawn.assert_called_once()

    def test_duplicate_request_does_not_start(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(progress, 'STATE', Path(directory)), \
                patch.object(progress.subprocess, 'Popen') as spawn:
            with (Path(directory) / 'restart.lock').open('a') as lock:
                progress.fcntl.flock(lock, progress.fcntl.LOCK_EX | progress.fcntl.LOCK_NB)
                self.assertEqual(progress.run(), 1)
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
