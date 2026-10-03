#!/usr/bin/env python3
"""Offline native-pipe integration: simulated Chrome, never launches a browser."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

host = module('native_host', ROOT / 'background-extension/native_host.py')
launcher = module('native_launcher', ROOT / 'launch-extension-in-automation-window.py')
builder = module('background_build', ROOT / 'background-extension/build.py')


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jb-', dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.directory = self.home / '.jarvis'
        self.directory.mkdir()
        (self.directory / 'extension-window.json').write_text(json.dumps({'windowId':71,'connectionTabId':72}))
        (self.directory / 'playwright-extension.token').write_text('fixture-only')
        self.url = self.connection_url()
        self.request = {'command':'connect','mode':host.MODE,'windowId':71,'url':self.url}

    def connection_url(self, **overrides):
        params = {'token':'fixture-only','mcpRelayUrl':'ws://127.0.0.1:1234/extension-id','protocolVersion':'2','client':json.dumps({'name':'JARVIS Browser'}), **overrides}
        return f'chrome-extension://{host.EXTENSION}/connect.html?{urlencode(params)}#jarvis-automation-anchor-v2'

    def test_frames_roundtrip_and_size_or_shape_rejections(self):
        data = io.BytesIO()
        host.write_frame(data, {'hello':1})
        data.seek(0)
        self.assertEqual(host.read_frame(data), {'hello':1})
        for frame in (struct.pack('<I',0),struct.pack('<I',host.MAX_MESSAGE+1),struct.pack('<I',2)+b'[]',struct.pack('<I',1)+b'x'):
            with self.assertRaises(ValueError):
                host.read_frame(io.BytesIO(frame))
        with self.assertRaises(EOFError):
            host.read_frame(io.BytesIO(b'\x01'))

    def test_validation_preserves_exact_recorded_window_and_authenticated_loopback(self):
        self.assertEqual(host.validate_request(self.request,self.directory),self.request)
        for change in ({'windowId':True},{'windowId':99},{'windowId':'71'},{'command':'evaluate'},{'mode':'stock'},
                       {'url':'https://example.com/'},{'url':self.url.replace(host.EXTENSION,'other')},
                       {'url':self.url.replace('#jarvis-automation-anchor-v2','')},
                       {'url':self.connection_url(token='wrong')},{'url':self.connection_url(mcpRelayUrl='ws://example.com:80/')},
                       {'url':self.connection_url(mcpRelayUrl='http://127.0.0.1:80/')},
                       {'url':self.connection_url(mcpRelayUrl='ws://user:pass@127.0.0.1:80/')},
                       {'url':self.connection_url(protocolVersion='1')},{'url':self.connection_url(client='{}')},
                       {'url':self.url.replace('?token=', '?token=duplicate&token=')}):
            with self.assertRaises((ValueError,TypeError,AttributeError)):
                host.validate_request({**self.request,**change},self.directory)

    def test_unreviewed_build_source_fails_closed(self):
        upstream = (ROOT / 'background-extension/upstream-background-0.4.0.mjs').read_text()
        addon = (ROOT / 'background-extension/native-addon.js').read_text()
        result = builder.patch_background(upstream,addon)
        self.assertNotIn('chrome.windows.update(',result)
        self.assertIn('JARVIS_BACKGROUND_HANDSHAKE_V1',result)
        with self.assertRaises(ValueError):
            builder.patch_background(upstream+'\n',addon)

    def test_missing_endpoint_does_not_create_or_launch_anything(self):
        self.assertIsNone(launcher.connect_native(self.url,71,self.directory))
        self.assertFalse((self.directory/'browser-native').exists())

    def test_native_failure_never_falls_back_even_with_supervised_allowance(self):
        allowance = self.directory / launcher.ALLOWANCE
        allowance.write_text(json.dumps({'windowId':71,'issuedAt':time.time(),'expiresAt':time.time()+59}))
        allowance.chmod(0o600)
        with patch.object(Path,'home',return_value=self.home), patch.object(launcher.sys,'argv',['launcher',self.url]), patch.object(launcher,'connect_native',side_effect=ValueError('unknown')), patch.object(launcher.subprocess,'run') as shell, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(launcher.main(),1)
            shell.assert_not_called()
        self.assertEqual(json.loads((self.directory/'extension-window.json').read_text())['connectionTabId'],72)

    def test_native_result_is_published_without_focus_restoration_or_allowance(self):
        result = {'windowId':71,'connectionTabId':99,'previousFrontWindowId':0,'previousFrontApp':'','connectionMode':host.MODE}
        with patch.object(Path,'home',return_value=self.home), patch.object(launcher.sys,'argv',['launcher',self.url]), patch.object(launcher,'connect_native',return_value=result), patch.object(launcher.subprocess,'run') as shell:
            self.assertEqual(launcher.main(),0)
            shell.assert_not_called()
        self.assertEqual(json.loads((self.directory/'extension-window.json').read_text()),result)
        self.assertEqual((self.directory/'extension-window.json').stat().st_mode & 0o777,0o600)

    def test_real_native_pipe_roundtrip_and_eof_cleanup_without_chrome(self):
        process = subprocess.Popen([sys.executable,str(ROOT/'background-extension/native_host.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'HOME':str(self.home)})
        errors = []
        def shutdown():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)
        self.addCleanup(shutdown)
        host.write_frame(process.stdin,{'type':'hello','mode':host.MODE})
        endpoint = self.directory/'browser-native/control.sock'
        deadline = time.monotonic()+5
        while not endpoint.exists() and time.monotonic()<deadline:
            time.sleep(.02)
        self.assertTrue(endpoint.exists())
        self.assertEqual(endpoint.stat().st_mode & 0o777,0o600)
        # Authentication rejection is answered locally: no command may reach
        # the simulated extension before the two valid requests below.
        with self.assertRaises(ValueError):
            launcher.connect_native(self.connection_url(token='wrong'),71,self.directory)
        # A competing profile/worker must not unlink the live socket.
        competitor = subprocess.Popen([sys.executable,str(ROOT/'background-extension/native_host.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'HOME':str(self.home)})
        hello = io.BytesIO()
        host.write_frame(hello,{'type':'hello','mode':host.MODE})
        out, err = competitor.communicate(hello.getvalue(),timeout=5)
        self.assertEqual(competitor.returncode,1)
        self.assertEqual(out,b'')
        self.assertEqual(err,b'')
        self.assertTrue(endpoint.exists())
        def fake_extension():
            try:
                for tab_id in (91,92):
                    message = host.read_frame(process.stdout)
                    self.assertEqual(message['url'],self.url)
                    self.assertEqual(message['windowId'],71)
                    host.write_frame(process.stdin,{'id':message['id'],'ok':True,'mode':host.MODE,'windowId':71,'connectionTabId':tab_id})
            except BaseException as error:
                errors.append(error)
        thread=threading.Thread(target=fake_extension,daemon=True)
        thread.start()
        first=launcher.connect_native(self.url,71,self.directory)
        second=launcher.connect_native(self.url,71,self.directory)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors,errors)
        self.assertEqual(first['connectionTabId'],91)
        self.assertEqual(second['connectionTabId'],92)
        self.assertEqual(first['previousFrontWindowId'],0)
        process.stdin.close()
        process.stdin=None
        self.assertEqual(process.wait(timeout=5),0)
        self.assertFalse(endpoint.exists())
        self.assertEqual(process.stderr.read(),b'')


if __name__ == '__main__':
    unittest.main()
