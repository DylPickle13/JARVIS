import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import runtime_paths
import dashboard_jobs as j
import delete_take as d
from delete_storage import checked_folder,verify_files,remote_operation


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.media=root/'media';self.media.mkdir();self.control=root/'control';self.control.mkdir()
        self.take='20260909-test';self.folder=self.media/self.take;(self.folder/'lg').mkdir(parents=True)
        (self.folder/'lg/a.mp4').write_bytes(b'test')
        self.files={'lg/a.mp4':{'sha256':hashlib.sha256(b'test').hexdigest()}}
        (self.folder/'_verified-export.json').write_text(json.dumps({'take_id':self.take,'files':self.files}))
        (self.folder/'transfer-manifest.json').write_text(json.dumps({'id':self.take,'files':{'lg/a.mp4':{**self.files['lg/a.mp4'],'deleted':True}}}))
        import resolve_native
        p=patch.object(resolve_native,'RUNTIME',self.control/'runtime');p.start();self.addCleanup(p.stop)
        p=patch.object(runtime_paths,'CAPTURE',self.media);p.start();self.addCleanup(p.stop)
        for name,value in [('STATE',root/'state'),('MEDIA',self.media),('ROOT',self.control)]:
            p=patch.object(j,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(j,'spawn');self.spawn=p.start();self.addCleanup(p.stop)
        j.cache({'states':{'lg':'idle'},'takes':[]})

    def test_confirmation_required_even_generic_jobs(self):
        with self.assertRaises(ValueError):j.submit('delete',self.take)
        self.spawn.assert_not_called()

    def test_exact_scope_bound_confirmation(self):
        with self.assertRaises(ValueError):j.submit('delete',self.take,confirmation=d.confirmation(self.take,'phones'))
        job=j.submit('delete',self.take,confirmation=d.confirmation(self.take,'both'))
        self.assertEqual(job['state'],'queued')

    def test_duplicate_does_not_repeat(self):
        args=dict(take_id=self.take,request_id='a'*32,confirmation=d.confirmation(self.take,'both'))
        j.submit('delete',**args);j.submit('delete',**args)
        self.spawn.assert_called_once()

    def test_active_job_blocks_deletion(self):
        j.submit('status')
        with self.assertRaises(RuntimeError):j.submit('delete',self.take,confirmation=d.confirmation(self.take,'both'))

    def test_recording_blocks_deletion(self):
        j.cache({'states':{'lg':'recording'}})
        with self.assertRaises(RuntimeError):d.eligible(self.take)

    def test_pending_only_when_explicit_review_ready(self):
        j.cache({'pending_take':self.take,'pending_review':False})
        with self.assertRaises(RuntimeError):d.eligible(self.take)
        j.cache({'pending_take':self.take,'pending_review':True})
        self.assertEqual(d.eligible(self.take)[1]['stage'],'phones')

    def test_no_local_copy_remote_stage(self):
        j.cache({'takes':[{'id':'remote-only'}]})
        self.assertEqual(d.eligible('remote-only')[1]['stage'],'remote')

    def test_path_traversal_and_symlink_blocked(self):
        with self.assertRaises(ValueError):checked_folder(self.media,'../control')
        (self.media/'link').symlink_to(self.folder)
        with self.assertRaises(ValueError):checked_folder(self.media,'link')
        (self.folder/'link').symlink_to(self.control)
        with self.assertRaises(ValueError):checked_folder(self.media,self.take)

    def test_checksum_change_blocks(self):
        (self.folder/'lg/a.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):verify_files(self.folder,self.files)

    def test_remote_check_is_read_only_and_delete_single_shot(self):
        job='b'*32
        self.assertEqual(remote_operation(self.media,self.control,self.take,job,'check',{})['status'],'checked')
        self.assertTrue(self.folder.exists())
        r=remote_operation(self.media,self.control,self.take,job,'delete',self.files)
        self.assertEqual(r['status'],'deleted');self.assertFalse(self.folder.exists())
        self.assertEqual(remote_operation(self.media,self.control,self.take,job,'delete',self.files),r)
        self.assertEqual(remote_operation(self.media,self.control,self.take,job,'read',self.files),r)

    def test_remote_pending_blocks(self):
        (self.control/'pending-take.json').write_text('{}')
        with self.assertRaises(RuntimeError):remote_operation(self.media,self.control,self.take,'b'*32,'delete',self.files)
        self.assertTrue(self.folder.exists())

    def test_remote_requires_phone_originals_already_deleted(self):
        p=self.folder/'transfer-manifest.json';m=json.loads(p.read_text());m['files']['lg/a.mp4']['deleted']=False;p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):remote_operation(self.media,self.control,self.take,'b'*32,'delete',self.files)

    def test_remote_unresolved_intent_not_replayed(self):
        path=self.control/'.dashboard-deletions'/('b'*32);path.mkdir(parents=True);(path/'intent.json').write_text('{}')
        self.assertEqual(remote_operation(self.media,self.control,self.take,'b'*32,'delete',self.files)['status'],'unknown')
        self.assertTrue(self.folder.exists())

    def test_recovery_never_mutates_or_calls_resolve(self):
        with patch.object(d,'remote') as rpc,patch.object(d,'resolve_delete') as resolve:
            with self.assertRaises(RuntimeError):d.run({'take_id':self.take,'id':'b'*32},True)
        rpc.assert_not_called();resolve.assert_not_called();self.assertTrue(self.folder.exists())

    def test_resolve_guards_and_no_backup(self):
        script=d.resolve_script(self.take,'uid',self.control,self.media)
        for text in ('GetTimelineCount()==1','GetUniqueId()','Unrelated project open','Project contains unrelated media','Already attempted'):
            self.assertIn(text,script)
        self.assertNotIn('ExportProject',script)
        self.assertLess(script.index("f:write('started')"),script.index('GetProjectManager'))

    def test_completed_local_delete_and_observation_only_recovery(self):
        import resolve_native as n
        runtime=self.control/'runtime';runtime.mkdir()
        job=j.submit('delete',self.take,request_id='c'*32,confirmation=d.confirmation(self.take,'both'))
        responses=[{'status':'checked','files':self.files},{'status':'deleted'}]
        with patch.object(n,'RUNTIME',runtime),patch.object(j,'ROOT',self.control),patch.object(d,'remote',side_effect=responses) as rpc,patch.object(d,'resolve_delete',return_value=False) as resolve:
            result=d.run(job)
            self.assertFalse(self.folder.exists());self.assertTrue(result['local_copies_deleted']);self.assertFalse(result['both_macs_deleted'])
            self.assertEqual(d.run(job,True),result)
            self.assertEqual(rpc.call_count,2);resolve.assert_called_once()

    def test_remote_failure_keeps_local_copy_and_blocks_replay(self):
        import resolve_native as n
        runtime=self.control/'runtime';runtime.mkdir()
        job=j.submit('delete',self.take,request_id='d'*32,confirmation=d.confirmation(self.take,'both'))
        with patch.object(n,'RUNTIME',runtime),patch.object(j,'ROOT',self.control),patch.object(d,'remote',side_effect=[{'status':'checked','files':self.files},TimeoutError('lost acknowledgement')]),patch.object(d,'resolve_delete',return_value=False):
            with self.assertRaises(TimeoutError):d.run(job)
            self.assertTrue(self.folder.exists())
            with self.assertRaises(RuntimeError):d.run(job)
            with patch.object(d,'remote',return_value={'status':'deleted','take_id':self.take}):
                with self.assertRaises(RuntimeError):d.run(job,True)

    def test_unexpected_media_blocks_check_and_delete(self):
        extra=self.folder/'lg/VID_unmanifested.mp4';extra.write_bytes(b'other footage')
        for mode in ('check','delete'):
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'Unexpected file'):
                remote_operation(self.media,self.control,self.take,'e'*32,mode,self.files)
            self.assertTrue(extra.exists())

    def test_unexpected_nonmedia_and_empty_directories_block(self):
        extra=self.folder/'notes.txt';extra.write_text('important notes')
        with self.assertRaisesRegex(ValueError,'Unexpected file'):verify_files(self.folder,self.files)
        extra.unlink();(self.folder/'unrelated').mkdir()
        with self.assertRaisesRegex(ValueError,'Unexpected directory'):verify_files(self.folder,self.files)

    def test_known_generated_outputs_are_allowed(self):
        sync=self.folder/'Resolve Sync';sync.mkdir()
        (sync/'sync-report.json').write_text('{}')
        (sync/'Synced.otio').write_text('{}')
        (sync/'Import into Resolve.lua').write_text('-- generated')
        verify_files(self.folder,self.files)

    def test_existing_job_database_upgrades_without_rewriting_history(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as temp,patch.object(j,'STATE',Path(temp)):
            with closing(sqlite3.connect(Path(temp)/'jobs.sqlite')) as db, db:
                db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, action TEXT NOT NULL, take_id TEXT, state TEXT NOT NULL, phase TEXT, created TEXT, updated TEXT, result TEXT, error TEXT)')
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',('a'*32,'delete',self.take,'queued','queued','old','old',None,None))
            old=j.get('a'*32)
            self.assertEqual(old['created'],'old')
            self.assertEqual(old['state'],'queued')
            self.assertIsNone(old['delete_plan'])
            with j.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM delete_approvals').fetchone()[0],0)

    def test_confirmation_plan_is_persisted_and_reloaded(self):
        job=j.submit('delete',self.take,confirmation=d.confirmation(self.take,'both'))
        reloaded=j.get(job['id'])
        self.assertEqual(reloaded['delete_plan'],job['delete_plan'])
        self.assertEqual(reloaded['delete_plan']['stage'],'both')
        self.assertEqual(reloaded['delete_plan']['files'],self.files)

    def test_idempotency_key_cannot_change_approved_scope(self):
        key='f'*32
        j.submit('delete',self.take,request_id=key,confirmation=d.confirmation(self.take,'both'))
        with self.assertRaisesRegex(ValueError,'scope conflict'):
            j.submit('delete',self.take,request_id=key,confirmation=d.confirmation(self.take,'remote'))
        self.spawn.assert_called_once()

    def test_execution_rejects_scope_expansion_after_confirmation(self):
        import resolve_native as n
        editing=self.control/'editing';editing.mkdir()
        with patch.object(j,'MEDIA',editing),patch.object(n,'RUNTIME',self.control/'runtime'):
            j.cache({'states':dict(j.IDLE),'takes':[{'id':self.take}]})
            job=j.submit('delete',self.take,confirmation=d.confirmation(self.take,'remote'))
            # A separate preparation finishes after capture-only confirmation.
            import shutil
            shutil.copytree(self.folder,editing/self.take)
            with patch.object(d,'remote') as rpc,patch.object(d,'resolve_delete') as resolve:
                with self.assertRaisesRegex(RuntimeError,'changed after confirmation'):d.run(job)
            rpc.assert_not_called();resolve.assert_not_called()
            self.assertTrue((editing/self.take/'lg/a.mp4').exists())
            self.assertTrue(self.folder.exists())

    def test_changed_manifest_after_confirmation_blocks_before_mutation(self):
        import resolve_native as n
        job=j.submit('delete',self.take,confirmation=d.confirmation(self.take,'both'))
        changed={'lg/a.mp4':{'sha256':hashlib.sha256(b'other').hexdigest()}}
        (self.folder/'lg/a.mp4').write_bytes(b'other')
        (self.folder/'_verified-export.json').write_text(json.dumps({'take_id':self.take,'files':changed}))
        (self.folder/'transfer-manifest.json').write_text(json.dumps({'id':self.take,'files':{'lg/a.mp4':{**changed['lg/a.mp4'],'deleted':True}}}))
        with patch.object(n,'RUNTIME',self.control/'runtime'),patch.object(d,'remote') as rpc,patch.object(d,'resolve_delete') as resolve:
            with self.assertRaisesRegex(RuntimeError,'changed after confirmation'):d.run(job)
        rpc.assert_not_called();resolve.assert_not_called();self.assertTrue(self.folder.exists())

    def test_legacy_unapproved_job_fails_closed(self):
        with patch.object(d,'remote') as rpc,patch.object(d,'resolve_delete') as resolve:
            with self.assertRaisesRegex(RuntimeError,'Missing durable deletion approval'):
                d.run({'id':'e'*32,'take_id':self.take})
        rpc.assert_not_called();resolve.assert_not_called()

    def test_unexpected_editing_media_blocks_before_resolve(self):
        import resolve_native as n
        job=j.submit('delete',self.take,confirmation=d.confirmation(self.take,'both'))
        extra=self.folder/'lg/VID_new.mp4';extra.write_bytes(b'new footage')
        with patch.object(n,'RUNTIME',self.control/'runtime'),patch.object(d,'remote') as rpc,patch.object(d,'resolve_delete') as resolve:
            with self.assertRaisesRegex(ValueError,'Unexpected file'):d.run(job)
        rpc.assert_not_called();resolve.assert_not_called();self.assertTrue(extra.exists())

    def test_scope_change_after_confirmation_blocks(self):
        confirmation=d.confirmation(self.take,'remote')
        with self.assertRaises(ValueError):j.submit('delete',self.take,confirmation=confirmation)
        self.spawn.assert_not_called()
