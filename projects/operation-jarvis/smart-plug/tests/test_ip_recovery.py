"""Offline recovery tests: synthetic SDK devices, private temporary configs only."""
import asyncio
import fcntl
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from smart_plug.config import PlugConfig
from smart_plug.ip_recovery import recover_failed_hosts
from smart_plug.kasa_client import SmartPlugController

MAC = '6C-4C-BC-28-A8-CF'


def device(host='192.168.21.10', mac=MAC, is_on=True):
    return SimpleNamespace(host=host, mac=mac, alias='Deliberately wrong alias',
                           model='HS103', is_on=is_on, rssi=-45,
                           update=AsyncMock(), disconnect=AsyncMock(),
                           turn_on=AsyncMock(), turn_off=AsyncMock())


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'plugs.json'
        self.payload = {'note': 'preserve', 'plugs': {
            'family-room-light': {'host': '192.168.21.9', 'mac': MAC,
                                  'aliases': ['plug 1'], 'verified': True},
            'lamp': {'host': '192.168.21.80', 'mac': '6C-4C-BC-28-9D-3A'}}}
        self.save()
        self.path.chmod(0o640)
        self.c = SmartPlugController(SimpleNamespace(
            config_path=self.path, username=None, password=None, credentials=[],
            plugs={'family-room-light': PlugConfig('family-room-light', '192.168.21.9'),
                   'lamp': PlugConfig('lamp', '192.168.21.80')}))
        self.results = {'family-room-light': {'ok': False, 'host': '192.168.21.9', 'is_on': None},
                        'lamp': {'ok': True, 'host': '192.168.21.80', 'is_on': False}}
        self.sdk = patch('smart_plug.ip_recovery.Discover.discover', new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)
        self.d = device()
        self.sdk.return_value = {self.d.host: self.d}
        self.clock = patch('smart_plug.ip_recovery.time.time', return_value=1000).start()

    def save(self):
        self.path.write_text(json.dumps(self.payload))

    async def poll(self, count=1, results=None):
        for _ in range(count):
            # Simulate independent, short-lived status-all subprocesses.
            controller = SmartPlugController(self.c.settings)
            result = await recover_failed_hosts(controller, self.results if results is None else results)
        return result

    def config(self):
        return json.loads(self.path.read_text())

    async def test_status_all_integration_recovers_without_replaying_failed_read(self):
        async def status(name):
            from smart_plug.kasa_client import PlugStatus
            if name == 'family-room-light':
                raise OSError('unreachable')
            return PlugStatus(name, '192.168.21.80', 'Lamp', 'HS103', None, False, -50)
        self.c.status = AsyncMock(side_effect=status)
        for _ in range(3):
            result = await self.c.status_all()
        self.assertEqual(self.c.status.await_count, 6)  # Exactly one read/device/batch.
        self.sdk.assert_awaited_once()
        self.assertEqual(result['family-room-light']['host'], self.d.host)
        self.assertTrue(result['lamp']['ok'])

    async def test_installed_sdk_exposes_raw_mac_before_authentication(self):
        from kasa import Discover, DeviceConfig
        from smart_plug.ip_recovery import _mac
        from smart_plug.kasa_client import _safe_get
        # Real installed SDK, synthetic discovery response; no socket/network I/O.
        real = Discover._get_device_instance({'result': {
            'device_type': 'IOT.SMARTPLUGSWITCH', 'device_model': 'HS103(US)',
            'device_id': 'fixture', 'ip': self.d.host, 'mac': MAC,
            'mgt_encrypt_schm': {'is_support_https': False, 'encrypt_type': 'KLAP', 'lv': 2}}},
            DeviceConfig(host=self.d.host))
        try:
            self.assertEqual(_mac(_safe_get(real, 'mac')), _mac(MAC))
            def update():
                info = {'mac': MAC, 'model': 'HS103', 'alias': 'Wrong alias', 'relay_state': 1}
                real._set_sys_info(info)
                real._last_update = {'system': {'get_sysinfo': info}}
            real.update = AsyncMock(side_effect=update)
            self.sdk.return_value = {self.d.host: real}
            result = await self.poll(3)
            self.assertTrue(result['family-room-light']['ok'])
            self.assertEqual(result['family-room-light']['host'], self.d.host)
            real.update.assert_awaited_once()
        finally:
            await real.disconnect()

    async def test_single_status_does_not_discover_or_modify_config(self):
        self.c._connect = AsyncMock(return_value=self.d)
        await self.c.status('family-room-light')
        self.sdk.assert_not_awaited()
        self.assertEqual(self.config(), self.payload)

    async def test_threshold_and_mac_match_ignore_alias_preserve_metadata(self):
        await self.poll(2)
        self.sdk.assert_not_awaited()
        result = await self.poll()
        self.sdk.assert_awaited_once()
        self.assertEqual(self.sdk.call_args.kwargs['target'], '192.168.21.255')
        self.assertTrue(result['family-room-light']['ok'])
        self.assertEqual(result['family-room-light']['host'], self.d.host)
        self.assertIs(result['lamp'], self.results['lamp'])
        self.payload['plugs']['family-room-light']['host'] = self.d.host
        self.assertEqual(self.config(), self.payload)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.d.update.assert_awaited_once()
        self.d.disconnect.assert_awaited_once()
        self.d.turn_on.assert_not_called()
        self.d.turn_off.assert_not_called()
        self.assertEqual((self.path.parent / '.plugs.json.ip-recovery.json').stat().st_mode & 0o777, 0o600)

    async def test_healthy_reads_no_files_or_discovery(self):
        await self.poll(4, {name: {'ok': True} for name in self.results})
        self.sdk.assert_not_awaited()
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['plugs.json'])

    async def test_success_resets_consecutive_failures(self):
        await self.poll(2)
        await self.poll(results={name: {'ok': True} for name in self.results})
        await self.poll(2)
        self.sdk.assert_not_awaited()
        await self.poll()
        self.sdk.assert_awaited_once()

    async def test_global_cooldown_persists_after_error_and_clock_rollback(self):
        self.sdk.side_effect = RuntimeError('PRIVATE credentials')
        self.assertEqual(await self.poll(3), self.results)
        await self.poll(10)
        self.clock.return_value = 500  # Future timestamps fail closed.
        await self.poll(3)
        self.clock.return_value = 1299
        await self.poll(3)
        self.sdk.assert_awaited_once()
        self.clock.return_value = 1300
        await self.poll()
        self.assertEqual(self.sdk.await_count, 2)
        self.assertEqual(self.config(), self.payload)

    async def test_cancellation_records_cooldown_and_releases_lock(self):
        async def cancel(**kwargs):
            raise asyncio.CancelledError()
        self.sdk.side_effect = cancel
        await self.poll(2)
        with self.assertRaises(asyncio.CancelledError):
            await self.poll()
        await self.poll()
        self.sdk.assert_awaited_once()

    async def test_wrong_mac_alias_is_not_enough(self):
        self.d.mac = '00:11:22:33:44:55'
        self.d.alias = 'Family room light'
        self.assertEqual(await self.poll(3), self.results)
        self.assertEqual(self.config(), self.payload)
        self.d.update.assert_not_called()
        self.d.disconnect.assert_awaited_once()

    async def test_duplicate_discovery_mac_is_rejected(self):
        other = device('192.168.21.11')
        self.sdk.return_value[other.host] = other
        self.assertEqual(await self.poll(3), self.results)
        self.d.update.assert_not_called()
        other.update.assert_not_called()
        other.disconnect.assert_awaited_once()

    async def test_missing_and_duplicate_config_macs_do_not_discover(self):
        del self.payload['plugs']['family-room-light']['mac']
        self.save()
        await self.poll(4)
        self.sdk.assert_not_awaited()
        self.payload['plugs']['family-room-light']['mac'] = MAC
        self.payload['plugs']['lamp']['mac'] = MAC
        self.save()
        await self.poll(4)
        self.sdk.assert_not_awaited()

    async def test_environment_override_is_not_rewritten(self):
        self.c.settings.plugs['family-room-light'] = PlugConfig('family-room-light', '192.168.21.20')
        await self.poll(4)
        self.sdk.assert_not_awaited()
        self.assertEqual(self.config(), self.payload)

    async def test_new_config_identity_resets_failures(self):
        await self.poll(2)
        self.payload['plugs']['family-room-light']['host'] = '192.168.21.12'
        self.save()
        self.c.settings.plugs['family-room-light'] = PlugConfig('family-room-light', '192.168.21.12')
        await self.poll(2)
        self.sdk.assert_not_awaited()
        await self.poll()
        self.sdk.assert_awaited_once()

    async def test_intervening_edit_is_preserved(self):
        async def edit(**kwargs):
            self.payload['note'] = 'owner edited during discovery'
            self.save()
            return {self.d.host: self.d}
        self.sdk.side_effect = edit
        self.assertEqual(await self.poll(3), self.results)
        self.assertEqual(self.config(), self.payload)

    async def test_target_host_collision_is_rejected(self):
        self.d.host = '192.168.21.80'
        self.sdk.return_value = {self.d.host: self.d}
        self.assertEqual(await self.poll(3), self.results)
        self.assertEqual(self.config(), self.payload)

    async def test_verification_failure_or_missing_state_is_rejected(self):
        self.d.update.side_effect = RuntimeError('PRIVATE')
        self.assertEqual(await self.poll(3), self.results)
        self.assertEqual(self.config(), self.payload)
        self.d.disconnect.assert_awaited_once()
        self.d.update.side_effect = None
        self.d.is_on = None
        self.clock.return_value = 1300
        self.assertEqual(await self.poll(), self.results)
        self.assertEqual(self.config(), self.payload)

    async def test_post_update_identity_change_is_rejected(self):
        async def change():
            self.d.mac = '00:11:22:33:44:55'
        self.d.update.side_effect = change
        self.assertEqual(await self.poll(3), self.results)
        self.assertEqual(self.config(), self.payload)

    async def test_out_of_subnet_and_same_address_are_not_updated(self):
        for host in ('8.8.8.8', '192.168.22.10', '192.168.21.9', '192.168.21.255'):
            self.d.host = host
            self.sdk.return_value = {host: self.d}
            await self.poll(3)
            self.clock.return_value += 300
        self.d.update.assert_not_called()
        self.assertEqual(self.config(), self.payload)

    async def test_busy_lock_does_not_queue_or_discover(self):
        lock = self.path.parent / '.plugs.json.ip-recovery.lock'
        with lock.open('w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            await self.poll(5)
        self.sdk.assert_not_awaited()
        self.assertEqual(self.config(), self.payload)

    async def test_symlinks_and_corrupt_state_fail_closed(self):
        state = self.path.parent / '.plugs.json.ip-recovery.json'
        state.symlink_to(self.path)
        await self.poll(4)
        self.sdk.assert_not_awaited()
        self.assertEqual(self.config(), self.payload)
        state.unlink()
        state.write_text('not json')
        await self.poll(4)
        self.sdk.assert_not_awaited()

    async def test_multiple_subnets_do_not_fan_out(self):
        self.payload['plugs']['lamp']['host'] = '192.168.22.80'
        self.save()
        self.c.settings.plugs['lamp'] = PlugConfig('lamp', '192.168.22.80')
        self.results['lamp']['ok'] = False
        await self.poll(3)
        self.sdk.assert_not_awaited()

    async def test_discovery_is_bounded_and_never_updates_unconfigured_devices(self):
        unrelated = device('192.168.21.195', '00:11:22:33:44:55')
        self.sdk.return_value[unrelated.host] = unrelated
        await self.poll(3)
        unrelated.update.assert_not_called()
        unrelated.disconnect.assert_awaited_once()
        self.assertLessEqual(self.sdk.call_args.kwargs['timeout'], 2)

    async def test_total_timeout_returns_original_results(self):
        async def slow(**kwargs):
            await asyncio.sleep(60)
        self.sdk.side_effect = slow
        with patch('smart_plug.ip_recovery.DISCOVERY_BUDGET_SECONDS', .01):
            self.assertEqual(await self.poll(3), self.results)
        self.sdk.assert_awaited_once()
        self.assertEqual(self.config(), self.payload)

    async def test_failed_atomic_update_preserves_config_and_results(self):
        import smart_plug.ip_recovery as recovery
        real_write = recovery._atomic_json
        def fail(path, payload, mode=0o600):
            if path == self.path:
                raise OSError('disk failure')
            return real_write(path, payload, mode)
        with patch('smart_plug.ip_recovery._atomic_json', side_effect=fail):
            self.assertEqual(await self.poll(3), self.results)
        self.assertEqual(self.config(), self.payload)


if __name__ == '__main__':
    unittest.main()
