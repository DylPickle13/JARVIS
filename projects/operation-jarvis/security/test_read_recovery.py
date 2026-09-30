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

    async def test_hub_http_session_forces_fresh_connections(self):
        session = cli.new_hub_read_http_session()
        try:
            self.assertTrue(session.connector.force_close)
            self.assertIsNotNone(session.cookie_jar)
            self.assertFalse(session.closed)
        finally:
            await session.close()
        self.assertTrue(session.closed)

    async def test_hub_read_http_scope_and_cleanup(self):
        from contextlib import nullcontext
        from types import SimpleNamespace as NS
        cases = [('H200', 'status', None), ('H200', 'capabilities', None),
                 ('H200', 'status', RuntimeError('private')),
                 ('H200', 'status', asyncio.CancelledError()),
                 ('H200', 'action', None), ('C230', 'status', None)]
        for model, command, failure in cases:
            with self.subTest(model=model, command=command, failure=type(failure).__name__):
                session = NS(close=AsyncMock())
                device = NS(model=model, device_type=NS(value='hub' if model == 'H200' else 'camera'),
                            config=NS(http_client=None), update=AsyncMock(), disconnect=AsyncMock(),
                            protocol=NS(query=AsyncMock(side_effect=failure, return_value={
                                'getDeviceInfo': {'device_info': {'basic_info': {'device_model': model}}}})))
                with patch.object(cli, 'registry', return_value={'fixture': {'model': model, 'host': '@hub'}}), \
                     patch.object(cli, 'load_settings', return_value=NS(host='192.0.2.1', username='u', password='p')), \
                     patch.object(cli, 'device_lock', return_value=nullcontext()), \
                     patch.object(cli, 'validate_request'), \
                     patch.object(cli, 'install_empty_child_lists_compat'), \
                     patch.object(cli, 'new_hub_read_http_session', return_value=session) as factory, \
                     patch.object(cli, 'operate', new=AsyncMock(return_value={'result': 'read_succeeded'})), \
                     patch('kasa.Discover.discover_single', new=AsyncMock(return_value=device)):
                    if failure is not None:
                        with self.assertRaises(type(failure)):
                            await cli._execute_once('fixture', command)
                    else:
                        await cli._execute_once('fixture', command)
                device.disconnect.assert_awaited_once()
                if model == 'H200' and command in ('status', 'capabilities'):
                    factory.assert_called_once_with()
                    self.assertIs(device.config.http_client, session)
                    session.close.assert_awaited_once_with()
                else:
                    factory.assert_not_called()
                    self.assertIsNone(device.config.http_client)
                    session.close.assert_not_awaited()
