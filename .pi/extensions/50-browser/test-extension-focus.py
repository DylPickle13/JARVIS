#!/usr/bin/env python3
"""Run local live tests while checking the user's foreground app/window/tab."""
import os
import json
from pathlib import Path
import subprocess
import threading
import time
SCRIPT='''tell application "System Events" to set a to bundle identifier of first application process whose frontmost is true
tell application "Google Chrome" to return a & ":" & (id of front window as text) & ":" & (id of active tab of front window as text)'''
def foreground():
    return subprocess.check_output(['osascript','-e',SCRIPT],text=True,stderr=subprocess.PIPE,timeout=5).strip()
before=foreground()
meta=json.loads((Path.home()/'.jarvis/extension-window.json').read_text())
assert before.split(':')[1]!=str(meta['windowId']), 'Focus test requires the personal Chrome window in front, not the automation window' 
samples=[];errors=[];stop=threading.Event()
def monitor():
    while not stop.is_set():
        try:samples.append(foreground())
        except Exception:errors.append('Foreground sample failed')
        stop.wait(.08)
t=threading.Thread(target=monitor);t.start()
try:
    result=subprocess.run(['python3',str(Path(__file__).with_name('test-extension-live.py'))],env={**os.environ,'JARVIS_TEST_BROWSER_URL':os.environ.get('JARVIS_TEST_BROWSER_URL','http://127.0.0.1:17323')})
finally:stop.set();t.join()
assert result.returncode==0,'Live tests failed'
assert not errors,errors
assert samples and all(s==before for s in samples),'Foreground changed during test'
assert foreground()==before,'Foreground changed after test'
print(f'PASS: foreground app, window and selected personal tab unchanged across {len(samples)} samples')
