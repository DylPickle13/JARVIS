"""Offline tests: no credentials, sockets or real VeSync managers."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from air_purifier.config import Settings, load_settings
from air_purifier.vesync_client import AirPurifierController, AirPurifierError
from air_purifier.cooldown import cloud_request, CooldownError
from air_purifier.cli import main


class MultiPurifierTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(None, None, 'CA', 'America/Toronto', 'cid-a', 1, Path(self.tmp.name)/'auth', {'dylan': 'cid-a'})
        self.a = SimpleNamespace(cid='cid-a', device_name='Same', device_type='same-model', update=AsyncMock(), turn_on=AsyncMock(return_value=True))
        self.b = SimpleNamespace(cid='cid-b', device_name='Same', device_type='same-model', update=AsyncMock(), turn_on=AsyncMock(return_value=True))
        self.manager = SimpleNamespace(get_devices=AsyncMock(), devices=SimpleNamespace(air_purifiers=[self.a, self.b]))
        self.controller = AirPurifierController(self.settings)
        # Routing tests remain SDK-free; the real mutation guard has a separate
        # loopback-only gate under jarvisd/tests_sdk/.
        async def simulated_write(target, method, *args, expected_cid=None, **kwargs):
            return await getattr(target, method)(*args, **kwargs)
        guard = patch('air_purifier.vesync_client.execute_write', side_effect=simulated_write)
        guard.start()
        self.addCleanup(guard.stop)
        observation = patch('air_purifier.vesync_client.observe', new_callable=AsyncMock)
        observation.start()
        self.addCleanup(observation.stop)
        self.sessions = 0
        @asynccontextmanager
        async def fake_session():
            self.sessions += 1
            yield self.manager
        self.controller._cloud_session = fake_session

    async def test_same_model_is_ambiguous(self):
        with self.assertRaisesRegex(AirPurifierError, 'Ambiguous'):
            await self.controller.set_power(True, 'same-model')
        self.a.turn_on.assert_not_awaited()
        self.b.turn_on.assert_not_awaited()

    async def test_duplicate_names_are_ambiguous(self):
        with self.assertRaisesRegex(AirPurifierError, 'Ambiguous'):
            await self.controller.status('Same')

    async def test_alias_survives_rename(self):
        self.a.device_name = 'Renamed'
        self.assertEqual((await self.controller.status('dylan')).cid, 'cid-a')
        self.b.update.assert_not_awaited()

    async def test_default_remains_selected(self):
        self.assertEqual((await self.controller.status()).cid, 'cid-a')

    async def test_alias_never_falls_back_to_name(self):
        self.a.cid = 'changed'
        self.b.device_name = 'dylan'
        with self.assertRaisesRegex(AirPurifierError, 'Could not find'):
            await self.controller.status('dylan')

    async def test_discovery_does_not_overwrite_duplicate_names_or_update(self):
        self.assertEqual(set(await self.controller.list()), {'cid-a', 'cid-b'})
        self.a.update.assert_not_awaited()
        self.b.update.assert_not_awaited()

    async def test_missing_and_duplicate_cids_fail(self):
        for cid in (None, '', 'cid-a'):
            self.b.cid = cid
            with self.assertRaises(AirPurifierError):
                await self.controller.list()

    async def test_all_status_uses_one_session_and_discovery(self):
        result = await self.controller.status_all()
        self.assertEqual(self.sessions, 1)
        self.manager.get_devices.assert_awaited_once()
        self.a.update.assert_awaited_once()
        self.b.update.assert_awaited_once()
        self.assertTrue(all(r['ok'] for r in result.values()))

    async def test_partial_failure_keeps_other_device(self):
        self.a.update.side_effect = RuntimeError('private diagnostic')
        result = await self.controller.status_all()
        self.assertFalse(result['cid-a']['ok'])
        self.assertNotIn('private', json.dumps(result))
        self.assertTrue(result['cid-b']['ok'])

    async def test_false_update_is_not_reported_as_fresh(self):
        self.a.update.return_value = False
        result = await self.controller.status_all()
        self.assertFalse(result['cid-a']['ok'])
        with self.assertRaises(AirPurifierError):
            await self.controller.status('cid-a')

    async def test_rate_limit_stops_batch_and_prevents_next_session(self):
        self.a.update.side_effect = RuntimeError('REQUEST_HIGH')
        with self.assertRaises(RuntimeError):
            await self.controller.status_all()
        self.b.update.assert_not_awaited()
        with self.assertRaisesRegex(AirPurifierError, 'backoff'):
            await self.controller.status_all()
        self.assertEqual(self.sessions, 1)

    async def test_cid_targeted_write_does_not_touch_other(self):
        self.controller._wait_for_status = AsyncMock(return_value='verified')
        self.assertEqual(await self.controller.set_power(True, 'cid-b'), 'verified')
        self.a.turn_on.assert_not_awaited()
        self.b.turn_on.assert_awaited_once()


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = Path(self.tmp.name)/'auth'
        self.path = self.auth.with_name('.vesync_cooldown')

    def test_failure_backoff_doubles_and_caps_without_automatic_retries(self):
        for delay in (300, 600, 1200, 2400, 3600, 3600):
            with patch('air_purifier.cooldown.time.time', return_value=1000):
                with self.assertRaises(RuntimeError):
                    with cloud_request(self.auth, retry=True):
                        raise RuntimeError('-11003000')
            self.assertEqual(json.loads(self.path.read_text())['until'], 1000+delay)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_explicit_probe_success_clears_legacy_cooldown(self):
        self.path.write_text('9999999999')
        with self.assertRaises(CooldownError):
            with cloud_request(self.auth):self.fail('must not make cloud call')
        with cloud_request(self.auth, retry=True):pass
        self.assertFalse(self.path.exists())

    def test_server_guidance_honored(self):
        error = RuntimeError('rate limit')
        error.retry_after = 7200
        with patch('air_purifier.cooldown.time.time', return_value=1000):
            with self.assertRaises(RuntimeError):
                with cloud_request(self.auth):raise error
        self.assertEqual(json.loads(self.path.read_text())['until'], 8200)

    def test_corrupt_files_fail_closed_even_for_probe(self):
        for content in ('NaN', 'Infinity', 'garbage', '{}', '-3', 'true'):
            self.path.write_text(content)
            with self.assertRaises(CooldownError):
                with cloud_request(self.auth, retry=True):self.fail('must not run')

    def test_concurrent_session_rejected(self):
        with cloud_request(self.auth):
            with self.assertRaisesRegex(CooldownError, 'in progress'):
                with cloud_request(self.auth):self.fail('must not overlap')

    def test_http_429_creates_backoff(self):
        error = RuntimeError('request failed')
        error.status = 429
        with self.assertRaises(RuntimeError):
            with cloud_request(self.auth):raise error
        self.assertTrue(self.path.exists())

    def test_non_rate_error_does_not_create_backoff(self):
        with self.assertRaises(RuntimeError):
            with cloud_request(self.auth):raise RuntimeError('offline')
        self.assertFalse(self.path.exists())

    def test_recovery_probe_not_allowed_for_writes(self):
        with self.assertRaises(SystemExit) as caught:
            main(['--retry-cooldown', 'on', 'cid-a'])
        self.assertEqual(caught.exception.code, 2)

    def test_alias_configuration_validation(self):
        with patch('air_purifier.config.load_dotenv'), patch.dict(os.environ, {'JARVIS_AIR_PURIFIER_ALIASES':'{"Dylan":"cid-a"}'}, clear=True):
            self.assertEqual(load_settings().aliases, {'dylan':'cid-a'})
        for text in ('[]', '{"dylan":""}', '{"Dylan":"a","dylan":"b"}'):
            with patch('air_purifier.config.load_dotenv'), patch.dict(os.environ, {'JARVIS_AIR_PURIFIER_ALIASES':text}, clear=True):
                with self.assertRaises(ValueError):load_settings()


if __name__ == '__main__':
    unittest.main()
