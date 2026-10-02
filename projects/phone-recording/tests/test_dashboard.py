from support import healthy
from camera_config import CONFIG_ID
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,Mock
import dashboard_jobs as jobs
import dashboard_server as web
import remote_jobs as remote


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(jobs,'STATE',Path(self.temp.name));p.start();self.addCleanup(p.stop)
        p=patch.object(jobs,'spawn');self.spawn=p.start();self.addCleanup(p.stop)

    def ready(self):jobs.cache({'config_id':CONFIG_ID,'readiness':healthy(),'states':{'lg':'idle','samsung':'idle','iphone':'idle'},'observed':jobs.now(),'pending_take':None})

    def test_start_requires_fresh_idle_observation(self):
        with self.assertRaises(RuntimeError):jobs.submit('start')
        self.ready();self.assertEqual(jobs.submit('start')['state'],'queued')

    def test_two_camera_cache_cannot_start_three_camera_workflow(self):
        jobs.cache({'states':{'lg':'idle','samsung':'idle'},'observed':jobs.now(),'pending_take':None})
        with self.assertRaises(RuntimeError):jobs.submit('start')
        self.spawn.assert_not_called()

    def test_duplicate_request_executes_once_and_busy_blocks_second(self):
        self.ready();key='a'*32
        self.assertEqual(jobs.submit('start',request_id=key)['id'],jobs.submit('start',request_id=key)['id'])
        self.spawn.assert_called_once()
        with self.assertRaises(RuntimeError):jobs.submit('stop')
        with self.assertRaises(ValueError):jobs.submit('stop',request_id=key)

    def test_explicit_take_and_action_allowlist(self):
        for action,take in [('delete',None),('prepare','../bad'),('import',None),('stop','some-take')]:
            with self.subTest(action=action),self.assertRaises(ValueError):jobs.submit(action,take)

    def test_ssh_timeout_never_retries_submit(self):
        self.ready();job=jobs.submit('start')
        with patch.object(jobs,'remote',side_effect=TimeoutError('SSH timeout')) as rpc:
            jobs.worker(job['id'])
        self.assertEqual(rpc.call_count,1);self.assertEqual(jobs.get(job['id'])['state'],'uncertain')

    def test_recovery_only_reads_same_remote_job(self):
        self.ready();job=jobs.submit('start');jobs.update(job['id'],state='uncertain');jobs.recover(job['id'])
        result={'state':'done','take_id':'take-1','result':{'ok':True,'after':{'lg':'recording','samsung':'recording','iphone':'recording'}}}
        with patch.object(jobs,'remote',return_value=result) as rpc:jobs.worker(job['id'],True)
        rpc.assert_called_once_with('read',job['id'])
        self.assertEqual(jobs.get(job['id'])['phase'],'recording')

    def test_stop_prepares_exact_take_not_latest(self):
        job=jobs.submit('stop')
        result={'state':'done','take_id':'specific-take','result':{'ok':True,'after':{'lg':'idle','samsung':'idle','iphone':'idle'}}}
        with patch.object(jobs,'remote',return_value=result),patch.object(jobs,'preparation',return_value={'ok':True}) as prep:
            jobs.worker(job['id'])
        prep.assert_called_once_with(job['id'],'specific-take')
        self.assertEqual(jobs.get(job['id'])['state'],'done')

    def test_failed_collection_does_not_prepare(self):
        job=jobs.submit('stop')
        result={'state':'done','take_id':'specific-take','result':{'ok':False,'after':{'lg':'idle','samsung':'unknown'}}}
        with patch.object(jobs,'remote',return_value=result),patch.object(jobs,'preparation') as prep:jobs.worker(job['id'])
        prep.assert_not_called();self.assertEqual(jobs.get(job['id'])['state'],'needs_review')

    def test_readonly_status_connection_failure_does_not_block_controller(self):
        job=jobs.submit('status')
        with patch.object(jobs,'remote',side_effect=TimeoutError('offline')):jobs.worker(job['id'])
        self.assertEqual(jobs.get(job['id'])['state'],'needs_review')


class RemoteTests(unittest.TestCase):
    def test_dead_remote_worker_is_flagged_without_replay(self):
        with tempfile.TemporaryDirectory() as root,patch.object(remote,'JOBS',Path(root)),patch.object(remote.subprocess,'Popen') as spawn:
            key='c'*32
            (Path(root)/(key+'.json')).write_text(json.dumps({'id':key,'action':'start','state':'running','created':'2020-01-01T00:00:00+00:00'}))
            result=remote.read_job(key)
            self.assertEqual(result['state'],'error');self.assertIn('unverified',result['error']);spawn.assert_not_called()

    def test_remote_idempotency_does_not_spawn_twice(self):
        with tempfile.TemporaryDirectory() as root,patch.object(remote,'JOBS',Path(root)),patch.object(remote.subprocess,'Popen') as spawn:
            first=remote.submit('b'*32,'start');second=remote.submit('b'*32,'start')
            self.assertEqual(first['id'],second['id']);spawn.assert_called_once()
            with self.assertRaises(RuntimeError):remote.submit('b'*32,'stop')


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.server=web.make_server(0,'test-token')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.host='127.0.0.1:'+str(self.server.server_address[1])
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def request(self,path='/',method='GET',data=None,headers=None):
        c=http.client.HTTPConnection(self.host,timeout=5)
        h={'Host':self.host,**(headers or {})}
        body=json.dumps(data) if data is not None else None
        c.request(method,path,body,h);r=c.getresponse();out=(r.status,dict(r.getheaders()),r.read());c.close();return out

    def test_unauthenticated_cannot_read_state(self):self.assertEqual(self.request('/api/state')[0],401)

    def test_rebinding_host_rejected(self):self.assertEqual(self.request(headers={'Host':'evil.example'})[0],421)

    def test_cross_origin_auth_rejected(self):
        self.assertEqual(self.request('/api/auth','POST',{'token':'test-token'},{'Origin':'http://evil.example','Content-Type':'application/json'})[0],403)

    def test_valid_auth_sets_httponly_cookie_and_security_headers(self):
        code,headers,_=self.request('/api/auth','POST',{'token':'test-token'},{'Origin':'http://'+self.host,'Content-Type':'application/json'})
        self.assertEqual(code,200);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie']);self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])

    def test_cookie_without_csrf_cannot_start(self):
        headers={'Origin':'http://'+self.host,'Content-Type':'application/json','Cookie':'phone_session=test-token'}
        with patch.object(jobs,'submit') as submit:
            self.assertEqual(self.request('/api/jobs','POST',{'action':'start'},headers)[0],403);submit.assert_not_called()

    def test_delete_endpoint_requires_csrf_and_passes_exact_confirmation(self):
        headers={'Origin':'http://'+self.host,'Content-Type':'application/json','Cookie':'phone_session=test-token'}
        payload={'take_id':'take','request_id':'a'*32,'confirmation':'DELETE take BOTH'}
        with patch.object(jobs,'submit',return_value={'state':'queued'}) as submit:
            self.assertEqual(self.request('/api/delete-take','POST',payload,headers)[0],403)
            submit.assert_not_called()
            headers['X-Phone-CSRF']=self.server.csrf
            self.assertEqual(self.request('/api/delete-take','POST',payload,headers)[0],202)
            submit.assert_called_once_with('delete','take','a'*32,confirmation='DELETE take BOTH')

    def test_open_resolve_requires_verified_known_take_and_never_imports(self):
        headers={'Origin':'http://'+self.host,'Content-Type':'application/json','Cookie':'phone_session=test-token','X-Phone-CSRF':self.server.csrf}
        with patch.object(jobs,'local_takes',return_value=[{'id':'take','import_status':{'ok':True}}]),patch.object(web.subprocess,'run') as run:
            self.assertEqual(self.request('/api/open-resolve','POST',{'take_id':'unknown'},headers)[0],400)
            run.assert_not_called()
            self.assertEqual(self.request('/api/open-resolve','POST',{'take_id':'take'},headers)[0],200)
            run.assert_called_once_with(['open','-a','/Applications/DaVinci Resolve.app'],check=True,timeout=10)

    def test_get_cannot_mutate(self):
        with patch.object(jobs,'submit') as submit:
            self.assertEqual(self.request('/api/jobs?action=start',headers={'Cookie':'phone_session=test-token'})[0],404);submit.assert_not_called()


if __name__=='__main__':unittest.main()
