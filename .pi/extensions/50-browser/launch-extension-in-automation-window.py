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
import time
import stat
import socket
import struct
from urllib.parse import urlparse

EXTENSION = 'mmlmfjhmonkocbjadbfplnigmagldckm'
MARKER_TITLE = 'JARVIS Browser — Automation Only'
# The official extension focuses its window during every fresh handshake.
# Deny before any AppleEvent unless a supervised, single-use allowance exists.
ALLOWANCE = 'browser-reconnect-once.json'
BLOCKED = 3
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
  -- Never create a replacement on the user's current Space. Placement of
  -- the existing window must be established manually before authorizing.
  if targetWindowID is missing value then error "Automation window unavailable; manual placement required"
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

def consume_allowance(directory, window_id):
    """Atomically consume before launching; uncertainty never grants a retry."""
    path = directory / ALLOWANCE
    claimed = directory / (ALLOWANCE + f'.claimed-{os.getpid()}')
    try:
        os.replace(path, claimed)
    except OSError:
        return False
    try:
        metadata = claimed.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            return False
        ticket = json.loads(claimed.read_text())
        now = time.time()
        issued = ticket.get('issuedAt')
        expires = ticket.get('expiresAt')
        return (type(window_id) is int and window_id > 0
                and type(ticket.get('windowId')) is int and ticket['windowId'] == window_id
                and type(issued) in (int, float) and type(expires) in (int, float)
                and issued <= now < expires and 0 < expires - issued <= 60)
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    finally:
        claimed.unlink(missing_ok=True)


def authorize_once(args):
    """Local owner-operated setup only, never called by a browser request."""
    import argparse
    parser = argparse.ArgumentParser(description='Allow ONE supervised Chrome handshake (may switch Spaces).')
    parser.add_argument('--allow-once', action='store_true', required=True)
    parser.add_argument('--window-id', type=int, required=True)
    parser.add_argument('--acknowledge-focus-change', action='store_true', required=True)
    options = parser.parse_args(args)
    directory = Path.home() / '.jarvis'
    identity = json.loads((directory / 'extension-window.json').read_text())
    if type(identity.get('windowId')) is not int or options.window_id <= 0 or identity['windowId'] != options.window_id:
        parser.error('Window must match the recorded automation window; no replacement is created')
    now = time.time()
    ticket = {'windowId': options.window_id, 'issuedAt': now, 'expiresAt': now + 60}
    with tempfile.NamedTemporaryFile(mode='w', dir=directory, prefix='browser-allow-', delete=False) as f:
        temporary = Path(f.name)
        json.dump(ticket, f)
    try:
        os.replace(temporary, directory / ALLOWANCE)
    finally:
        temporary.unlink(missing_ok=True)
    print('One supervised handshake allowed for 60 seconds. It MAY switch Spaces; do not use while working.')
    return 0


def connect_native(url, window_id, directory):
    """Return None only if no native endpoint exists BEFORE dispatch.

    Once dispatched, failures are uncertain: never fall back to AppleScript.
    This endpoint exists only while the reviewed background extension is alive.
    """
    private = directory / 'browser-native'
    endpoint = private / 'control.sock'
    if not endpoint.exists():
        return None
    metadata = private.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError('Unsafe native socket directory')
    metadata = endpoint.lstat()
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError('Unsafe native socket')
    mode = 'jarvis-background-native-v1'
    message = json.dumps({'command': 'connect', 'mode': mode, 'url': url, 'windowId': window_id}).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(22)
        client.connect(str(endpoint))
        client.sendall(struct.pack('<I', len(message)) + message)
        def receive(size):
            data = bytearray()
            while len(data) < size:
                chunk = client.recv(size - len(data))
                if not chunk:
                    raise ValueError('Native connection outcome unknown')
                data.extend(chunk)
            return bytes(data)
        size = struct.unpack('<I', receive(4))[0]
        if not 0 < size <= 65536:
            raise ValueError('Invalid native response size')
        result = json.loads(receive(size))
    if (not isinstance(result, dict) or result.get('ok') is not True or result.get('mode') != mode
            or type(result.get('windowId')) is not int or result['windowId'] != window_id
            or type(result.get('connectionTabId')) is not int or result['connectionTabId'] <= 0):
        raise ValueError('Native connection refused')
    return {'windowId': window_id, 'connectionTabId': result['connectionTabId'],
            'previousFrontWindowId': 0, 'previousFrontApp': '', 'connectionMode': mode}


def publish_identity(path, identity):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='extension-window-', delete=False) as f:
            temporary = f.name
            json.dump(identity, f)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if '--allow-once' in sys.argv[1:]:
        return authorize_once(sys.argv[1:])
    url = sys.argv[-1] if len(sys.argv)>1 else ''
    parsed = urlparse(url)
    if parsed.scheme != 'chrome-extension' or parsed.netloc != EXTENSION or parsed.path != '/connect.html':
        return 2
    path=Path.home()/'.jarvis'/'extension-window.json'
    try:
        prior_window=json.loads(path.read_text())['windowId']
        if type(prior_window) is not int or prior_window <= 0: raise ValueError('Invalid window ID')
    except (OSError,ValueError,KeyError,TypeError): prior_window=0
    url=parsed._replace(fragment='jarvis-automation-anchor-v2').geturl()
    if prior_window:
        try:
            identity = connect_native(url, prior_window, path.parent)
            if identity is not None:
                publish_identity(path, identity)
                return 0
        except (OSError, ValueError, TypeError):
            print('Background native connection failed or outcome unknown; no foreground fallback or replay.', file=sys.stderr)
            return 1
    if not consume_allowance(path.parent, prior_window):
        print('Background-only policy: fresh Chrome connection blocked to prevent focus/Space switching. Ask sir before a supervised reconnect.', file=sys.stderr)
        return BLOCKED
    try:
        result=subprocess.run(['/usr/bin/osascript','-e',SCRIPT,'--',url,str(prior_window)],capture_output=True,text=True,timeout=30)
    except (OSError, subprocess.SubprocessError):
        # Timeout exceptions include argv (and therefore the token). The consumed
        # allowance stays consumed: an uncertain handshake must not be retried.
        return 1
    if result.returncode:
        # AppleScript errors can embed arguments; do not print stderr.
        return 1
    ids=result.stdout.strip().split(',')
    if len(ids)!=4 or not all(s.isdigit() for s in ids[:3]): return 1
    if int(ids[0]) != prior_window or int(ids[1]) <= 0: return 1
    path=Path.home()/'.jarvis'/'extension-window.json'
    # Publish a complete generation atomically; readers must never see a
    # truncated identity file while Chrome is already completing its handshake.
    publish_identity(path, {'windowId':int(ids[0]),'connectionTabId':int(ids[1]),'previousFrontWindowId':int(ids[2]),'previousFrontApp':ids[3]})
    return 0

if __name__=='__main__':
    raise SystemExit(main())
