#!/usr/bin/env python3
"""Opt-in local fixture test. Never reads or controls personal tabs."""
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import urllib.error
import urllib.request

URL = os.environ.get('JARVIS_TEST_BROWSER_URL', 'http://127.0.0.1:17324')
TOKEN = (Path.home()/'.jarvis/chrome-bridge.token').read_text().strip()
class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
        self.wfile.write(b'''<!doctype html><title>JARVIS browser fixture</title><h1>Local test</h1><input id="name"><button id="go" onclick="document.querySelector('#out').innerText=document.querySelector('#name').value">Show</button><p id="out"></p><input id="file" type="file"><a href="https://example.com">Example</a><div style="height:2000px">Scroll test</div>''')
    def log_message(self,*args): pass

def call(path, body=None):
    req=urllib.request.Request(URL+path, data=None if body is None else json.dumps(body).encode(), headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=160) as response: result=json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode()) from None
    assert result['ok'],result
    return result['result']

server=HTTPServer(('127.0.0.1',0),Fixture)
Thread(target=server.serve_forever,daemon=True).start()
try:
    baseline=len(call('/status')['pages'])
    first=call('/open',{'url':f'http://127.0.0.1:{server.server_port}','newTab':True})
    assert first['title']=='JARVIS browser fixture'
    call('/type',{'selector':'#name','text':'Verified','clear':True,'delayMs':0})
    call('/click',{'selector':'#go'})
    call('/wait',{'text':'Verified'})
    assert call('/extract',{'selector':'#out'})['text']=='Verified'
    assert any(l['text']=='Example' for l in call('/extract',{'includeLinks':True})['links'])
    image=call('/screenshot',{})
    assert base64.b64decode(image['data']).startswith(b'\x89PNG\r\n\x1a\n')
    assert image['width']>0 and image['height']>0
    call('/scroll',{'direction':'down','amount':500})
    call('/type',{'selector':'#name','text':'','clear':True,'delayMs':0})
    # Clearing to an empty string must actually clear the field.
    call('/click',{'selector':'#go'})
    assert call('/extract',{'selector':'#out'})['text']==''
    with tempfile.NamedTemporaryFile(suffix='.txt') as f:
        f.write(b'JARVIS local browser fixture only');f.flush()
        uploaded=call('/upload',{'selector':'#file','path':f.name})
        assert uploaded['method']=='input'
    second=call('/open',{'url':'about:blank','newTab':True})
    assert len(call('/tabs',{'action':'list'})['pages'])==baseline+2
    call('/tabs',{'action':'switch','index':first['index']})
    call('/key',{'key':'Tab'})
    call('/tabs',{'action':'close','index':second['index']})
    call('/close',{'all':False})
    assert len(call('/status')['pages'])==baseline
    print('PASS: navigation, typing, empty clear, click, wait, extraction, links, PNG, scroll, local upload, tab isolation and cleanup')
finally:
    server.shutdown()
