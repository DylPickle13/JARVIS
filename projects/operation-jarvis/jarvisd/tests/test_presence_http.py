"""Presence reads must not inherit trusted-LAN authorization."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch
from jarvisd_core import presence
from jarvisd_core.control_http import ControlHTTPServer
from test_jarvisd import jarvisd as daemon


class PresenceHTTPTests(unittest.TestCase):
    def test_private_read(self):
        with patch.object(daemon, 'API_TOKEN', 'test-api'), patch.object(daemon, 'AUTH_MODE', 'trusted-network'), patch.object(presence, 'read_status', return_value=presence.unknown()) as read, patch.object(presence, 'read_living_room', return_value=presence.unknown(zone='living room')):
            server = ControlHTTPServer(('127.0.0.1', 0), daemon.Handler)
            server.local_control_token = 'test-local'
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            thread.start()
            try:
                for headers, expected in [({}, 401), ({'x-jarvis-token': 'wrong'}, 401),
                        ({'x-jarvis-token': 'test-api'}, 200),
                        ({'Authorization': 'Bearer test-local'}, 200),
                        ({'Authorization': 'Bearer test-local', 'Origin': 'https://evil.example'}, 403)]:
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    conn.request('GET', '/api/v1/presence', headers=headers)
                    reply = conn.getresponse()
                    self.assertEqual(reply.status, expected)
                    self.assertEqual(reply.getheader('Cache-Control'), 'no-store')
                    reply.read()
                    conn.close()
                self.assertEqual(read.call_count, 2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
