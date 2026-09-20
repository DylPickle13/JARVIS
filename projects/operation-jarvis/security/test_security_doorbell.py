"""Offline D235 read-only boundary tests. Synthetic data only."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import security_cli as cli
import security_doorbell as doorbell


def response(*cameras):
    return {'general_camera_manage': {'paired_general_device_list': list(cameras)}}


class DoorbellTests(unittest.TestCase):
    def test_summary_allowlist(self):
        result = doorbell.summarize(response({
            'device_model': 'D235', 'device_id': 'DO_NOT_PRINT',
            'mac': 'DO_NOT_PRINT', 'backup_wifi': {'password': 'DO_NOT_PRINT'},
            'hub_storage_enabled': True, 'plan_24h_record': False,
            'network_mode': 'wireless',
        }))
        self.assertNotIn('DO_NOT_PRINT', json.dumps(result))
        self.assertIs(result['features']['hub_storage_enabled']['value'], True)
        self.assertIs(result['features']['plan_24h_record']['value'], False)
        self.assertEqual(result['doorbell_reachability'], 'not_assessed')
        self.assertIsNone(result['features']['wifi_backup_enabled']['value'])
        for name in doorbell.UNVERIFIED:
            self.assertFalse(result['capabilities'][name]['enabled_in_cli'])

    def test_missing_ambiguous_and_malformed_fail_closed(self):
        for value in ({}, response(), response({'device_model': 'C230'}),
                      response({'device_model': 'D235'}, {'device_model': 'D235'}),
                      response(None)):
            with self.subTest(value=value), self.assertRaises(cli.ControlError):
                doorbell.summarize(value)

    def test_no_coercion(self):
        result = doorbell.summarize(response({'device_model': 'D235',
            'hub_storage_enabled': 'true', 'plan_24h_record': 1,
            'network_mode': 'secret'}))
        for name in ('hub_storage_enabled', 'plan_24h_record', 'network_mode'):
            self.assertIsNone(result['features'][name]['value'])

    def test_unsupported_writes_and_media_fail_before_connecting(self):
        for command in ('set', 'action', 'move', 'storage', 'audio'):
            with self.subTest(command=command), self.assertRaises(cli.ControlError):
                cli.validate_request('D235', command, 'state', 'on', True, True)
        for command in ('status', 'capabilities'):
            cli.validate_request('D235', command, None, None, False, False)
        with self.assertRaises(cli.ControlError):
            cli.validate_request('D235', 'privacy', None, 'on', False, False)

    def test_registry_requires_hub_and_no_guessed_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'devices.json'
            hub = {'hub': {'model': 'H200', 'host': '@hub'}}
            for entry in ({'model': 'D235', 'host': '192.168.1.2'},
                          {'model': 'D235', 'hub': 'other'}):
                path.write_text(json.dumps({**hub, 'bell': entry}))
                with self.assertRaises(cli.ControlError):
                    cli.registry(path)
            entry = {'model': 'D235', 'hub': 'hub'}
            path.write_text(json.dumps({'bell': entry}))
            with self.assertRaises(cli.ControlError):
                cli.registry(path)
            path.write_text(json.dumps({**hub, 'bell': entry}))
            self.assertEqual(cli.registry(path)['bell'], entry)

    def test_cli_uses_hub_lock_and_read_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'devices.json'
            path.write_text(json.dumps({'hub': {'model': 'H200', 'host': '@hub'},
                                       'bell': {'model': 'D235', 'hub': 'hub'}}))
            with patch.object(cli, 'device_lock') as lock, patch.object(
                    doorbell, 'execute', new_callable=AsyncMock) as reader:
                reader.return_value = {'result': 'read_succeeded', 'model': 'D235'}
                result = asyncio.run(cli.execute('bell', 'status', registry_path=path))
                self.assertEqual(result['device'], 'bell')
                lock.assert_called_once_with('hub')
                reader.assert_awaited_once()


class DirectDoorbellTests(unittest.TestCase):
    def setUp(self):
        import security_doorbell_direct
        self.d = security_doorbell_direct

    def test_switch_validation(self):
        for name in self.d.WRITABLE:
            spec = self.d.SPECS[name]
            if spec.kind == 'Switch':
                self.assertEqual(self.d.validate('set', name, 'on', True), (name, True))
                self.assertEqual(self.d.validate('set', name, 'off', True), (name, False))
                for invalid in ('true', 'yes', '', None):
                    with self.assertRaises(cli.ControlError):
                        self.d.validate('set', name, invalid, True)
        self.assertEqual(self.d.validate('privacy', None, 'on', True), ('privacy', True))

    def test_confirmation_and_numeric_ranges(self):
        for confirm in (False, None, 'true', 1):
            with self.assertRaises(cli.ControlError):
                self.d.validate('set', 'speaker_volume', '10', confirm)
        for name in self.d.WRITABLE:
            spec = self.d.SPECS[name]
            if spec.kind != 'Number':
                continue
            for value in (spec.minimum, spec.maximum):
                self.assertEqual(self.d.validate('set', name, str(value), True), (name, value))
            for invalid in (str(spec.minimum - 1), str(spec.maximum + 1), '1.0', 'NaN', '999999', True):
                with self.assertRaises(cli.ControlError):
                    self.d.validate('set', name, invalid, True)

    def test_unimplemented_actions_fail(self):
        for name in ('reboot', 'format', 'power_mode', 'chime_ring', 'state', 'night_vision_mode'):
            with self.assertRaises(cli.ControlError):
                self.d.validate('set', name, 'on', True)
            with self.assertRaises(cli.ControlError):
                self.d.validate('action', name, None, True)

    def test_decode_strict_and_private(self):
        spec = self.d.SPECS['battery_percent']
        self.assertEqual(self.d.decode(spec, {'battery': {'status': {'battery_percent': '66'}}}), 66)
        for invalid in (True, 101, -1, {}, 'DO_NOT_PRINT'):
            with self.assertRaises(cli.ControlError):
                self.d.decode(spec, {'battery': {'status': {'battery_percent': invalid}}})
        client = Mock()
        client.executeFunction.return_value = {'device_id': 'DO_NOT_PRINT', 'password': 'DO_NOT_PRINT'}
        result = self.d.snapshot(client)
        self.assertNotIn('DO_NOT_PRINT', json.dumps(result))
        self.assertTrue(all(row['status'] == 'unknown' for row in result['features'].values()))
        self.assertTrue(all(not row['writable'] for row in result['features'].values()))
        self.assertTrue(all(call.args[0].startswith('get') for call in client.executeFunction.call_args_list))

    def test_exact_minimal_write_payload_and_readback(self):
        client = Mock()
        client.executeFunction.side_effect = [
            {'audio_config': {'speaker': {'volume': '100'}}}, {},
            {'audio_config': {'speaker': {'volume': '35'}}}]
        result = self.d.apply_setting(client, 'speaker_volume', 35)
        self.assertEqual(result['result'], 'verified')
        self.assertEqual(client.executeFunction.call_args_list[1].args,
                         ('setSpeakerVolume', {'audio_config': {'speaker': {'volume': 35}}, 'method': 'set'}))
        self.assertEqual(client.executeFunction.call_count, 3)

    def test_readback_mismatch_and_failure_are_unknown_no_replay(self):
        for after in ({'people_detection': {'detection': {'enabled': 'off'}}}, RuntimeError('secret')):
            client = Mock()
            client.executeFunction.side_effect = [
                {'people_detection': {'detection': {'enabled': 'off'}}}, {}, after]
            if isinstance(after, Exception):
                with self.assertRaisesRegex(cli.ControlError, '^write_outcome_unknown$'):
                    self.d.apply_setting(client, 'person_detection', True)
            else:
                self.assertEqual(self.d.apply_setting(client, 'person_detection', True)['outcome'], 'unknown')
            self.assertEqual(sum(c.args[0].startswith('set') for c in client.executeFunction.call_args_list), 1)

    def test_failed_preflight_never_writes(self):
        client = Mock()
        client.executeFunction.return_value = {}
        with self.assertRaises(cli.ControlError):
            self.d.apply_setting(client, 'privacy', True)
        self.assertEqual(client.executeFunction.call_count, 1)
        self.assertEqual(client.executeFunction.call_args.args[0], 'getLensMaskConfig')

    def test_identity_mismatch_closes_without_setting(self):
        client = Mock()
        client.basicInfo = {'device_info': {'basic_info': {'device_model': 'C230'}}}
        with patch.object(self.d, 'load_settings', return_value=cli.Settings(
                host='192.168.1.2', username='synthetic', password='synthetic')), \
                patch.object(self.d, 'make_client', return_value=client):
            with self.assertRaisesRegex(cli.ControlError, 'device_identity_mismatch'):
                self.d.run({'model': 'D235', 'host': '192.168.1.3'}, 'unused',
                           'set', 'person_detection', 'on', True)
        client.executeFunction.assert_not_called()
        client.close.assert_called_once()

    def test_identity_only_skips_snapshot_and_still_checks_model_and_type(self):
        for model, kind, accepted in (
                ('D235', 'SMART.TAPODOORBELL', True),
                ('C230', 'SMART.TAPODOORBELL', False),
                ('D235', 'SMART.IPCAMERA', False)):
            with self.subTest(model=model, kind=kind):
                client = Mock()
                client.basicInfo = {'device_info': {'basic_info': {
                    'device_model': model, 'device_type': kind}}}
                with patch.object(self.d, 'load_settings', return_value=cli.Settings(
                        host='192.168.1.2', username='synthetic', password='synthetic')), \
                        patch.object(self.d, 'make_client', return_value=client), \
                        patch.object(self.d, 'snapshot') as snapshot:
                    if accepted:
                        result = self.d.run({'model': 'D235', 'host': '192.168.1.3'},
                                            'unused', 'identity')
                        self.assertEqual(result['result'], 'read_succeeded')
                        self.assertEqual(result['doorbell_reachability'], 'authenticated')
                        self.assertNotIn('features', result)
                    else:
                        with self.assertRaisesRegex(cli.ControlError, 'device_identity_mismatch'):
                            self.d.run({'model': 'D235', 'host': '192.168.1.3'}, 'unused', 'identity')
                    snapshot.assert_not_called()
                client.executeFunction.assert_not_called()
                client.close.assert_called_once()

    def test_transport_replay_guards(self):
        try:
            import pytapo
            from pytapo.const import MAX_LOGIN_RETRIES
            from pytapo.transport.pytapo.pytapo import TRANSIENT_REQUEST_RETRIES
        except ImportError:
            self.skipTest('transport guard runs in isolated archive environment')
        transport = Mock()
        send = AsyncMock(return_value={})
        request = Mock(return_value={})
        transport.send, transport._request = send, request
        self.d.disable_transport_replays(transport)
        asyncio.run(transport.send({'method': 'synthetic'}))
        send.assert_awaited_once_with({'method': 'synthetic'}, retry=MAX_LOGIN_RETRIES)
        transport._request('POST', 'https://synthetic.invalid')
        request.assert_called_once_with('POST', 'https://synthetic.invalid',
            transientRetryCount=TRANSIENT_REQUEST_RETRIES, timeout=5)

    def test_direct_registry_and_cli_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'devices.json'
            entry = {'model': 'D235', 'hub': 'hub', 'host': '192.168.1.3'}
            path.write_text(json.dumps({'hub': {'model': 'H200', 'host': '@hub'}, 'bell': entry}))
            self.assertEqual(cli.registry(path)['bell'], entry)
            with patch.object(cli, 'device_lock') as lock, patch.object(
                    doorbell, 'execute', new_callable=AsyncMock) as reader:
                reader.return_value = {'result': 'read_succeeded', 'model': 'D235'}
                asyncio.run(cli.execute('bell', 'status', registry_path=path))
                lock.assert_called_once_with('hub')
                self.assertEqual(reader.await_args.kwargs['entry'], entry)
                reader.reset_mock()
                with self.assertRaisesRegex(cli.ControlError, 'confirmation_required'):
                    asyncio.run(cli.execute('bell', 'set', name='speaker_volume', value='35', registry_path=path))
                reader.assert_not_awaited()

    def test_legacy_registry_never_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'devices.json'
            path.write_text(json.dumps({'hub': {'model': 'H200', 'host': '@hub'},
                                       'bell': {'model': 'D235', 'hub': 'hub'}}))
            with patch.object(doorbell, 'execute', new_callable=AsyncMock) as reader:
                with self.assertRaisesRegex(cli.ControlError, 'direct_doorbell_required'):
                    asyncio.run(cli.execute('bell', 'privacy', value='on', confirm=True, registry_path=path))
                reader.assert_not_awaited()

    def test_worker_timeout_kills_and_reaps(self):
        process = Mock(returncode=None)
        process.communicate = AsyncMock(side_effect=[TimeoutError(), (b'', b'')])
        process.kill = Mock()
        with patch.object(Path, 'is_file', return_value=True), \
                patch.object(asyncio, 'create_subprocess_exec', AsyncMock(return_value=process)):
            with self.assertRaisesRegex(cli.ControlError, '^write_outcome_unknown$'):
                asyncio.run(doorbell.execute('unused', entry={'model': 'D235'},
                                            command='set', name='led', value='off', confirm=True))
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.await_count, 2)


if __name__ == '__main__':
    unittest.main()
