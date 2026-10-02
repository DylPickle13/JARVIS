#!/usr/bin/env python3
"""Playwright executable shim: open its connection ONLY in the JARVIS window.
Never logs connection URLs (they contain an authentication token).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

EXTENSION = 'mmlmfjhmonkocbjadbfplnigmagldckm'
MARKER_TITLE = 'JARVIS Browser — Automation Only'
SCRIPT = '''
on run argv
 set connectURL to item 1 of argv
 set priorWindowID to item 2 of argv
 set priorApp to ""
 try
  tell application "System Events" to set priorApp to bundle identifier of first application process whose frontmost is true
 end try
 tell application "Google Chrome"
  set oldFront to missing value
  if (count of windows) > 0 then set oldFront to id of front window
  set targetWindowID to missing value
  set createdTabID to missing value
  -- Follow only our recorded native window ID. A moved marker must never
  -- cause a personal window to be adopted as the automation window.
  repeat with w in windows
   if (id of w as text) is priorWindowID then
    set targetWindowID to id of w
    exit repeat
   end if
  end repeat
  if targetWindowID is missing value then
   set createdWindow to make new window
   set targetWindowID to id of createdWindow
   set URL of active tab of (first window whose id is targetWindowID) to connectURL
   set createdTabID to id of active tab of (first window whose id is targetWindowID)
  end if
  if createdTabID is missing value then
   tell (first window whose id is targetWindowID)
    -- Never reuse the old connection tab: its asynchronous debugger/group
    -- cleanup can detach a new connection that reuses the same Chrome tab ID.
    set newTab to make new tab at end of tabs with properties {URL:connectURL}
    set createdTabID to id of newTab
   end tell
  end if
  if oldFront is missing value then set oldFront to 0
  set resultIDs to (targetWindowID as text) & "," & (createdTabID as text) & "," & (oldFront as text) & "," & priorApp
  if oldFront is not missing value and oldFront is not targetWindowID then
   try
    set index of (first window whose id is oldFront) to 1
   end try
  end if
  return resultIDs
 end tell
end run
'''

def main():
    url = sys.argv[-1] if len(sys.argv)>1 else ''
    parsed = urlparse(url)
    if parsed.scheme != 'chrome-extension' or parsed.netloc != EXTENSION or parsed.path != '/connect.html':
        return 2
    path=Path.home()/'.jarvis'/'extension-window.json'
    try:
        prior_window=json.loads(path.read_text())['windowId']
        if not isinstance(prior_window,int) or isinstance(prior_window,bool): raise ValueError('Invalid window ID')
    except (OSError,ValueError,KeyError): prior_window=0
    url=parsed._replace(fragment='jarvis-automation-anchor-v2').geturl()
    result=subprocess.run(['/usr/bin/osascript','-e',SCRIPT,'--',url,str(prior_window)],capture_output=True,text=True,timeout=30)
    if result.returncode:
        # AppleScript errors can embed arguments; do not print stderr.
        return 1
    ids=result.stdout.strip().split(',')
    if len(ids)!=4 or not all(s.isdigit() for s in ids[:3]): return 1
    path=Path.home()/'.jarvis'/'extension-window.json'
    # Publish a complete generation atomically; readers must never see a
    # truncated identity file while Chrome is already completing its handshake.
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='extension-window-',delete=False) as f:
            temporary=f.name
            json.dump({'windowId':int(ids[0]),'connectionTabId':int(ids[1]),'previousFrontWindowId':int(ids[2]),'previousFrontApp':ids[3]},f)
        os.replace(temporary,path)
    finally:
        if temporary and os.path.exists(temporary): os.unlink(temporary)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
