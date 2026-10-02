#!/usr/bin/env python3
"""Start/open the local dashboard. No login service and no recording side effects."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from dashboard_server import secret
import dashboard_jobs as jobs

PORT=8768
URL=f'http://127.0.0.1:{PORT}'


def ensure_server():
    jobs.STATE.mkdir(mode=0o700,exist_ok=True)
    with (jobs.STATE/'launcher.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        token=secret()
        try:
            req=urllib.request.Request(URL+'/api/session',headers={'Cookie':'phone_session='+token})
            with urllib.request.urlopen(req,timeout=2) as response:
                if response.status==200:return token
        except Exception:pass
        with (jobs.STATE/'server.log').open('ab') as log:
            p=subprocess.Popen([sys.executable,str(jobs.ROOT/'dashboard_server.py'),'--port',str(PORT)],cwd=jobs.ROOT,
                               stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        (jobs.STATE/'server.pid').write_text(str(p.pid))
        for _ in range(30):
            if p.poll() is not None:raise RuntimeError('Dashboard server exited; inspect .dashboard/server.log (port may be occupied)')
            try:
                req=urllib.request.Request(URL+'/api/session',headers={'Cookie':'phone_session='+token})
                with urllib.request.urlopen(req,timeout=1) as response:
                    if response.status==200:return token
            except Exception:time.sleep(.2)
        raise RuntimeError('Dashboard not ready; see server.log')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--no-open',action='store_true');a=p.parse_args()
    token=ensure_server()
    if not a.no_open:subprocess.run(['open',URL+'/#token='+token],check=True)
    print('Phone Recording dashboard: '+URL)
    print('Closing the browser does not stop recording or cancel jobs.')
