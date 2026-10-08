"""Response-cache regressions: fixtures only, no agents/ASR/TTS/device activity."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from room_audio_server import RoomAudioBridge, RoomAudioHandler, RoomAudioHTTPServer


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 2000.0
        self.bridge = RoomAudioBridge.__new__(RoomAudioBridge)
        self.bridge._jobs_lock = threading.Lock()
        self.bridge._jobs = {}
        self.clock = patch('room_audio_server.time.monotonic', lambda: self.now)
        self.ttl = patch('room_audio_server.ASYNC_JOB_TTL_SECONDS', 900)
        self.clock.start()
        self.ttl.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.ttl.stop)

    def done(self, completed, created=0):
        return {'pending': False, 'status': 'done', 'createdMonotonic': created,
                'completedMonotonic': completed,
                'response': {'ok': True, 'pending': False, 'audioWavBase64': 'synthetic-payload'}}

    def test_prunes_expired_payloads_but_preserves_recent_results(self):
        expired = self.done(1000)
        recent = self.done(1500)
        self.bridge._jobs.update(expired=expired, recent=recent)
        self.bridge.prune_completed_jobs()
        self.assertEqual(self.bridge._jobs, {'recent': recent})
        self.assertEqual(recent['response']['audioWavBase64'], 'synthetic-payload')

    def test_pending_turn_survives_age_and_keeps_cancel_event(self):
        event = threading.Event()
        pending = {'pending': True, 'status': 'running', 'createdMonotonic': 0,
                   'cancelEvent': event}
        self.bridge._jobs['pending'] = pending
        self.bridge.prune_completed_jobs()
        self.assertIs(self.bridge._jobs['pending'], pending)
        self.assertFalse(event.is_set())

    def test_full_retry_ttl_begins_at_completion_not_creation(self):
        job = self.done(1900, created=0)
        self.bridge._jobs['long-turn'] = job
        self.bridge.prune_completed_jobs()
        self.assertIs(self.bridge._jobs['long-turn'], job)
        self.now = 2800
        self.bridge.prune_completed_jobs()
        self.assertIn('long-turn', self.bridge._jobs)
        self.now += .01
        self.bridge.prune_completed_jobs()
        self.assertNotIn('long-turn', self.bridge._jobs)

    def test_cancelled_timestamp_and_legacy_completed_fallback(self):
        self.bridge._jobs.update(
            old_cancel={'pending': False, 'cancelledMonotonic': 1000, 'createdMonotonic': 0},
            new_cancel={'pending': False, 'cancelledMonotonic': 1900, 'createdMonotonic': 0},
            old_legacy={'pending': False, 'createdMonotonic': 1000},
            new_legacy={'pending': False, 'createdMonotonic': 1900},
        )
        self.bridge.prune_completed_jobs()
        self.assertEqual(set(self.bridge._jobs), {'new_cancel', 'new_legacy'})

    def test_old_pending_turn_can_complete_and_remain_pollable(self):
        self.bridge._jobs['long-turn'] = {'pending': True, 'status': 'running',
                                          'createdMonotonic': 0}
        self.bridge.prune_completed_jobs()
        self.bridge._jobs['long-turn'].update(self.done(self.now, created=0))
        result = self.bridge.get_turn_result('long-turn')
        self.assertEqual(result['audioWavBase64'], 'synthetic-payload')
        self.assertFalse(result['pending'])

    def test_http_idle_housekeeping_reaps_without_any_requests(self):
        expired = self.done(1000)
        pending = {'pending': True, 'status': 'running', 'createdMonotonic': 0}
        self.bridge._jobs.update(expired=expired, pending=pending)
        server = RoomAudioHTTPServer(('127.0.0.1', 0), RoomAudioHandler)
        server.bridge = self.bridge
        worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        worker.start()
        try:
            deadline = time.perf_counter() + 1
            while 'expired' in self.bridge._jobs and time.perf_counter() < deadline:
                time.sleep(.005)
            self.assertNotIn('expired', self.bridge._jobs)
            self.assertIs(self.bridge._jobs['pending'], pending)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=1)
        self.assertFalse(worker.is_alive())

    def test_housekeeping_does_not_abort_sessions_or_touch_controls(self):
        fail = lambda *args, **kwargs: self.fail('Cache expiry must not control a session/device')
        self.bridge._session = SimpleNamespace(abort_active=fail, stop=fail)
        self.bridge.control = SimpleNamespace(status=fail)
        server = RoomAudioHTTPServer.__new__(RoomAudioHTTPServer)
        server.bridge = self.bridge
        server.service_actions()

    def test_housekeeping_allows_uninitialized_or_fixture_server(self):
        server = RoomAudioHTTPServer.__new__(RoomAudioHTTPServer)
        server.service_actions()
        server.bridge = SimpleNamespace()
        server.service_actions()


if __name__ == '__main__':
    unittest.main()
