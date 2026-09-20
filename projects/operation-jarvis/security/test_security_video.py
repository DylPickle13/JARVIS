"""Offline video checks: never contact a device or show footage."""
from contextlib import ExitStack, nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import security_cli as cli
import security_video as video


class VideoTests(unittest.TestCase):
    def args(self, *extra):
        return cli.parser().parse_args(list(extra))

    def test_quality_defaults_to_hd_with_low_override(self):
        for command in ('live', 'snapshot'):
            self.assertEqual(self.args(command, 'bell').quality, 'hd')
            self.assertEqual(self.args(command, 'bell', '--quality', 'low').quality, 'low')

    def test_confirmation_before_registry_or_network(self):
        with patch.object(cli, 'registry') as registry:
            with self.assertRaisesRegex(cli.ControlError, 'confirmation_required'):
                video.execute_video(self.args('snapshot', 'bell'))
        registry.assert_not_called()

    def test_invalid_duration_before_registry(self):
        with patch.object(cli, 'registry') as registry:
            with self.assertRaisesRegex(cli.ControlError, 'invalid_video_duration'):
                video.execute_video(self.args('live', 'bell', '--confirm', '--seconds', '121'))
        registry.assert_not_called()

    def test_wrong_model_rejected(self):
        with patch.object(cli, 'registry', return_value={'bell': {'model': 'C230'}}):
            with self.assertRaisesRegex(cli.ControlError, 'direct_doorbell_required'):
                video.execute_video(self.args('snapshot', 'bell', '--confirm'))

    def setup_fake(self, stack, root):
        stack.enter_context(patch.object(cli, 'ROOT', root))
        stack.enter_context(patch.object(cli, 'registry', return_value={
            'bell': {'model': 'D235', 'host': '192.0.2.1', 'hub': 'hub'}}))
        stack.enter_context(patch.object(cli, 'load_settings', return_value=Mock(password='synthetic')))
        lock = stack.enter_context(patch.object(cli, 'device_lock', side_effect=lambda _: nullcontext()))
        identity = stack.enter_context(patch.object(video.audio, 'identify_doorbell', new_callable=AsyncMock))
        stack.enter_context(patch.object(video.shutil, 'which', side_effect=lambda x: '/bin/' + x))
        session = Mock(rtsp_video_url='rtsp://127.0.0.1:1234/speaker?video')
        stack.enter_context(patch.object(video.audio, 'CameraSession', return_value=session))
        return session, lock, identity

    def test_private_snapshot_and_cleanup(self):
        with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
            root = Path(name)
            session, lock, identity = self.setup_fake(stack, root)
            def capture(command, timeout):
                self.assertIn('-an', command)
                self.assertIn('-n', command)
                Path(command[-1]).write_bytes(b'synthetic frame')
            stack.enter_context(patch.object(video, 'run_bounded', side_effect=capture))
            result = video.execute_video(self.args('snapshot', 'bell', '--confirm'))
            output = Path(result['path'])
            self.assertEqual(output.parent, root / 'private-snapshots')
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)
            self.assertFalse(result['displayed'])
            self.assertEqual([c.args[0] for c in lock.call_args_list], ['hub', 'bell'])
            identity.assert_awaited_once()
            session.start.assert_called_once_with(video_only=True, video_quality='hd')
            session.close.assert_called_once()
            self.assertFalse(list((root / '.video-runtime').iterdir()))

    def test_failed_identity_never_starts_transport(self):
        with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
            session, _, identity = self.setup_fake(stack, Path(name))
            identity.side_effect = video.audio.AudioError('audio_identity_mismatch')
            with self.assertRaises(cli.ControlError):
                video.execute_video(self.args('snapshot', 'bell', '--confirm'))
            session.start.assert_not_called()

    def test_verify_requires_decoded_frames_and_closes(self):
        for frames in (0, 12):
            with self.subTest(frames=frames), tempfile.TemporaryDirectory() as name, ExitStack() as stack:
                session, _, _ = self.setup_fake(stack, Path(name))
                def decode(command, timeout):
                    self.assertIn('-an', command)
                    Path(command[command.index('-progress') + 1]).write_text(f'frame={frames}\n')
                stack.enter_context(patch.object(video, 'run_bounded', side_effect=decode))
                args = self.args('live', 'bell', '--confirm', '--verify-only', '--seconds', '2')
                if frames:
                    self.assertEqual(video.execute_video(args)['decoded_frames'], frames)
                else:
                    with self.assertRaisesRegex(cli.ControlError, 'empty_video_stream'):
                        video.execute_video(args)
                session.close.assert_called_once()

    def test_hd_uses_separate_app_and_explicit_hevc_mode(self):
        with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
            root = Path(name)
            session, _, _ = self.setup_fake(stack, root)
            factory = video.audio.CameraSession
            stack.enter_context(patch.object(video, 'run_bounded'))
            result = video.execute_video(self.args('live', 'bell', '--quality', 'hd', '--confirm'))
            self.assertEqual(factory.call_args.args[0],
                             root / 'private-notes/audio-poc/hd-video/JARVIS Doorbell Video.app')
            session.start.assert_called_once_with(video_only=True, video_quality='hd')
            self.assertEqual(result['quality'], 'hd')
            session.close.assert_called_once()

    def test_live_view_is_muted_and_wall_clock_bounded(self):
        with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
            session, _, _ = self.setup_fake(stack, Path(name))
            runner = stack.enter_context(patch.object(video, 'run_bounded'))
            result = video.execute_video(self.args('live', 'bell', '--confirm', '--seconds', '5'))
            command = runner.call_args.args[0]
            self.assertEqual(command[0], '/bin/ffplay')
            self.assertIn('-an', command)
            self.assertEqual(runner.call_args.args[1], 5)
            self.assertTrue(runner.call_args.kwargs['timeout_expected'])
            self.assertEqual(result['physical_verification'], 'not_assessed')
            session.close.assert_called_once()

    def test_viewer_deadline_is_normal_and_reaps(self):
        proc = Mock(pid=123)
        proc.poll.return_value = None
        proc.wait.side_effect = [video.subprocess.TimeoutExpired('synthetic', 2), 0]
        with patch.object(video.subprocess, 'Popen', return_value=proc), patch.object(video.os, 'killpg') as kill:
            video.run_bounded(['synthetic'], 2, timeout_expected=True)
        kill.assert_called_once_with(123, video.audio.signal.SIGTERM)
        self.assertEqual(proc.wait.call_count, 2)

    def test_subprocess_timeout_reaps(self):
        proc = Mock(pid=123)
        proc.poll.return_value = None
        proc.wait.side_effect = [video.subprocess.TimeoutExpired('synthetic', 2), 0]
        with patch.object(video.subprocess, 'Popen', return_value=proc), patch.object(video.os, 'killpg') as kill:
            with self.assertRaisesRegex(cli.ControlError, 'video_timeout'):
                video.run_bounded(['synthetic'], 2)
        kill.assert_called_once_with(123, video.audio.signal.SIGTERM)
        self.assertEqual(proc.wait.call_count, 2)


if __name__ == '__main__':
    unittest.main()
