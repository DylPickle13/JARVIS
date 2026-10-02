import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import iphone_api as api


class IphoneApiTests(unittest.TestCase):
    def test_rejects_unapproved_mutation(self):
        with self.assertRaises(ValueError):
            api.request('/control/api/v1/media/devices/local/doformat', 'PUT', {})

    def test_rejects_unknown_or_recording_state(self):
        for state in (None, True):
            with self.subTest(state=state), patch.object(api, 'read_json', return_value={'recording':state}), patch.object(api, 'request') as send:
                with self.assertRaises(RuntimeError):
                    api.setup_4k30()
                send.assert_not_called()

    def test_format_setup_single_write_and_readback(self):
        before = {'offSpeedEnabled':False,'frameRate':'24','recordResolution':{'width':3840,'height':2160},'sensorResolution':{'width':3840,'height':2160},'codec':'HEVC'}
        after = {**before,'frameRate':'30'}
        with tempfile.TemporaryDirectory() as root, patch.object(api,'__file__',str(Path(root)/'iphone_api.py')), patch.object(api,'read_json',side_effect=[{'recording':False},before,{'videoFormats':['3840x2160p30']},{'recording':False},after,{'recording':False}]), patch.object(api,'request',return_value=(204,'')) as send:
            result = api.setup_4k30()
            self.assertTrue(result['ok'])
            self.assertFalse(result['clip_recorded'])
            send.assert_called_once_with('/control/api/v1/system/videoFormat','PUT',{'name':'3840x2160p30'})
            self.assertTrue((Path(root)/'iphone-before-4k30.json').exists())


if __name__ == '__main__':
    unittest.main()
