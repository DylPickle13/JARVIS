import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from smart_plug.kasa_client import PlugStatus, SmartPlugController
from smart_plug.cli import build_parser


class BatchTests(unittest.IsolatedAsyncioTestCase):
    def controller(self, count):
        return SmartPlugController(SimpleNamespace(plugs={str(n): SimpleNamespace(host='192.0.2.' + str(n + 1)) for n in range(count)}))

    async def test_bounded_parallelism_and_independent_failure(self):
        c = self.controller(20)
        active, maximum = 0, 0
        async def read(name):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(.001)
                if name == '1':
                    raise RuntimeError('PRIVATE')
                return PlugStatus(name, c.settings.plugs[name].host, None, None, None, True, None)
            finally:
                active -= 1
        c.status = AsyncMock(side_effect=read)
        result = await c.status_all()
        self.assertEqual(len(result), 20)
        self.assertLessEqual(maximum, 8)
        self.assertGreater(maximum, 1)
        self.assertTrue(result['0']['ok'])
        self.assertFalse(result['1']['ok'])
        self.assertIsNone(result['1']['is_on'])
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(c.status.await_count, 20)

    async def test_timeout_cancels_read_without_replaying(self):
        c = self.controller(1)
        c.status = AsyncMock(side_effect=lambda _: None)
        async def slow(_):
            await asyncio.sleep(60)
        c.status.side_effect = slow
        real_timeout = asyncio.timeout
        with patch('smart_plug.kasa_client.asyncio.timeout', side_effect=lambda _: real_timeout(.01)):
            result = await c.status_all()
        self.assertFalse(result['0']['ok'])
        c.status.assert_awaited_once()

    async def test_missing_state_is_not_false_off(self):
        c = self.controller(1)
        c.status = AsyncMock(return_value=PlugStatus('0', '192.0.2.1', None, None, None, None, None))
        self.assertFalse((await c.status_all())['0']['ok'])

    async def test_empty_and_oversized_configuration(self):
        self.assertEqual(await self.controller(0).status_all(), {})
        c = self.controller(65)
        c.status = AsyncMock()
        with self.assertRaises(ValueError):
            await c.status_all()
        c.status.assert_not_called()

    def test_read_only_cli_command_has_no_target_or_write_flags(self):
        self.assertEqual(build_parser().parse_args(['--json', 'status-all']).command, 'status-all')
