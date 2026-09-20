"""Offline event staging checks; no camera access or notification delivery."""
from contextlib import nullcontext
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

import security_cli as cli
import security_events as events


class EventTests(unittest.TestCase):
    def response(self, rows):
        return {'playback': {'search_detection_list': rows}}

    def row(self, **extra):
        return {'start_time': 100, 'end_time': 110, 'event_type': 7, **extra}

    def args(self, operation='status', minutes=10):
        return cli.parser().parse_args(['events', 'bell', operation, '--minutes', str(minutes)])

    def test_no_delivery_or_button_claim_in_status(self):
        result = events.status()
        self.assertFalse(result['delivery_enabled'])
        self.assertFalse(result['background_listener'])
        self.assertEqual(result['button_mapping'], 'unverified')

    def test_sanitizes_and_deduplicates_without_guessing_type(self):
        row = self.row(password='DO_NOT_PRINT', device_id='DO_NOT_PRINT')
        result = events.normalize(self.response([row, row]), 90, 120)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['kind'], 'unknown')
        self.assertNotIn('DO_NOT_PRINT', json.dumps(result))
        self.assertEqual(events.preview(result)[0]['decision'], 'suppressed')

    def test_unknown_text_type_never_exposed_or_mapped(self):
        result = events.normalize(self.response([self.row(event_type='DO_NOT_PRINT')]), 90, 120)
        self.assertIsNone(result[0]['type_code'])
        self.assertNotIn('DO_NOT_PRINT', json.dumps(result))

    def test_empty_is_not_synthesized_event(self):
        self.assertEqual(events.normalize(self.response([]), 90, 120), [])
        self.assertEqual(events.preview([]), [])

    def test_invalid_rows_and_shapes_fail_closed(self):
        for response in ({}, {'playback': None}, self.response(None), self.response([None]),
                         self.response([self.row(start_time=True)]),
                         self.response([self.row(end_time=99)]),
                         self.response([self.row()] * 21)):
            with self.subTest(response=response), self.assertRaises(cli.ControlError):
                events.normalize(response, 90, 120)

    def test_out_of_window_not_treated_as_new(self):
        for row in (self.row(end_time=130), self.row(start_time=20, end_time=30)):
            with self.assertRaisesRegex(cli.ControlError, 'event_time_unverified'):
                events.normalize(self.response([row]), 90, 120)

    def test_invalid_window_before_registry(self):
        with patch.object(cli, 'registry') as registry:
            with self.assertRaisesRegex(cli.ControlError, 'invalid_event_window'):
                events.execute_events(self.args(minutes=61))
        registry.assert_not_called()

    def test_status_offline(self):
        entry = {'model': 'D235', 'host': '192.0.2.1', 'hub': 'hub'}
        with patch.object(cli, 'registry', return_value={'bell': entry}), \
                patch('security_doorbell.execute', new_callable=AsyncMock) as worker:
            result = events.execute_events(self.args())
        worker.assert_not_awaited()
        self.assertFalse(result['delivery_enabled'])

    def test_preview_locks_and_never_delivers(self):
        entry = {'model': 'D235', 'host': '192.0.2.1', 'hub': 'hub'}
        rows = events.normalize(self.response([self.row()]), 90, 120)
        with patch.object(cli, 'registry', return_value={'bell': entry}), \
                patch.object(cli, 'device_lock', side_effect=lambda _: nullcontext()) as locks, \
                patch('security_doorbell.execute', new_callable=AsyncMock,
                      return_value={**events.status(), 'events': rows}) as worker:
            result = events.execute_events(self.args('preview'))
        self.assertEqual([c.args[0] for c in locks.call_args_list], ['hub', 'bell'])
        self.assertEqual(worker.await_args.kwargs['command'], 'events')
        self.assertEqual(result['notification_preview'][0]['decision'], 'suppressed')

    def test_worker_is_bounded_and_closes_hub(self):
        hub = Mock()
        hub.executeFunction.return_value = self.response([])
        settings = Mock(missing=None)
        with patch('security_recording.archive_client', return_value=hub), \
                patch('security_recording.camera_from_hub', return_value={'device_id': 'private', 'mac': 'private'}), \
                patch.object(cli, 'load_settings', return_value=settings), \
                patch.object(events.time, 'time', return_value=1000):
            result = events.run({'model': 'D235', 'host': '192.0.2.1'}, 'unused', value=10)
        hub.close.assert_called_once()
        method, payload = hub.executeFunction.call_args.args
        self.assertEqual(method, 'searchDetectionList')
        self.assertEqual(payload['playback']['search_detection_list']['end_index'], 19)
        self.assertTrue(result['empty_does_not_prove_no_activity'])
        self.assertNotIn('private', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
