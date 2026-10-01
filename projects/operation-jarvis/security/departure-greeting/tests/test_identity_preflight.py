import sys
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import identity_preflight as identity
import runtime
import watcher
import security_audio


class IdentityTests(unittest.TestCase):
    def test_ticket_binding_freshness_attempt_and_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root/'env'
            env.write_text('synthetic secret')
            entry = {'model': 'D235', 'host': 'fixture', 'hub': 'hub'}
            with patch.object(identity.time, 'time', return_value=100), patch.object(identity.time, 'monotonic', return_value=200):
                evidence = identity.evidence(entry, env)
                identity.ticket(root, evidence, 'one', 116, entry, env)
                self.assertTrue(identity.valid(root, 'one', 116, entry, env))
                self.assertFalse(identity.valid(root, 'two', 116, entry, env))
                self.assertFalse(identity.valid(root, 'one', 117, entry, env))
                self.assertFalse(identity.valid(root, 'one', 116, {**entry, 'host':'changed'}, env))
                self.assertNotIn('synthetic secret', (root/'identity-ticket.json').read_text())
                env.write_text('changed credentials')
                self.assertFalse(identity.valid(root, 'one', 116, entry, env))
                env.write_text('synthetic secret')
            for wall, mono in ((111,211),(99,201),(101,211)):
                with patch.object(identity.time, 'time', return_value=wall), patch.object(identity.time, 'monotonic', return_value=mono):
                    self.assertFalse(identity.valid(root, 'one', 116, entry, env))
            identity.clear(root)
            self.assertFalse(identity.valid(root, 'one', 116, entry, env))

    def test_opening_preflight_is_read_only_locked_and_timeout_falls_back(self):
        reader = watcher.HubSession(SimpleNamespace(registry='fixture'), ('hub',))
        entry = {'model': 'D235', 'host': 'fixture', 'hub': 'hub'}
        for timeout in (False, True):
            with patch.object(watcher.departure.cli, 'registry', return_value={'bell': entry}), \
                 patch.object(watcher.departure.cli, 'device_lock', side_effect=lambda *_: nullcontext()) as lock, \
                 patch.object(identity, 'binding', return_value='bound'), \
                 patch.object(identity, 'evidence', return_value={'binding':'bound'}) as evidence, \
                 patch.object(security_audio, 'identify_doorbell', new_callable=AsyncMock,
                              side_effect=TimeoutError() if timeout else None) as identify:
                asyncio.run(reader.preflight_identity({'speaker_device':'bell'}))
                self.assertEqual(lock.call_count, 2)
                identify.assert_awaited_once()
                if timeout:
                    self.assertIsNone(reader.identity_evidence)
                    evidence.assert_not_called()
                else:
                    self.assertEqual(reader.identity_evidence, {'binding':'bound'})

    def test_missing_malformed_evidence_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in (None, {}, {'binding':'x','checked_at':True,'tick':1}):
                self.assertFalse(identity.fresh(value, {}, root/'missing-env'))
