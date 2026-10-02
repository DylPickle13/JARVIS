from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
import iphone_collect as c
from collect import save

OLD=c.MEDIA+'/old.mov';NEW=c.MEDIA+'/new.mov'


class Phone:
    def __init__(self):
        self.data={OLD:b'personal old media',NEW:b'new verified video'};self.positions={};self.deleted=[];self.opens=0
        self.corrupt_second=False;self.fail_delete=None
    async def listdir(self,path):return [p.rsplit('/',1)[1] for p in self.data if p.rsplit('/',1)[0]==path]
    async def stat(self,path):return {'st_ifmt':'S_IFREG','st_size':len(self.data[path])}
    async def fopen(self,path,mode):self.positions[path]=0;self.opens+=1;return path
    async def fread(self,handle,size):
        content=self.data[handle]
        if self.corrupt_second and self.opens==2:content=b'x'*len(content)
        pos=self.positions[handle];data=content[pos:pos+size];self.positions[handle]+=len(data);return data
    async def fclose(self,handle):pass
    async def rm(self,path):
        if self.fail_delete=='before':raise TimeoutError('delete not sent')
        self.deleted.append(path);del self.data[path]
        if self.fail_delete=='after':raise TimeoutError('delete acknowledgement lost')


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.dest=self.root/'media';self.pending=self.root/'pending-take.json'
        save(self.pending,{'id':'take','before':{},'files':{},'iphone_before':{OLD:18},'iphone_files':{}})
        self.phone=Phone()
        @asynccontextmanager
        async def files(root):yield self.phone
        for p in [patch.object(c,'files',files),patch.object(c.asyncio,'sleep',new=AsyncMock()),
                  patch.object(c,'verify_media',return_value={'format':{'duration':'1'}}),
                  patch('iphone_wifi.read_json',return_value={'recording':False})]:
            p.start();self.addCleanup(p.stop)

    async def test_verified_copy_deletes_only_new_media_and_publishes_manifest(self):
        result=await c.transfer(self.root,self.dest)
        self.assertTrue(result['ok']);self.assertEqual(self.phone.deleted,[NEW]);self.assertIn(OLD,self.phone.data)
        take=json.loads(self.pending.read_text());self.assertTrue(take['iphone_complete'])
        record=json.loads((self.dest/'take/iphone/iphone-transfer.json').read_text())[0]
        self.assertTrue(record['verified'] and record['deleted']);self.assertEqual(record['sha256'],hashlib.sha256(b'new verified video').hexdigest())

    async def test_checksum_mismatch_retains_original(self):
        self.phone.corrupt_second=True
        with self.assertRaisesRegex(RuntimeError,'checksum'):await c.transfer(self.root,self.dest)
        self.assertIn(NEW,self.phone.data);self.assertEqual(self.phone.deleted,[])

    async def test_failed_full_decode_never_deletes(self):
        with patch.object(c,'verify_media',side_effect=RuntimeError('decode error')):
            with self.assertRaises(RuntimeError):await c.transfer(self.root,self.dest)
        self.assertEqual(self.phone.deleted,[])

    async def test_lost_delete_ack_reconciles_without_replaying_delete(self):
        self.phone.fail_delete='after'
        with self.assertRaises(TimeoutError):await c.transfer(self.root,self.dest)
        take=json.loads(self.pending.read_text());record=take['iphone_files'][NEW]
        self.assertTrue(record['verified'] and record['delete_intent']);self.assertFalse(record['deleted'])
        self.phone.fail_delete=None
        self.assertTrue((await c.transfer(self.root,self.dest))['ok']);self.assertEqual(self.phone.deleted,[NEW])

    async def test_changed_local_copy_on_retry_retains_phone(self):
        self.phone.fail_delete='before'
        with self.assertRaises(TimeoutError):await c.transfer(self.root,self.dest)
        (self.dest/'take/iphone/new.mov').write_bytes(b'changed')
        self.phone.fail_delete=None
        with self.assertRaisesRegex(RuntimeError,'Mac copy'):await c.transfer(self.root,self.dest)
        self.assertIn(NEW,self.phone.data)

    async def test_unexplained_disappearance_not_counted_as_success(self):
        self.phone.fail_delete='before'
        with self.assertRaises(TimeoutError):await c.transfer(self.root,self.dest)
        take=json.loads(self.pending.read_text());take['iphone_files'][NEW]['delete_intent']=False;save(self.pending,take)
        del self.phone.data[NEW]
        with self.assertRaisesRegex(RuntimeError,'without durable delete intent'):await c.transfer(self.root,self.dest)

    async def test_new_personal_file_after_fixed_plan_is_not_swept(self):
        self.phone.fail_delete='before'
        with self.assertRaises(TimeoutError):await c.transfer(self.root,self.dest)
        self.phone.data[c.MEDIA+'/later.mov']=b'later personal video'
        self.phone.fail_delete=None
        with self.assertRaisesRegex(RuntimeError,'additional'):await c.transfer(self.root,self.dest)
        self.assertEqual(self.phone.deleted,[])

    async def test_missing_new_clip_does_not_finalize(self):
        del self.phone.data[NEW]
        with self.assertRaisesRegex(RuntimeError,'No new'):await c.transfer(self.root,self.dest)
        self.assertFalse(json.loads(self.pending.read_text()).get('iphone_complete'))

    async def test_recording_state_change_retains_original(self):
        with patch('iphone_wifi.read_json',return_value={'recording':True}):
            with self.assertRaisesRegex(RuntimeError,'state changed'):await c.transfer(self.root,self.dest)
        self.assertEqual(self.phone.deleted,[])

    def test_unsafe_paths_rejected(self):
        for path in ['/Documents/Media/../private.mov','/private.mov','/Documents/Media/file.txt']:
            with self.subTest(path=path),self.assertRaises(RuntimeError):c.relative(path)


if __name__=='__main__':unittest.main()
