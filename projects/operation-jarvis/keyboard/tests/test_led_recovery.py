import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import led_cycle as led


def presence(where='nearby'):
    return {'ok':True,'zones':[{'subject':'dylan','zone':'basement','state':where,'stale':False,'ageSeconds':0}]}


class Recovery(unittest.TestCase):
    def test_unknown_write_reads_before_any_later_current_intent(self):
        s=led.initial();faults=set();apply=Mock(side_effect=TimeoutError());observe=Mock(return_value='on')
        def tick(t,where):led.tick(s,faults,now=t,get_presence=lambda:presence(where),apply=apply,observe=observe,save=lambda _:None)
        tick(100,'nearby');self.assertTrue(s['pending'])
        tick(103,'away');observe.assert_not_called()
        tick(160,'away');observe.assert_called_once();self.assertFalse(s['pending']);apply.assert_called_once()
        apply.side_effect=None;apply.return_value=True
        tick(163,'away');apply.assert_called_once()
        tick(220,'away');self.assertEqual(apply.call_args.args[0],'off');self.assertFalse(s['pending'])

    def test_failed_reads_remain_paced_and_never_authorize_writes(self):
        s=led.initial()|{'pending':True};observe=Mock(side_effect=RuntimeError());apply=Mock()
        for t in (100,103,157,160,163,220):
            led.tick(s,set(),now=t,get_presence=presence,apply=apply,observe=observe,save=lambda _:None)
        self.assertEqual(observe.call_count,3);apply.assert_not_called();self.assertTrue(s['pending'])

    def test_prewrite_rejection_is_not_uncertain(self):
        payload={'result':'error','reason':'device_identity_mismatch','stage':'connection'}
        with patch.object(led.subprocess,'run',return_value=Mock(returncode=2,stdout=json.dumps(payload).encode(),stderr=b'')):
            with self.assertRaises(led.NotSent):led.send('on',100)
        s=led.initial();apply=Mock(side_effect=led.NotSent({}))
        led.tick(s,set(),now=100,get_presence=presence,apply=apply,save=lambda _:None)
        self.assertFalse(s['pending']);self.assertEqual(s['last_busy'],100)

    def test_power_read_requires_exact_authenticated_alias_model_and_boolean(self):
        p={'result':'read_succeeded','device':'led-strip','model':'L930-5','features':{'state':{'value':False}}}
        with patch.object(led.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(p).encode(),stderr=b'')):
            self.assertEqual(led.read_power(),'off')
        for altered in (p|{'model':'HS103'},p|{'features':{'state':{'value':0}}},p|{'device':'other'}):
            with patch.object(led.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(altered).encode(),stderr=b'')):
                with self.assertRaises(led.LightingError):led.read_power()

if __name__=='__main__':unittest.main()
