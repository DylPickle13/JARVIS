import tempfile
from pathlib import Path
import unittest
from resolve_rough_cut import generate

class RoughCutTests(unittest.TestCase):
    def report(self):
        return {'ok':True,'fps':30,'take_id':'test','clips':[{'role':r,'path':'/media/'+r+'.mov','timeline_start_frame':o,'metadata':{'format':{'duration':'78'}}} for r,o in [('lg',74),('samsung',45),('iphone',0)]]}
    def test_edit_plan_is_bounded_and_non_destructive(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'edit.lua';plan=generate(self.report(),p);s=p.read_text()
            self.assertEqual(plan['common_start'],90);self.assertEqual(plan['duration_frames'],2160)
            self.assertEqual(len(plan['shots']),12)
            self.assertNotIn('Delete',s);self.assertIn('Timeline exists; do not overwrite',s)
            self.assertIn('resolve or bmd.scriptapp',s)
    def test_unapproved_sync_refused(self):
        r=self.report();r['ok']=False
        with self.assertRaises(ValueError):generate(r,'/unused')
