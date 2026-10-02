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
        self.assertEqual(progress.summary(), '8/10 ready · Waiting for idle: sessions #1, #3')
        progress.update('slot 1: restarting conversation.jsonl')
        self.assertEqual(progress.summary(),
                         '8/10 ready · Waiting for idle: session #3 · Restarting: session #1')
        progress.update('slot 1: did not become ready: timeout')
        self.assertEqual(progress.summary(),
                         '8/10 ready · Waiting for idle: session #3 · Restart failed: session #1')
        progress.update('slot 3: ready (PID 1->2, conversation.jsonl)')
        self.assertEqual(progress.summary(), '9/10 ready · Restart failed: session #1')

    def test_multiple_restarting_and_failed_session_ids(self):
        tracker = progress.Progress()
        for slot in (1, 3, 10):
            tracker.update(f'slot {slot}: restarting conversation.jsonl')
        self.assertIn('Restarting: sessions #1, #3, #10', tracker.summary())
        for slot in (1, 3, 10):
            tracker.update(f'slot {slot}: no valid Pi status descriptor')
        self.assertIn('Restart failed: sessions #1, #3, #10', tracker.summary())
        with tempfile.TemporaryDirectory() as directory, patch.object(progress, 'STATE', Path(directory)):
            progress.publish(tracker.summary())
            self.assertIn('Restart failed: sessions ##1, ##3, ##10', progress.status_line())

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
            self.assertIn('8/10 ready · Waiting for idle: sessions ##1, ##3', progress.status_line())
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
                self.assertEqual(spawn.call_args.kwargs['stdin'], progress.subprocess.DEVNULL)

    def test_duplicate_request_is_not_an_error_and_preserves_progress(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(progress, 'STATE', Path(directory)), \
                patch.object(progress.subprocess, 'Popen') as spawn, \
                patch.object(progress, 'notify') as notify:
            progress.publish('9/10 ready · Waiting for idle: session #2')
            status = (progress.STATE / 'restart-status').read_bytes()
            log = progress.STATE / 'restart.log'
            log.write_text('original worker output\n')
            with (progress.STATE / 'restart.lock').open('a') as lock:
                progress.fcntl.flock(lock, progress.fcntl.LOCK_EX | progress.fcntl.LOCK_NB)
                self.assertEqual(progress.run(client='/dev/test-client'), 0)
            spawn.assert_not_called()
            notify.assert_called_once_with(
                'Restart already in progress; see the top status area.', '/dev/test-client')
            self.assertEqual((progress.STATE / 'restart-status').read_bytes(), status)
            self.assertEqual(log.read_text(), 'original worker output\n')

    def test_notification_is_client_scoped_status_only(self):
        with patch.object(progress, 'tmux') as tmux:
            progress.notify('Restart already in progress.', '/dev/test-client')
        tmux.assert_called_once_with('display-message', '-d', '5000', '-c',
                                    '/dev/test-client', 'Restart already in progress.', check=False)

    def test_detached_notification_does_not_fail_the_request(self):
        with patch.object(progress, 'tmux', side_effect=RuntimeError('client detached')) as tmux:
            progress.notify('Restart already in progress.', '/dev/test-client')
        tmux.assert_called_once()

    def test_launch_failure_still_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(progress, 'STATE', Path(directory)), \
                patch.object(progress, 'load') as backend, \
                patch.object(progress.subprocess, 'Popen', side_effect=OSError('helper unavailable')) as spawn:
            backend.return_value.restart.return_value = ['helper']
            self.assertEqual(progress.run(), 1)
            self.assertIn('Failed: helper unavailable', progress.status_line())
            spawn.assert_called_once()


if __name__ == '__main__':
    unittest.main()
