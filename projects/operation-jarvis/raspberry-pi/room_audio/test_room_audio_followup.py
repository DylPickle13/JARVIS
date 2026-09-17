"""Two-part wake/prompt/request protocol and continuous-capture client tests."""
import base64
import contextlib
import http.client
import io
import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pi_room_audio_client as client
import room_audio_server as server
from room_audio_followup import WakeFollowups
import test_room_wake_verification as wake_tests


class FollowupStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.store = WakeFollowups(clock=lambda: self.now)
        self.ticket = self.store.issue('peer/client', 'wake-1234')

    def ready_claim(self):
        self.assertTrue(self.store.transition(self.ticket, 'peer/client', 'ready'))
        self.assertTrue(self.store.transition(self.ticket, 'peer/client', 'claim'))

    def test_no_command_before_prompt_finishes_and_speech_starts(self):
        self.assertFalse(self.store.consume(self.ticket, 'peer/client'))
        self.assertFalse(self.store.transition(self.ticket, 'peer/client', 'claim'))
        self.assertTrue(self.store.transition(self.ticket, 'peer/client', 'ready'))
        self.assertFalse(self.store.consume(self.ticket, 'peer/client'))
        self.assertFalse(self.store.transition(self.ticket, 'peer/client', 'ready'))
        self.assertTrue(self.store.transition(self.ticket, 'peer/client', 'claim'))
        self.assertTrue(self.store.consume(self.ticket, 'peer/client'))
        self.assertFalse(self.store.consume(self.ticket, 'peer/client'))

    def test_window_starts_after_playback_not_verification(self):
        self.now += 20
        self.assertTrue(self.store.transition(self.ticket, 'peer/client', 'ready'))
        self.now += 4.9
        self.assertTrue(self.store.transition(self.ticket, 'peer/client', 'claim'))
        self.now += 30
        self.assertTrue(self.store.consume(self.ticket, 'peer/client'))

    def test_expired_prompt_listening_and_command_are_rejected(self):
        self.now += 30
        self.assertFalse(self.store.transition(self.ticket, 'peer/client', 'ready'))
        self.ticket = self.store.issue('peer/client', 'wake-1234')
        self.assertTrue(self.store.transition(self.ticket, 'peer/client', 'ready'))
        self.now += 5
        self.assertFalse(self.store.transition(self.ticket, 'peer/client', 'claim'))
        self.ticket = self.store.issue('peer/client', 'wake-1234')
        self.ready_claim()
        self.now += 40
        self.assertFalse(self.store.consume(self.ticket, 'peer/client'))

    def test_client_binding_does_not_burn_rightful_ticket(self):
        for peer in ('peer/other', 'other/client'):
            self.assertFalse(self.store.transition(self.ticket, peer, 'ready'))
            self.assertFalse(self.store.transition(self.ticket, peer, 'cancel'))
        self.ready_claim()
        self.assertFalse(self.store.consume(self.ticket, 'peer/other'))
        self.assertTrue(self.store.consume(self.ticket, 'peer/client'))

    def test_new_wake_and_cancellation_revoke_old_ticket(self):
        self.ready_claim()
        new = self.store.issue('peer/client', 'wake-5678')
        self.assertFalse(self.store.consume(self.ticket, 'peer/client'))
        self.assertTrue(self.store.has_turn('wake-5678'))
        self.store.revoke_turn('wake-5678')
        self.assertFalse(self.store.has_turn('wake-5678'))
        self.assertFalse(self.store.transition(new, 'peer/client', 'ready'))

    def test_atomic_single_use_under_race(self):
        self.ready_claim()
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.store.consume(self.ticket, 'peer/client'))) for _ in range(12)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(results), 1)

    def test_restart_forgets_all_authorizations(self):
        self.ready_claim()
        self.assertFalse(WakeFollowups().consume(self.ticket, 'peer/client'))


class FollowupClientTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(server_url='http://unused', token='', rate=16000,
                                    playback_device='unused', bt_playback_drain_seconds=0)
        self.controller = client.RoomAudioTurnController(self.args)
        self.response = {'ok': True, 'accepted': True, 'pending': False,
                         'status': 'awaiting_command', 'wakeTicket': 'test-private-ticket',
                         'audioWavBase64': 'audio', 'listenSeconds': 5}

    def test_prompt_is_played_before_followup_is_armed_and_ticket_is_not_logged(self):
        calls = Mock()
        with patch.object(client, 'post_turn', return_value=self.response) as post, \
             patch.object(client, 'play_response_audio') as playback, \
             patch.object(self.controller, 'arm_followup') as arm, \
             patch.object(client, 'wait_for_final_response_controlled') as wait, \
             contextlib.redirect_stdout(io.StringIO()) as log:
            calls.attach_mock(playback, 'play'); calls.attach_mock(arm, 'arm')
            client.process_vad_utterance_controlled(self.args, b'\0' * 3200, duration_seconds=.1,
                voiced_ms=100, max_rms=400, require_wake_word=True, turn_id='wake-turn',
                cancel_event=threading.Event(), controller=self.controller)
            self.assertEqual([c[0] for c in calls.mock_calls], ['play', 'arm'])
            self.assertEqual(post.call_args.kwargs['client_id'], self.controller._client_id)
            wait.assert_not_called()
            self.assertNotIn('test-private-ticket', log.getvalue())

    def test_ready_then_single_claim_at_speech_start(self):
        with patch.object(client, 'post_wake_followup', return_value={'ok': True, 'listenSeconds': 5}) as post:
            self.controller.arm_followup(self.response, threading.Event())
            claim = self.controller.reserve_followup(time.monotonic())
            self.assertIsNotNone(claim)
            self.assertTrue(claim.done.wait(1))
            self.assertTrue(claim.accepted)
            self.assertIsNone(self.controller.reserve_followup(time.monotonic()))
            self.assertEqual([c.args[-1] for c in post.call_args_list], ['ready', 'claim'])

    def test_expired_or_busy_client_cannot_claim(self):
        self.controller._followup_ticket = 'ticket'
        self.controller._followup_deadline = 10
        with patch.object(self.controller, '_revoke_followup') as revoke:
            self.assertIsNone(self.controller.reserve_followup(10))
            revoke.assert_called_once_with('ticket')
        self.controller._followup_ticket = 'new-ticket'
        self.controller._turn_id = 'busy-turn'
        self.assertIsNone(self.controller.reserve_followup(1))

    def test_cancellation_during_ready_does_not_arm(self):
        cancel = threading.Event()
        def ready(*args):
            cancel.set()
            return {'ok': True, 'listenSeconds': 5}
        with patch.object(client, 'post_wake_followup', side_effect=ready), \
             patch.object(self.controller, '_revoke_followup') as revoke:
            self.controller.arm_followup(self.response, cancel)
            self.assertEqual(self.controller._followup_ticket, '')
            revoke.assert_called_once_with('test-private-ticket')

    def test_failed_claim_drops_command_without_upload(self):
        claim = client.FollowupClaim('ticket'); claim.done.set()
        with patch.object(client, 'process_vad_utterance_controlled') as upload, \
             patch.object(self.controller, '_revoke_followup'):
            self.controller._run_turn('turn-123', threading.Event(), b'pcm', 1, 500, 400, False, claim)
            upload.assert_not_called()

    def test_claim_network_request_does_not_block_capture_thread(self):
        release = threading.Event()
        self.controller._followup_ticket = 'ticket'
        self.controller._followup_deadline = time.monotonic() + 5
        def slow(*args):
            release.wait(2)
            return {'ok': True}
        with patch.object(client, 'post_wake_followup', side_effect=slow):
            started = time.monotonic()
            claim = self.controller.reserve_followup(started)
            elapsed = time.monotonic() - started
            release.set()
            self.assertTrue(claim.done.wait(1))
            self.assertLess(elapsed, .5)


class FollowupHTTPTests(unittest.TestCase):
    def setUp(self):
        self.bridge = wake_tests.WakeVerificationTests().make_bridge('Hey Jarvis turn on the light')
        self.server = server.RoomAudioHTTPServer(('127.0.0.1', 0), server.RoomAudioHandler)
        self.server.token = 'fixture'
        self.server.max_request_bytes = 100000
        self.server.bridge = self.bridge
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, path, payload, token='fixture'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        conn.request('POST', path, json.dumps(payload), {'content-type': 'application/json', 'x-jarvis-room-token': token})
        response = conn.getresponse(); result = json.loads(response.read()); conn.close()
        return response.status, result

    def test_two_parts_over_http_and_no_one_shot_execution(self):
        body = dict(clientID='a'*32, turnId='b'*32, wakeFollowupSupported=True,
                    audioWavBase64=base64.b64encode(b'test').decode(), asyncAck=True)
        status, wake = self.request('/turn', body)
        self.assertEqual(status, 200)
        self.assertEqual(wake['ackText'], 'Yes sir?')
        self.bridge._pipeline.transcribe_audio.assert_not_called()
        control = dict(clientID='a'*32, wakeTicket=wake['wakeTicket'], action='ready')
        self.assertEqual(self.request('/wake-followup', control, token='')[0], 401)
        self.assertEqual(self.request('/wake-followup', {**control, 'clientID': 'c'*32})[0], 409)
        self.assertEqual(self.request('/wake-followup', control)[0], 200)
        control['action'] = 'claim'
        self.assertEqual(self.request('/wake-followup', control)[0], 200)
        body.update(wakeTicket=wake['wakeTicket'], turnId='d'*32, asyncAck=False)
        status, result = self.request('/turn', body)
        self.assertEqual(status, 200)
        self.assertTrue(result['accepted'])
        self.bridge._pipeline.transcribe_audio.assert_called_once()
        self.assertEqual(self.request('/turn', body)[1]['reason'], 'invalid_wake_authorization')


if __name__ == '__main__':
    unittest.main()
