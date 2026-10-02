import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,AsyncMock,patch
import review_take as review
import dashboard_jobs as jobs


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.pair=SimpleNamespace(ROOT=root,IDLE={'lg':'idle'},CONFIG_ID='config',status=Mock(return_value={'lg':'idle'}),
          android=SimpleNamespace(PHONES={'lg':'serial'},adb=Mock()),bounded=lambda a,t:a)
        self.take={'id':'test-review','config_id':'config','before':{'lg':[]},'iphone_before':{},'files':{},'iphone_files':{}}
        (root/'pending-take.json').write_text(json.dumps(self.take))

    def test_freeze_inventory_without_copy_or_delete(self):
        with patch.object(review,'android_new',return_value={'lg':['VID_test.mp4']}),patch.object(review,'android_hash',return_value='a'*64),patch.object(review,'iphone_plan',new=AsyncMock(return_value={'/Documents/Media/a.mov':{'bytes':1,'sha256':'b'*64}})):
            r=review.freeze(self.pair,self.take)
        self.assertIn('iphone',r);self.pair.android.adb.assert_not_called()
        self.assertTrue(json.loads((self.pair.ROOT/'pending-take.json').read_text())['review'])

    def test_multiple_new_clips_fail_closed(self):
        with patch.object(review,'android_new',return_value={'lg':['VID_a.mp4','VID_b.mp4']}):
            with self.assertRaises(RuntimeError):review.freeze(self.pair,self.take)
        self.pair.android.adb.assert_not_called()

    def test_recording_or_unknown_blocks_freeze(self):
        self.pair.status.return_value={'lg':'unknown'}
        with self.assertRaises(RuntimeError):review.freeze(self.pair,self.take)

    def test_discard_requires_matching_pending_identity(self):
        with self.assertRaises(RuntimeError):review.discard(self.pair,'other','a'*32)
        self.pair.android.adb.assert_not_called()

    def test_changed_approved_phone_inventory_never_deletes(self):
        approved=review.approval_binding(self.take)
        self.take['review']={'android':{'lg':{'VID_new.mp4':'a'*64}},'iphone':{}}
        (self.pair.ROOT/'pending-take.json').write_text(json.dumps(self.take))
        with self.assertRaisesRegex(RuntimeError,'changed after confirmation'):
            review.discard(self.pair,self.take['id'],'a'*32,approved)
        self.pair.android.adb.assert_not_called()

    def test_discard_requires_frozen_inventory(self):
        with self.assertRaises(RuntimeError):review.discard(self.pair,self.take['id'],'a'*32)
        self.pair.android.adb.assert_not_called()

    def test_discard_prior_intent_never_replays(self):
        p=self.pair.ROOT/'.dashboard-deletions'/('a'*32);p.mkdir(parents=True);(p/'intent.json').write_text('{}')
        with self.assertRaises(RuntimeError):review.discard(self.pair,self.take['id'],'a'*32)
        self.pair.android.adb.assert_not_called()


    def test_successful_discard_removes_only_frozen_paths_once(self):
        from contextlib import asynccontextmanager
        path='/Documents/Media/a.mov';name='VID_test.mp4'
        self.take['review']={'android':{'lg':{name:'a'*64}},'iphone':{path:{'bytes':3,'sha256':'b'*64}}}
        (self.pair.ROOT/'pending-take.json').write_text(json.dumps(self.take))
        service=Mock();service.rm=AsyncMock()
        @asynccontextmanager
        async def files(root):yield service
        with patch.object(review,'files',files),patch.object(review.ic,'inventory',new=AsyncMock(side_effect=[{path:3},{}])),patch.object(review.ic,'stream',new=AsyncMock(return_value='b'*64)),patch.object(review,'android_new',return_value={'lg':[name]}),patch.object(review,'android_hash',return_value='a'*64),patch.object(review,'names',return_value=[]),patch.object(Path,'home',return_value=self.pair.ROOT):
            result=review.discard(self.pair,self.take['id'],'a'*32)
            self.assertEqual(result['status'],'deleted')
            self.assertFalse((self.pair.ROOT/'pending-take.json').exists())
            service.rm.assert_awaited_once_with(path)
            self.pair.android.adb.assert_called_once_with('lg','shell','rm',review.REMOTE+name)
            with self.assertRaises(RuntimeError):review.discard(self.pair,self.take['id'],'a'*32)
            self.assertEqual(service.rm.await_count,1)

    def test_iphone_changed_hash_never_deletes(self):
        from contextlib import asynccontextmanager
        path='/Documents/Media/a.mov'
        service=Mock();service.rm=AsyncMock()
        @asynccontextmanager
        async def files(root):yield service
        self.take['review']={'iphone':{path:{'bytes':3,'sha256':'b'*64}}}
        with patch.object(review,'files',files),patch.object(review.ic,'inventory',new=AsyncMock(return_value={path:3})),patch.object(review.ic,'stream',new=AsyncMock(return_value='c'*64)):
            with self.assertRaises(RuntimeError):asyncio.run(review.discard_iphone(self.pair,self.take,self.pair.ROOT))
        service.rm.assert_not_awaited()


class ReviewJobTests(unittest.TestCase):
    def test_stop_review_does_not_collect_or_prepare_locally(self):
        with tempfile.TemporaryDirectory() as d,patch.object(jobs,'STATE',Path(d)),patch.object(jobs,'spawn'):
            job=jobs.submit('stop_review')
            r={'state':'done','take_id':'test','result':{'ok':True,'after':dict(jobs.IDLE),'review_ready':True}}
            with patch.object(jobs,'remote',return_value=r),patch.object(jobs,'preparation') as prep:
                jobs.worker(job['id'])
            prep.assert_not_called()
            self.assertEqual(jobs.get(job['id'])['phase'],'awaiting_transfer')
            self.assertEqual(jobs.cache()['pending_take'],'test')
            self.assertTrue(jobs.cache()['pending_review'])

    def test_collect_pauses_before_second_mac_copy(self):
        with tempfile.TemporaryDirectory() as d,patch.object(jobs,'STATE',Path(d)),patch.object(jobs,'spawn'):
            job=jobs.submit('collect')
            r={'state':'done','take_id':'test','result':{'ok':True,'after':dict(jobs.IDLE)}}
            with patch.object(jobs,'remote',return_value=r),patch.object(jobs,'preparation') as prep:
                jobs.worker(job['id'])
            prep.assert_not_called()
            self.assertEqual(jobs.get(job['id'])['phase'],'awaiting_verified_copy')
            self.assertEqual(jobs.cache()['takes'][0]['id'],'test')
