import asyncio
import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch
import test_person_gate as fixtures
BASE, EXPIRES = fixtures.BASE, fixtures.EXPIRES
import person_gate
import runtime
import sensor_trial
import watcher


class SensorTrialTests(unittest.TestCase):
    setUp = fixtures.GateTests.setUp
    sample = fixtures.GateTests.sample
    def authorize_sensor(self):
        runtime.save_json(self.root / 'sensor-trial.json', {'version': 1, 'authorized': True,
            'authorized_at': '2026-10-01T18:00:00+00:00'})

    def test_sensor_only_delivery_never_reads_person_history(self):
        self.authorize_sensor()
        play = Mock(return_value='completed')
        async def confirm(root, reader, attempt, opened, expires):
            return await person_gate.confirm(root, reader, attempt, opened, expires, now=lambda: BASE+.2)
        with patch.object(person_gate, 'history', new_callable=AsyncMock) as history:
            result = asyncio.run(watcher.deliver(self.root, self.journal, self.sample(),
                now=lambda: BASE+.2, speaker=play, confirm=confirm))
        self.assertEqual(result, 'completed')
        play.assert_called_once()
        history.assert_not_called()
        self.assertFalse(person_gate.status(self.root)['person_gate_required'])
        self.assertFalse((self.root/'person-proof.json').exists())
        self.assertIn('sensor_only_sequence_authorized', [e['reason'] for e in self.journal.state['events']])
        # Durable household cooldown still rejects a second attempt.
        self.assertFalse(self.journal.reserve('second', BASE+60))

    def test_close_trigger_delivery_uses_fresh_close_deadline(self):
        self.authorize_sensor()
        original = self.sample()
        closed = replace(original, motion=False, door_open=False,
                         observed_at=original.observed_at + timedelta(seconds=600))
        at = closed.observed_at.timestamp()
        play = Mock(return_value='completed')
        async def confirm(root, reader, attempt, trigger, expires):
            return await person_gate.confirm(root, reader, attempt, trigger, expires, now=lambda: at+.1)
        # Opening samples cannot bypass the close requirement.
        self.assertEqual(asyncio.run(watcher.deliver(self.root, self.journal, original,
            now=lambda: BASE+.2, speaker=play, confirm=confirm, require_close=True)), 'suppressed')
        play.assert_not_called()
        result = asyncio.run(watcher.deliver(self.root, self.journal, closed,
            now=lambda: at+.1, speaker=play, confirm=confirm, require_close=True))
        self.assertEqual(result, 'completed')
        self.assertEqual(play.call_args.args[2], at+16)
        self.assertEqual(self.journal.state['last_attempt'], at+.1)

    def test_sensor_proof_expiry_revocation_and_pending(self):
        self.authorize_sensor()
        self.journal.reserve('one', BASE+.2)
        self.assertTrue(sensor_trial.reserve_proof(self.root,'one',BASE+.1,EXPIRES,now=BASE+.2))
        self.assertTrue(person_gate.valid_proof(self.root,'one',EXPIRES,now=BASE+1))
        self.assertFalse(person_gate.valid_proof(self.root,'other',EXPIRES,now=BASE+1))
        self.assertFalse(person_gate.valid_proof(self.root,'one',EXPIRES,now=EXPIRES))
        (self.root/'sensor-trial.json').unlink()
        self.assertFalse(person_gate.valid_proof(self.root,'one',EXPIRES,now=BASE+1))
        self.authorize_sensor()
        self.journal.finish('one','failed_before_play')
        self.assertFalse(person_gate.valid_proof(self.root,'one',EXPIRES,now=BASE+1))

    def test_malformed_sensor_authorization_fails_closed(self):
        runtime.save_json(self.root/'sensor-trial.json', {'authorized': True})
        with self.assertRaises(runtime.TrialError): person_gate.effective_policy(self.root)
