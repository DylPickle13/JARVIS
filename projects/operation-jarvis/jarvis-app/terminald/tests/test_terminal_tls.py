"""Real loopback TLS regression tests; no production credentials, tmux or sessions."""
import http.client
import ipaddress
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from terminald import jarvis_terminald as terminald


class TerminalTLSHandshakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="jarvis-test-tls-")
        cls.root = Path(cls.directory.name)
        config = cls.root / "openssl.cnf"
        config.write_text("""[req]
prompt = no
distinguished_name = dn
x509_extensions = extensions
[dn]
CN = localhost
[extensions]
basicConstraints = critical,CA:TRUE
keyUsage = critical,digitalSignature,keyEncipherment,keyCertSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
subjectAltName = DNS:localhost,IP:127.0.0.1
""")
        cls.cert = cls.root / "certificate.pem"
        cls.key = cls.root / "key.pem"
        subprocess.run([
            "/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-config", str(config), "-keyout", str(cls.key), "-out", str(cls.cert),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        cls.key.chmod(0o600)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(self.cert), str(self.key))
        self.service = mock.Mock(session_id=1)
        with mock.patch.object(terminald, "RUNTIME_DIR", self.root):
            self.server = terminald.TerminalHTTPServer(
                ("127.0.0.1", 0), self.service, "fixture-only-token",
                [ipaddress.ip_network("127.0.0.0/8")], ssl_context=context,
            )
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def health(self, authorized=True):
        context = ssl.create_default_context(cafile=str(self.cert))
        connection = http.client.HTTPSConnection("127.0.0.1", self.server.server_port,
                                                context=context, timeout=1)
        try:
            headers = {"Authorization": "Bearer fixture-only-token"} if authorized else {}
            connection.request("GET", "/health", headers=headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, data
        finally:
            connection.close()

    def test_partial_tls_client_does_not_block_another_authenticated_connection(self):
        with mock.patch.object(terminald, "TLS_HANDSHAKE_TIMEOUT_SECONDS", 2.0):
            stalled = socket.create_connection(self.server.server_address, timeout=1)
            self.addCleanup(stalled.close)
            stalled.sendall(b"\x16\x03\x01\x00")  # deliberately incomplete TLS record
            time.sleep(0.05)
            self.assertNotIsInstance(self.server.socket, ssl.SSLSocket,
                                     "TLS accept must not run on the listener thread")
            status, data = self.health()
            self.assertEqual(status, 200)
            self.assertIn(b'"ok":true', data)
            self.service.frame_after.assert_not_called()
            self.service.send_input.assert_not_called()

    def test_stalled_handshake_is_closed_at_deadline(self):
        with mock.patch.object(terminald, "TLS_HANDSHAKE_TIMEOUT_SECONDS", 0.15):
            stalled = socket.create_connection(self.server.server_address, timeout=1)
            self.addCleanup(stalled.close)
            stalled.sendall(b"\x16\x03\x01\x00")
            stalled.settimeout(1)
            try:
                self.assertEqual(stalled.recv(1), b"")
            except ConnectionResetError:
                pass  # closure may be FIN or RST depending on the TLS implementation
            self.assertEqual(self.health()[0], 200)

    def test_tls_still_requires_bearer_authentication(self):
        status, data = self.health(authorized=False)
        self.assertEqual(status, 401)
        self.assertIn(b'"ok":false', data)
        self.assertEqual(self.health()[0], 200)

    def test_plain_http_cannot_bypass_tls(self):
        connection = socket.create_connection(self.server.server_address, timeout=1)
        self.addCleanup(connection.close)
        connection.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        try:
            self.assertEqual(connection.recv(100), b"")
        except ConnectionResetError:
            pass
        self.assertEqual(self.health()[0], 200)

    def test_handshake_timeout_does_not_change_established_request_semantics(self):
        raw = mock.Mock()
        secure = mock.Mock()
        context = mock.Mock()
        context.wrap_socket.return_value = secure
        self.server.ssl_context = context
        with mock.patch.object(terminald.ThreadingHTTPServer, "process_request_thread") as handle:
            self.server.process_request_thread(raw, ("127.0.0.1", 12345))
        context.wrap_socket.assert_called_once_with(raw, server_side=True, do_handshake_on_connect=False)
        secure.do_handshake.assert_called_once_with()
        self.assertEqual(secure.settimeout.call_args_list,
                         [mock.call(terminald.TLS_HANDSHAKE_TIMEOUT_SECONDS), mock.call(None)])
        handle.assert_called_once_with(secure, ("127.0.0.1", 12345))
