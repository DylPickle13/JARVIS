from support import healthy
from camera_config import CONFIG_ID,PREVIEW_ROLES
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import framing_preview as framing
import dashboard_jobs as jobs


class CaptureSafetyTests(unittest.TestCase):
    def test_recording_and_unknown_states_never_capture(self):
        for state in ('recording','unknown'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as d,patch.object(framing.pair,'ROOT',Path(d)),patch.object(framing.pair,'status',return_value={'lg':state,'samsung':'idle'}),patch.object(framing.subprocess,'check_output') as capture:
                with self.assertRaises(RuntimeError):framing.capture()
                capture.assert_not_called()

    def test_pending_take_never_captures(self):
        with tempfile.TemporaryDirectory() as d,patch.object(framing.pair,'ROOT',Path(d)),patch.object(framing.pair,'status') as status,patch.object(framing.subprocess,'check_output') as capture:
            (Path(d)/'pending-take.json').write_text('{}')
            with self.assertRaises(RuntimeError):framing.capture()
            status.assert_not_called();capture.assert_not_called()

    def test_changed_state_discards_snapshots(self):
        idle={'lg':'idle','samsung':'idle','iphone':'idle'}
        def fake_sips(args,**kwargs):Path(args[-1]).write_bytes(b'\xff\xd8image')
        with tempfile.TemporaryDirectory() as d,patch.object(framing.pair,'ROOT',Path(d)),patch.object(framing.pair,'status',side_effect=[idle,{'lg':'recording','samsung':'idle','iphone':'idle'}]),patch.object(framing.subprocess,'check_output',return_value=b'\x89PNG\r\n\x1a\nimage'),patch.object(framing.subprocess,'run',side_effect=fake_sips),patch.object(framing,'iphone_snapshot',return_value=b'\x89PNG\r\n\x1a\nimage'):
            with self.assertRaisesRegex(RuntimeError,'changed'):framing.capture()

    def test_all_three_images_and_two_android_commands(self):
        def sips(args,**kwargs):Path(args[-1]).write_bytes(b'\xff\xd8image')
        with tempfile.TemporaryDirectory() as d,patch.object(framing.pair,'ROOT',Path(d)),patch.object(framing.pair,'status',return_value=framing.pair.IDLE),patch.object(framing.subprocess,'check_output',return_value=b'\x89PNG\r\n\x1a\nimage') as adb,patch.object(framing.subprocess,'run',side_effect=sips),patch.object(framing,'iphone_snapshot',return_value=b'\x89PNG\r\n\x1a\nimage') as iphone:
            result=framing.capture()
            self.assertEqual(set(result['images']),set(PREVIEW_ROLES))
            self.assertEqual(adb.call_count,2);iphone.assert_called_once_with()

    def test_iphone_failure_does_not_publish_partial_images(self):
        def sips(args,**kwargs):Path(args[-1]).write_bytes(b'\xff\xd8image')
        with tempfile.TemporaryDirectory() as d,patch.object(framing.pair,'ROOT',Path(d)),patch.object(framing.pair,'status',return_value=framing.pair.IDLE),patch.object(framing.subprocess,'check_output',return_value=b'\x89PNG\r\n\x1a\nimage'),patch.object(framing.subprocess,'run',side_effect=sips),patch.object(framing,'iphone_snapshot',side_effect=TimeoutError('unavailable')):
            with self.assertRaises(TimeoutError):framing.capture()

    def test_controller_lock_prevents_capture(self):
        import fcntl
        with tempfile.TemporaryDirectory() as d,patch.object(framing.pair,'ROOT',Path(d)),patch.object(framing.pair,'status') as status:
            with (Path(d)/'.pair-control.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):framing.capture()
            status.assert_not_called()


class LocalPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(jobs,'STATE',Path(self.temp.name));p.start();self.addCleanup(p.stop)
        p=patch.object(jobs,'spawn');p.start();self.addCleanup(p.stop)
        jobs.cache({'config_id':CONFIG_ID,'readiness':healthy(),'states':{'lg':'idle','samsung':'idle','iphone':'idle'},'observed':jobs.now(),'pending_take':None})

    def frames(self,created=None):
        for role in PREVIEW_ROLES:(jobs.STATE/(role+'.jpg')).write_bytes(b'\xff\xd8image')
        (jobs.STATE/'preview.json').write_text(json.dumps({'created':created or time.time(),'observed':jobs.now()}))

    def test_start_invalidates_snapshots_before_worker_launch(self):
        self.frames();self.assertIsNotNone(jobs.preview_info());jobs.submit('start')
        self.assertIsNone(jobs.preview_info());self.assertFalse((jobs.STATE/'lg.jpg').exists())

    def test_expired_snapshots_removed(self):
        self.frames(time.time()-70);self.assertIsNone(jobs.preview_info());self.assertFalse((jobs.STATE/'lg.jpg').exists())

    def test_busy_jobs_hide_existing_snapshots(self):
        self.frames();jobs.submit('status');self.assertIsNone(jobs.preview_info())

    def test_preview_worker_does_not_journal_images(self):
        j=jobs.submit('preview');value={'config_id':CONFIG_ID,'observed':jobs.now(),'states':{'lg':'idle','samsung':'idle','iphone':'idle'},'images':{r:base64.b64encode(b'\xff\xd8image').decode() for r in PREVIEW_ROLES}}
        with patch.object(jobs,'remote',return_value=value) as rpc:jobs.worker(j['id'])
        rpc.assert_called_once_with('preview',j['id']);r=jobs.get(j['id'])
        self.assertEqual(r['state'],'done');self.assertNotIn('images',r['result']);self.assertIsNotNone(jobs.preview_info())

    def test_bad_iphone_jpeg_clears_partial_mac_images(self):
        j=jobs.submit('preview')
        images={r:base64.b64encode(b'\xff\xd8image').decode() for r in PREVIEW_ROLES}
        images['iphone']=base64.b64encode(b'not jpeg').decode()
        value={'config_id':CONFIG_ID,'observed':jobs.now(),'states':dict(framing.pair.IDLE),'images':images}
        with patch.object(jobs,'remote',return_value=value):jobs.worker(j['id'])
        self.assertEqual(jobs.get(j['id'])['state'],'needs_review')
        self.assertFalse(any((jobs.STATE/(r+'.jpg')).exists() for r in PREVIEW_ROLES))

    def test_server_expires_images_without_browser_requests(self):
        from dashboard_server import PreviewExpiryServer
        self.frames(time.time()-70)
        PreviewExpiryServer.service_actions(None)
        self.assertFalse(any((jobs.STATE/(r+'.jpg')).exists() for r in PREVIEW_ROLES))


if __name__=='__main__':unittest.main()
