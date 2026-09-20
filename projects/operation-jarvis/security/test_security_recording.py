"""Offline recording tests; no network, device writes or real media."""
import json
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import Mock, AsyncMock, patch

import security_cli as cli
import security_recording as r


def plan(kind='2', enabled='on'):
    return {'enabled': enabled, **{day: json.dumps([f'0000-2400:{kind}']) for day in r.DAYS}}


def camera(kind='2', power='wired_always_on', storage='online'):
    client = Mock()
    client.getRecordPlan.return_value = plan(kind)
    client.getPowerMode.return_value = {'battery': {'power': {'mode': power}}}
    client.getHubStorage.return_value = {'hub_manage': {'hub_storage_info': {'enabled': 'on', 'status': storage}}}
    return client


class RecordingTests(unittest.TestCase):
    def test_schedule_strict(self):
        valid = {day: ['0000-0600:1', '0800-2400:2'] for day in r.DAYS}
        self.assertEqual(r.schedule(valid), valid)
        for invalid in ({}, {'monday': []}, {**valid, 'password': 'secret'},
                        {**valid, 'monday': ['0060-2400:1']},
                        {**valid, 'monday': ['0000-2500:1']},
                        {**valid, 'monday': ['2400-2400:1']},
                        {**valid, 'monday': ['0000-1200:1', '1000-2400:2']},
                        {**valid, 'monday': ['0000-2400:3']},
                        {**valid, 'monday': ['0000-2400:1'] * 11}):
            with self.subTest(invalid=invalid), self.assertRaises(cli.ControlError):
                r.schedule(invalid)

    def test_confirm_gates_and_commands(self):
        for mode in ('continuous', 'events', 'schedule'):
            with self.assertRaises(cli.ControlError):
                r.validate('recording', mode, {}, False)
        r.validate('recording', 'status', None, False)
        with self.assertRaises(cli.ControlError):
            r.validate('clip', None, {}, False)
        for command in ('recording', 'recordings', 'clip'):
            with self.assertRaises(cli.ControlError):
                cli.validate_request('C230', command, 'status', None, True, False)

    def test_parse_timestamp_requires_timezone(self):
        self.assertEqual(r.timestamp('2026-09-20T12:00:00-04:00'), r.timestamp('2026-09-20T16:00:00Z'))
        for value in ('2026-09-20T12:00:00', True, None, 'yesterday'):
            with self.assertRaises(cli.ControlError):
                r.timestamp(value)

    def test_interval_bounds(self):
        self.assertEqual(r.interval({'start': 900, 'end': 910}, clip=True, now=1000), (900, 910))
        for value in ({'start': 900, 'end': 920}, {'start': 960, 'end': 970},
                      {'start': 900, 'end': 899}, {'start': -100000, 'end': 0}):
            with self.assertRaises(cli.ControlError):
                r.interval(value, clip=True, now=1000)

    def test_status_no_writes(self):
        c = camera()
        result = r.plan_operation(c, 'status', None)
        self.assertEqual(result['recording']['mode'], 'events')
        c.setRecordPlan.assert_not_called()

    def test_power_and_storage_gates(self):
        for c in (camera(power='battery'), camera(storage='offline')):
            with self.assertRaises(cli.ControlError):
                r.plan_operation(c, 'continuous', None)
            c.setRecordPlan.assert_not_called()
        mixed = {day: ['0000-2400:2'] for day in r.DAYS}
        mixed['monday'] = ['0000-0100:1']
        c = camera(power='battery')
        with self.assertRaises(cli.ControlError):
            r.plan_operation(c, 'schedule', mixed)
        c.setRecordPlan.assert_not_called()

    def test_verified_schedule_and_idempotence(self):
        c = camera()
        c.getRecordPlan.side_effect = [plan('2'), plan('1')]
        result = r.plan_operation(c, 'continuous', None)
        self.assertEqual(result['result'], 'verified')
        self.assertTrue(result['changed'])
        c.setRecordPlan.assert_called_once_with(True, **{day: ['0000-2400:1'] for day in r.DAYS})
        c = camera('1')
        self.assertFalse(r.plan_operation(c, 'continuous', None)['changed'])
        c.setRecordPlan.assert_not_called()

    def test_event_mode_does_not_require_always_on(self):
        c = camera('1', power='battery')
        c.getRecordPlan.side_effect = [plan('1'), plan('2')]
        self.assertEqual(r.plan_operation(c, 'events', None)['recording']['mode'], 'events')

    def test_write_failure_no_retry_and_unknown(self):
        c = camera()
        c.setRecordPlan.side_effect = RuntimeError('secret')
        with self.assertRaisesRegex(cli.ControlError, '^write_outcome_unknown$'):
            r.plan_operation(c, 'continuous', None)
        c.setRecordPlan.assert_called_once()
        c = camera()
        self.assertEqual(r.plan_operation(c, 'continuous', None)['outcome'], 'unknown')
        c.setRecordPlan.assert_called_once()

    def test_archive_redaction_and_bad_shapes(self):
        response = {'playback': {'search_video_results': [{'search_video_results_1': {
            'startTime': 100, 'endTime': 200, 'video_type': '1', 'mac': 'SECRET', 'url': 'SECRET'}}]}}
        clips = r.parse_clips(response, 110, 190)
        self.assertEqual(clips[0]['recording_type'], 'continuous')
        self.assertNotIn('SECRET', json.dumps(clips))
        for invalid in ({}, {'playback': {'search_video_results': None}},
                        {'playback': {'search_video_results': [{'bad': {}}]}}):
            with self.assertRaises(cli.ControlError):
                r.parse_clips(invalid, 110, 190)

    def test_missing_or_duplicate_doorbell_fails(self):
        h = Mock()
        for cameras in ([], [{'device_model': 'C230'}], [{'device_model': 'D235'}] * 2):
            h.executeFunction.return_value = {'general_camera_manage': {'paired_general_device_list': cameras}}
            with self.assertRaises(cli.ControlError):
                r.camera_from_hub(h)

    def test_archive_directory_privacy(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'ROOT', Path(tmp)):
            path = r.private_output()
            self.assertTrue(path.name.endswith('.partial.ts'))
            self.assertEqual(path.parent.stat().st_mode & 0o077, 0)
            path.parent.chmod(0o755)
            with self.assertRaisesRegex(cli.ControlError, 'archive_directory_not_private'):
                r.private_output()

    def test_download_complete_and_partial_cleanup(self):
        for complete in (True, False):
            with self.subTest(complete=complete), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'test.partial.ts'
                async def download(*args):
                    args[-1].write_bytes(b'synthetic')
                    return {'complete': complete, 'bytes': 9}
                h = Mock()
                with patch.object(r, 'interval', return_value=(100, 105)), \
                     patch.object(r, 'load_settings', return_value=cli.Settings(
                         host='192.168.1.2', username='synthetic', password='synthetic')), \
                     patch.object(r, 'archive_client', return_value=h), \
                     patch.object(r, 'camera_from_hub', return_value={'model': 'D235'}), \
                     patch.object(r, 'query_clips', return_value=[{'start': 90, 'end': 110}]), \
                     patch.object(r, 'private_output', return_value=output), \
                     patch.object(r, 'verify_video', return_value={'video_decode_verified': True}), \
                     patch.object(r.os, 'umask'), \
                     patch.dict('sys.modules', {'archive_download_probe': types.SimpleNamespace(download=download)}):
                    if complete:
                        result = r.archive_operation('unused', 'clip', {})
                        self.assertTrue(result['download_complete'])
                        self.assertTrue(result['video_decode_verified'])
                        self.assertTrue(Path(result['path']).exists())
                    else:
                        with self.assertRaisesRegex(cli.ControlError, 'clip_download_incomplete'):
                            r.archive_operation('unused', 'clip', {})
                    self.assertFalse(output.exists())
                    h.close.assert_called_once()

    def test_download_requires_index_coverage(self):
        h = Mock()
        with patch.object(r, 'interval', return_value=(100, 105)), \
             patch.object(r, 'load_settings', return_value=cli.Settings(
                 host='192.168.1.2', username='synthetic', password='synthetic')), \
             patch.object(r, 'archive_client', return_value=h), \
             patch.object(r, 'camera_from_hub', return_value={}), \
             patch.object(r, 'query_clips', return_value=[]), \
             patch.object(r, 'private_output') as output:
            with self.assertRaisesRegex(cli.ControlError, 'clip_not_covered_by_archive_index'):
                r.archive_operation('unused', 'clip', {})
            output.assert_not_called()
            h.close.assert_called_once()

    def test_video_verification_requires_decoded_frames(self):
        with patch.object(r.shutil, 'which', return_value=None):
            self.assertFalse(r.verify_video(Path('unused'))['video_decode_verified'])
        for frames, good in (('frame=5\n', True), ('frame=0\n', False), ('', False)):
            with patch.object(r.shutil, 'which', return_value='/synthetic/decoder'), \
                 patch.object(r.subprocess, 'run', side_effect=[
                     types.SimpleNamespace(returncode=0, stdout=json.dumps({'streams': [
                         {'codec_name': 'hevc', 'width': 2560, 'height': 1920}]})),
                     types.SimpleNamespace(returncode=0, stdout=frames)]) as run:
                result = r.verify_video(Path('unused'))
                self.assertEqual(result['video_decode_verified'], good)
                self.assertEqual(result['audio_decode'], 'not_assessed')
                for call in run.call_args_list:
                    self.assertIn('file,pipe', call.args[0])

    def test_parser_commands(self):
        args = cli.parser().parse_args(['recording', 'front-doorbell', 'continuous', '--confirm'])
        self.assertEqual(args.name, 'continuous')
        self.assertTrue(args.confirm)
        args = cli.parser().parse_args(['recordings', 'front-doorbell'])
        self.assertEqual(args.command, 'recordings')
        with self.assertRaises(cli.ControlError):
            cli.parser().parse_args(['clip', 'front-doorbell'])


if __name__ == '__main__':
    unittest.main()
