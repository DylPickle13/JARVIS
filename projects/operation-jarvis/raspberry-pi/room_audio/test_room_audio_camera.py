"""Offline camera transport tests. No network, playback or service writes."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pi_room_audio_client as client
import room_audio_camera as camera
import camera_room_audio_service as service


class CameraTests(unittest.TestCase):
    def test_backend_routes_capture_and_playback_to_camera_worker(self):
        with patch.object(client, 'AUDIO_BACKEND', 'camera'):
            cmd = client.playback_command(Path('/tmp/test.wav'), 'camera')
            self.assertEqual(Path(cmd[1]).name, 'room_audio_camera.py')
            self.assertIn('playback', cmd)
            self.assertNotIn('aplay', cmd)
            cmd = client.coreaudio_command('capture', device='camera', rate=16000)
            self.assertEqual(Path(cmd[1]).name, 'room_audio_camera.py')
            self.assertIn('16000', cmd)

    def test_existing_coreaudio_unchanged(self):
        with patch.object(client, 'AUDIO_BACKEND', 'coreaudio'):
            cmd = client.playback_command(Path('/tmp/test.wav'), 'PowerConf')
            self.assertEqual(Path(cmd[1]).name, 'room_audio_coreaudio.py')

    def test_existing_alsa_unchanged(self):
        with patch.object(client, 'AUDIO_BACKEND', 'alsa'):
            self.assertEqual(client.playback_command(Path('/tmp/test.wav'), 'hw:1')[0], 'aplay')

    def test_pcm_contract(self):
        cmd = camera.capture_command({'rtsp': 'rtsp://127.0.0.1:1234/speaker?audio=pcma'}, 16000)
        self.assertEqual(cmd[-3:], ['-f', 's16le', 'pipe:1'])
        self.assertIn('5000000', cmd)
        self.assertNotIn('-t', cmd)
        self.assertNotIn('avfoundation', cmd)

    def test_fixed_capture_requires_duration(self):
        with self.assertRaises(camera.AudioError):
            camera.capture_command({'rtsp': 'rtsp://127.0.0.1:1234/speaker'}, 16000, path=Path('/tmp/test.wav'))

    def test_unsupported_sample_rate(self):
        with self.assertRaises(camera.AudioError):
            camera.capture_command({}, 44100)

    def test_manifest_loopback_only(self):
        data = {'device': 'camera', 'api': 'http://192.0.2.1:1984/api/streams',
                'rtsp': 'rtsp://127.0.0.1:8554/speaker', 'token': 'x'*32, 'volume': 30}
        with patch.dict(os.environ, {'JARVIS_ROOM_CAMERA_SESSION_FILE': '/synthetic/private.json'}), patch.object(camera, 'read_json', return_value=data):
            with self.assertRaisesRegex(camera.AudioError, 'loopback'):
                camera.load_session('camera')

    def test_manifest_must_match_device(self):
        with patch.dict(os.environ, {'JARVIS_ROOM_CAMERA_SESSION_FILE': '/synthetic/private.json'}), patch.object(camera, 'read_json', return_value={'device': 'different'}):
            with self.assertRaisesRegex(camera.AudioError, 'mismatch'):
                camera.load_session('camera')

    def test_watch_reply_producers_not_capture_consumers(self):
        before = {'producers': [{'id': 1, 'format_name': 'tapo'}], 'consumers': [{'id': 2}]}
        during = {'producers': [{'id': 1}, {'id': 3}], 'consumers': [{'id': 2}]}
        self.assertEqual(camera.producer_ids(during) - camera.producer_ids(before), {3})

    def test_reuses_pi_server_not_mac_server(self):
        args = service.client_arguments('camera')
        self.assertIn('http://127.0.0.1:8791', args)
        self.assertNotIn('http://127.0.0.1:8793', args)
        self.assertIn('--local-wake-word', args)
        self.assertIn('--interrupt-while-busy', args)
        self.assertIn('--no-startup-greeting', args)
        self.assertIn('--no-openwakeword-auto-download', args)
        self.assertIn('0.75', args)

    def test_setup_needs_confirmation(self):
        import argparse
        with self.assertRaisesRegex(service.AudioError, 'confirmation_required'):
            service.configure(argparse.Namespace(confirm=False))


if __name__ == '__main__':
    unittest.main()
