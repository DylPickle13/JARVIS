#!/usr/bin/env python3
"""Opt-in live recovery test: local fixture only; leaves existing work tabs untouched."""
import json
import os
from pathlib import Path
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import urllib.request
from uuid import uuid4

SESSION = str(uuid4())

URL = os.environ.get('JARVIS_TEST_BROWSER_URL', 'http://127.0.0.1:17324')
TOKEN = (Path.home()/'.jarvis/chrome-bridge.token').read_text().strip()
def call(path, body=None):
    request = urllib.request.Request(URL+path, data=None if body is None else json.dumps(body).encode(), headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json','X-Jarvis-Browser-Session':SESSION})
    with urllib.request.urlopen(request, timeout=160) as response:
        result = json.load(response)
    assert result['ok'], result
    return result['result']
class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
        self.wfile.write(b'<title>Window recovery fixture</title><input id="draft"><button id="read" onclick="document.querySelector(\'#out\').innerText=document.querySelector(\'#draft\').value">Read</button><p id="out"></p>')
    def log_message(self,*args): pass
server = HTTPServer(('127.0.0.1',0),Fixture)
Thread(target=server.serve_forever,daemon=True).start()
created_id = None
try:
    baseline = call('/tabs',{'action':'list'})
    window = baseline['automationWindow']['windowId']
    background_only = os.environ.get('JARVIS_TEST_BACKGROUND_RECOVERY') == '1'
    if background_only:
        # For focus acceptance, avoid AppleScript's foregrounding OpenURL path.
        # This mode tests bridge restart recovery, not external-tab creation.
        created_id = call('/open', {'url':f'http://127.0.0.1:{server.server_port}/','newTab':True})['tabId']
    else:
        # Simulate a user opening a tab outside the bridge's creation history.
        # This setup action may itself show Chrome; do not use for focus tests.
        script = f'''tell application "Google Chrome"
          set w to first window whose id is {window}
          set t to make new tab at end of tabs of w with properties {{URL:"http://127.0.0.1:{server.server_port}/"}}
          return id of t
        end tell'''
        created_id = int(subprocess.check_output(['/usr/bin/osascript','-e',script],text=True).strip())
    status = call('/tabs',{'action':'list'})
    page = next(p for p in status['pages'] if p['tabId']==created_id)
    call('/tabs',{'action':'switch','index':page['index']})
    call('/type',{'selector':'#draft','text':'Unsaved draft survives reconnect','clear':True,'delayMs':0})
    subprocess.run(['launchctl','kickstart','-k',f'gui/{os.getuid()}/com.jarvis.browser-bridge'],check=True)
    time.sleep(2)
    status = call('/tabs',{'action':'list'})
    page = next(p for p in status['pages'] if p['tabId']==created_id)
    call('/tabs',{'action':'switch','index':page['index']})
    call('/click',{'selector':'#read'})
    assert call('/extract',{'selector':'#out'})['text']=='Unsaved draft survives reconnect'
    print('PASS: '+('background-created fixture recovered' if background_only else 'externally opened automation tab discovered')+'; Chrome ID and unsaved input survive bridge restart')
finally:
    if created_id is not None:
        status = call('/tabs',{'action':'list'})
        page = next((p for p in status['pages'] if p.get('tabId')==created_id),None)
        if page:
            call('/tabs',{'action':'close','index':page['index']})
    call('/close', {'all': True})
    server.shutdown()
