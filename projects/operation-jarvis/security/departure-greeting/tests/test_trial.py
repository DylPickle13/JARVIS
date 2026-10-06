"""Offline audible-trial safeguards. Speaker/network operations are mocked."""
import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import departure
import person_gate
import runtime
import speaker
import watcher

START = datetime(2026, 9, 29, 16, tzinfo=timezone.utc)


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'Application Support'
        self.root.mkdir(mode=0o700)
        self.value = {'version': 1, 'enabled': True, 'motion_device': 'motion-sensor',
                      'door_device': 'door-sensor', 'speaker_device': 'front-doorbell', 'volume': 60}
        runtime.save_json(self.root / 'config.json', self.value)
        runtime.save_json(self.root / 'state.json', runtime.default_state())
        # Synthetic commissioned fixture only; not a real Tapo type mapping.
        runtime.save_json(self.root / 'person-gate.json', {**person_gate.default_policy(),
            'verified': True, 'person_code': 7, 'binding': 'a' * 64,
            'timestamp_basis': 'unix_utc_seconds', 'verified_at': START.isoformat()})
        self.journal = runtime.Journal(self.root)

    def deliver(self, *args, **kwargs):
        async def fixture_gate(*args):
            return person_gate.Result(True, 'fresh_person_after_opening')
        return asyncio.run(watcher.deliver(*args, **kwargs, confirm=fixture_gate))

    def write_proof(self, at=START):
        event = {'start': int(at.timestamp()) + 1, 'end': int(at.timestamp()) + 1, 'code': 7}
        runtime.save_json(self.root / 'person-proof.json', {'version': 1, 'attempt': 'one',
            'opened_at': at.timestamp(), 'expires': at.timestamp() + person_gate.VOICE_ONSET_SECONDS,
            'checked_at': at.timestamp() + 1, 'event_start': event['start'], 'event_end': event['end'],
            'event_key': person_gate.event_key('a' * 64, event), 'person_code': 7, 'binding': 'a' * 64})

    def sample(self, at=START):
        return departure.Sample(0, at, True, True, 0.1)

    def test_master_off_suppresses_delivery_without_touching_reader_safeguards(self):
        before = dict(self.journal.state)
        play = Mock()
        with patch.object(watcher.automatic_voice, 'current',
                return_value=watcher.automatic_voice.Policy(False, 'a'*32)):
            result = self.deliver(self.root, self.journal, self.sample(), now=lambda: START.timestamp(), speaker=play)
        self.assertEqual(result, 'suppressed')
        self.assertEqual(self.journal.state, before)
        play.assert_not_called()

    def test_old_departure_generation_is_rejected_after_off_on(self):
        play = Mock()
        with patch.object(watcher.automatic_voice, 'current',
                return_value=watcher.automatic_voice.Policy(True, 'b'*32)):
            result = self.deliver(self.root, self.journal, self.sample(), now=lambda: START.timestamp(),
                speaker=play, voice_revision='a'*32)
        self.assertEqual(result, 'suppressed')
        play.assert_not_called()
        self.assertIsNone(self.journal.state['pending'])

    def test_off_on_before_worker_prevents_doorbell_transport(self):
        request = {'attempt': 'one', 'expires': START.timestamp() + person_gate.VOICE_ONSET_SECONDS}
        runtime.save_json(self.root / 'voice-admission.json', {**request, 'revision': 'a'*32})
        with patch.object(speaker.automatic_voice, 'current',
                return_value=speaker.automatic_voice.Policy(True, 'b'*32)), \
                patch.object(departure.cli, 'registry') as registry:
            self.assertEqual(speaker.play_once(self.root, request, clock=lambda: START.timestamp()), 'failed_before_play')
        registry.assert_not_called()

    def test_owner_authorized_louder_volume_is_bounded(self):
        runtime.save_json(self.root / 'config.json', {**self.value, 'volume': 100})
        self.assertEqual(runtime.config(self.root)['volume'], 100)
        runtime.save_json(self.root / 'config.json', {**self.value, 'volume': 101})
        with self.assertRaises(runtime.TrialError): runtime.config(self.root)

    def test_phrase_is_exact(self):
        self.assertEqual(runtime.PHRASE, 'Have a good day, sir')
        self.assertEqual(departure.status()['phrase'], runtime.PHRASE)
        with patch.object(runtime, 'PHRASE', 'status fixture only'):
            self.assertEqual(departure.status()['phrase'], 'status fixture only')

    def test_reservation_is_durable_before_worker(self):
        def play(root, attempt, expires):
            state = runtime.read_json(root / 'state.json')
            self.assertEqual(state['pending'], attempt)
            self.assertEqual(state['last_attempt'], START.timestamp())
            self.assertEqual(expires, START.timestamp() + person_gate.VOICE_ONSET_SECONDS)
            return 'completed'
        result = self.deliver(self.root, self.journal, self.sample(), now=lambda: START.timestamp(), speaker=play)
        self.assertEqual(result, 'completed')
        self.assertIsNone(self.journal.state['pending'])
        self.assertEqual(self.journal.state['completed_count'], 1)

    def test_unknown_outcome_survives_restart_and_blocks_retry(self):
        play = Mock(return_value='unknown')
        self.deliver(self.root, self.journal, self.sample(), now=lambda: START.timestamp(), speaker=play)
        restored = runtime.Journal(self.root)
        self.assertTrue(restored.blocked)
        self.deliver(self.root, restored, self.sample(START + timedelta(minutes=5)),
                        now=lambda: START.timestamp() + 300, speaker=play)
        self.assertEqual(play.call_count, 1)

    def test_worker_exception_is_unknown_not_retryable(self):
        play = Mock(side_effect=RuntimeError('private fixture'))
        self.assertEqual(self.deliver(self.root, self.journal, self.sample(),
            now=lambda: START.timestamp(), speaker=play), 'unknown')
        self.assertTrue(runtime.Journal(self.root).blocked)

    def test_durable_cooldown_across_restarts_and_backward_clock(self):
        self.journal.reserve('one', START.timestamp())
        self.journal.finish('one', 'completed')
        restored = runtime.Journal(self.root)
        for seconds in (-10, 0, 119):
            self.assertFalse(restored.reserve('two', START.timestamp() + seconds))
        self.assertTrue(restored.reserve('two', START.timestamp() + 120))

    def test_pending_crash_never_resumed(self):
        self.journal.reserve('one', START.timestamp())
        self.assertTrue(runtime.Journal(self.root).blocked)

    def test_expired_or_failed_preplay_attempt_has_no_immediate_retry(self):
        for outcome in ('expired_before_play', 'failed_before_play'):
            runtime.save_json(self.root / 'state.json', runtime.default_state())
            journal = runtime.Journal(self.root)
            play = Mock(return_value=outcome)
            self.deliver(self.root, journal, self.sample(), now=lambda: START.timestamp(), speaker=play)
            self.assertFalse(journal.blocked)
            self.deliver(self.root, journal, self.sample(), now=lambda: START.timestamp(), speaker=play)
            self.assertEqual(play.call_count, 1)

    def test_disabled_stale_and_future_samples_never_speak(self):
        play = Mock()
        for now in (START.timestamp() + 2, START.timestamp() - 1):
            self.assertEqual(self.deliver(self.root, self.journal, self.sample(),
                now=lambda: now, speaker=play), 'suppressed')
        self.value['enabled'] = False
        runtime.save_json(self.root / 'config.json', self.value)
        self.deliver(self.root, self.journal, self.sample(), now=lambda: START.timestamp(), speaker=play)
        play.assert_not_called()

    def test_delivery_allowed_at_every_hour_including_overnight(self):
        for hour in range(24):
            with self.subTest(hour=hour):
                runtime.save_json(self.root / 'state.json', runtime.default_state())
                journal = runtime.Journal(self.root)
                at = START.replace(hour=hour)
                play = Mock(return_value='completed')
                result = self.deliver(self.root, journal, self.sample(at),
                    now=lambda: at.timestamp(), speaker=play)
                self.assertEqual(result, 'completed')
                play.assert_called_once()

    def test_reservation_latency_cannot_extend_expiry(self):
        ticks = iter((START.timestamp(), START.timestamp(), START.timestamp() + 2))
        play = Mock()
        result = self.deliver(self.root, self.journal, self.sample(), now=lambda: next(ticks), speaker=play)
        self.assertEqual(result, 'expired_before_play')
        play.assert_not_called()
        self.assertFalse(self.journal.blocked)

    def test_installed_status_not_running_without_fresh_heartbeat(self):
        status = runtime.installed_status(self.root)
        self.assertFalse(status['running'])
        self.assertFalse(status['delivery_enabled'])
        self.journal.state['health'] = 'observing'
        self.journal.flush()
        self.assertTrue(runtime.installed_status(self.root)['delivery_enabled'])
        self.journal.reserve('one', START.timestamp())
        self.assertFalse(runtime.installed_status(self.root)['delivery_enabled'])

    def test_singleton_prevents_duplicate_watchers(self):
        lock = runtime.singleton(self.root)
        try:
            with self.assertRaises(runtime.TrialError):
                runtime.singleton(self.root)
        finally:
            os.close(lock)

    def test_private_file_and_directory_required(self):
        os.chmod(self.root / 'config.json', 0o644)
        with self.assertRaises(runtime.TrialError):
            runtime.config(self.root)
        os.chmod(self.root / 'config.json', 0o600)
        os.chmod(self.root, 0o755)
        try:
            with self.assertRaises(runtime.TrialError):
                runtime.private_dir(self.root)
        finally:
            os.chmod(self.root, 0o700)

    def test_state_symlink_and_bad_json_rejected(self):
        target = self.root / 'target'
        target.write_text('{}')
        (self.root / 'link').symlink_to(target)
        with self.assertRaises(OSError):
            runtime.read_json(self.root / 'link')
        runtime.save_json(self.root / 'state.json', {})
        with self.assertRaises(runtime.TrialError):
            runtime.Journal(self.root)

    def test_unsafe_configuration_rejected(self):
        for key, value in (('volume', 101), ('enabled', 'yes'), ('version', True), ('speaker_device', '')):
            changed = {**self.value, key: value}
            runtime.save_json(self.root / 'config.json', changed)
            with self.assertRaises(runtime.TrialError):
                runtime.config(self.root)

    def test_history_is_bounded(self):
        for i in range(100):
            self.journal.event('fixture', motion=False)
        self.journal.flush()
        self.assertEqual(len(runtime.read_json(self.root / 'state.json')['events']), 64)

    def test_disable_is_confirmed_and_preserves_unknown_fault(self):
        self.journal.reserve('one', START.timestamp())
        self.journal.finish('one', 'unknown')
        with patch.object(runtime, 'ROOT', self.root):
            with self.assertRaises(departure.cli.ControlError):
                departure.execute_departure(departure.parser().parse_args(['disable']))
            result = departure.execute_departure(departure.parser().parse_args(['disable', '--confirm']))
        self.assertFalse(result['enabled'])
        self.assertTrue(runtime.Journal(self.root).blocked)

    def test_phrase_hash_and_non_d235_block_worker(self):
        self.journal.reserve('one', START.timestamp())
        request = {'attempt': 'one', 'expires': START.timestamp() + person_gate.VOICE_ONSET_SECONDS}
        with patch.object(departure.cli, 'registry', return_value={}), patch.object(speaker.audio, 'CameraSession') as session:
            self.assertEqual(speaker.play_once(self.root, request, clock=lambda: START.timestamp()), 'failed_before_play')
        session.assert_not_called()

    def test_expired_worker_never_reads_devices(self):
        self.journal.reserve('one', START.timestamp())
        with patch.object(departure.cli, 'registry') as registry:
            self.assertEqual(speaker.play_once(self.root,
                {'attempt': 'one', 'expires': START.timestamp()}, clock=lambda: START.timestamp()), 'expired_before_play')
        registry.assert_not_called()

    def test_preplay_path_deadline_and_unknown_after_send(self):
        for mode, expected in (('success', 'completed'), ('warm', 'completed'), ('success_night', 'completed'),
                               ('late_start', 'completed'), ('slow', 'expired_before_play'),
                               ('send_error', 'unknown')):
            at = START.replace(hour=2) if mode == 'success_night' else START
            runtime.save_json(self.root / 'state.json', runtime.default_state())
            self.journal = runtime.Journal(self.root)
            self.journal.reserve('one', at.timestamp())
            self.write_proof(at)
            source = self.root / 'phrase.wav'
            source.write_bytes(b'fixture local audio')
            os.chmod(source, 0o600)
            runtime.save_json(self.root / 'phrase.json', {'phrase': runtime.PHRASE,
                'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
            tick = [at.timestamp() + (10 if mode == 'late_start' else 1)]
            sent = []
            class FakeSession:
                def __init__(self, *args): pass
                def start(self):
                    if mode == 'slow': tick[0] += person_gate.VOICE_ONSET_SECONDS - 1
                def play(self, file):
                    sent.append(file)
                    if mode == 'send_error': raise OSError('fixture')
                def close(self): pass
            def prepare(args, tmp, volume, check):
                self.assertFalse(any(char.isspace() for char in str(tmp)))
                self.assertEqual(tmp.stat().st_mode & 0o777, 0o700)
                self.assertFalse(tmp.is_relative_to(self.root))
                return tmp / 'playback.wav', 5
            def loop(session, file, *args):
                session.play(file)
                return 'completed', 1
            devices = {'front-doorbell': {'model': 'D235', 'host': '192.0.2.1', 'hub': 'hub'},
                       'motion-sensor': {'model': 'T100', 'hub': 'hub'}}
            with patch.object(departure.cli, 'registry', return_value=devices), \
                 patch.object(departure.cli, 'device_lock', side_effect=lambda *_: nullcontext()), \
                 patch.object(departure.cli, 'load_settings', return_value=NS(password='fixture')), \
                 patch.object(speaker.identity_preflight, 'valid', return_value=mode == 'warm'), \
                 patch.object(speaker.audio, 'identify_doorbell', new_callable=AsyncMock) as identify, \
                 patch.object(speaker.audio, 'prepare', side_effect=prepare), \
                 patch.object(speaker.audio, 'CameraSession', FakeSession), \
                 patch.object(speaker.audio, 'interruptible', side_effect=nullcontext), \
                 patch.object(speaker.audio, 'playback_loop', side_effect=loop):
                result = speaker.play_once(self.root, {'attempt': 'one', 'expires': at.timestamp() + person_gate.VOICE_ONSET_SECONDS},
                                           clock=lambda: tick[0])
            self.assertEqual(result, expected)
            if mode == 'warm': identify.assert_not_awaited()
            else: identify.assert_awaited_once()
            timing = runtime.read_json(self.root / 'speaker-timing.json')
            self.assertFalse(timing['audible_onset_measured'])
            self.assertEqual(timing['trigger_observed_at'], at.timestamp())
            self.assertIn('identity_finished', timing['elapsed_seconds'])
            self.assertIn('cleanup_finished', timing['elapsed_seconds'])
            if sent:
                self.assertIn('play_request_started', timing['elapsed_seconds'])
            self.assertEqual(len(sent), 0 if mode == 'slow' else 1)
            if sent:
                self.assertTrue(sent[0].startswith('"') and sent[0].endswith('"'))
            marker = runtime.read_json(self.root / 'playback.json')
            if mode != 'slow': self.assertTrue(marker['started'])
            if mode == 'send_error':
                diagnostic = runtime.read_json(self.root / 'speaker-diagnostic.json')
                self.assertEqual(diagnostic['stage'], 'play_request')
                self.assertTrue(diagnostic['playback_attempted'])
                self.assertEqual(diagnostic['error_type'], 'OSError')
                self.assertNotIn('fixture', json.dumps(diagnostic))

    def test_fast_polling_only_while_waiting_for_close(self):
        detector = departure.DepartureDetector(allow_simultaneous=True, require_close=True)
        self.assertEqual(watcher.poll_delay(detector), 2)
        detector.accept(departure.Sample(0, START, False, False))
        detector.accept(departure.Sample(2, START+timedelta(seconds=2), True, True))
        self.assertEqual(watcher.poll_delay(detector), 0.25)
        detector.accept(departure.Sample(3, START+timedelta(seconds=3), False, False))
        self.assertEqual(watcher.poll_delay(detector), 2)
        detector.reset()
        self.assertEqual(watcher.poll_delay(detector), 2)

    def test_go2rtc_playback_path_is_one_quoted_argument(self):
        path = Path('/private/fixture/jarvis-departure-one/playback.wav')
        self.assertEqual(speaker.quoted_playback_path(path), '"' + str(path) + '"')
        for bad in ('relative.wav', '/tmp/a"b.wav', '/tmp/a#b.wav', '/tmp/a?b.wav',
                    '/private/fixture/Application Support/playback.wav', '/tmp/a\tb.wav',
                    '/tmp/a\nb.wav', '/tmp/a\rb.wav', '/tmp/a\x00b.wav'):
            with self.assertRaises(ValueError): speaker.quoted_playback_path(bad)

    def test_worker_process_budget_tracks_longer_onset_window(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ('{"outcome":"completed"}', None)
        process.poll.return_value = 0
        with patch.object(watcher.subprocess, 'Popen', return_value=process):
            result = watcher.run_speaker(self.root, 'one', START.timestamp() + person_gate.VOICE_ONSET_SECONDS)
        self.assertEqual(result, 'completed')
        self.assertEqual(process.communicate.call_args.kwargs['timeout'], 30)

    def test_shared_snapshot_publication_and_invalidation(self):
        sample = departure.Sample(10., START, False, True, 0.1)
        watcher.publish_snapshot(self.root, self.value, sample)
        value = runtime.read_json(self.root / 'sensor-snapshot.json')
        self.assertEqual(value['observed_at'], START.isoformat())
        self.assertEqual(value['tick'], 10.)
        self.assertEqual(value['sensors']['door-sensor'], {'model': 'T110', 'state': True})
        self.assertEqual((self.root / 'sensor-snapshot.json').stat().st_mode & 0o777, 0o600)
        watcher.publish_snapshot(self.root, self.value, departure.Sample(11., START, None, True, 0.1))
        self.assertFalse((self.root / 'sensor-snapshot.json').exists())
        watcher.clear_snapshot(self.root)

    def test_busy_reconnects_promptly_and_rebaselines_without_speech(self):
        def sample(tick, motion, opened):
            return departure.Sample(tick, START + timedelta(seconds=tick), motion, opened, 0.1)
        reader = NS(device=object(), person_camera=object(), phase='paired_read',
                    connect=AsyncMock(), close=AsyncMock(),
                    sample=AsyncMock(side_effect=[sample(1, False, False), sample(3, True, False),
                        departure.cli.ControlError('device_busy'),
                        departure.cli.ControlError('device_busy'), sample(5, True, True),
                        asyncio.CancelledError()]))
        sleeps = AsyncMock()
        with patch.object(watcher, 'HubSession', return_value=reader) as factory, \
             patch.object(departure, 'validate_devices', return_value=('hub', {}, {}, {})), \
             patch.object(departure.cli, 'registry', return_value={
                 'front-doorbell': {'model': 'D235', 'host': 'fixture', 'hub': 'hub'}}), \
             patch.object(watcher.asyncio, 'sleep', sleeps), \
             patch.object(watcher, 'deliver', new_callable=AsyncMock) as deliver:
            with self.assertRaises(asyncio.CancelledError): asyncio.run(watcher.watch(self.root))
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(reader.connect.await_count, 3)
        self.assertEqual(reader.close.await_count, 3)  # Busy sessions and final cancellation.
        deliver.assert_not_awaited()
        self.assertEqual([call.args[0] for call in sleeps.await_args_list], [2, 2, 0.5, 0.5, 2])
        events = runtime.Journal(self.root).state['events']
        self.assertEqual(sum(e['reason'] == 'hub_busy' for e in events), 1)
        self.assertEqual(events[-1]['reason'], 'baseline')
        self.assertTrue(events[-1]['door_open'])

    def test_retryable_read_recovers_silently_and_exhaustion_latches(self):
        from kasa.exceptions import _RetryableError, AuthenticationError
        self.assertTrue(watcher.transient(_RetryableError('private response')))
        self.assertFalse(watcher.transient(AuthenticationError('private response')))
        for exhausted in (False, True):
            runtime.save_json(self.root / 'state.json', runtime.default_state())
            fail = lambda: _RetryableError('private response must not be logged')
            samples = ([fail(), fail(), fail()] if exhausted else [
                departure.Sample(1., START, False, False, 0.1),
                departure.Sample(3., START + timedelta(seconds=2), True, False, 0.1),
                fail(), departure.Sample(5., START + timedelta(seconds=4), True, True, 0.1),
                asyncio.CancelledError()])
            reader = NS(device=object(), person_camera=object(), phase='paired_read',
                        connect=AsyncMock(), close=AsyncMock(), sample=AsyncMock(side_effect=samples))
            async def sleep(seconds):
                if exhausted and seconds == 15: raise asyncio.CancelledError()
            with patch.object(watcher, 'HubSession', return_value=reader), \
                 patch.object(departure, 'validate_devices', return_value=('hub', {}, {}, {})), \
                 patch.object(departure.cli, 'registry', return_value={
                     'front-doorbell': {'model': 'D235', 'host': 'fixture', 'hub': 'hub'}}), \
                 patch.object(watcher.asyncio, 'sleep', side_effect=sleep), \
                 patch.object(watcher, 'deliver', new_callable=AsyncMock) as deliver:
                with self.assertRaises(asyncio.CancelledError): asyncio.run(watcher.watch(self.root))
            state = runtime.Journal(self.root).state
            self.assertEqual(state['fault'], 'sensor_read_requires_review' if exhausted else None)
            self.assertEqual(reader.connect.await_count, 3 if exhausted else 2)
            deliver.assert_not_awaited()
            self.assertNotIn('private response', json.dumps(state))
            self.assertFalse((self.root / 'sensor-snapshot.json').exists())
            if exhausted:
                self.assertTrue(state['events'][-1]['recovery_exhausted'])
                self.assertEqual(state['events'][-1]['read_failure_count'], 3)
            else:
                self.assertEqual(state['events'][-1]['reason'], 'baseline')

    def test_sensor_query_uses_shared_lock_and_paired_getter(self):
        device = NS(protocol=NS(query=AsyncMock(return_value={'getChildDeviceList': {'child_device_list': [
            {'device_id': 'fixture-motion', 'model': 'T100', 'detected': False},
            {'device_id': 'fixture-door', 'model': 'T110', 'open': False}]}})))
        reader = watcher.HubSession(None, ('hub', {}, {}, {}))
        reader.device = device
        reader.motion_id, reader.door_id = 'fixture-motion', 'fixture-door'
        with patch.object(departure.cli, 'device_lock', side_effect=lambda *_: nullcontext()) as lock:
            sample = asyncio.run(reader.sample())
        lock.assert_called_once_with('hub')
        self.assertFalse(sample.motion)
        self.assertFalse(sample.door_open)
        self.assertEqual(set(device.protocol.query.await_args.args[0]), {'getChildDeviceList'})


if __name__ == '__main__':
    unittest.main()
