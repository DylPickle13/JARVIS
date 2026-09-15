import concurrent.futures
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('dual_purifier_daemon', Path(__file__).resolve().parents[1]/'jarvisd.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

class MultiPurifierStateTests(unittest.TestCase):
    def setUp(self):
        self.clock = 1000.0
        self.c = d.StateCoordinator(collectors={'purifier': lambda: {}}, now=lambda: self.clock)
        self.c.start = Mock()
        self.a, self.b = d._purifier_id('private-a'), d._purifier_id('private-b')
        self.batch = {'ok': True, 'defaultDeviceID': self.a, 'devices': {
            self.a: {'ok': True, 'deviceID': self.a, 'name': "Dylan's Air Purifier", 'isOn': True, 'pm25': 1},
            self.b: {'ok': True, 'deviceID': self.b, 'name': "Bran's Air Purifier", 'isOn': True, 'pm25': 2}}}

    def complete(self, batch=None, revision=None):
        future = concurrent.futures.Future()
        future.set_result(self.batch if batch is None else batch)
        if revision is None:revision=self.c._records['purifier']['revision']
        self.c._complete('purifier', future, revision)

    def snapshot(self):
        return self.c.snapshot()['subsystems']['purifier']

    def test_default_compatibility_and_two_independent_rows(self):
        self.complete()
        state = self.snapshot()
        self.assertEqual(state['name'], "Dylan's Air Purifier")
        self.assertEqual(state['pm25'], 1)
        self.assertEqual(state['devices'][self.b]['pm25'], 2)
        self.assertNotIn('private-', str(state))

    def test_peer_command_cannot_refresh_default_or_change_default_readings(self):
        self.complete()
        self.clock += 80
        self.assertTrue(self.c.apply_purifier_result({'cid':'private-b','name':"Bran's Air Purifier",'is_on':False,'pm25':3}))
        self.clock += 20
        state=self.snapshot()
        self.assertTrue(state['stale'])
        self.assertEqual(state['pm25'],1)
        self.assertFalse(state['devices'][self.b]['stale'])
        self.assertFalse(state['devices'][self.b]['isOn'])

    def test_partial_failure_does_not_poison_peer(self):
        self.complete()
        failed={'ok': True,'defaultDeviceID':self.a,'devices':{self.a:self.batch['devices'][self.a],self.b:{'ok':False,'error':'offline'}}}
        self.complete(failed)
        state=self.snapshot()
        self.assertFalse(state['stale'])
        self.assertTrue(state['devices'][self.b]['stale'])
        self.assertEqual(state['devices'][self.b]['pm25'],2)

    def test_selected_pending_does_not_mark_default_pending(self):
        self.complete()
        self.c.apply_purifier_result({'cid':'private-b','name':"Bran's Air Purifier",'is_on':True,'verification_pending':True},{'isOn':False})
        state=self.snapshot()
        self.assertFalse(state['verificationPending'])
        self.assertTrue(state['devices'][self.b]['verificationPending'])
        self.complete()
        self.assertTrue(self.snapshot()['devices'][self.b]['verificationPending'])

    def test_stale_inflight_batch_cannot_overwrite_command(self):
        self.complete()
        revision=self.c._records['purifier']['revision']
        self.c.apply_purifier_result({'cid':'private-b','is_on':False})
        self.complete(revision=revision)
        self.assertFalse(self.snapshot()['devices'][self.b]['isOn'])
        self.assertEqual(self.c._records['purifier']['nextDue'],float('inf'))

    def test_removed_device_cannot_fall_back_to_default(self):
        self.complete()
        self.assertFalse(self.c.apply_purifier_result({'cid':'private-other','is_on':False}))
        with patch.object(d,'STATE_COORDINATOR',self.c), patch.dict(d._PURIFIER_SELECTORS,{self.a:'private-a',self.b:'private-b'},clear=True):
            with self.assertRaises(d.CommandError):
                d._purifier_set_args({'setting':'power','value':'off','deviceID':'missing'})
            args=d._purifier_set_args({'setting':'power','value':'off','deviceID':self.b})
            self.assertIn('private-b',args)
            self.assertNotIn('private-a',args)
            self.clock += 100
            with self.assertRaises(d.CommandError):
                d._purifier_set_args({'setting':'power','value':'off','deviceID':self.b})

    def test_batch_collector_is_one_adapter_call_and_hides_cids(self):
        payload={'purifiers':{'private-a':{'ok':True,'isDefault':True,'status':{'name':'Dylan','pm25':1}},'private-b':{'ok':False,'name':'Bran'}}}
        with patch.object(d,'run_cli_json',return_value=payload) as run:
            state=d._purifier()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1],'purifier-status-all')
        self.assertNotIn('private-', str(state))
        self.assertEqual(state['defaultDeviceID'],self.a)

    def test_recovery_read_is_explicit_and_debounced(self):
        self.c.request_refresh('purifier')
        self.c.request_refresh('purifier',retry_cooldown=True)
        self.assertTrue(self.c._records['purifier']['retryCooldown'])
        first=self.c._records['purifier']['lastRecoveryRequestedAt']
        self.clock += 1
        self.c.request_refresh('purifier',retry_cooldown=True)
        self.assertEqual(self.c._records['purifier']['lastRecoveryRequestedAt'],first)
        with patch.object(d,'run_cli_json',return_value={'purifiers':{}}) as run:
            d._purifier(retry=True)
            self.assertIn('--retry-cooldown',run.call_args.args[0])

    def test_account_failure_marks_each_row_stale_with_actionable_error(self):
        self.complete()
        self.complete({'ok':False,'error':'VeSync local backoff: 300 seconds remaining'})
        for row in self.snapshot()['devices'].values():
            self.assertTrue(row['stale'])
            self.assertIn('backoff',row['lastError'])
