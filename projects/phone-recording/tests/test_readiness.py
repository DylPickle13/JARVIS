import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import readiness as r
import dashboard_jobs as jobs
import managed_control as control
from camera_config import ROLES,IDLE,CONFIG_ID
from support import healthy


class HealthTests(unittest.TestCase):
    def metrics(self,**change):return {'battery_percent':80,'free_bytes':10*1024**3,'external_power':True,'battery_temperature_c':30,**change}

    def test_healthy(self):self.assertTrue(r.assess(self.metrics())['ok'])

    def test_low_battery_blocks_even_on_power(self):
        self.assertFalse(r.assess(self.metrics(battery_percent=19))['ok'])
        self.assertTrue(r.assess(self.metrics(battery_percent=20))['ok'])

    def test_warning_battery_and_not_powered(self):
        value=r.assess(self.metrics(battery_percent=30,external_power=False))
        self.assertTrue(value['ok']);self.assertEqual(len(value['warnings']),2)

    def test_missing_battery_or_disk_blocks(self):
        for field in ['battery_percent','free_bytes']:
            with self.subTest(field=field):self.assertFalse(r.assess(self.metrics(**{field:None}))['ok'])

    def test_storage_thresholds(self):
        self.assertFalse(r.assess(self.metrics(free_bytes=2*1024**3-1))['ok'])
        value=r.assess(self.metrics(free_bytes=2*1024**3));self.assertTrue(value['ok']);self.assertTrue(value['warnings'])

    def test_temperature_and_severe_thermal_status(self):
        self.assertFalse(r.assess(self.metrics(battery_temperature_c=45))['ok'])
        value=r.assess(self.metrics(battery_temperature_c=40));self.assertTrue(value['ok']);self.assertTrue(value['warnings'])
        self.assertFalse(r.assess(self.metrics(thermal_status=3))['ok'])

    def test_unsupported_temperature_warns_not_fabricated(self):
        value=r.assess(self.metrics(battery_temperature_c=None));self.assertTrue(value['ok'])
        self.assertTrue(any('temperature unavailable' in w for w in value['warnings']))

    def test_nonfinite_or_invalid_telemetry_is_json_safe_and_blocks_core(self):
        for value in [float('nan'),float('inf'),True,-1,'90']:
            result=r.assess(self.metrics(battery_percent=value));self.assertFalse(result['ok']);json.dumps(result,allow_nan=False)

    def test_android_parser(self):
        battery='level: 50\nscale: 100\ntemperature: 415\nAC powered: true\nUSB powered: false\nWireless powered: false'
        disk='Filesystem 1K-blocks Used Available Use% Mounted on\n/data/media 20000000 9000000 11000000 45% /storage/emulated'
        value=r.parse_android(battery,disk,'Thermal Status: 2')
        self.assertEqual(value['battery_percent'],50);self.assertEqual(value['battery_temperature_c'],41.5)
        self.assertEqual(value['free_bytes'],11000000*1024);self.assertTrue(value['external_power']);self.assertEqual(value['thermal_status'],2)

    def test_bad_df_is_not_guessed(self):
        self.assertIsNone(r.parse_android('', 'garbage 10 20 30','')['free_bytes'])

    def test_recording_skips_all_phone_metadata_sessions(self):
        with patch.object(r,'probe') as probe,patch.object(r,'local_storage',return_value={'ok':True,'free_bytes':10**11}):
            result=r.check({**IDLE,'lg':'recording'});self.assertFalse(result['ok']);probe.assert_not_called()

    def test_offline_phone_is_not_queried_or_silently_skipped(self):
        with patch.object(r,'probe',return_value=r.assess(self.metrics())) as probe,patch.object(r,'local_storage',return_value={'ok':True,'free_bytes':10**11}):
            result=r.check({**IDLE,'samsung':'unknown'})
            self.assertFalse(result['ok']);self.assertNotIn('samsung',[c.args[0] for c in probe.call_args_list]);self.assertEqual(set(result['phones']),set(ROLES))

    def test_stale_future_or_mismatched_readiness_rejected(self):
        self.assertTrue(r.approved(healthy()))
        for offset in [-121,10]:
            value=healthy();value['checked_at']=(datetime.datetime.now().astimezone()+datetime.timedelta(seconds=offset)).isoformat()
            self.assertFalse(r.approved(value))
        value=healthy();value['config_id']='wrong';self.assertFalse(r.approved(value))

    def test_remote_start_checks_health_before_inventory(self):
        with patch.object(control,'status',return_value=IDLE),patch.object(r,'check',return_value={'ok':False}),patch.object(control,'begin') as inventory,patch.object(control,'change') as command:
            self.assertFalse(control.managed('start')['ok']);inventory.assert_not_called();command.assert_not_called()

    def test_health_never_blocks_stop_or_opens_a_probe_during_stop(self):
        with tempfile.TemporaryDirectory() as d,patch.object(control,'ROOT',Path(d)),patch.object(control,'change',return_value={'ok':True,'after':IDLE}) as stop,patch.object(r,'check') as check:
            result=control.managed('stop')
            stop.assert_called_once_with('stop');check.assert_not_called()
            self.assertIn('No managed take',result['collection']['error'])

    def test_pending_configuration_change_blocks_stop_commands(self):
        with tempfile.TemporaryDirectory() as d,patch.object(control,'ROOT',Path(d)),patch.object(control,'status',return_value=IDLE),patch.object(control,'command') as command:
            (Path(d)/'pending-take.json').write_text(json.dumps({'config_id':'old'}))
            self.assertFalse(control.managed('stop')['ok']);command.assert_not_called()


class LocalGates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        for p in [patch.object(jobs,'STATE',Path(self.temp.name)),patch.object(jobs,'spawn')]:p.start();self.addCleanup(p.stop)

    def cache(self,health):jobs.cache({'config_id':CONFIG_ID,'readiness':health,'states':IDLE,'observed':jobs.now(),'pending_take':None})

    def test_idle_without_health_cannot_start(self):
        self.cache(None)
        with self.assertRaises(RuntimeError):jobs.submit('start')

    def test_unhealthy_cached_report_cannot_start(self):
        value=healthy();value['phones']['lg']['metrics']['battery_percent']=1;self.cache(value)
        with self.assertRaises(RuntimeError):jobs.submit('start')

    def test_low_local_disk_cannot_start(self):
        self.cache(healthy())
        with patch.object(r,'local_storage',return_value={'ok':False}),self.assertRaises(RuntimeError):jobs.submit('start')

    def test_preview_timestamp_cannot_refresh_old_health(self):
        value=healthy();value['checked_at']=(datetime.datetime.now().astimezone()-datetime.timedelta(minutes=5)).isoformat();self.cache(value)
        with self.assertRaises(RuntimeError):jobs.submit('start')


if __name__=='__main__':unittest.main()
