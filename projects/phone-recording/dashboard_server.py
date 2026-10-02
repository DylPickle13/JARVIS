#!/usr/bin/env python3
"""Authenticated loopback-only dashboard on mac-mini-64. No recording in HTTP threads."""
import argparse
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import urlsplit,parse_qs
import dashboard_jobs as jobs

ROOT=Path(__file__).resolve().parent
STATIC=ROOT/'dashboard'


def secret():
    jobs.STATE.mkdir(mode=0o700,exist_ok=True)
    path=jobs.STATE/'auth-token'
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
    except FileExistsError:pass
    os.chmod(path,0o600)
    return path.read_text().strip()


class Handler(BaseHTTPRequestHandler):
    server_version='PhoneDashboard'

    def log_message(self,format,*args):
        # Never log authentication bodies/cookies or URL query strings.
        print(self.command,urlsplit(self.path).path,args[1] if len(args)>1 else '',flush=True)

    def respond(self,status,body,kind='application/json',cookie=None):
        data=json.dumps(body).encode() if kind=='application/json' else body
        self.send_response(status)
        self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(data)

    def host_ok(self):return self.headers.get('Host') in self.server.hosts

    def authenticated(self):
        try:
            cookie=SimpleCookie(self.headers.get('Cookie',''));candidate=cookie['phone_session'].value
            return hmac.compare_digest(candidate,self.server.token)
        except (KeyError,ValueError):return False

    def do_GET(self):
        try:
            if not self.host_ok():return self.respond(421,{'error':'Invalid host'})
            path=urlsplit(self.path).path
            assets={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if path in assets:
                name,kind=assets[path];return self.respond(200,(STATIC/name).read_bytes(),kind)
            if not self.authenticated():return self.respond(401,{'error':'Open the Dashboard.command launcher to authorize this browser.'})
            if path=='/api/session':return self.respond(200,{'csrf':self.server.csrf})
            if path=='/api/state':return self.respond(200,jobs.state())
            if path=='/api/preview':
                role=parse_qs(urlsplit(self.path).query).get('camera',[''])[0]
                if role not in jobs.PREVIEW_ROLES:raise ValueError('Unknown camera')
                p=jobs.STATE/(role+'.jpg')
                if not jobs.preview_info() or not p.exists():return self.respond(404,{'error':'Snapshot unavailable or expired'})
                return self.respond(200,p.read_bytes(),'image/jpeg')
            if path=='/api/log':
                job_id=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
                job=jobs.get(job_id)
                # ID is resolved through the database, not arbitrary filesystem input.
                p=jobs.STATE/(job['id']+'.log')
                if p.exists():
                    with p.open('rb') as f:f.seek(max(0,p.stat().st_size-20000));text=f.read().decode(errors='replace')
                else:text='No log output yet.'
                return self.respond(200,{'text':text})
            return self.respond(404,{'error':'Not found'})
        except (ValueError,KeyError) as e:self.respond(400,{'error':str(e)})
        except Exception as e:self.respond(500,{'error':str(e)[:400]})

    def do_POST(self):
        try:
            if not self.host_ok():return self.respond(421,{'error':'Invalid host'})
            if self.headers.get('Origin')!='http://'+self.headers['Host']:
                return self.respond(403,{'error':'Same-origin requests only'})
            if self.headers.get_content_type()!='application/json':return self.respond(415,{'error':'JSON required'})
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=16384:return self.respond(413,{'error':'Invalid body size'})
            data=json.loads(self.rfile.read(size));path=urlsplit(self.path).path
            if not isinstance(data,dict):raise ValueError('JSON object required')
            if path=='/api/auth':
                token=data.get('token','')
                if not isinstance(token,str) or not hmac.compare_digest(token,self.server.token):return self.respond(401,{'error':'Invalid authorization'})
                return self.respond(200,{'csrf':self.server.csrf},cookie='phone_session='+self.server.token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000')
            if not self.authenticated():return self.respond(401,{'error':'Not authorized'})
            if not hmac.compare_digest(self.headers.get('X-Phone-CSRF',''),self.server.csrf):return self.respond(403,{'error':'Invalid request authorization'})
            if path=='/api/jobs':return self.respond(202,jobs.submit(data.get('action'),data.get('take_id'),data.get('request_id')))
            if path=='/api/delete-take':return self.respond(202,jobs.submit('delete',data.get('take_id'),data.get('request_id'),confirmation=data.get('confirmation')))
            if path=='/api/recover':return self.respond(202,jobs.recover(data.get('id')))
            if path=='/api/open-resolve':
                take=next((t for t in jobs.local_takes() if t['id']==data.get('take_id')),None)
                if not take or not (take.get('import_status') or {}).get('ok'):
                    raise ValueError('No completed local Resolve import for this take')
                # Launch only: never switch projects or replay a cached import.
                subprocess.run(['open','-a','/Applications/DaVinci Resolve.app'],check=True,timeout=10)
                return self.respond(200,{'ok':True})
            if path=='/api/reveal':
                take_id=data.get('take_id')
                take=next((t for t in jobs.local_takes() if t['id']==take_id),None)
                if not take:raise ValueError('Unknown local take')
                subprocess.run(['open',take['path']],check=True,timeout=10)
                return self.respond(200,{'ok':True})
            return self.respond(404,{'error':'Not found'})
        except (ValueError,KeyError,TypeError) as e:self.respond(400,{'error':str(e)[:400]})
        except RuntimeError as e:self.respond(409,{'error':str(e)[:400]})
        except Exception as e:self.respond(500,{'error':str(e)[:400]})


class PreviewExpiryServer(ThreadingHTTPServer):
    def service_actions(self):
        # Local cache only: expiry continues even after the browser closes.
        jobs.preview_info()


def make_server(port=8768,token=None):
    server=PreviewExpiryServer(('127.0.0.1',port),Handler)
    port=server.server_address[1];server.hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    server.token=token or secret();server.csrf=hashlib.sha256((server.token+':csrf').encode()).hexdigest()
    return server


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8768);args=parser.parse_args()
    jobs.clear_previews()
    server=make_server(args.port)
    print('Phone dashboard listening at http://127.0.0.1:'+str(server.server_address[1]),flush=True)
    server.serve_forever()
