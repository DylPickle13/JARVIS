"""Offline retry policy tests; no discovery or private config."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
import security_cli as cli


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, side_effect, *, model='T110', command='status'):
        with patch.object(cli, 'registry', return_value={'fixture': {'model': model}}), \
             patch.object(cli, '_execute_once', new=AsyncMock(side_effect=side_effect)) as run, \
             patch.object(cli.asyncio, 'sleep', new=AsyncMock()):
            try:
                return await cli.execute('fixture', command), run.await_count
            except Exception as exc:
                return exc, run.await_count

    async def test_transient_read_recovers(self):
        for command in ('status', 'capabilities'):
            result, count = await self.invoke([TimeoutError(), ConnectionError(), {'result': 'read_succeeded'}], command=command)
            self.assertEqual(count, 3)
            self.assertEqual(result['read_attempts'], 3)
            self.assertTrue(result['transient_recovered'])

    async def test_sdk_transport_recovers_but_authentication_does_not(self):
        from kasa.exceptions import _ConnectionError, AuthenticationError
        result, count = await self.invoke([_ConnectionError('private'), {'result': 'read_succeeded'}])
        self.assertEqual(count, 2)
        self.assertTrue(result['transient_recovered'])
        _, count = await self.invoke(AuthenticationError('private'))
        self.assertEqual(count, 1)

    async def test_bounded_failure(self):
        result, count = await self.invoke(TimeoutError('private'))
        self.assertIsInstance(result, TimeoutError)
        self.assertEqual(count, 3)
        self.assertEqual(result.read_attempts, 3)

    async def test_no_retry_identity_auth_generic_or_writes(self):
        for error in (cli.ControlError('device_identity_mismatch'), cli.ControlError('sensor_missing_or_ambiguous'),
                      RuntimeError('private')):
            _, count = await self.invoke(error)
            self.assertEqual(count, 1)
        for model, command in (('T110', 'set'), ('C230', 'status'), ('H200', 'action')):
            _, count = await self.invoke(TimeoutError(), model=model, command=command)
            self.assertEqual(count, 1)

    async def test_single_overall_budget(self):
        original = asyncio.timeout
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        with patch.object(cli, 'registry', return_value={'fixture': {'model': 'T100'}}), \
             patch.object(cli, '_execute_once', new=AsyncMock(side_effect=slow)) as run, \
             patch.object(cli.asyncio, 'timeout', side_effect=lambda seconds: original(.01)):
            with self.assertRaises(TimeoutError):
                await cli.execute('fixture', 'status')
            self.assertEqual(run.await_count, 1)
