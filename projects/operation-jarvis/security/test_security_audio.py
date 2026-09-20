"""Offline tests only: never connect to a camera or emit sound."""
import argparse
from contextlib import nullcontext
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch, call

import security_audio as audio
import security_cli as cli


class Clock:
    def __init__(self):
        self.now = 0
    def __call__(self):
        return self.now
    def sleep(self, value):
        self.now += value


class PlaybackTests(unittest.TestCase):
    def test_preparation_waits_for_completion_without_fixed_sleep(self):
        proc = Mock(returncode=0)
        proc.poll.side_effect = [None, None, 0, 0]
        proc.wait.side_effect = [audio.subprocess.TimeoutExpired('test', 0.1), 0]
        stop = Mock()
        with patch.object(audio.subprocess, 'Popen', return_value=proc), \
                patch.object(audio.time, 'sleep') as sleep:
            audio.run_child(['test'], stop)
        self.assertEqual(stop.call_count, 2)
        self.assertEqual(proc.wait.call_args_list, [call(timeout=0.1), call(timeout=0.1)])
        sleep.assert_not_called()

    def test_preparation_wait_still_cleans_up_on_stop(self):
        proc = Mock(pid=123, returncode=None)
        proc.poll.return_value = None
        with patch.object(audio.subprocess, 'Popen', return_value=proc), \
                patch.object(audio.os, 'killpg') as kill:
            with self.assertRaises(audio.Stopped):
                audio.run_child(['test'], Mock(side_effect=audio.Stopped))
        kill.assert_called_once_with(123, audio.signal.SIGTERM)
        proc.wait.assert_called_once_with(timeout=3)

    def test_preparation_wait_still_reports_failure(self):
        proc = Mock(returncode=1)
        proc.poll.return_value = 1
        with patch.object(audio.subprocess, 'Popen', return_value=proc):
            with self.assertRaisesRegex(audio.AudioError, 'audio_preparation_failed'):
                audio.run_child(['test'], Mock())

    def test_standalone_commands_share_room_audio_bundle(self):
        parser = argparse.ArgumentParser()
        audio.add_parser(parser.add_subparsers())
        for command, extra in [('speak', ['--text', 'test']), ('play', ['test.wav'])]:
            args = parser.parse_args(['audio', command, 'indoor-camera', *extra])
            self.assertEqual(Path(args.app), audio.MIC16_APP)
        session = audio.CameraSession(audio.APP, Path('/tmp/test'), 'test', 'test', lambda: None)
        self.assertEqual(session.codec, 'pcma')
        self.assertFalse(session.microphone16)

    def test_unlimited_default_runs_long_file(self):
        clock = Clock()
        session = Mock()
        session.busy.side_effect = lambda: clock.now < 7200
        result = audio.playback_loop(session, Path('test.wav'), 7200, False, None,
                                     lambda: None, clock, clock.sleep)
        self.assertEqual(result, ('completed', 1))
        self.assertGreaterEqual(clock.now, 7200)

    def test_optional_duration(self):
        clock = Clock()
        session = Mock()
        session.busy.return_value = True
        result = audio.playback_loop(session, Path('test.wav'), 1000, False, 3,
                                     lambda: None, clock, clock.sleep)
        self.assertEqual(result, ('duration_reached', 1))
        self.assertLess(clock.now, 3.3)

    def test_loop_stops_cooperatively(self):
        session = Mock()
        session.busy.return_value = False
        def stop():
            if session.play.call_count >= 3:
                raise audio.Stopped
        with self.assertRaises(audio.Stopped):
            audio.playback_loop(session, Path('test.wav'), 0.5, True, None, stop)
        self.assertEqual(session.play.call_count, 3)

    def test_early_exit_not_success(self):
        session = Mock()
        session.busy.return_value = False
        with self.assertRaisesRegex(audio.AudioError, 'audio_ended_early'):
            audio.playback_loop(session, Path('test.wav'), 100, False, None, lambda: None)

    def test_scaled_watchdog(self):
        clock = Clock()
        session = Mock()
        session.busy.return_value = True
        with self.assertRaisesRegex(audio.AudioError, 'audio_completion_timeout'):
            audio.playback_loop(session, Path('test.wav'), 1, False, None,
                                lambda: None, clock, clock.sleep)
        self.assertGreater(clock.now, 31)


class ArgumentTests(unittest.TestCase):
    def test_speech_defaults(self):
        args = cli.parser().parse_args(['audio', 'speak', 'camera', '--text', 'Hello', '--confirm'])
        self.assertEqual(args.voice, 'jarvis')
        self.assertIsNone(args.duration)
        self.assertIsNone(args.volume)

    def test_doorbell_defaults_to_jarvis_voice(self):
        args = cli.parser().parse_args(['audio', 'speak', 'front-doorbell', '--text', 'Hello', '--confirm'])
        self.assertEqual(args.voice, 'jarvis')

    def test_invalid_volume(self):
        for value in ('-1', '101', 'nan', '1.5'):
            with self.subTest(value=value), self.assertRaises(cli.ControlError):
                cli.parser().parse_args(['audio', 'volume', 'camera', value, '--confirm'])

    def test_invalid_duration(self):
        for value in ('0', '-1', 'nan', 'inf'):
            with self.subTest(value=value), self.assertRaises(cli.ControlError):
                cli.parser().parse_args(['audio', 'play', 'camera', 'file.wav', '--duration', value])

    def test_help_formats_without_error(self):
        with patch('sys.stdout', io.StringIO()), self.assertRaises(SystemExit) as result:
            cli.parser().parse_args(['audio', 'speak', '--help'])
        self.assertEqual(result.exception.code, 0)

    def test_text_exclusive(self):
        with self.assertRaises(cli.ControlError):
            cli.parser().parse_args(['audio', 'speak', 'camera', '--text', 'a', '--text-file', 'x'])

    def test_no_truncation(self):
        text = 'Sir, this is a long message. ' * 1000
        self.assertEqual(audio.load_text(argparse.Namespace(text=text)), text)

    def test_stdin(self):
        with patch('sys.stdin', io.StringIO('Hello sir')):
            self.assertEqual(audio.load_text(argparse.Namespace(text=None, text_file='-')), 'Hello sir')

    def test_empty_text(self):
        with self.assertRaises(audio.AudioError):
            audio.load_text(argparse.Namespace(text='  '))


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(audio, 'ROOT', self.root).start()
        self.adapter = Mock()
        self.adapter.ControlError = cli.ControlError
        self.adapter.registry.return_value = {'camera': {'model': 'C230', 'host': '192.0.2.10'},
                                              'bell': {'model': 'D235', 'host': '192.0.2.11'}}
        self.adapter.device_lock.return_value = nullcontext()

    def args(self, *words):
        return cli.parser().parse_args(['audio', *words])

    def test_confirmation_precedes_credentials_and_network(self):
        with self.assertRaisesRegex(cli.ControlError, 'confirmation_required'):
            audio.execute_audio(self.args('speak', 'camera', '--text', 'test'), self.adapter)
        self.adapter.load_settings.assert_not_called()

    def test_uncommissioned_doorbell_rejected(self):
        with self.assertRaisesRegex(cli.ControlError, 'audio_model_not_commissioned'):
            audio.execute_audio(self.args('speak', 'bell', '--text', 'test', '--confirm'), self.adapter)
        self.adapter.load_settings.assert_not_called()

    def test_doorbell_confirmation_precedes_network(self):
        self.adapter.registry.return_value['bell']['hub'] = 'hub'
        with self.assertRaisesRegex(cli.ControlError, 'confirmation_required'):
            audio.execute_audio(self.args('speak', 'bell', '--text', 'test'), self.adapter)
        self.adapter.load_settings.assert_not_called()

    def test_doorbell_uses_direct_identity_and_both_locks(self):
        self.adapter.registry.return_value['bell']['hub'] = 'hub'
        self.adapter.device_lock.side_effect = lambda *_: nullcontext()
        self._mock_run()
        with patch.object(audio, 'identify_doorbell', new_callable=AsyncMock) as identity:
            result = audio.execute_audio(self.args('play', 'bell', __file__, '--confirm'), self.adapter)
        identity.assert_awaited_once()
        self.assertEqual(self.adapter.device_lock.call_args_list, [call('hub'), call('bell')])
        self.assertEqual(result['result'], 'audio_completed')
        self.assertTrue(audio.prepare.call_args.args[0].doorbell_padding)
        self.assertEqual(result['physical_verification'], 'not_assessed')
        self.session.close.assert_called_once()
        self.assertEqual(list((self.root/'.audio-runtime/bell').iterdir()), [])

    def test_doorbell_identity_requests_only_identity(self):
        import asyncio
        entry = {'model': 'D235', 'host': '192.0.2.11', 'hub': 'hub'}
        with patch('security_doorbell.execute', new_callable=AsyncMock,
                   return_value={'model': 'D235', 'doorbell_reachability': 'authenticated'}) as worker:
            asyncio.run(audio.identify_doorbell(entry, 'unused'))
        worker.assert_awaited_once_with('unused', entry=entry, command='identity')

    def test_doorbell_identity_mismatch_fails_before_transport(self):
        self.adapter.registry.return_value['bell']['hub'] = 'hub'
        self.adapter.device_lock.side_effect = lambda *_: nullcontext()
        self._mock_run()
        with patch('security_doorbell.execute', new_callable=AsyncMock,
                   return_value={'model': 'C230', 'doorbell_reachability': 'authenticated'}):
            with self.assertRaisesRegex(cli.ControlError, 'audio_identity_mismatch'):
                audio.execute_audio(self.args('speak', 'bell', '--text', 'test', '--confirm'), self.adapter)
        self.session.start.assert_not_called()

    def test_volume_save_and_read_offline(self):
        result = audio.execute_audio(self.args('volume', 'camera', '42', '--confirm'), self.adapter)
        self.assertEqual(result['volume'], 42)
        result = audio.execute_audio(self.args('volume', 'camera'), self.adapter)
        self.assertEqual(result['volume'], 42)
        self.assertEqual(result['scope'], 'digital_gain_future_sessions')
        self.adapter.load_settings.assert_not_called()

    def test_idle_stop(self):
        result = audio.execute_audio(self.args('stop', 'camera', '--confirm'), self.adapter)
        self.assertEqual(result['result'], 'audio_idle')

    def test_status_and_stop_use_matching_session(self):
        import os
        directory = audio.private_dir(audio.private_dir(self.root/'.audio-runtime')/'camera')
        audio.save_json(directory/'state.json', {'pid': os.getpid(), 'session': 'example',
                                               'phase': 'playing', 'volume': 30})
        result = audio.execute_audio(self.args('status', 'camera'), self.adapter)
        self.assertEqual(result['phase'], 'playing')
        self.assertNotIn('pid', result)
        result = audio.execute_audio(self.args('stop', 'camera', '--confirm'), self.adapter)
        self.assertEqual(result['result'], 'audio_stop_requested')
        self.assertEqual(audio.read_json(directory/'stop.json'), {'session': 'example'})

    def test_private_directory_required(self):
        (self.root/'bad').mkdir(mode=0o755)
        with self.assertRaises(audio.AudioError):
            audio.private_dir(self.root/'bad')

    def test_reject_symlink_runtime(self):
        (self.root/'target').mkdir(mode=0o700)
        (self.root/'link').symlink_to(self.root/'target')
        with self.assertRaises(audio.AudioError):
            audio.private_dir(self.root/'link')

    def test_native_microphone_does_not_change_speaker_codec(self):
        session = audio.CameraSession(self.root/'app', self.root, '192.0.2.10', 'secret',
                                      lambda: None, microphone16=True)
        self.assertTrue(session.microphone16)
        self.assertEqual(session.codec, 'pcma')
        session.request = Mock(return_value={})
        session.play(self.root/'sample.wav')
        self.assertIn('#audio=pcma#', session.request.call_args.args[0]['src'])
        self.assertNotIn('16000', session.request.call_args.args[0]['src'])

    def test_error_output_has_no_raw_secret(self):
        session = audio.CameraSession(self.root/'app', self.root, '192.0.2.10', 'secret', lambda: None)
        session.base = 'http://127.0.0.1:1/api/streams'
        session.opener = Mock()
        session.opener.open.side_effect = RuntimeError('secret tapo://credentials@private')
        with self.assertRaisesRegex(audio.AudioError, '^camera_audio_transport_failed$'):
            session.request({})

    def test_complete_session_cleans_temp_state(self):
        self._mock_run()
        result = audio.execute_audio(self.args('speak', 'camera', '--text', 'test', '--confirm'), self.adapter)
        self.assertEqual(result['result'], 'audio_completed')
        self.session.close.assert_called_once()
        directory = self.root/'.audio-runtime/camera'
        self.assertEqual(list(directory.iterdir()), [])

    def test_failed_play_reports_unknown_and_cleans(self):
        self._mock_run()
        patch.object(audio, 'playback_loop', side_effect=audio.AudioError('transport secret')).start()
        result = audio.execute_audio(self.args('speak', 'camera', '--text', 'test', '--confirm'), self.adapter)
        self.assertEqual(result['outcome'], 'unknown')
        self.assertNotIn('secret', json.dumps(result))
        self.session.close.assert_called_once()
        self.assertEqual(list((self.root/'.audio-runtime/camera').iterdir()), [])

    def test_start_failure_closes_session_and_cleans(self):
        self._mock_run()
        self.session.start.side_effect = audio.AudioError('camera_audio_transport_failed')
        with self.assertRaisesRegex(cli.ControlError, 'camera_audio_transport_failed'):
            audio.execute_audio(self.args('speak', 'camera', '--text', 'test', '--confirm'), self.adapter)
        self.session.close.assert_called_once()
        self.assertEqual(list((self.root/'.audio-runtime/camera').iterdir()), [])

    def test_stop_during_preparation(self):
        self._mock_run()
        patch.object(audio, 'prepare', side_effect=audio.Stopped).start()
        result = audio.execute_audio(self.args('speak', 'camera', '--text', 'test', '--confirm'), self.adapter)
        self.assertEqual(result['result'], 'audio_stopped')
        self.assertEqual(list((self.root/'.audio-runtime/camera').iterdir()), [])

    def test_keyboard_interrupt_cleans(self):
        self._mock_run()
        patch.object(audio, 'playback_loop', side_effect=KeyboardInterrupt).start()
        with self.assertRaises(KeyboardInterrupt):
            audio.execute_audio(self.args('speak', 'camera', '--text', 'test', '--confirm'), self.adapter)
        self.session.close.assert_called_once()
        self.assertEqual(list((self.root/'.audio-runtime/camera').iterdir()), [])

    def _mock_run(self):
        async def identity(*args):
            pass
        patch.object(audio, 'identify', identity).start()
        patch.object(audio, 'prepare', return_value=(self.root/'test.wav', 10)).start()
        self.session = Mock()
        patch.object(audio, 'CameraSession', return_value=self.session).start()
        patch.object(audio, 'playback_loop', return_value=('completed', 1)).start()


class PreparationTests(unittest.TestCase):
    def test_full_file_gain_and_restricted_protocols(self):
        import wave
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'original.wav'
            source.write_bytes(b'synthetic fixture')
            args = cli.parser().parse_args(['audio', 'play', 'camera', str(source)])
            commands = []
            def convert(command, check_stop):
                commands.append(command)
                with wave.open(command[-1], 'wb') as wav:
                    wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    wav.writeframes(b'\0' * 16000)
            with patch.object(audio, 'run_child', convert), patch.object(audio.shutil, 'which', return_value='/bin/ffmpeg'):
                output, seconds = audio.prepare(args, root, 25, lambda: None)
            self.assertEqual(seconds, 1)
            self.assertEqual(output, root/'playback.wav')
            self.assertNotIn('-t', commands[0])
            self.assertIn('volume=0.25', commands[0])
            self.assertEqual(commands[0][commands[0].index('-ar') + 1], '8000')
            self.assertIn('file,pipe', commands[0])
            self.assertIn('-format_whitelist', commands[0])
            args.doorbell_padding = True
            with patch.object(audio, 'run_child', convert), patch.object(audio.shutil, 'which', return_value='/bin/ffmpeg'):
                audio.prepare(args, root, 60, lambda: None)
            self.assertIn('volume=0.6,adelay=1500:all=1,apad=pad_dur=2', commands[1])

    def test_missing_local_file(self):
        with self.assertRaisesRegex(audio.AudioError, 'local_media_file_required'):
            audio.local_file('https://example.invalid/message.mp3')


if __name__ == '__main__':
    unittest.main()
