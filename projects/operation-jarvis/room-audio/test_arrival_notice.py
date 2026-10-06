import unittest
import io
import json
from types import SimpleNamespace
from unittest.mock import patch
import pi_room_audio_client as client_module
from room_audio_control import RoomAudioControl


class ArrivalPlaybackTests(unittest.TestCase):
    def make_client(self):
        client = client_module.RoomAudioTurnController(SimpleNamespace(
            server_url='http://127.0.0.1:8793', token='test', playback_device='PowerConf',
            bt_playback_drain_seconds=0))
        client.capture_online = True
        return client

    def test_playback_uses_configured_device(self):
        client = self.make_client()
        with patch.object(client_module.urllib.request, 'urlopen', return_value=io.BytesIO(
                json.dumps({'ok': True, 'audioWavBase64': 'test'}).encode())), \
                patch.object(client_module, 'play_response_audio') as play:
            client.start_arrival_notice()
            client._turn_thread.join(2)
            play.assert_called_once()
            self.assertEqual(play.call_args.kwargs['device'], 'PowerConf')
            self.assertFalse(client.is_busy())

    def test_busy_offline_followup_skip(self):
        for mode in ('busy', 'offline', 'followup'):
            client = self.make_client()
            if mode == 'busy': client._turn_id = 'occupied'
            if mode == 'offline': client.capture_online = False
            if mode == 'followup': client._reserved_followup = object()
            with patch.object(client_module.urllib.request, 'urlopen') as request:
                client.start_arrival_notice()
                request.assert_not_called()

    def test_master_off_suppresses_only_arrival_without_request(self):
        client = self.make_client()
        with patch.object(client_module.automatic_voice, 'current',
                return_value=client_module.automatic_voice.Policy(False, 'a'*32)), \
                patch.object(client_module.urllib.request, 'urlopen') as request:
            client.start_arrival_notice('a'*32)
            request.assert_not_called()
            self.assertFalse(client.is_busy())

    def test_off_on_during_synthesis_cannot_play_old_notice(self):
        client = self.make_client()
        with patch.object(client_module.automatic_voice, 'current',
                return_value=client_module.automatic_voice.Policy(True, 'a'*32)) as gate, \
                patch.object(client_module, 'play_response_audio') as play:
            def reply(*args, **kwargs):
                gate.return_value = client_module.automatic_voice.Policy(True, 'b'*32)
                return io.BytesIO(json.dumps({'ok': True, 'audioWavBase64': 'test'}).encode())
            with patch.object(client_module.urllib.request, 'urlopen', side_effect=reply) as request:
                client.start_arrival_notice('a'*32)
                client._turn_thread.join(2)
                request.assert_called_once()
                play.assert_not_called()
                self.assertFalse(client.is_busy())

    def test_network_failure_does_not_play_or_retry(self):
        client = self.make_client()
        with patch.object(client_module.urllib.request, 'urlopen', side_effect=TimeoutError) as request, \
                patch.object(client_module, 'play_response_audio') as play:
            client.start_arrival_notice()
            client._turn_thread.join(2)
            request.assert_called_once()
            play.assert_not_called()
            self.assertFalse(client.is_busy())


class ArrivalNoticeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.control = RoomAudioControl(clock=lambda: self.now)
        self.seq = 0

    def report(self, phase='idle', client='a' * 32):
        self.seq += 1
        return self.control.report({'clientID': client, 'sequence': self.seq,
            'phase': phase, 'turnID': None if phase == 'idle' else 'b' * 32})

    def test_offline_and_busy_skip(self):
        self.assertFalse(self.control.request_arrival()['accepted'])
        self.report('speaking')
        self.assertFalse(self.control.request_arrival()['accepted'])

    def test_deliver_once(self):
        self.report()
        self.assertTrue(self.control.request_arrival()['accepted'])
        self.assertFalse(self.control.request_arrival()['accepted'])
        self.assertTrue(self.report()['arrivalNotice'])
        self.assertNotIn('arrivalNotice', self.report())

    def test_off_on_invalidates_admitted_pending_notice(self):
        import room_audio_control
        with patch.object(room_audio_control.automatic_voice, 'current',
                return_value=room_audio_control.automatic_voice.Policy(True, 'a'*32)) as gate:
            self.report()
            self.assertTrue(self.control.request_arrival('a'*32)['accepted'])
            gate.return_value = room_audio_control.automatic_voice.Policy(True, 'b'*32)
            self.assertNotIn('arrivalNotice', self.report())
            self.assertIsNone(self.control.arrival)

    def test_expired_skip(self):
        self.report()
        self.control.request_arrival()
        self.now = 5
        self.assertNotIn('arrivalNotice', self.report())

    def test_busy_or_replaced_client_consumes(self):
        for phase, client in [('speaking', 'a' * 32), ('idle', 'c' * 32)]:
            self.setUp()
            self.report()
            self.control.request_arrival()
            self.assertNotIn('arrivalNotice', self.report(phase, client))
            self.assertNotIn('arrivalNotice', self.report('idle', client))
