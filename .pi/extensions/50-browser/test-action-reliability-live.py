#!/usr/bin/env python3
"""Supervised, opt-in fixture. Never restart Chrome/bridge or touch existing forms."""
import os
if os.environ.get('JARVIS_TEST_RELIABILITY_MAINTENANCE') != '1':
    raise SystemExit('Not authorized: requires JARVIS_TEST_RELIABILITY_MAINTENANCE=1 in a supervised idle maintenance window')

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from threading import Thread
import urllib.error
import urllib.request
from uuid import uuid4

URL = os.environ.get('JARVIS_TEST_BROWSER_URL', 'http://127.0.0.1:17323')
TOKEN = (Path.home()/'.jarvis/chrome-bridge.token').read_text().strip()
A, B = str(uuid4()), str(uuid4())
created = {}


def call(session, path, body=None):
    request = urllib.request.Request(URL+path, data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+TOKEN, 'Content-Type':'application/json', 'X-Jarvis-Browser-Session':session})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from None
    assert result['ok'], result
    return result['result']


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'''<!doctype html><title>JARVIS reliability fixture</title>
<style>body{height:3000px}#draft{position:absolute;left:20px;top:20px;width:500px;height:100px}
#nested{position:absolute;left:20px;top:180px;width:500px;height:240px;overflow:auto}
#readout{position:fixed;top:0;right:0;background:white;max-width:500px;max-height:100px;overflow:hidden}
</style><textarea id="draft" oninput="document.querySelector('#mirror').textContent=this.value"></textarea>
<div id="nested" onscroll="document.querySelector('#nested-y').textContent=this.scrollTop"><div style="height:2000px">Nested scroll</div></div>
<div id="readout"><p id="mirror"></p><p id="window-y">0</p><p id="nested-y">0</p></div>
<script>addEventListener('scroll',()=>document.querySelector('#window-y').textContent=scrollY)</script>''')

    def log_message(self, *args):
        pass


server = HTTPServer(('127.0.0.1', 0), Fixture)
Thread(target=server.serve_forever, daemon=True).start()
try:
    status = call(A, '/status')
    assert status['protocolVersion'] == 2 and 'quarantined' in status['daemon'], 'Candidate backend is not deployed'
    assert not status['daemon']['quarantined'], 'Do not test a quarantined bridge'
    fixture_url = f'http://127.0.0.1:{server.server_port}'
    # Record each successful creation immediately; an uncertain creation is never replayed.
    for session in (A, B):
        created[session] = call(session, '/open', {'url':fixture_url, 'newTab':True})['tabId']
    values = {A:'ALPHA-'*900, B:'BRAVO-'*1000}
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(call, session, '/type', {'selector':'#draft', 'text':values[session], 'clear':True, 'delayMs':0}) for session in (A, B)]
        for job in jobs:
            result = job.result()
            assert result['valueVerified'] and result['inputMethod'] == 'fill'
    for session in (A, B):
        assert call(session, '/extract', {'selector':'#mirror', 'maxText':10000})['text'] == values[session]
    # Validate real wheel delivery, not just command success, on nested and page scrollers.
    for session in (A, B):
        call(session, '/scroll', {'direction':'down', 'amount':300, 'x':150, 'y':280})
        assert int(call(session, '/extract', {'selector':'#nested-y'})['text']) > 0
        call(session, '/scroll', {'direction':'down', 'amount':300, 'x':900, 'y':500})
        assert int(call(session, '/extract', {'selector':'#window-y'})['text']) > 0
    # A completed selector timeout may fence A, but must not reset/fence B.
    before = call(B, '/status')['daemon']['resetCount']
    try:
        call(A, '/click', {'selector':'#deliberately-absent', 'timeoutMs':500})
    except RuntimeError as error:
        assert 'TimeoutError' in str(error), str(error)
    else:
        raise AssertionError('Missing selector was not rejected')
    status_a, status_b = call(A, '/status'), call(B, '/status')
    assert status_a['needsReselect'] and not status_b['needsReselect']
    assert status_b['daemon']['resetCount'] == before
    assert call(B, '/extract', {'selector':'#mirror', 'maxText':10000})['text'] == values[B]
    call(A, '/tabs', {'action':'switch', 'tabId':created[A]})
    assert call(A, '/extract', {'selector':'#mirror', 'maxText':10000})['text'] == values[A]
    print('PASS: simultaneous verified long fields, nested/page wheel delivery, local failure isolation, retained drafts')
finally:
    # If execution is uncertain, preserve evidence and do not force cleanup or
    # restart/reselect around the fence. Only the owner can authorize recovery.
    try:
        status = call(A, '/status')
        if status['daemon'].get('quarantined'):
            print('STOP: bridge quarantined; fixture tabs retained for supervised recovery. No restart or retry attempted.')
        else:
            for session, tab_id in created.items():
                try:
                    call(session, '/tabs', {'action':'close', 'tabId':tab_id})
                except Exception:
                    print('Fixture cleanup failed; retained tab ID:', tab_id)
                    break
        for session in (A, B):
            call(session, '/close', {'all':True})
    except Exception:
        print('Cleanup unavailable; no blind retry. Inspect fixture tabs during maintenance.')
    finally:
        server.shutdown()
