import http.client
import json
import math
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import sanitize, Server


class Sanitization(unittest.TestCase):
    def payload(self, **changes):
        p = {'zone': 'basement', 'stale': False, 'state': 'nearby', 'ageSeconds': 2}
        p.update(changes)
        return {'ok': True, 'presence': p}

    def test_good_and_only_minimal_fields(self):
        self.assertEqual(sanitize(self.payload()), {'version': 1, 'state': 'nearby', 'ageSeconds': 2})
        self.assertEqual(sanitize(self.payload(state='away'))['state'], 'away')

    def test_bad_inputs_unknown(self):
        for p in (None, [], {}, {'ok': False}, {'ok': True, 'presence': []}):
            self.assertEqual(sanitize(p)['state'], 'unknown')
        for patch in ({'stale': True}, {'stale': 0}, {'zone': 'living room'}, {'ageSeconds': -1},
                      {'ageSeconds': 16}, {'ageSeconds': None}, {'ageSeconds': True},
                      {'ageSeconds': math.nan}, {'ageSeconds': math.inf}, {'state': 'bad'}):
            with self.subTest(patch=patch):
                self.assertEqual(sanitize(self.payload(**patch))['state'], 'unknown')

    def test_fetch_latency_counts(self):
        self.assertEqual(sanitize(self.payload(ageSeconds=14), 2)['state'], 'unknown')


class Endpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=localhost', '-keyout', str(root/'key'), '-out', str(root/'cert')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(root/'cert', root/'key')
        cls.server = Server(('127.0.0.1', 0), tls, 'test-token', lambda: sanitize({'ok': True,
            'presence': {'zone': 'basement', 'state': 'away', 'stale': False, 'ageSeconds': 1}}))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.tmp.cleanup()

    def request(self, token=None, path='/v1/presence', method='GET'):
        # Local test certificate only; production Android uses pinned TLS + hostname checks.
        c = http.client.HTTPSConnection('127.0.0.1', self.server.server_port, context=ssl._create_unverified_context(), timeout=3)
        try:
            c.request(method, path, headers={} if token is None else {'Authorization': token})
            r = c.getresponse()
            return r.status, r.getheader('Cache-Control'), r.read()
        finally: c.close()

    def test_auth_required(self):
        for token in (None, 'Bearer wrong'):
            self.assertEqual(self.request(token)[0], 401)

    def test_valid_no_store(self):
        code, cache, body = self.request('Bearer test-token')
        self.assertEqual(code, 200); self.assertEqual(cache, 'no-store')
        self.assertEqual(json.loads(body), {'version': 1, 'state': 'away', 'ageSeconds': 1})

    def test_no_proxy_or_write_routes(self):
        self.assertEqual(self.request('Bearer test-token', '/api/v1/state')[0], 404)
        self.assertEqual(self.request('Bearer test-token', method='POST')[0], 501)


if __name__ == '__main__': unittest.main()
