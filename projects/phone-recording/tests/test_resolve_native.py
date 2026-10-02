import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import resolve_native as n
import resolve_import as entry
from dashboard_jobs import preparation_status


class NativeImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.p={'schema':1,'take_id':'test','project':n.PROJECT,'timeline':'Phone Sync test','reference':'samsung','clips':[{'role':'samsung','label':'Dyl Cam','path':'/test/file.mp4','offset':0,'seconds':10,'sha256':'a'*64}]}
        for name,value in [('RUNTIME',self.root/'runtime'),('MENU',self.root/'scripts/menu.lua')]:
            p=patch.object(n,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(n,'plan',return_value=self.p);self.plan_mock=p.start();self.addCleanup(p.stop)

    def complete(self,status='ok',message='timeline-uid'):
        request=next(p.parent for p in n.RUNTIME.glob('*/request.json') if not (p.parent/'result.txt').exists())
        (request/'result.txt').write_text(status+'\n'+message+'\n')
        if status!='blocked':(request/'intent.txt').write_text('started')

    def test_exact_retry_never_launches_again(self):
        with patch.object(n,'launch',side_effect=self.complete) as launch:
            self.assertTrue(n.import_timeline('report')['ok'])
            second=n.import_timeline('report')
            self.assertTrue(second['already_imported']);launch.assert_called_once()

    def test_ambiguous_launch_is_not_replayed(self):
        with patch.object(n,'launch',side_effect=TimeoutError('ambiguous')) as launch:
            self.assertFalse(n.import_timeline('report')['ok'])
            self.assertFalse(n.import_timeline('report')['ok']);launch.assert_called_once()

    def test_blocked_project_can_retry_without_mutations(self):
        with patch.object(n,'launch',side_effect=lambda:self.complete('blocked','Wrong project')):
            self.assertFalse(n.import_timeline('report')['ok'])
        with patch.object(n,'launch',side_effect=self.complete) as launch:
            self.assertTrue(n.import_timeline('report')['ok']);launch.assert_called_once()

    def test_partial_edit_error_not_replayed(self):
        with patch.object(n,'launch',side_effect=lambda:self.complete('error','Placement failed')) as launch:
            self.assertFalse(n.import_timeline('report')['ok'])
            self.assertFalse(n.import_timeline('report')['ok']);launch.assert_called_once()

    def test_unresolved_job_blocks_another_take(self):
        with patch.object(n,'launch',side_effect=TimeoutError()):n.import_timeline('report')
        self.p={**self.p,'take_id':'second','timeline':'Phone Sync second'}
        self.plan_mock.return_value=self.p
        with patch.object(n,'launch') as launch:
            self.assertFalse(n.import_timeline('report')['ok']);launch.assert_not_called()

    def test_default_entry_uses_native_not_external(self):
        with patch.object(n,'import_timeline',return_value={'ok':True}) as native,patch.object(entry,'connect') as external:
            self.assertTrue(entry.import_timeline('report')['ok'])
            native.assert_called_once_with('report');external.assert_not_called()

    def test_sync_success_does_not_hide_failed_import(self):
        self.assertEqual(preparation_status({'ok':True,'resolve_import':{'ok':False}})['phase'],'resolve_import_needs_review')

    def test_generated_script_stacks_full_sources_without_cutting(self):
        p={**self.p,'clips':[{'role':r,'label':r,'path':'/path/'+r+'/CLIPS.mp4','offset':i*10,'seconds':10} for i,r in enumerate(('lg','samsung','iphone','overhead'))]}
        s=n.script(p,'/result','/intent')
        self.assertIn('overhead',s);self.assertIn('/iphone/CLIPS.mp4',s)
        self.assertIn('trackIndex=i',s);self.assertIn('startFrame=0,endFrame=c.frames',s)
        self.assertNotIn('Delete',s);self.assertNotIn('rough',s)
        self.assertIn('Unrelated project open; no switch',s)

    def test_normal_import_does_not_read_or_write_menu_container(self):
        n.MENU.parent.mkdir(parents=True)
        n.MENU.write_text('fixed launcher')
        with patch.object(n,'launch',side_effect=self.complete):
            self.assertTrue(n.import_timeline('report')['ok'])
        self.assertEqual(n.MENU.read_text(),'fixed launcher')
        self.assertTrue((n.RUNTIME/'dispatch.lua').exists())

    def test_explicit_rebuild_generation_creates_new_receipt(self):
        with patch.object(n,'launch',side_effect=self.complete) as launch:
            first=n.import_timeline('report')
            (n.RUNTIME/'generation.json').write_text(json.dumps({'id':'approved-rebuild'}))
            second=n.import_timeline('report')
            self.assertTrue(second['ok']);self.assertNotEqual(first['request_id'],second['request_id'])
            self.assertEqual(launch.call_count,2)

    def test_placeholder_guard_excludes_saved_and_populated_projects(self):
        s=n.script(self.p,'/result','/intent')
        self.assertIn("project:GetName()=='Untitled Project'",s)
        self.assertIn('project:GetTimelineCount()==0',s)
        self.assertIn("if n=='Untitled Project' then saved=true",s)
        self.assertIn('not saved and #root:GetClipList()==0 and #root:GetSubFolderList()==0',s)

    def test_partial_receipt_is_not_completion(self):
        path=self.root/'result';path.write_text('ok\n')
        self.assertIsNone(n.read_result(path))


class VerifiedPlanTests(unittest.TestCase):
    def test_verified_files_and_declared_scope_required(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'take';(folder/'samsung').mkdir(parents=True)
            video=folder/'samsung/a.mp4';video.write_bytes(b'test')
            manifest={'take_id':'take','files':{'samsung/a.mp4':{'bytes':4,'sha256':hashlib.sha256(b'test').hexdigest()}}}
            (folder/'_verified-export.json').write_text(json.dumps(manifest))
            sync=folder/'Resolve Sync';sync.mkdir();report=sync/'sync-report.json'
            data={'ok':True,'fps':30,'take_id':'take','reference':'samsung','clips':[{'role':'samsung','path':str(video),'timeline_start_frame':0,'metadata':{'format':{'duration':'10'}}}]}
            report.write_text(json.dumps(data));self.assertEqual(n.plan(report)['clips'][0]['label'],'Dyl Cam')
            video.write_bytes(b'bad!')
            with self.assertRaises(RuntimeError):n.plan(report)
