"""Offline DHCP-reuse regressions; fake devices and temporary configs only."""
import contextlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from smart_plug.config import (
    PlugConfig, _parse_json_plugs, load_settings, normalize_mac, write_plug_config,
)
from smart_plug.kasa_client import SmartPlugController

MAC = 'AA-BB-CC-DD-EE-01'
OTHER_MAC = 'AA:BB:CC:DD:EE:02'
HOST = '192.168.50.10'
NEW_HOST = '192.168.50.9'


def device(mac=MAC, host=HOST):
    return SimpleNamespace(
        host=host, mac=mac, alias='Alias is not identity', model='HS103',
        is_on=False, rssi=-45, update=AsyncMock(), disconnect=AsyncMock(),
        turn_on=AsyncMock(), turn_off=AsyncMock(),
    )


def controller(plug=None):
    return SmartPlugController(SimpleNamespace(
        plugs={'light': plug or PlugConfig('light', HOST, ('room-light',), MAC)},
        username=None, password=None, credentials=[],
    ))


class ConfigIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'plugs.json'

    def save(self, payload):
        self.path.write_text(json.dumps(payload))

    def test_mac_formats_and_invalid_values(self):
        for value in (MAC, 'aa:bb:cc:dd:ee:01', 'aabbccddee01'):
            self.assertEqual(normalize_mac(value), 'aabbccddee01')
        for value in (None, '', 'invalid', '00:00:00:00:00:00', 123):
            self.assertIsNone(normalize_mac(value))

    def test_dictionary_and_list_configs_keep_mac_and_aliases(self):
        item = {'host': HOST, 'mac': MAC, 'aliases': ['room light']}
        for payload in ({'plugs': {'light': item}}, [{'name': 'light', **item}]):
            self.save(payload)
            plug = _parse_json_plugs(self.path)['light']
            self.assertEqual(plug.mac, normalize_mac(MAC))
            self.assertEqual(plug.aliases, ('room-light',))

    def test_legacy_config_and_missing_mac_remain_supported(self):
        for payload in ({'light': HOST}, {'plugs': {'light': {'host': HOST}}}):
            self.save(payload)
            self.assertIsNone(_parse_json_plugs(self.path)['light'].mac)

    def test_malformed_recorded_mac_does_not_downgrade_to_unbound_access(self):
        for value in ('', 'invalid', '00:00:00:00:00:00', 123):
            self.save({'plugs': {'light': {'host': HOST, 'mac': value}}})
            with self.assertRaisesRegex(ValueError, 'Invalid configured plug MAC'):
                _parse_json_plugs(self.path)

    def test_environment_ip_override_preserves_identity_and_aliases(self):
        self.save({'plugs': {'light': {'host': HOST, 'mac': MAC, 'aliases': ['room light']}}})
        with patch.dict(os.environ, {'SMART_PLUGS': f'light={NEW_HOST}'}, clear=True), \
                patch('smart_plug.config.load_dotenv'):
            plug = load_settings(self.path).plugs['light']
        self.assertEqual(plug.host, NEW_HOST)
        self.assertEqual(plug.mac, normalize_mac(MAC))
        self.assertEqual(plug.aliases, ('room-light',))

    def test_config_writer_keeps_mac(self):
        write_plug_config({'light': PlugConfig('light', HOST, mac=MAC)}, self.path)
        self.assertEqual(_parse_json_plugs(self.path)['light'].mac, normalize_mac(MAC))


class ControllerIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_checks_identity_for_name_alias_and_direct_ip(self):
        for selector in ('light', 'room light', HOST):
            c, d = controller(), device(OTHER_MAC)
            c._connect = AsyncMock(return_value=d)
            with self.assertRaisesRegex(RuntimeError, 'MAC identity mismatch'):
                await c.status(selector)
            d.disconnect.assert_awaited_once()
            d.turn_on.assert_not_called()
            d.turn_off.assert_not_called()

    async def test_status_requires_observed_mac_but_does_not_trust_alias(self):
        for mac in (None, '', OTHER_MAC):
            c, d = controller(), device(mac)
            d.alias = 'light'
            c._connect = AsyncMock(return_value=d)
            with self.assertRaisesRegex(RuntimeError, 'MAC identity mismatch'):
                await c.status('light')
        c, d = controller(), device('aa:bb:cc:dd:ee:01')
        c._connect = AsyncMock(return_value=d)
        self.assertIs((await c.status('light')).is_on, False)
        d.disconnect.assert_awaited_once()

    async def test_on_off_toggle_reject_reused_ip_before_any_mutation(self):
        for action in ('on', 'off', 'toggle'):
            for expected_host in (None, HOST):
                with self.subTest(action=action, expected_host=expected_host):
                    c, d = controller(), device(OTHER_MAC)
                    c.settings.credentials = [
                        SimpleNamespace(username='fixture', password='fixture'),
                        SimpleNamespace(username='alternate', password='alternate'),
                    ]
                    c._connect = AsyncMock(return_value=d)
                    with patch('smart_plug.kasa_client._single_attempt_write') as guard:
                        with self.assertRaisesRegex(RuntimeError, 'MAC identity mismatch'):
                            if action == 'toggle':
                                await c.toggle('room light', expected_host=expected_host)
                            else:
                                await c.set_power('light', action == 'on', expected_host=expected_host)
                        guard.assert_not_called()
                    c._connect.assert_awaited_once()  # No credential fallback on mismatch.
                    d.turn_on.assert_not_called()
                    d.turn_off.assert_not_called()
                    d.disconnect.assert_awaited_once()

    async def test_missing_mac_blocks_write(self):
        c, d = controller(), device(None)
        c._connect = AsyncMock(return_value=d)
        with self.assertRaisesRegex(RuntimeError, 'MAC identity mismatch'):
            await c.set_power('light', True)
        d.turn_on.assert_not_called()
        d.disconnect.assert_awaited_once()

    async def test_matching_identity_allows_one_synthetic_write(self):
        for action in ('on', 'off', 'toggle'):
            c, d = controller(), device()
            async def on():
                d.is_on = True
            d.turn_on.side_effect = on
            c._connect = AsyncMock(return_value=d)
            with patch('smart_plug.kasa_client._single_attempt_write', side_effect=lambda *_: contextlib.nullcontext()):
                if action == 'toggle':
                    result = await c.toggle('light', expected_host=HOST)
                else:
                    result = await c.set_power('light', action == 'on', expected_host=HOST)
            self.assertIs(result.is_on, action != 'off')
            self.assertEqual(d.turn_on.await_count + d.turn_off.await_count, 1)
            d.disconnect.assert_awaited_once()

    async def test_verification_identity_change_is_uncertain_without_replay(self):
        c, d = controller(), device()
        def update():
            if d.update.await_count == 2:
                d.mac = OTHER_MAC
                d.is_on = True
        d.update.side_effect = update
        c._connect = AsyncMock(return_value=d)
        with patch('smart_plug.kasa_client._single_attempt_write', side_effect=lambda *_: contextlib.nullcontext()):
            with self.assertRaisesRegex(RuntimeError, 'MAC identity mismatch'):
                await c.set_power('light', True, expected_host=HOST)
        d.turn_on.assert_awaited_once()
        c._connect.assert_awaited_once()
        d.disconnect.assert_awaited_once()

    async def test_invalid_or_conflicting_config_identity_blocks_connection(self):
        c = controller(PlugConfig('light', HOST, mac='invalid'))
        c._connect = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, 'Invalid configured plug MAC'):
            await c.set_power('light', True)
        c._connect.assert_not_called()
        c = controller()
        c.settings.plugs['other'] = PlugConfig('other', HOST, mac=OTHER_MAC)
        c._connect = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, 'Conflicting configured plug identities'):
            await c.status('light')
        c._connect.assert_not_called()

    async def test_legacy_config_still_supports_unbound_status(self):
        c, d = controller(PlugConfig('light', HOST)), device(None)
        c._connect = AsyncMock(return_value=d)
        self.assertIs((await c.status('light')).is_on, False)

    async def test_save_discovery_does_not_drop_identity(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        c, d = controller(), device()
        c.settings.config_path = Path(temporary.name) / 'plugs.json'
        c._connect = AsyncMock(return_value=d)
        c.discover = AsyncMock(return_value={'light': await c.status('light')})
        await c.save_discovery()
        self.assertEqual(_parse_json_plugs(c.settings.config_path)['light'].mac, normalize_mac(MAC))

    async def test_reused_ip_is_failed_read_then_mac_verified_dhcp_recovery(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'plugs.json'
        path.write_text(json.dumps({'plugs': {'light': {'host': HOST, 'mac': MAC}}}))
        wrong, correct = device(OTHER_MAC), device(host=NEW_HOST)
        with patch.dict(os.environ, {}, clear=True), patch('smart_plug.config.load_dotenv'), \
                patch('smart_plug.ip_recovery.Discover.discover', new_callable=AsyncMock) as discovery, \
                patch('smart_plug.ip_recovery.time.time', return_value=1000):
            discovery.return_value = {HOST: wrong, NEW_HOST: correct}
            for poll in range(3):
                c = SmartPlugController(load_settings(path))
                c._connect = AsyncMock(return_value=wrong)
                result = (await c.status_all())['light']
                if poll < 2:
                    self.assertFalse(result['ok'])
                    self.assertIsNone(result['is_on'])
                    discovery.assert_not_awaited()
            self.assertTrue(result['ok'])
            self.assertEqual(result['host'], NEW_HOST)
            self.assertIs(result['is_on'], False)
            self.assertEqual(load_settings(path).plugs['light'].host, NEW_HOST)
            discovery.assert_awaited_once()
        correct.update.assert_awaited_once()
        for d in (wrong, correct):
            d.turn_on.assert_not_called()
            d.turn_off.assert_not_called()
