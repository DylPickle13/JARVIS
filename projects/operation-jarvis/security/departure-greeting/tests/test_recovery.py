"""Offline autonomous recovery: real proof, no replay, bounded read pacing."""
import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone, timedelta
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import departure
import recovery
import runtime
import watcher


class RecoveryTests(unittest.TestCase):
    def test_retry_delay_caps_forever_without_overflow(self):
        self.assertEqual([recovery.delay(n,transport=True,jitter=lambda:0) for n in range(1,9)],
                         [2,4,8,16,32,60,60,60])
        self.assertEqual(recovery.delay(10**100,transport=True),60)
        self.assertEqual(recovery.delay(1,transport=False),300)

    def test_wrapped_handshake_timeout_is_read_transport_not_auth(self):
        from kasa.exceptions import KasaException, AuthenticationError
        wrapped=KasaException('secret');wrapped.__cause__=TimeoutError()
        self.assertTrue(recovery.transient(wrapped))
        auth=AuthenticationError('secret');auth.__cause__=TimeoutError()
        self.assertFalse(recovery.transient(auth))
        self.assertFalse(recovery.transient(ValueError('bad schema')))
        self.assertFalse(recovery.transient(KasaException('unclassified')))

    def test_hub_session_expiry_reconnects_fast_but_other_device_codes_do_not(self):
        from kasa.exceptions import (AuthenticationError, DeviceError, SmartErrorCode,
                                     _RetryableError)
        expired=_RetryableError('secret',error_code=SmartErrorCode.SESSION_EXPIRED)
        self.assertTrue(recovery.transient(expired))
        self.assertLess(recovery.delay(1,transport=recovery.transient(expired)),3)
        # Same code on a non-retryable/auth class, or other retryable codes, stay slow faults.
        self.assertFalse(recovery.transient(DeviceError('secret',error_code=SmartErrorCode.SESSION_EXPIRED)))
        self.assertFalse(recovery.transient(AuthenticationError('secret',error_code=SmartErrorCode.SESSION_EXPIRED)))
        self.assertFalse(recovery.transient(_RetryableError('secret',error_code=SmartErrorCode.UNSPECIFIC_ERROR)))
        self.assertFalse(recovery.transient(_RetryableError('secret',error_code=SmartErrorCode.SESSION_TIMEOUT_ERROR)))

    def test_recovery_never_learns_changed_hub_or_sensor_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            reader=NS(hub_info={'device_model':'H200','mac':'02:11:22:33:44:55'},motion_id='motion',door_id='door')
            with self.assertRaises(runtime.TrialError):recovery.verify_identity(root,reader)
            pins={'version':1,'hub':hashlib.sha256(b'021122334455').hexdigest(),
                  'sensors':[hashlib.sha256(x).hexdigest() for x in (b'motion',b'door')]}
            runtime.save_json(root/'sensor-identity.json',pins)
            recovery.verify_identity(root,reader)
            reader.door_id='other'
            with self.assertRaises(runtime.TrialError):recovery.verify_identity(root,reader)
            self.assertEqual(runtime.read_json(root/'sensor-identity.json'),pins)

    def fixture(self, root):
        value={'version':1,'enabled':True,'motion_device':'motion-sensor','door_device':'door-sensor','speaker_device':'front-doorbell','volume':60}
        runtime.save_json(root/'config.json',value)
        state=runtime.default_state();state.update(pending='old',fault='playback_outcome_unknown',last_attempt=100,last_outcome='unknown')
        runtime.save_json(root/'state.json',state)
        return value,runtime.Journal(root)

    def test_unknown_event_retired_only_after_idle_and_cooldown_never_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);value,j=self.fixture(root)
            with patch.object(departure.cli,'registry',return_value={'front-doorbell':{'model':'D235','hub':'hub'}}), \
                 patch.object(departure.cli,'device_lock',side_effect=lambda *_:nullcontext()):
                self.assertFalse(watcher.retire_abandoned(root,j,value,now=lambda:219))
                with runtime.worker_lock(root):
                    self.assertFalse(watcher.retire_abandoned(root,j,value,now=lambda:220))
                self.assertTrue(watcher.retire_abandoned(root,j,value,now=lambda:220))
                self.assertFalse(watcher.retire_abandoned(root,j,value,now=lambda:221))
            restored=runtime.Journal(root).state
            self.assertIsNone(restored['pending']);self.assertIsNone(restored['fault'])
            self.assertEqual(restored['last_attempt'],100);self.assertEqual(restored['last_outcome'],'unknown')
            self.assertEqual(restored['completed_count'],0)

    def test_busy_device_preserves_unknown_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);value,j=self.fixture(root)
            with patch.object(departure.cli,'registry',return_value={'front-doorbell':{'model':'D235','hub':'hub'}}), \
                 patch.object(departure.cli,'device_lock',side_effect=departure.cli.ControlError('device_busy')):
                self.assertFalse(watcher.retire_abandoned(root,j,value,now=lambda:500))
            self.assertEqual(j.state['pending'],'old')

    def test_existing_sensor_fault_requires_three_new_samples_and_no_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);value,j=self.fixture(root)
            j.state.update(pending=None,fault='sensor_read_requires_review');j.flush()
            samples=[departure.Sample(i,datetime.now(timezone.utc)+timedelta(seconds=i),False,False,.1) for i in range(3)]
            reader=NS(phase='paired_read',person_camera=object(),connect=AsyncMock(),close=AsyncMock(),
                      sample=AsyncMock(side_effect=[*samples,asyncio.CancelledError()]))
            with patch.object(watcher.recovery,'verify_identity'), \
                 patch.object(watcher,'HubSession',return_value=reader), \
                 patch.object(departure,'validate_devices',return_value=('hub',{}, {},{})), \
                 patch.object(departure.cli,'registry',return_value={'front-doorbell':{'model':'D235','host':'fixture','hub':'hub'}}), \
                 patch.object(watcher.person_gate,'effective_policy',return_value={}), \
                 patch.object(watcher.person_gate,'permitted',return_value=False), \
                 patch.object(watcher.asyncio,'sleep',new_callable=AsyncMock), \
                 patch.object(watcher,'deliver',new_callable=AsyncMock) as speak:
                with self.assertRaises(asyncio.CancelledError):asyncio.run(watcher.watch(root))
            self.assertIsNone(runtime.Journal(root).state['fault']);speak.assert_not_called()
            self.assertEqual(reader.sample.await_count,4)


if __name__=='__main__':unittest.main()
