#!/usr/bin/env python3
"""Opt-in spoofed-discovery test: wrong TLS cert must receive zero HTTP requests.
Temporarily replaces ONLY the monitor relay, and restores it in finally.
Run only with a paired, enabled, externally powered handset on home Wi-Fi.
"""
import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Server, advertise


class Trap(Server):
    rejected = 0
    http_requests = 0

    def get_request(self):
        try:
            return super().get_request()
        except ssl.SSLError:
            self.rejected += 1
            raise

    def finish_request(self, request, address):
        self.http_requests += 1
        super().finish_request(request, address)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--confirm-phone-discovery-test', action='store_true', required=True)
    p.add_argument('--private-dir', type=Path, required=True)
    a = p.parse_args()
    root = a.private_dir
    config = json.loads((root / 'server.json').read_text())
    if config.get('discovery') is not True:
        raise SystemExit('Enable discovery first.')
    domain = 'gui/' + str(os.getuid())
    label = 'com.jarvis.android-monitor'
    plist = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    with tempfile.TemporaryDirectory(prefix='jarvis-pin-test-') as tmp:
        tmp = Path(tmp)
        # Valid certificate with the SAME SAN, but a different key/fingerprint.
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-days', '1', '-config', str(root / 'openssl.cnf'),
                        '-keyout', str(tmp / 'key'), '-out', str(tmp / 'cert')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(tmp / 'cert', tmp / 'key')
        server = thread = publisher = None
        subprocess.run(['launchctl', 'bootout', domain + '/' + label], check=True)
        try:
            for attempt in range(10):
                try:
                    server = Trap(('0.0.0.0', config['port']), ctx, config['token'],
                                  lambda: {'version': 1, 'state': 'unknown', 'ageSeconds': None})
                    break
                except OSError as exc:
                    if exc.errno != 48 or attempt == 9: raise
                    time.sleep(1)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            # Spoof the legitimate PUBLIC discovery name, never its certificate.
            publisher = advertise(root, config['port'])
            time.sleep(50)
            if publisher.poll() is not None:
                raise AssertionError('Discovery publisher exited')
            if server.rejected < 2 or server.http_requests != 0:
                raise AssertionError('Expected repeated TLS rejection and zero HTTP requests')
            print('Spoofed discovery: TLS rejected repeatedly; zero HTTP requests/credentials received.')
        finally:
            if publisher:
                publisher.terminate()
                try: publisher.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    publisher.kill(); publisher.wait()
            if server:
                if thread: server.shutdown()
                server.server_close()
            if thread: thread.join(timeout=5)
            subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
            print('Production monitor relay restored.')


if __name__ == '__main__':
    main()
