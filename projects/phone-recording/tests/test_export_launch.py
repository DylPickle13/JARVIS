import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import camera_config
import prepare_resolve as p


class ExportLaunchTests(unittest.TestCase):
    def test_local_export_imports_registry_from_any_working_directory(self):
        import runtime_paths as runtime
        import sys
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);source=home/'local-source';source.mkdir()
            for name in ('camera_config.py','camera-config.json'):
                shutil.copy2(p.ROOT/name,source/name)
            (source/'export_verified_take.py').write_text('from camera_config import CONFIG_ID\nprint(CONFIG_ID)\n')
            with patch.object(runtime,'ROOT',source),patch.object(runtime,'PYTHON',sys.executable):
                command=p.remote_command('test-take',True)
            self.assertNotIn('ssh',command)
            self.assertEqual(command[-2:],['test-take','--catalog'])
            result=subprocess.run(command,cwd=home,text=True,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),camera_config.CONFIG_ID)

    def test_shell_metacharacters_rejected(self):
        with self.assertRaises(ValueError):p.remote_command('take; exit 0')

class ProgressTests(unittest.TestCase):
    def test_direct_cli_has_no_dashboard_side_effect(self):
        with patch('dashboard_jobs.update') as update:
            p.report_phase(None,'take','audio_sync');update.assert_not_called()

    def test_only_own_running_take_can_publish(self):
        job={'state':'running','take_id':'take','action':'prepare'}
        with patch('dashboard_jobs.get',return_value=job),patch('dashboard_jobs.update') as update:
            p.report_phase('a'*32,'take','audio_sync')
            update.assert_called_once_with('a'*32,phase='audio_sync')
            for field,value in [('state','done'),('take_id','other'),('action','start')]:
                with patch('dashboard_jobs.get',return_value={**job,field:value}):
                    with self.assertRaises(RuntimeError):p.report_phase('a'*32,'take','resolve_import')
            with self.assertRaises(ValueError):p.report_phase('a'*32,'take','made_up')
