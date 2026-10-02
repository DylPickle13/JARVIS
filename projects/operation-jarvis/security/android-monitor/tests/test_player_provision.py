import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('provision_player', ROOT / 'provision_player.py')
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


class PlayerProvisionTests(unittest.TestCase):
    def config(self, **changes):
        result = dict(version=1, host='192.168.40.12', port=554, path='/stream2',
                      username='camera@example.invalid', password='dummy:p@ss% word')
        result.update(changes)
        return result

    def test_valid(self):
        self.assertTrue(provision.validate(self.config()))

    def test_public_dns_and_loopback_rejected(self):
        for host in ('8.8.8.8', 'camera.example', '127.0.0.1', '::1', '169.254.1.1'):
            self.assertFalse(provision.validate(self.config(host=host)))

    def test_endpoint_rejected(self):
        for change in ({'port': 80}, {'path': '/admin'}, {'version': 2}):
            self.assertFalse(provision.validate(self.config(**change)))

    def test_credentials_bounded_and_no_control_characters(self):
        for value in ('', 'x'*257, 'dummy\n', 'dummy\x00'):
            self.assertFalse(provision.validate(self.config(password=value)))
        self.assertFalse(provision.validate(self.config(username='colon:user')))
        self.assertFalse(provision.validate({}))

    def test_viewer_isolation_and_permissions(self):
        root = ET.parse(ROOT / 'android/AndroidManifest.xml').getroot()
        ns = '{http://schemas.android.com/apk/res/android}'
        app = root.find('application')
        self.assertEqual(app.get(ns+'allowBackup'), 'false')
        self.assertEqual(app.get(ns+'debuggable'), 'false')
        viewer = next(n for n in app.findall('activity') if n.get(ns+'name') == '.ViewerActivity')
        self.assertEqual(viewer.get(ns+'exported'), 'false')
        self.assertEqual(viewer.get(ns+'process'), ':video')
        self.assertEqual(viewer.get(ns+'launchMode'), 'singleTask')
        permissions = {n.get(ns+'name') for n in root.findall('uses-permission')}
        self.assertEqual(permissions, {'android.permission.'+p for p in (
            'INTERNET','ACCESS_NETWORK_STATE','ACCESS_WIFI_STATE','WAKE_LOCK',
            'RECEIVE_BOOT_COMPLETED','DISABLE_KEYGUARD')})

    def test_dependency_lock(self):
        lock = json.loads((ROOT / 'player-dependencies.json').read_text())
        self.assertEqual(len(lock), len({x['name'] for x in lock}))
        for item in lock:
            self.assertEqual(Path(item['name']).name, item['name'])
            self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
            url = urlsplit(item['url'])
            self.assertEqual(url.scheme, 'https')
            self.assertIn(url.hostname, ('dl.google.com', 'repo.maven.apache.org'))
        self.assertEqual(sum(x['type']=='rtsp-sources' for x in lock), 1)
        self.assertEqual(sum(x['type']=='platform' for x in lock), 1)
        self.assertFalse(any('libvlc' in x['name'].lower() for x in lock))


if __name__ == '__main__':
    unittest.main()
