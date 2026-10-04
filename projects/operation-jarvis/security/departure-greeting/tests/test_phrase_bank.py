"""Protected farewell-bank tests. All household I/O is mocked."""
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import departure
import runtime
import speaker
import phrase_bank
from test_phrase_banks import fixture_bundle, save_manifest

banks = phrase_bank.phrase_banks


class DepartureBankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = runtime.private_dir(Path(self.tmp.name) / 'departure')
        self.assets = Path(self.tmp.name) / 'assets'
        self.pin, self.manifest = fixture_bundle(self.assets)
        self.selector = banks.Selector(Path(self.tmp.name) / 'state' / 'selection.sqlite3')
        self.patch_selector = mock.patch.object(banks, 'Selector', return_value=self.selector)
        self.patch_selector.start()
        self.addCleanup(self.patch_selector.stop)
        self.value = {'version': 1, 'enabled': True, 'motion_device': 'motion-sensor',
            'door_device': 'door-sensor', 'speaker_device': 'front-doorbell', 'volume': 60}
        runtime.save_json(self.root / 'config.json', self.value)
        runtime.save_json(self.root / 'state.json', runtime.default_state())
        self.journal = runtime.Journal(self.root)
        self.journal.reserve('fixture-attempt', 100)
        self.request = {'attempt': 'fixture-attempt', 'expires': 110}
        self.devices = {'front-doorbell': {'model': 'D235', 'host': '192.0.2.1', 'hub': 'hub'},
                       'motion-sensor': {'model': 'T100', 'hub': 'hub'}}

    def enable(self, pin=None):
        runtime.save_json(self.root / 'phrase-bank.json', {'version': 1, 'bundle': str(self.assets),
            'manifest_sha256': pin or self.pin})

    def test_default_does_not_load_or_select_any_bank(self):
        with mock.patch.object(banks, 'Bundle') as bundle:
            self.assertIsNone(phrase_bank.select(self.root, 'fixture-attempt', 110))
        bundle.assert_not_called()

    def test_selection_is_bound_to_attempt_and_repeat_worker_cannot_replay(self):
        self.enable()
        clip = phrase_bank.select(self.root, 'fixture-attempt', 110)
        record = runtime.read_json(self.root / 'phrase-selection.json')
        self.assertEqual(record['attempt'], 'fixture-attempt')
        self.assertEqual(record['sha256'], clip.sha256)
        self.assertEqual(record['manifest_sha256'], self.pin)
        with self.assertRaises(runtime.TrialError): phrase_bank.select(self.root, 'fixture-attempt', 110)

    def test_broken_pin_fails_before_identity_or_playback_without_legacy_fallback(self):
        self.enable('0' * 64)
        with mock.patch.object(speaker.person_gate, 'valid_proof', return_value=True), \
             mock.patch.object(departure.cli, 'registry', return_value=self.devices), \
             mock.patch.object(speaker.audio, 'identify_doorbell') as identity, \
             mock.patch.object(speaker.audio, 'CameraSession') as session:
            result = speaker.play_once(self.root, self.request, clock=lambda: 101)
        self.assertEqual(result, 'failed_before_play')
        identity.assert_not_called()
        session.assert_not_called()

    def test_stale_disabled_faulted_or_unauthorized_attempt_never_selects(self):
        self.enable()
        for mode in ('expired', 'disabled', 'fault', 'proof', 'mismatch'):
            with self.subTest(mode=mode):
                runtime.save_json(self.root / 'config.json', {**self.value, 'enabled': mode != 'disabled'})
                state = runtime.default_state()
                state['pending'] = 'other' if mode == 'mismatch' else 'fixture-attempt'
                state['fault'] = 'blocked' if mode == 'fault' else None
                runtime.save_json(self.root / 'state.json', state)
                with mock.patch.object(speaker.phrase_bank, 'select') as select, \
                     mock.patch.object(speaker.person_gate, 'valid_proof', return_value=mode != 'proof'), \
                     mock.patch.object(departure.cli, 'registry') as registry:
                    result = speaker.play_once(self.root, self.request, clock=lambda: 111 if mode == 'expired' else 101)
                self.assertIn(result, ('failed_before_play', 'expired_before_play'))
                select.assert_not_called()
                registry.assert_not_called()

    def test_banked_clip_uses_original_locks_padding_volume_and_unknown_latch(self):
        for fail_send in (False, True):
            with self.subTest(fail_send=fail_send):
                # Separate attempt IDs, no actual sensor event or device access.
                attempt = 'send-error' if fail_send else 'completed'
                state = runtime.default_state()
                state.update(pending=attempt, last_attempt=100)
                runtime.save_json(self.root / 'state.json', state)
                self.enable()
                sent = []
                class Session:
                    def __init__(self, *args): pass
                    def start(self): pass
                    def play(self, path):
                        sent.append(path)
                        if fail_send: raise OSError('fixture')
                    def close(self): pass
                def prepare(args, tmp, volume, check):
                    record = runtime.read_json(self.root / 'phrase-selection.json')
                    self.assertEqual(record['attempt'], attempt)
                    self.assertEqual(banks.digest(Path(args.file).read_bytes()), record['sha256'])
                    self.assertTrue(args.doorbell_padding)
                    self.assertEqual(volume, 60)
                    return tmp / 'playback.wav', 2
                def loop(session, file, seconds, repeat, duration, check):
                    self.assertFalse(repeat)
                    self.assertEqual(duration, 8)
                    session.play(file)
                    return 'completed', 1
                with mock.patch.object(speaker.person_gate, 'valid_proof', return_value=True), \
                     mock.patch.object(departure.cli, 'registry', return_value=self.devices), \
                     mock.patch.object(departure.cli, 'device_lock', side_effect=lambda *_: nullcontext()) as locks, \
                     mock.patch.object(departure.cli, 'load_settings', return_value=SimpleNamespace(password='fixture')), \
                     mock.patch.object(speaker.identity_preflight, 'valid', return_value=True), \
                     mock.patch.object(speaker.audio, 'prepare', side_effect=prepare), \
                     mock.patch.object(speaker.audio, 'CameraSession', Session), \
                     mock.patch.object(speaker.audio, 'interruptible', side_effect=nullcontext), \
                     mock.patch.object(speaker.audio, 'playback_loop', side_effect=loop):
                    result = speaker.play_once(self.root, {'attempt': attempt, 'expires': 110}, clock=lambda: 101)
                self.assertEqual(result, 'unknown' if fail_send else 'completed')
                self.assertEqual(len(sent), 1)
                self.assertEqual([call.args[0] for call in locks.call_args_list], ['hub', 'front-doorbell'])
                journal = runtime.Journal(self.root)
                journal.finish(attempt, result)
                self.assertEqual(journal.blocked, fail_send)
                self.assertEqual(runtime.read_json(self.root / 'playback.json')['attempt'], attempt)

    def test_duration_cap_enforced_even_with_relaxed_review_limits(self):
        long_assets = Path(self.tmp.name) / 'long'
        pin, manifest = fixture_bundle(long_assets, seconds=4.6)
        manifest['limits_seconds']['departure'] = 10
        self.assets, self.pin = long_assets, save_manifest(long_assets, manifest)
        self.enable()
        with self.assertRaises(banks.BankError): phrase_bank.select(self.root, 'fixture-attempt', 110)


if __name__ == '__main__':
    unittest.main()
