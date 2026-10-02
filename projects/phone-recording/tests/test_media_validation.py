import json
import subprocess
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile

from android_media import fingerprint, hash_timeout
import media_validation as media
import pair_control


class FingerprintTests(unittest.TestCase):
    def test_timeout_scales_with_size_and_is_bounded(self):
        self.assertEqual(hash_timeout(1), 60)
        self.assertGreater(hash_timeout(10 * 1024**3), 15)
        self.assertLessEqual(hash_timeout(10**15), 3600)
        with self.assertRaises(ValueError):
            hash_timeout(0)

    def test_hash_uses_large_file_budget_and_checks_size(self):
        size = 10 * 1024**3
        adb = Mock(side_effect=[str(size), 'a' * 64 + ' file', str(size)])
        self.assertEqual(fingerprint(adb, 'lg', '/clip.mp4'), ('a' * 64, size))
        self.assertEqual(adb.call_args_list[1].kwargs['timeout'], hash_timeout(size))

    def test_size_change_or_invalid_hash_fails(self):
        for responses in (['100', 'bad file'], ['100', 'a' * 64, '101']):
            with self.subTest(responses=responses), self.assertRaises(RuntimeError):
                fingerprint(Mock(side_effect=responses), 'lg', '/clip.mp4')

    def test_control_timeout_stays_short_and_never_replays(self):
        with patch.object(pair_control.transport, 'ensure', return_value='fake'), patch.object(pair_control.subprocess, 'check_output') as command:
            pair_control.adb('lg', 'shell', 'input', 'keyevent', 'KEYCODE_VOLUME_UP')
            self.assertEqual(command.call_args.kwargs['timeout'], 15)
            pair_control.adb('lg', 'shell', 'sha256sum', '/clip.mp4', timeout=600)
            self.assertEqual(command.call_args.kwargs['timeout'], 600)
            self.assertEqual(command.call_count, 2)


class MediaTests(unittest.TestCase):
    def metadata(self, duration='2', streams=None):
        return {'format': {'duration': duration}, 'streams': streams if streams is not None else
                [{'codec_type': 'video', 'width': 3840, 'height': 2160}]}

    def run_metadata(self, metadata):
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(metadata))

    def test_nonfinite_or_nonpositive_duration_is_rejected(self):
        for duration in ('nan', 'inf', '-1', '0'):
            with self.subTest(duration=duration), patch.object(media.subprocess, 'run', return_value=self.run_metadata(self.metadata(duration))) as run:
                with self.assertRaises(RuntimeError):
                    media.verify_video(Path('/synthetic'))
                self.assertEqual(run.call_count, 1)

    def test_audio_only_and_wrong_iphone_dimensions_rejected(self):
        for streams in ([{'codec_type': 'audio'}], [{'codec_type': 'video', 'width': 640, 'height': 480}]):
            with self.subTest(streams=streams), patch.object(media.subprocess, 'run', return_value=self.run_metadata(self.metadata(streams=streams))):
                with self.assertRaises(RuntimeError):
                    media.verify_video(Path('/synthetic'), (3840, 2160))

    def test_decode_error_propagates(self):
        with patch.object(media.subprocess, 'run', side_effect=[
                self.run_metadata(self.metadata()), subprocess.CalledProcessError(1, 'ffmpeg')]):
            with self.assertRaises(subprocess.CalledProcessError):
                media.verify_video(Path('/synthetic'))

    def test_full_video_and_audio_decode_requested(self):
        with patch.object(media.subprocess, 'run', side_effect=[
                self.run_metadata(self.metadata()), subprocess.CompletedProcess([], 0)]) as run:
            media.verify_video(Path('/synthetic'))
        args = run.call_args.args[0]
        self.assertIn('-xerror', args)
        self.assertIn('0:v:0', args)
        self.assertIn('0:a?', args)
        self.assertIn('-nostdin', args)

    @unittest.skipUnless(Path(media.FFMPEG).is_file() and Path(media.FFPROBE).is_file(), 'FFmpeg not installed')
    def test_real_synthetic_video_and_invalid_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.mp4'
            subprocess.run([media.FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi',
                            '-i', 'color=c=black:s=64x64:r=30', '-f', 'lavfi',
                            '-i', 'sine=frequency=440:sample_rate=48000', '-t', '0.5',
                            '-c:v', 'mpeg4', '-c:a', 'aac', str(path)], check=True, capture_output=True, timeout=30)
            self.assertGreater(float(media.verify_video(path)['format']['duration']), 0)
            path.write_bytes(b'not a video')
            with self.assertRaises(subprocess.CalledProcessError):
                media.verify_video(path)
