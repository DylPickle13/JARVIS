"""No hardware, microphone access, HTTP calls or launchd mutations."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pi_room_audio_client as client
import room_audio_coreaudio as core
import macos_room_audio_service as service


def fake_audio():
    sd = MagicMock()
    sd.query_hostapis.return_value = [{'name': 'Core Audio'}]
    sd.query_devices.return_value = [
        {'name': 'PowerConf', 'hostapi': 0, 'max_input_channels': 0, 'max_output_channels': 2},
        {'name': 'PowerConf', 'hostapi': 0, 'max_input_channels': 1, 'max_output_channels': 0},
        {'name': 'Other', 'hostapi': 0, 'max_input_channels': 1, 'max_output_channels': 2},
    ]
    return sd


class SelectionTests(unittest.TestCase):
    def test_separate_direction_endpoints(self):
        sd = fake_audio()
        self.assertEqual(core.resolve_device(sd, 'PowerConf', 'input')[0], 1)
        self.assertEqual(core.resolve_device(sd, 'PowerConf', 'output')[0], 0)

    def test_missing_partial_empty_ambiguous_fail_closed(self):
        sd = fake_audio()
        for name in ('', 'Power', 'missing'):
            with self.assertRaises(ValueError): core.resolve_device(sd, name, 'input')
        sd.query_devices.return_value.append(sd.query_devices.return_value[1].copy())
        with self.assertRaises(ValueError): core.resolve_device(sd, 'PowerConf', 'input')
        sd.default.assert_not_called()

    def test_reenumerates_after_hotplug(self):
        sd = fake_audio()
        self.assertEqual(core.resolve_device(sd, 'PowerConf', 'input')[0], 1)
        sd.query_devices.return_value.reverse()
        self.assertEqual(core.resolve_device(sd, 'PowerConf', 'output')[0], 2)
        sd.query_devices.return_value = []
        with self.assertRaises(ValueError): core.resolve_device(sd, 'PowerConf', 'input')

    def test_non_coreaudio_host_rejected(self):
        sd = fake_audio()
        sd.query_hostapis.return_value = [{'name': 'Other host'}]
        with self.assertRaises(ValueError): core.resolve_device(sd, 'PowerConf', 'input')


class ConversionTests(unittest.TestCase):
    def test_mono_tts_resamples_to_stereo_48k(self):
        import numpy as np
        data = np.full(2205, 1000, dtype='<i2').tobytes()
        result = core.convert_pcm(data, 1, 22050, 2, 48000)
        self.assertEqual(result.shape, (4800, 2))
        self.assertEqual(result.dtype, np.dtype('<i2'))
        np.testing.assert_array_equal(result[:, 0], result[:, 1])

    def test_stereo_48k_unchanged(self):
        data = b'\xe8\x03\x18\xfc' * 100
        self.assertEqual(core.convert_pcm(data, 2, 48000, 2, 48000).tobytes(), data)

    def test_record_is_bounded_and_mono(self):
        import wave
        sd = fake_audio()
        stream = sd.RawInputStream.return_value.__enter__.return_value
        stream.read.side_effect = lambda n: (b'\1\0' * n, False)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.wav'
            core.capture(sd, 'PowerConf', 48000, path=path, seconds=0.05)
            with wave.open(str(path)) as wav:
                self.assertEqual((wav.getnframes(), wav.getnchannels()), (2400, 1))
        self.assertEqual(stream.read.call_count, 3)


class BackendTests(unittest.TestCase):
    def test_alsa_still_default(self):
        self.assertEqual(client.build_parser().parse_args([]).audio_backend, 'alsa')
        with patch.object(client, 'AUDIO_BACKEND', 'alsa'):
            self.assertEqual(client.playback_command(Path('x.wav'), 'hw:0'), ['aplay', '-q', '-D', 'hw:0', 'x.wav'])

    def test_coreaudio_commands_explicit_device_and_interpreter(self):
        with patch.object(client, 'AUDIO_BACKEND', 'coreaudio'), patch.object(client.subprocess, 'Popen') as popen:
            client.start_raw_arecord(device='PowerConf', rate=48000)
            cmd = popen.call_args.args[0]
            self.assertEqual(cmd[0], client.sys.executable)
            self.assertIn('capture', cmd)
            self.assertEqual(cmd[cmd.index('--device') + 1], 'PowerConf')
            playback = client.playback_command(Path('/tmp/test.wav'), 'PowerConf')
            self.assertIn('playback', playback)
            self.assertNotIn('aplay', playback)

    def test_cancel_before_playback_never_opens_device(self):
        event = threading.Event()
        event.set()
        with patch.object(client.subprocess, 'Popen') as popen:
            self.assertFalse(client.PlaybackController().play(Path('unused'), device='PowerConf', cancel_event=event))
            popen.assert_not_called()

    def test_playback_stop_terminates_helper(self):
        player = client.PlaybackController()
        proc = Mock()
        proc.poll.return_value = None
        player._proc = proc
        self.assertTrue(player.stop())
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=0.75)


class DeploymentTests(unittest.TestCase):
    def test_agents_isolated_no_secret_arguments(self):
        for role in ('client', 'server'):
            path, definition = service.build_agent(role, Path('/python'), Path('/private/state'), Path('/agents'))
            self.assertIn('room-audio-mac-', path.name)
            self.assertNotIn('8791', str(definition))
            self.assertNotIn('TOKEN', str(definition))
            self.assertEqual(definition['Umask'], 0o077)
        args = service.client_arguments(8793, 'PowerConf')
        self.assertIn('http://127.0.0.1:8793', args)
        self.assertIn('--interrupt-while-busy', args)
        self.assertIn('--no-openwakeword-auto-download', args)

    def test_environment_requires_private_permissions_and_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'environment.json'
            path.write_text(json.dumps({'JARVIS_ROOM_AUDIO_TOKEN': 'test-only'}))
            path.chmod(0o644)
            with self.assertRaises(ValueError): service.read_environment(path)
            path.chmod(0o600)
            self.assertEqual(service.read_environment(path)['JARVIS_ROOM_AUDIO_TOKEN'], 'test-only')
            path.write_text('{}')
            with self.assertRaises(ValueError): service.read_environment(path)


if __name__ == '__main__':
    unittest.main()
