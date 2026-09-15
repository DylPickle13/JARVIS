#!/usr/bin/env python3
"""Playwright executable shim: open its connection ONLY in the JARVIS window.
Never logs connection URLs (they contain an authentication token).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

EXTENSION = 'mmlmfjhmonkocbjadbfplnigmagldckm'
MARKER_TITLE = 'JARVIS Browser — Automation Only'
SCRIPT = '''
on run argv
 set connectURL to item 1 of argv
 set priorConnectionID to item 2 of argv
 set priorApp to ""
 try
  tell application "System Events" to set priorApp to bundle identifier of first application process whose frontmost is true
 end try
 tell application "Google Chrome"
  set oldFront to missing value
  if (count of windows) > 0 then set oldFront to id of front window
  set targetWindowID to missing value
  set createdTabID to missing value
  repeat with w in windows
   repeat with t in tabs of w
    if title of t is "JARVIS Browser — Automation Only" or ((URL of t starts with "chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html") and (URL of t ends with "#jarvis-automation-anchor-v2")) then
     set targetWindowID to id of w
     exit repeat
    end if
   end repeat
   if targetWindowID is not missing value then exit repeat
  end repeat
  if targetWindowID is missing value then
   set createdWindow to make new window
   set targetWindowID to id of createdWindow
   set URL of active tab of (first window whose id is targetWindowID) to connectURL
   set createdTabID to id of active tab of (first window whose id is targetWindowID)
  end if
  if createdTabID is missing value then
   tell (first window whose id is targetWindowID)
    repeat with t in tabs
     if (URL of t starts with "chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html") and (((id of t as text) is priorConnectionID) or (URL of t ends with "#jarvis-automation-anchor-v2")) then
      set createdTabID to id of t
      set URL of t to connectURL
      exit repeat
     end if
    end repeat
    if createdTabID is missing value then
     set newTab to make new tab at end of tabs with properties {URL:connectURL}
     set createdTabID to id of newTab
    end if
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
    try: prior_id=str(json.loads(path.read_text())['connectionTabId'])
    except (OSError,ValueError,KeyError): prior_id='0'
    url=parsed._replace(fragment='jarvis-automation-anchor-v2').geturl()
    result=subprocess.run(['/usr/bin/osascript','-e',SCRIPT,'--',url,prior_id],capture_output=True,text=True,timeout=30)
    if result.returncode:
        # AppleScript errors can embed arguments; do not print stderr.
        return 1
    ids=result.stdout.strip().split(',')
    if len(ids)!=4 or not all(s.isdigit() for s in ids[:3]): return 1
    path=Path.home()/'.jarvis'/'extension-window.json'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump({'windowId':int(ids[0]),'connectionTabId':int(ids[1]),'previousFrontWindowId':int(ids[2]),'previousFrontApp':ids[3]},f)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
