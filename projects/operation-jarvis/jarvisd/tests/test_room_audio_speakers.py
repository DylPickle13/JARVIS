"""Room proxy selection with fake peers only: never play or stop live audio."""
import json
import unittest
from unittest import mock
from test_jarvisd import jarvisd as daemon


class RoomSpeakerTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(daemon.Handler)
        self.handler._send = mock.Mock()
        self.status = {'ok': True, 'clientOnline': True, 'phase': 'speaking',
                       'turnID': 'a'*32, 'canStop': True, 'ageSeconds': 1, 'transcript': 'must not escape'}

    def connection(self, status=200):
        conn = mock.Mock(); conn.getresponse.return_value.status = status
        conn.getresponse.return_value.read.return_value = json.dumps(self.status).encode()
        return conn

    def test_named_status_uses_only_fixed_selected_port_and_sanitizes(self):
        for speaker, port in [('pi',8791),('mac',8793)]:
            conn=self.connection()
            with mock.patch.object(daemon.http.client,'HTTPConnection',return_value=conn) as factory:
                self.handler._room_audio(speaker_id=speaker)
            factory.assert_called_once_with('127.0.0.1',port,timeout=2)
            self.assertEqual(conn.request.call_args.args[:2],('GET','/control/status'))
            code,body=self.handler._send.call_args.args
            self.assertEqual(code,200);self.assertEqual(body['speakerID'],speaker)
            self.assertNotIn('transcript',body)

    def test_stop_preserves_selected_speaker_and_exact_turn(self):
        for speaker,port in [('pi',8791),('mac',8793)]:
            conn=self.connection()
            with mock.patch.object(daemon.http.client,'HTTPConnection',return_value=conn) as factory:
                self.handler._room_audio('b'*32,speaker_id=speaker)
            factory.assert_called_once_with('127.0.0.1',port,timeout=2)
            self.assertEqual(conn.request.call_args.args[:2],('POST','/control/stop'))
            self.assertEqual(json.loads(conn.request.call_args.kwargs['body']),{'turnID':'b'*32})

    def test_mac_failure_never_falls_back_to_pi(self):
        with mock.patch.object(daemon.http.client,'HTTPConnection',side_effect=OSError('offline')) as factory:
            self.handler._room_audio(speaker_id='mac')
        factory.assert_called_once_with('127.0.0.1',8793,timeout=2)
        self.assertEqual(self.handler._send.call_args.args[0],503)

    def test_unknown_speaker_never_connects(self):
        with mock.patch.object(daemon.http.client,'HTTPConnection') as factory:
            self.handler._room_audio('a'*32,speaker_id='other/pi')
        factory.assert_not_called();self.assertEqual(self.handler._send.call_args.args[0],400)

    def test_changed_turn_is_not_retried_or_sent_to_other_speaker(self):
        conn=self.connection(409)
        with mock.patch.object(daemon.http.client,'HTTPConnection',return_value=conn) as factory:
            self.handler._room_audio('a'*32,speaker_id='mac')
        factory.assert_called_once();conn.request.assert_called_once()
        self.assertEqual(self.handler._send.call_args.args[0],409)

    def test_legacy_status_still_selects_pi(self):
        with mock.patch.object(daemon.http.client,'HTTPConnection',return_value=self.connection()) as factory:
            self.handler._room_audio()
        factory.assert_called_once_with('127.0.0.1',8791,timeout=2)
