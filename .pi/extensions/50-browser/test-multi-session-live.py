#!/usr/bin/env python3
"""Opt-in two-client fixture test. Only controls tabs created by this test."""
import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import subprocess
import time
import traceback
from pathlib import Path
from threading import Thread
import urllib.error
import urllib.request
from uuid import uuid4

URL = os.environ.get('JARVIS_TEST_BROWSER_URL', 'http://127.0.0.1:17322')
TOKEN = (Path.home()/'.jarvis/chrome-bridge.token').read_text().strip()
A, B = str(uuid4()), str(uuid4())
created = set()


def call(session, path, body=None):
    headers = {'Authorization': 'Bearer '+TOKEN, 'Content-Type': 'application/json',
               'X-Jarvis-Browser-Session': session}
    request = urllib.request.Request(URL+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from None
    assert result['ok'], result
    return result['result']


def rejected(session, path, body, expected):
    try:
        call(session, path, body)
    except RuntimeError as error:
        assert expected in str(error), str(error)
    else:
        raise AssertionError('Unsafe operation was not rejected')


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'''<!doctype html><title>Multi-session fixture</title>
<input id="draft"><button id="show" onclick="document.querySelector('#out').innerText=document.querySelector('#draft').value">Show</button><p id="out"></p>''')

    def log_message(self, *args):
        pass


server = HTTPServer(('127.0.0.1', 0), Fixture)
Thread(target=server.serve_forever, daemon=True).start()
try:
    assert call(A, '/status')['protocolVersion'] == 2
    url = f'http://127.0.0.1:{server.server_port}'
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(call, session, '/open', {'url': url, 'newTab': True}) for session in (A, B)]
        a, b = [job.result() for job in jobs]
    created.update((a['tabId'], b['tabId']))
    assert a['tabId'] != b['tabId']
    sa, sb = call(A, '/status'), call(B, '/status')
    assert created.issubset({p['tabId'] for p in sa['pages']})
    assert created.issubset({p['tabId'] for p in sb['pages']})
    assert sa['selectedTabId'] == a['tabId'] and sb['selectedTabId'] == b['tabId']
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(call, session, '/type', {'selector': '#draft', 'text': text, 'clear': True, 'delayMs': 0})
                for session, text in ((A, 'ALPHA'), (B, 'BRAVO'))]
        for job in jobs:
            job.result()
    screenshot = call(A, '/screenshot', {})
    assert base64.b64decode(screenshot['data']).startswith(b'\x89PNG\r\n\x1a\n')
    call(B, '/click', {'selector': '#show'})
    call(A, '/click', {'selector': '#show'})
    assert call(A, '/extract', {'selector': '#out'})['text'] == 'ALPHA'
    assert call(B, '/extract', {'selector': '#out'})['text'] == 'BRAVO'
    # Opt-in disruption: reload ONLY the verified connection anchor. No user
    # pages are reloaded. The daemon must recover before any fixture action.
    for attempt in range(int(os.environ.get('JARVIS_TEST_RECONNECTS', '0'))):
        metadata=json.loads((Path.home()/'.jarvis/extension-window.json').read_text())
        window_id, anchor_id=metadata['windowId'],metadata['connectionTabId']
        assert isinstance(window_id,int) and isinstance(anchor_id,int)
        script=f'''tell application "Google Chrome"
          set w to first window whose id is {window_id}
          set t to first tab of w whose id is {anchor_id}
          if not ((URL of t starts with "chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html") and (URL of t ends with "#jarvis-automation-anchor-v2")) then error "Not the automation anchor"
          set URL of t to URL of t
        end tell'''
        subprocess.run(['/usr/bin/osascript','-e',script],check=True,capture_output=True,timeout=20)
        time.sleep(1)
        for session, expected, tab in ((A,'ALPHA',a),(B,'BRAVO',b)):
            status=call(session,'/status')
            assert status['selectedTabId']==tab['tabId']
            assert not status['needsReselect']
            assert call(session,'/extract',{'selector':'#out'})['text']==expected
        after=json.loads((Path.home()/'.jarvis/extension-window.json').read_text())
        assert after['connectionTabId']!=anchor_id, 'reconnect must use a fresh anchor tab ID'
        assert after['windowId']==window_id, 'reconnect must retain the automation window'
        print(f'PASS: forced reconnect {attempt+1}, fresh anchor, selections and page state retained',flush=True)
    for action in ('switch', 'close'):
        rejected(B, '/tabs', {'action': action, 'tabId': a['tabId']}, 'controlled by another')
    call(A, '/tabs', {'action': 'release'})
    call(B, '/tabs', {'action': 'switch', 'tabId': a['tabId']})
    rejected(A, '/click', {'selector': '#show'}, 'released or expired')
    assert call(B, '/extract', {'selector': '#out'})['text'] == 'ALPHA'
    call(B, '/close', {'all': False})
    created.remove(a['tabId'])
    rejected(A, '/click', {'selector': '#show'}, 'closed or moved')
    rejected(B, '/key', {'key': 'Enter'}, 'closed or moved')
    call(B, '/tabs', {'action': 'switch', 'tabId': b['tabId']})
    assert call(B, '/extract', {'selector': '#out'})['text'] == 'BRAVO'
    print('PASS: shared inventory, concurrent sessions, independent inputs/screenshots, lease conflict, handoff, closed-tab safety')
except BaseException:
    # Preserve the primary failure even if cleanup itself hits a transport fault.
    traceback.print_exc()
    raise
finally:
    # Release both handles, then close only known test-created tab IDs.
    for session in (A, B):
        call(session, '/close', {'all': True})
    cleanup = str(uuid4())
    for tab_id in sorted(created):
        call(cleanup, '/tabs', {'action': 'close', 'tabId': tab_id})
    call(cleanup, '/close', {'all': True})
    server.shutdown()
