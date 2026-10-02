from support import healthy
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import managed_control as c
import iphone_wifi


class ControlTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(c.readiness,'check',return_value=healthy());p.start();self.addCleanup(p.stop)

    def test_missing_or_unknown_iphone_blocks_all_start_commands(self):
        for state in ('unknown','recording'):
            with self.subTest(state=state),patch.object(c,'status',return_value={**c.IDLE,'iphone':state}),patch.object(c,'begin') as inventory,patch.object(c,'command') as send:
                self.assertFalse(c.managed('start')['ok']);inventory.assert_not_called();send.assert_not_called()

    def test_partial_start_rolls_back_only_confirmed_recordings(self):
        with patch.object(c,'status',return_value=c.IDLE),patch.object(c,'after_commands',side_effect=[{'lg':'recording','samsung':'unknown','iphone':'recording'},c.IDLE]),patch.object(c,'command',return_value='sent') as send:
            result=c.change('start')
            self.assertFalse(result['ok'])
            self.assertEqual(sorted(call.args for call in send.call_args_list),sorted([('lg',True),('samsung',True),('iphone',True),('lg',False),('iphone',False)]))

    def test_unknown_stop_skips_iphone_and_defers_all_collection(self):
        values={**c.IDLE,'lg':'recording','iphone':'unknown'}
        with patch.object(c,'status',return_value=values),patch.object(c,'after_commands',return_value={**c.IDLE,'iphone':'unknown'}),patch.object(c,'command') as send,patch.object(c.iphone_collect,'transfer') as collect:
            self.assertFalse(c.managed('stop')['ok']);send.assert_called_once_with('lg',False);collect.assert_not_called()

    def test_iphone_ambiguous_post_sent_once(self):
        with patch.object(iphone_wifi,'request',side_effect=TimeoutError('ambiguous')) as request:
            self.assertIn('uncertain',c.command('iphone',True));request.assert_called_once_with('/control/api/v1/transports/0/record','POST')

    def test_async_stop_only_observes(self):
        with patch.object(c,'status',return_value={**c.IDLE,'iphone':'recording'}),patch.object(c,'observe',side_effect=['recording','idle']) as observe,patch.object(c.time,'sleep'),patch.object(c,'command') as send:
            self.assertEqual(c.after_commands(True),c.IDLE);self.assertEqual(observe.call_count,2);send.assert_not_called()

    def test_baseline_closed_and_journal_exists_before_recording(self):
        events=[]
        async def baseline(root):events.extend(['file_session_open','file_session_closed']);return {}
        with tempfile.TemporaryDirectory() as d,patch.object(c,'ROOT',Path(d)),patch.object(c,'status',return_value=c.IDLE),patch.object(c.iphone_collect,'baseline',side_effect=baseline),patch.object(c,'names',return_value=[]),patch.object(iphone_wifi,'read_json',side_effect=[{'recordResolution':{'width':3840,'height':2160},'frameRate':'30','offSpeedEnabled':False},{'enabled':False}]):
            def change(action):
                self.assertEqual(events,['file_session_open','file_session_closed'])
                take=json.loads((Path(d)/'pending-take.json').read_text())
                self.assertEqual(take['scope'],list(c.ROLES));self.assertIn('iphone_before',take)
                return {'ok':True}
            with patch.object(c,'change',side_effect=change):self.assertTrue(c.managed('start')['ok'])

    def test_failed_iphone_collection_prevents_android_finalization(self):
        async def fail(*args):raise RuntimeError('phone checksum mismatch')
        with tempfile.TemporaryDirectory() as d,patch.object(c,'ROOT',Path(d)),patch.object(c,'status',return_value=c.IDLE),patch.object(c.iphone_collect,'transfer',side_effect=fail),patch.object(c,'android_transfer') as android:
            (Path(d)/'pending-take.json').write_text(json.dumps({'id':'take','scope':list(c.ROLES),'config_id':c.CONFIG_ID,'iphone_before':{}}))
            self.assertFalse(c.managed('collect')['ok']);android.assert_not_called();self.assertTrue((Path(d)/'pending-take.json').exists())

    def test_network_writes_allow_only_explicit_record_stop(self):
        for path,method in [('/control/api/v1/clips','DELETE'),('/control/api/v1/system/videoFormat','PUT'),('/control/api/v1/transports/0/record','PUT')]:
            with patch.object(iphone_wifi.socket,'create_connection') as sock,self.assertRaises(ValueError):iphone_wifi.request(path,method)
            sock.assert_not_called()


if __name__=='__main__':unittest.main()
