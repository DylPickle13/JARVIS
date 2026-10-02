"""Single-Mac cutover tests. Synthetic media only; never contact phones."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import dashboard_jobs as jobs
import delete_take
import prepare_resolve as prepare
import runtime_paths as runtime


class LocalControllerTests(unittest.TestCase):
    def test_paths_are_local_and_capture_is_not_editing(self):
        self.assertEqual(runtime.ROOT, Path(__file__).resolve().parents[1])
        self.assertNotEqual(runtime.CAPTURE, runtime.EDITING)
        self.assertEqual(jobs.MEDIA, runtime.EDITING)
        with self.assertRaises(ValueError):
            runtime.helper('../untrusted.py')

    def test_dispatch_uses_local_interpreter_and_no_shell(self):
        with patch.object(jobs.subprocess, 'check_output', return_value='{"state":"done"}') as run:
            self.assertEqual(jobs.remote('read', 'a'*32)['state'], 'done')
        args = run.call_args.args[0]
        self.assertEqual(args, runtime.helper('remote_jobs.py', 'read', 'a'*32))
        self.assertNotIn('ssh', args)
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_local_timeout_does_not_retry(self):
        with patch.object(jobs.subprocess, 'check_output', side_effect=subprocess.TimeoutExpired('helper', 40)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                jobs.remote('submit', 'a'*32, 'start')
            run.assert_called_once()

    def test_deletion_routes_to_capture_not_editing(self):
        with patch('delete_storage.remote_operation', return_value={'status':'checked'}) as operation:
            delete_take.remote('take', 'a'*32, 'check', {'lg/clip.mp4':{'sha256':'f'*64}})
        self.assertEqual(operation.call_args.args[:2], (runtime.CAPTURE, runtime.ROOT))

    def test_local_export_copy_verify_and_pending_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); control=root/'control';control.mkdir()
            capture=root/'capture'; editing=root/'editing'
            folder=capture/'take'; (folder/'lg').mkdir(parents=True)
            data=b'synthetic-media-for-copy-test'
            (folder/'lg/clip.mp4').write_bytes(data)
            manifest={'id':'take','scope':['lg'],'files':{'lg/clip.mp4':{
                'sha256':hashlib.sha256(data).hexdigest(),'deleted':True}}}
            (folder/'transfer-manifest.json').write_text(json.dumps(manifest))
            def command(take, catalog=False):
                # Real local child process + tar pipeline, isolated controller/media roots.
                script=('import sys;sys.path.insert(0,'+repr(str(runtime.ROOT))+');'
                        'import runtime_paths as r;from pathlib import Path;'
                        'r.ROOT=Path('+repr(str(control))+');r.CAPTURE=Path('+repr(str(capture))+');'
                        'import export_verified_take as e;e.main()')
                return [sys.executable,'-c',script,take]+(['--catalog'] if catalog else [])
            with patch.object(prepare,'DEST',editing),patch.object(prepare,'remote_command',side_effect=command):
                result=prepare.receive('take')
                self.assertEqual((result/'lg/clip.mp4').read_bytes(),data)
                self.assertEqual(prepare.receive('take'),result)
                (result/'lg/clip.mp4').write_bytes(b'corrupted')
                with self.assertRaisesRegex(RuntimeError,'checksum conflict'):
                    prepare.receive('take')
                (control/'pending-take.json').write_text('{}')
                with self.assertRaises(subprocess.CalledProcessError):
                    prepare.receive('take')
            self.assertEqual((folder/'lg/clip.mp4').read_bytes(),data)
