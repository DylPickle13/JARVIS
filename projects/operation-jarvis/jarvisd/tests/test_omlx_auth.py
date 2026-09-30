import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from test_jarvisd import jarvisd
from jarvisd_core.omlx_auth import AdminSessions


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = Path(self.temp.name) / 'key'
        self.key.write_text('PRIVATE-fixture-key')
        self.key.chmod(0o600)
        self.now = [100]
        self.sessions = AdminSessions(now=lambda: self.now[0])

    def test_cache_renewal_rejection_and_host_isolation(self):
        with mock.patch.object(self.sessions, '_login', return_value='omlx_admin_session=PRIVATE') as login:
            for _ in range(10):
                self.sessions.cookie('127.0.0.1', str(self.key))
            self.assertEqual(login.call_count, 1)
            self.sessions.cookie('192.168.21.30', str(self.key))
            self.assertEqual(login.call_count, 2)
            self.now[0] += 31
            self.sessions.invalidate('127.0.0.1', str(self.key))
            self.sessions.cookie('127.0.0.1', str(self.key))
            self.assertEqual(login.call_count, 3)
            self.now[0] += 12 * 3600
            self.sessions.cookie('127.0.0.1', str(self.key))
            self.assertEqual(login.call_count, 4)

    def test_private_file_validation(self):
        self.assertEqual(self.sessions._key(self.key), 'PRIVATE-fixture-key')
        self.key.chmod(0o644)
        with self.assertRaises(ValueError): self.sessions._key(self.key)
        self.key.chmod(0o600)
        link = self.key.parent / 'link'
        link.symlink_to(self.key)
        with self.assertRaises(OSError): self.sessions._key(link)
        for value in ['', 'a b c', 'x' * 4097, 'bad\nheader']:
            self.key.write_text(value)
            with self.assertRaises(ValueError): self.sessions._key(self.key)

    def test_invalid_hosts_never_login(self):
        with mock.patch.object(self.sessions, '_login') as login:
            for host in ['8.8.8.8', 'example.com', '0.0.0.0', '224.0.0.1']:
                with self.assertRaises(ValueError): self.sessions.cookie(host, str(self.key))
            login.assert_not_called()

    def test_failure_cooldown_and_single_flight(self):
        with mock.patch.object(self.sessions, '_login', side_effect=ValueError('fixture')) as login:
            for _ in range(10):
                with self.assertRaises(ValueError): self.sessions.cookie('127.0.0.1', str(self.key))
            self.assertEqual(login.call_count, 1)
            self.now[0] += 31
            with self.assertRaises(ValueError): self.sessions.cookie('127.0.0.1', str(self.key))
            self.assertEqual(login.call_count, 2)
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            release.wait(2)
            return 'omlx_admin_session=fixture'
        self.now[0] += 31
        with mock.patch.object(self.sessions, '_login', side_effect=slow) as login:
            thread = threading.Thread(target=lambda: self.sessions.cookie('127.0.0.1', str(self.key)))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(ValueError): self.sessions.cookie('127.0.0.1', str(self.key))
                self.assertEqual(login.call_count, 1)
            finally:
                release.set()
                thread.join(2)

    def test_login_is_bounded_fixed_path_no_redirect_and_cookie_allowlist(self):
        for status in [200, 302, 401, 500]:
            connection = mock.MagicMock()
            response = connection.getresponse.return_value
            response.status = status
            response.read.return_value = b'{"success":true}'
            response.getheader.return_value = 'other=ignored; Path=/, omlx_admin_session=fixture; HttpOnly'
            with mock.patch('jarvisd_core.omlx_auth.http.client.HTTPConnection', return_value=connection):
                if status == 200:
                    self.assertEqual(self.sessions._login('127.0.0.1', 'PRIVATE'), 'omlx_admin_session=fixture')
                else:
                    with self.assertRaises(ValueError): self.sessions._login('127.0.0.1', 'PRIVATE')
            self.assertEqual(connection.request.call_args.args, ('POST', '/admin/api/login'))
            connection.request.assert_called_once()
            connection.close.assert_called_once()

    def test_dashboard_authentication_failure_is_safe_and_invalidates_session(self):
        from test_omlx_status import OMLXTests
        connection = OMLXTests().fake_connection(401)
        env = {'JARVISD_OMLX_16_API_KEY_FILE': str(self.key)}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch(
                'jarvisd_core.omlx_auth.ADMIN_SESSIONS') as sessions, mock.patch.object(
                jarvisd.http.client, 'HTTPConnection', return_value=connection):
            sessions.cookie.return_value = 'omlx_admin_session=PRIVATE'
            result = jarvisd._omlx_collect('mac-mini-16')
            self.assertEqual(result, {'ok': False, 'error': 'Authentication required.'})
            sessions.invalidate.assert_called_once_with('192.168.21.30', str(self.key))
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertEqual(connection.request.call_args.kwargs['headers']['Cookie'], 'omlx_admin_session=PRIVATE')
