import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import advertise, local_peer


class Discovery(unittest.TestCase):
    def test_only_loopback_and_rfc1918(self):
        for ip in ('127.0.0.1', '10.2.3.4', '172.16.0.1', '172.31.255.254', '192.168.21.120'):
            self.assertTrue(local_peer(ip), ip)
        for ip in ('8.8.8.8', '100.87.28.34', '169.254.1.1', '172.32.0.1', '0.0.0.0', '::1'):
            self.assertFalse(local_peer(ip), ip)

    @patch('server.subprocess.Popen')
    @patch('server.ssl.PEM_cert_to_DER_cert', return_value=b'public-certificate')
    def test_advertisement_has_only_public_identity(self, der, popen):
        root = Mock()
        root.__truediv__ = Mock(return_value=Mock(read_text=Mock(return_value='CERT')))
        advertise(root, 8794)
        name = 'JARVIS-' + hashlib.sha256(b'public-certificate').hexdigest()[:32]
        self.assertEqual(popen.call_args.args[0],
                         ['/usr/bin/dns-sd', '-R', name, '_jarvis-monitor._tcp', 'local.', '8794'])
        self.assertLessEqual(len(name.encode()), 63)


if __name__ == '__main__':
    unittest.main()
