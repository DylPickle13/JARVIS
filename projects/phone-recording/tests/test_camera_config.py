import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import camera_config as c


class RegistryTests(unittest.TestCase):
    def data(self):return {'version':1,'cameras':copy.deepcopy(list(c.CAMERAS.values()))}

    def load(self,data):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'camera-config.json';p.write_text(json.dumps(data));return c.load(p)

    def test_overhead_planned_not_enabled(self):
        self.assertIn('overhead',c.CAMERAS);self.assertNotIn('overhead',c.ROLES);self.assertNotIn('overhead',c.ANDROID_ROLES)

    def test_enabling_before_onboarding_refused(self):
        value=self.data();value['cameras'][-1]['enabled']=True
        with self.assertRaises(ValueError):self.load(value)

    def test_duplicate_roles_and_identities_refused(self):
        for field in ('role','serial'):
            value=self.data();value['cameras'][-1][field]=value['cameras'][0][field]
            with self.assertRaises(ValueError):self.load(value)

    def test_paths_and_nonboolean_flags_refused(self):
        for field,value in [('role','../overhead'),('enabled','false')]:
            data=self.data();data['cameras'][-1][field]=value
            with self.assertRaises(ValueError):self.load(data)

    def test_fingerprint_changes_with_scope_and_no_serials_in_public_cards(self):
        data=copy.deepcopy(c.CAMERAS);data['overhead'].update(enabled=True,onboarded=True)
        self.assertNotEqual(c.fingerprint(data),c.CONFIG_ID)
        self.assertTrue(all('serial' not in value for value in c.public()))

    def test_four_camera_consumers_in_isolated_process_without_phone_access(self):
        # This copy lives only in a temporary directory; active configuration stays unchanged.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'camera_config.py').write_text(Path(c.__file__).read_text())
            data=self.data();data['cameras'][-1].update(enabled=True,onboarded=True)
            (root/'camera-config.json').write_text(json.dumps(data))
            script=r'''
import sys
sys.path.insert(0,sys.argv[1])
from unittest.mock import patch
import camera_config as cfg
# Force USB defaults in this isolated process, never touch real transport configuration.
import android_transport as transport
with patch.object(transport,'config',return_value={r:{'mode':'usb'} for r in cfg.ANDROID_ROLES}):
 import managed_control as control
 import dashboard_jobs as jobs
 import export_verified_take as export
assert len(cfg.ROLES)==4 and 'overhead' in transport.IDENTITIES
assert 'overhead' in jobs.PREVIEW_ROLES and 'overhead' in export.CAMERAS
recording={r:'recording' for r in cfg.ROLES}
with patch.object(control,'status',return_value=cfg.IDLE),patch.object(control,'after_commands',return_value=recording),patch.object(control,'command',return_value='sent') as command:
 assert control.change('start')['ok']
 assert {call.args[0] for call in command.call_args_list}==set(cfg.ROLES)
with patch.object(control,'status',return_value={**cfg.IDLE,'overhead':'unknown'}),patch.object(control,'command') as command:
 assert not control.change('start')['ok'];command.assert_not_called()
print('four-role routing and missing-camera guard passed; no phone access')
'''
            result=subprocess.run([sys.executable,'-c',script,d],cwd=Path(c.__file__).parent,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
