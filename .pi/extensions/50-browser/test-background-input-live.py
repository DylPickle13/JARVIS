#!/usr/bin/env python3
"""Supervised, opt-in check of frame-free scroll/click while the automation
window is out of view. Uses the production bridge as an ordinary session, on a
localhost fixture tab only. Never restarts Chrome/bridge or touches existing tabs.

Run with the JARVIS automation window on a Space you are NOT viewing:
  JARVIS_TEST_BACKGROUND_INPUT=1 python3 test-background-input-live.py
"""
import os
if os.environ.get('JARVIS_TEST_BACKGROUND_INPUT') != '1':
    raise SystemExit('Not authorized: requires JARVIS_TEST_BACKGROUND_INPUT=1 while no browser job is running')

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from threading import Thread
import time
import urllib.error
import urllib.request
from uuid import uuid4

URL = os.environ.get('JARVIS_TEST_BROWSER_URL', 'http://127.0.0.1:17323')
TOKEN = (Path.home()/'.jarvis/chrome-bridge.token').read_text().strip()
IDLE = int(os.environ.get('JARVIS_TEST_IDLE_SECONDS', '70'))
# Optional: open the fixture while the window is visible (so the tab has really
# been shown), then wait up to N seconds for the owner to switch Spaces and the
# page to report hidden. A never-shown tab keeps painting and proves nothing.
WAIT_HIDDEN = int(os.environ.get('JARVIS_TEST_WAIT_HIDDEN_SECONDS', '0'))
SESSION = str(uuid4())
timings = {}


def call(path, body=None, label=None):
    request = urllib.request.Request(URL+path, data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+TOKEN, 'Content-Type':'application/json', 'X-Jarvis-Browser-Session':SESSION})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from None
    finally:
        if label:
            timings[label] = round(time.monotonic()-start, 2)
    assert result['ok'], result
    return result['result']


def readout():
    return json.loads(call('/extract', {'selector':'#state'})['text'])


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        # No animation-frame loop, timer or animation: nothing keeps the renderer drawing.
        self.wfile.write(b'''<!doctype html><title>JARVIS background input fixture</title>
<style>html{scroll-behavior:smooth}body{height:4000px;margin:0}
#nested{position:absolute;left:20px;top:80px;width:400px;height:240px;overflow:auto}
#below{position:absolute;left:40px;top:2600px}
#covered{position:absolute;left:600px;top:120px}
#cover{position:absolute;left:580px;top:100px;width:200px;height:80px;background:#ccc}
#state{position:fixed;right:0;top:0;width:420px;background:white}</style>
<div id="nested"><div style="height:2000px">Nested panel</div></div>
<button id="below">Below the fold</button><button id="covered">Covered</button><div id="cover"></div>
<pre id="state"></pre>
<script>
const s={visibility:document.visibilityState,hiddenSeen:document.visibilityState==='hidden',below:0,covered:0,wheels:0,scrollY:0,nestedY:0};
// Read positions live: scroll events are deferred to the next frame while hidden.
const show=()=>{s.visibility=document.visibilityState;s.scrollY=Math.round(scrollY);s.nestedY=Math.round(document.querySelector('#nested').scrollTop);document.querySelector('#state').textContent=JSON.stringify(s)};
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')s.hiddenSeen=true;show()});
document.querySelector('#below').onclick=()=>{s.below++;show()};
document.querySelector('#covered').onclick=()=>{s.covered++;show()};
document.querySelector('#nested').onscroll=e=>{s.nestedY=Math.round(e.target.scrollTop);show()};
addEventListener('wheel',()=>{s.wheels++;show()},{passive:true});
addEventListener('scroll',show);show();
</script>''')

    def log_message(self, *args):
        pass


server = HTTPServer(('127.0.0.1', 0), Fixture)
Thread(target=server.serve_forever, daemon=True).start()
tab = None
try:
    status = call('/status')
    assert status['protocolVersion'] == 2 and not status['daemon']['quarantined'], 'Bridge unavailable'
    resets = status['daemon']['resetCount']
    tab = call('/open', {'url':f'http://127.0.0.1:{server.server_port}', 'newTab':True})['tabId']
    if WAIT_HIDDEN:
        print(f'Fixture tab {tab} open; waiting up to {WAIT_HIDDEN}s for the page to report hidden...', flush=True)
        deadline = time.monotonic() + WAIT_HIDDEN
        while readout()['visibility'] != 'hidden':
            assert time.monotonic() < deadline, 'Page never became hidden; automation window stayed on screen'
            time.sleep(5)
        print('Page hidden; idling so Chrome settles...', flush=True)
    else:
        print(f'Fixture tab {tab} open. Idling {IDLE}s so Chrome settles the hidden window...', flush=True)
    time.sleep(IDLE)
    before = readout()
    print('Page visibility before actions:', before['visibility'], '| hidden seen:', before['hiddenSeen'], flush=True)

    # Nested panel first, while it is under the point at the top of the page.
    nested = call('/scroll', {'direction':'down', 'amount':300, 'x':200, 'y':200}, 'scroll-nested')
    assert nested['method'] == 'script' and nested['container'] == 'element' and nested['movedY'] == 300, nested
    page = call('/scroll', {'direction':'down', 'amount':600}, 'scroll-page')
    assert page['container'] == 'page' and page['movedY'] == 600, page
    call('/scroll', {'direction':'up', 'amount':3000}, 'scroll-up')
    clicked = call('/click', {'selector':'#below'}, 'click-below-fold')
    state = readout()
    assert state['below'] == 1 and state['nestedY'] == 300 and state['wheels'] == 0, state

    # A covered target must fail locally (this session only) and never be clicked.
    try:
        call('/click', {'selector':'#covered', 'timeoutMs':1500}, 'click-covered')
    except RuntimeError as error:
        assert 'TimeoutError' in str(error) and 'covered by div#cover' in str(error), str(error)
    else:
        raise AssertionError('Covered target was clicked')
    call('/tabs', {'action':'switch', 'tabId':tab})
    final = readout()
    assert final['covered'] == 0 and final['below'] == 1, final
    assert call('/status')['daemon']['resetCount'] == resets, 'Bridge reset during the test'
    slow = {k: v for k, v in timings.items() if k != 'click-covered' and v > 5}
    assert not slow, f'Slow actions: {slow}'
    print('Timings (s):', timings)
    print('Page visibility during actions:', final['visibility'], '| hidden seen:', final['hiddenSeen'])
    if WAIT_HIDDEN:
        assert final['visibility'] == 'hidden', 'Window became visible during the actions; result is not conclusive'
    if not final['hiddenSeen']:
        print('NOTE: the page never reported hidden; rerun with the automation window out of view to exercise the stall case.')
    print('PASS: script scroll (page + nested), below-the-fold selector click, covered-target refusal, no bridge reset')
finally:
    try:
        if tab is not None:
            call('/tabs', {'action':'close', 'tabId':tab})
        call('/close', {'all':True})
    except Exception as error:
        print('Fixture cleanup failed; retained tab ID:', tab, error)
    server.shutdown()
