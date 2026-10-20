#!/usr/bin/env python3
"""Real URLSession redirect/pin/recovery tests; disposable loopback endpoints only."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading

root = Path(__file__).resolve().parents[2]
records = []
servers = []

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_): pass
    def handle_fixture(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        records.append((self.server.kind, self.server.code, self.command, self.path, body))
        if self.server.kind == 'redirect' and self.path != '/unapproved':
            self.send_response(self.server.code)
            # Exercise cross-origin and HTTPS-to-HTTP redirects; pinning must not
            # be relied on to stop a non-TLS destination after a trusted response.
            target = '/unapproved' if self.server.code == 307 else f'http://127.0.0.1:{receiver.server_port}/unapproved'
            self.send_header('Location', target)
            data = b''
        else:
            self.send_response(200)
            data = b'{"ok":true}'
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)
    do_GET = handle_fixture
    do_POST = handle_fixture

def serve(kind, code=200, context=None):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.kind, server.code = kind, code
    if context:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    servers.append(server)
    return server

with tempfile.TemporaryDirectory(prefix='jarvis-network-checks-') as temp:
    work = Path(temp)
    cert, key = work/'cert.pem', work/'key.pem'
    subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
    try:
        receiver = serve('unapproved')
        approved = serve('approved')
        routes = []
        for code in (301, 302, 303, 307, 308):
            http, https = serve('redirect', code), serve('redirect', code, context)
            routes.append(dict(status=code, http=f'http://127.0.0.1:{http.server_port}',
                               https=f'https://127.0.0.1:{https.server_port}'))
        (work/'Tests').mkdir()
        shutil.copy2(Path(__file__).with_name('NetworkRedirectChecks.swift'), work/'Tests')
        (work/'Package.swift').write_text('''// swift-tools-version:5.9
import PackageDescription
let package = Package(name: "NetworkRedirectChecks", platforms: [.macOS(.v13)],
    dependencies: [.package(path: ''' + json.dumps(str(root/'JARVISKit')) + ''')],
    targets: [.testTarget(name: "NetworkRedirectChecks", dependencies: [.product(name: "JARVISKit", package: "JARVISKit")], path: "Tests")])
''')
        env = dict(os.environ, JARVIS_TEST_ROUTES=json.dumps(routes), JARVIS_TEST_PIN=pin,
                   JARVIS_TEST_APPROVED=f'http://127.0.0.1:{approved.server_port}')
        result = subprocess.run(['swift', 'test', '--package-path', str(work)], env=env, timeout=180)
        assert not any(r[0] == 'unapproved' or r[3] == '/unapproved' for r in records), 'Redirect destination received a request'
        for code in (301, 302, 303, 307, 308):
            posts = [r for r in records if r[1] == code and r[2] == 'POST']
            assert len(posts) == 2, (code, 'Input/allocation must each be attempted exactly once')
        assert result.returncode == 0, 'Swift network checks failed'
        print('PASS: six real-transport checks; no request reached the unapproved origin; no POST replay.')
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
