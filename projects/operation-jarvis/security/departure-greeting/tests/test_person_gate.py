"""Synthetic gate commissioning/evidence tests; never contact cameras or speak."""
import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import departure
import person_gate as gate
import runtime
import speaker
import watcher

BASE = datetime(2026, 9, 29, 16, tzinfo=timezone.utc).timestamp()
BINDING = 'a' * 64
# Arbitrary synthetic code, NOT a claim about real Tapo person-event values.
CODE = 7


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        runtime.save_json(self.root / 'config.json', {'version': 1, 'enabled': True,
            'motion_device': 'motion-sensor', 'door_device': 'door-sensor',
            'speaker_device': 'front-doorbell', 'volume': 60})
        runtime.save_json(self.root / 'state.json', runtime.default_state())
        self.journal = runtime.Journal(self.root)

    def commission(self):
        value = {**gate.default_policy(), 'verified': True, 'person_code': CODE,
            'binding': BINDING, 'timestamp_basis': 'unix_utc_seconds',
            'verified_at': datetime.fromtimestamp(BASE, timezone.utc).isoformat()}
        runtime.save_json(self.root / 'person-gate.json', value)
        return value

    def sample(self):
        return departure.Sample(0, datetime.fromtimestamp(BASE + 0.1, timezone.utc), True, True, 0.1)

    def result(self, rows):
        return {'playback': {'search_detection_list': rows}}

    def row(self, start=BASE + 1, end=BASE + 1, code=CODE):
        return {'start_time': int(start), 'end_time': int(end), 'event_type': code}

    def proof(self, attempt='one'):
        event = {'start': int(BASE + 1), 'end': int(BASE + 1), 'code': CODE}
        return {'version': 1, 'attempt': attempt, 'opened_at': BASE + 0.1,
            'expires': BASE + 8.1, 'checked_at': BASE + 1.25, 'event_start': event['start'],
            'event_end': event['end'], 'event_key': gate.event_key(BINDING, event),
            'person_code': CODE, 'binding': BINDING}

    def test_missing_policy_is_mandatory_and_unverified(self):
        self.assertEqual(gate.policy(self.root), gate.default_policy())
        self.assertTrue(gate.status(self.root)['person_gate_required'])
        self.assertFalse(gate.status(self.root)['person_gate_verified'])

    def test_cannot_enable_gate_with_only_a_type_code(self):
        for key, bad in (('binding', None), ('timestamp_basis', 'local'), ('person_code', True),
                         ('person_code', '7'), ('verified_at', '2026-09-29'), ('version', True)):
            value = self.commission()
            value[key] = bad
            runtime.save_json(self.root / 'person-gate.json', value)
            with self.assertRaises(runtime.TrialError): gate.policy(self.root)

    def test_policy_private_permissions_and_symlinks(self):
        self.commission()
        os.chmod(self.root / 'person-gate.json', 0o644)
        with self.assertRaises(runtime.TrialError): gate.policy(self.root)
        (self.root / 'person-gate.json').unlink()
        (self.root / 'person-gate.json').symlink_to(self.root / 'state.json')
        with self.assertRaises(OSError): gate.policy(self.root)

    def test_source_identity_is_unique_and_bound_without_exposing_ids(self):
        camera = {'device_model': 'D235', 'device_id': 'private-doorbell', 'mac': 'private-mac'}
        hub = {'device_model': 'H200', 'dev_id': 'private-hub', 'sw_version': 'fixture firmware'}
        response = {'general_camera_manage': {'paired_general_device_list': [camera]}}
        selected, binding = gate.camera_binding(response, hub)
        self.assertEqual(selected['device_id'], camera['device_id'])
        self.assertEqual(len(binding), 64)
        newer_hub = {**hub, 'sw_version': 'new firmware'}
        self.assertNotEqual(gate.camera_binding(response, newer_hub)[1], binding)
        response['general_camera_manage']['paired_general_device_list'].append(camera)
        with self.assertRaises(runtime.TrialError): gate.camera_binding(response, hub)

    def test_source_rejects_missing_wrong_or_conflicting_identity(self):
        camera = {'device_model': 'D235', 'device_id': 'fixture', 'mac': 'fixture'}
        response = {'general_camera_manage': {'paired_general_device_list': [camera]}}
        for hub in ({'device_model': 'C230'}, {'device_model': 'H200', 'dev_id': {}},
                    {'device_model': 'H200', 'dev_id': 'one', 'device_id': 'two'}):
            with self.assertRaises(runtime.TrialError): gate.camera_binding(response, hub)

    def test_event_schema_types_time_and_truncation_fail_closed(self):
        for rows in ([self.row(code=True)], [self.row(code='7')], [self.row(start=BASE + 3, end=BASE + 3)],
                     [self.row(end=0)], [self.row(start=BASE - 60)], [self.row()] * gate.MAX_ROWS,
                     [{'person': True}], ['private payload']):
            with self.assertRaises(runtime.TrialError):
                gate.event_rows(self.result(rows), int(BASE - 1), int(BASE + 2))
        self.assertEqual(gate.event_rows(self.result([]), int(BASE), int(BASE + 2)), [])

    def test_explicit_getter_uses_one_request_no_paging_or_replay(self):
        query = AsyncMock(return_value={'multipleRequest': {'responses': [
            {'method': 'searchDetectionList', 'error_code': 0, 'result': self.result([])}]}})
        reader = NS(device=NS(protocol=NS(query=query)))
        self.assertEqual(asyncio.run(gate.read_one(reader, 'searchDetectionList', {'fixture': {}})), self.result([]))
        query.assert_awaited_once()
        self.assertEqual(query.await_args.kwargs, {'retry_count': 0})
        self.assertEqual(len(query.await_args.args[0]['multipleRequest']['requests']), 1)
        with self.assertRaises(runtime.TrialError): asyncio.run(gate.read_one(reader, 'setDetection', {}))

    def test_malformed_error_and_extra_method_responses_rejected(self):
        for response in ({}, {'multipleRequest': {'responses': []}},
                         {'multipleRequest': {'responses': [{'method': 'searchDetectionList', 'error_code': -1}]}},
                         {'multipleRequest': {'responses': [
                             {'method': 'getDeviceInfo', 'error_code': 0, 'result': {}}]}}):
            reader = NS(device=NS(protocol=NS(query=AsyncMock(return_value=response))))
            with self.assertRaises(runtime.TrialError): asyncio.run(gate.read_one(reader, 'searchDetectionList', {}))

    def test_history_scopes_to_bound_d235_under_hub_lock(self):
        reader = NS(entries=('hub',), person_camera={'device_id': 'fixture-camera', 'mac': 'fixture-mac'})
        with patch.object(departure.cli, 'device_lock', side_effect=lambda *_: nullcontext()) as lock, \
             patch.object(gate, 'read_one', new_callable=AsyncMock, return_value=self.result([])) as read:
            self.assertEqual(asyncio.run(gate.history(reader, int(BASE), int(BASE + 2))), [])
        lock.assert_called_once_with('hub')
        params = read.await_args.args[2]['playback']['search_detection_list']
        self.assertEqual(params['child_device_id'], 'fixture-camera')
        self.assertEqual(params['end_index'], gate.MAX_ROWS - 1)
        self.assertEqual(params['child_device_mac'], 'fixture-mac')

    def test_fresh_matching_event_writes_attempt_scoped_proof(self):
        self.commission()
        reader = NS(person_binding=BINDING)
        with patch.object(gate, 'history', new_callable=AsyncMock, return_value=[
            {'start': int(BASE + 1), 'end': int(BASE + 1), 'code': CODE}]):
            result = asyncio.run(gate.confirm(self.root, reader, 'one', BASE + 0.1, BASE + 8.1,
                now=lambda: BASE + 1.25))
        self.assertTrue(result.confirmed)
        self.assertTrue(gate.valid_proof(self.root, 'one', BASE + 8.1, now=BASE + 1.5))
        self.assertFalse(gate.valid_proof(self.root, 'another', BASE + 8.1, now=BASE + 1.5))

    def test_old_same_second_motion_and_empty_events_do_not_confirm(self):
        self.commission()
        for events in ([], [{'start': int(BASE), 'end': int(BASE), 'code': CODE}],
                       [{'start': int(BASE + 1), 'end': int(BASE + 1), 'code': CODE + 1}]):
            with patch.object(gate, 'history', new_callable=AsyncMock, return_value=events):
                result = asyncio.run(gate.confirm(self.root, NS(person_binding=BINDING), 'one',
                    BASE + 0.1, BASE + 8.1, now=lambda: BASE + 1.25, sleep=AsyncMock()))
            self.assertFalse(result.confirmed)
            self.assertFalse((self.root / 'person-proof.json').exists())

    def test_source_binding_change_or_unverified_policy_never_reads_history(self):
        for reader in (None, NS(person_binding='b' * 64)):
            self.commission()
            with patch.object(gate, 'history', new_callable=AsyncMock) as history:
                result = asyncio.run(gate.confirm(self.root, reader, 'one', BASE, BASE + 8))
            self.assertFalse(result.confirmed)
            history.assert_not_awaited()
        (self.root / 'person-gate.json').unlink()
        with patch.object(gate, 'history', new_callable=AsyncMock) as history:
            result = asyncio.run(gate.confirm(self.root, NS(person_binding=BINDING), 'one', BASE, BASE + 8))
        self.assertFalse(result.confirmed)
        history.assert_not_awaited()

    def test_proof_tampering_clock_jumps_expiry_and_changed_policy_rejected(self):
        self.commission()
        original = self.proof()
        for key, bad in (('event_start', int(BASE)), ('event_end', int(BASE + 20)),
                         ('person_code', True), ('event_key', 'wrong'), ('binding', 'b' * 64),
                         ('opened_at', float('nan')), ('expires', BASE + 10)):
            runtime.save_json(self.root / 'person-proof.json', {**original, key: bad})
            self.assertFalse(gate.valid_proof(self.root, 'one', BASE + 8.1, now=BASE + 1.5))
        runtime.save_json(self.root / 'person-proof.json', original)
        for now in (BASE, BASE + 6.6, BASE + 8.1):
            self.assertFalse(gate.valid_proof(self.root, 'one', BASE + 8.1, now=now))
        value = self.commission()
        runtime.save_json(self.root / 'person-gate.json', {**value, 'person_code': CODE + 1})
        self.assertFalse(gate.valid_proof(self.root, 'one', BASE + 8.1, now=BASE + 1.5))

    def test_unverified_gate_suppresses_coordinator_without_reservation_or_speaker(self):
        play = Mock()
        result = asyncio.run(watcher.deliver(self.root, self.journal, self.sample(),
            now=lambda: BASE + 0.1, speaker=play))
        self.assertEqual(result, 'suppressed')
        play.assert_not_called()
        self.assertIsNone(self.journal.state['last_attempt'])
        self.assertEqual(self.journal.state['last_reason'], 'person_gate_unverified')

    def test_no_person_read_error_timeout_and_bad_result_never_invoke_speaker(self):
        self.commission()
        async def timeout(*args): await asyncio.sleep(1)
        for confirmation in (AsyncMock(return_value=gate.Result(False, 'no_fresh_person_after_opening')),
                             AsyncMock(side_effect=OSError('private fixture')), timeout,
                             AsyncMock(return_value=None)):
            runtime.save_json(self.root / 'state.json', runtime.default_state())
            journal, play = runtime.Journal(self.root), Mock()
            with patch.object(gate, 'MAX_WAIT', 0.01):
                result = asyncio.run(watcher.deliver(self.root, journal, self.sample(),
                    now=lambda: BASE + 0.1, speaker=play, confirm=confirmation))
            self.assertEqual(result, 'failed_before_play')
            play.assert_not_called()
            self.assertIsNone(journal.state['pending'])
            self.assertIsNotNone(journal.state['last_attempt'])

    def test_pending_is_durable_before_gate_and_deadline_not_extended(self):
        self.commission()
        async def check(root, reader, attempt, opened, expires):
            self.assertEqual(runtime.read_json(root / 'state.json')['pending'], attempt)
            self.assertEqual(expires, BASE + 8.1)
            return gate.Result(True, 'fresh_person_after_opening')
        play = Mock(return_value='completed')
        ticks = iter((BASE + 0.1, BASE + 0.1, BASE + 0.1, BASE + 6.2))
        result = asyncio.run(watcher.deliver(self.root, self.journal, self.sample(),
            now=lambda: next(ticks), speaker=play, confirm=check))
        self.assertEqual(result, 'expired_before_play')
        play.assert_not_called()
        self.assertFalse(self.journal.blocked)

    def test_worker_without_matching_proof_never_contacts_doorbell(self):
        self.commission()
        self.journal.reserve('one', BASE)
        with patch.object(departure.cli, 'registry') as registry:
            result = speaker.play_once(self.root, {'attempt': 'one', 'expires': BASE + 8.1},
                clock=lambda: BASE + 1.5)
        self.assertEqual(result, 'failed_before_play')
        registry.assert_not_called()

    def test_status_unverified_gate_and_stopped_heartbeat_cannot_claim_delivery(self):
        self.journal.state['health'] = 'observing'
        self.journal.flush()
        self.assertFalse(runtime.installed_status(self.root)['delivery_enabled'])
        self.commission()
        self.assertTrue(runtime.installed_status(self.root)['delivery_enabled'])
        self.journal.state['health'] = 'stopped'
        self.journal.flush()
        self.assertFalse(runtime.installed_status(self.root)['running'])

    def test_gate_cancellation_keeps_pending_to_prevent_replay(self):
        self.commission()
        confirmation = AsyncMock(side_effect=asyncio.CancelledError())
        play = Mock()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(watcher.deliver(self.root, self.journal, self.sample(),
                now=lambda: BASE + 0.1, speaker=play, confirm=confirmation))
        play.assert_not_called()
        self.assertTrue(runtime.Journal(self.root).blocked)

    def test_proof_revocation_before_send_prevents_playback(self):
        self.commission()
        self.journal.reserve('one', BASE)
        runtime.save_json(self.root / 'person-proof.json', self.proof())
        source = self.root / 'phrase.wav'
        source.write_bytes(b'fixture')
        os.chmod(source, 0o600)
        import hashlib
        runtime.save_json(self.root / 'phrase.json', {'phrase': runtime.PHRASE,
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
        sent = Mock()
        root = self.root
        class FakeSession:
            def __init__(self, *args): pass
            def start(self):
                runtime.save_json(root / 'person-gate.json', gate.default_policy())
            def play(self, file): sent(file)
            def close(self): pass
        devices = {'front-doorbell': {'model': 'D235', 'host': '192.0.2.1', 'hub': 'hub'},
                   'motion-sensor': {'model': 'T100', 'hub': 'hub'}}
        with patch.object(departure.cli, 'registry', return_value=devices), \
             patch.object(departure.cli, 'device_lock', side_effect=lambda *_: nullcontext()), \
             patch.object(departure.cli, 'load_settings', return_value=NS(password='fixture')), \
             patch.object(speaker.audio, 'identify_doorbell', new_callable=AsyncMock), \
             patch.object(speaker.audio, 'prepare', return_value=(source, 5)), \
             patch.object(speaker.audio, 'CameraSession', FakeSession), \
             patch.object(speaker.audio, 'interruptible', side_effect=nullcontext), \
             patch.object(speaker.audio, 'playback_loop') as playback:
            result = speaker.play_once(root, {'attempt': 'one', 'expires': BASE + 8.1},
                clock=lambda: BASE + 1.5)
        self.assertEqual(result, 'expired_before_play')
        playback.assert_not_called()
        sent.assert_not_called()
        self.assertFalse((root / 'playback.json').exists())

    def test_person_preview_bounds_are_checked_without_network(self):
        with patch.object(gate, 'preview', new_callable=AsyncMock) as preview:
            with self.assertRaises(departure.cli.ControlError):
                departure.execute_departure(departure.parser().parse_args(['person-preview', '--seconds', '61']))
        preview.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
