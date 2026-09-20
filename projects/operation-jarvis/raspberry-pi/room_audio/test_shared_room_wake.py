import base64
import tempfile
import threading
import unittest
from pathlib import Path

from shared_room_wake import Coordinator, RemoteWakeDetector, WakeServer, Handler


class Detector:
    def __init__(self):
        self.last_score = 0.0
        self.last_model = ''
        self.frames = []
        self.hit = None
        self.resets = 0

    def reset_stream(self):
        self.resets += 1
        self.last_score = 0.0
        self.last_model = ''

    def process_frame(self, frame, **kwargs):
        self.frames.append(frame)
        hit, self.hit = self.hit, None
        return hit


def frame(room, loud=True):
    pcm = (b'\xe8\x03' if loud else b'\0\0') * 1280
    return dict(room=room, op='frame', rate=16000, pcm=base64.b64encode(pcm).decode())


class SharedWakeTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = Detector(), Detector()
        self.now = 100.0
        self.c = Coordinator({'a': self.a, 'b': self.b}, clock=lambda: self.now)

    def claim(self):
        self.a.hit = {'model': 'jarvis', 'score': 0.9}
        self.assertIsNotNone(self.c.handle(frame('a'))['hit'])

    def test_silence_skips_inference_and_preroll_is_bounded(self):
        for _ in range(200):
            self.c.handle(frame('a', False))
            self.now += 0.08
        self.assertEqual(self.a.frames, [])
        self.assertLessEqual(self.c.rooms['a'].pending_seconds, 0.4)
        self.c.handle(frame('a'))
        self.assertGreater(len(self.a.frames), 1)
        self.assertLessEqual(len(self.a.frames), 6)

    def test_first_wake_wins_and_other_room_does_not_infer(self):
        self.claim()
        self.b.hit = {'model': 'jarvis', 'score': 0.99}
        self.assertFalse(self.c.handle(frame('b'))['allowed'])
        self.assertEqual(self.b.frames, [])
        self.assertEqual(self.c.owner, 'a')

    def test_idle_or_dead_client_lease_expires(self):
        self.claim()
        self.now += 8.1
        result = self.c.handle(frame('b'))
        self.assertTrue(result['allowed'])
        self.assertIsNone(self.c.owner)
        self.assertTrue(self.b.frames)

    def test_activity_renews_only_owner(self):
        self.claim()
        self.now += 7
        self.c.handle(dict(room='b', op='activity', active=True))
        self.assertEqual(self.c.deadline, 108)
        self.c.handle(dict(room='a', op='activity', active=True))
        self.assertEqual(self.c.deadline, 115)
        self.now += 2
        self.assertFalse(self.c.handle(frame('b'))['allowed'])

    def test_active_conversation_recovers_after_worker_restart(self):
        result = self.c.handle(dict(room='a', op='activity', active=True))
        self.assertTrue(result['allowed'])
        self.assertEqual(self.c.owner, 'a')
        self.assertFalse(self.c.handle(frame('b'))['allowed'])

    def test_reset_does_not_release_active_conversation(self):
        self.claim()
        self.c.handle(dict(room='a', op='reset'))
        self.assertEqual(self.c.owner, 'a')

    def test_quiet_transition_resets_once_and_replays_context(self):
        self.c.handle(frame('a'))
        self.now += 1.1
        self.c.handle(frame('a', False))
        resets = self.a.resets
        for _ in range(10):
            self.c.handle(frame('a', False))
        self.assertEqual(self.a.resets, resets)
        self.assertEqual(resets, 1)

    def test_reject_unknown_room_bad_rate_and_oversized_pcm(self):
        with self.assertRaises(ValueError):
            self.c.handle(frame('intruder'))
        request = frame('a')
        request['rate'] = 0
        with self.assertRaises(ValueError):
            self.c.handle(request)
        request['rate'] = 16000
        request['pcm'] = base64.b64encode(b'\0' * 32002).decode()
        with self.assertRaises(ValueError):
            self.c.handle(request)

    def test_remote_adapter_and_worker_loss_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'wake.sock')
            with WakeServer(path, Handler) as server:
                server.coordinator = self.c
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                remote = RemoteWakeDetector(path, 'a')
                remote.reset_stream()
                self.a.hit = {'score': 0.9, 'model': 'jarvis'}
                hit = remote.process_frame(b'\xe8\x03' * 1280, source_rate=16000, now=100)
                self.assertEqual(hit['score'], 0.9)
                remote.update_activity(True, 100)
                remote.close()
                self.assertFalse(remote.allowed)
                server.shutdown()
                thread.join()
            with self.assertRaises(OSError):
                remote.reset_stream()
            self.assertFalse(remote.allowed)

    def test_existing_gate_accepts_shared_adapter(self):
        from pi_room_audio_client import LocalWakeWordGate
        detector = Detector()
        gate = LocalWakeWordGate(detector, 3)
        detector.hit = {'score': 0.9}
        gate.process_frame(b'\0\0', source_rate=16000, now=100, busy=False)
        self.assertTrue(gate.accepts(101))
        gate.process_frame(b'\0\0', source_rate=16000, now=101, busy=True)
        self.assertFalse(gate.accepts(101))


if __name__ == '__main__':
    unittest.main()
