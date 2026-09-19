"""Offline bounds/completion checks for the experimental single-segment reader."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import archive_download_probe as probe


class FakeMedia:
    responses = []
    def __init__(self, **kwargs):
        self._writer = None
    async def start(self):
        pass
    async def close(self):
        pass
    async def transceive(self, payload):
        request = json.loads(payload)
        assert request['params']['method'] == 'get'
        assert set(request['params']) == {'method', 'download'}
        for item in self.responses:
            yield item


def video(data):
    return SimpleNamespace(mimetype='video/mp2t', plaintext=data)


def finished():
    return SimpleNamespace(mimetype='application/json', plaintext=json.dumps({
        'type': 'notification', 'params': {'event_type': 'stream_status', 'status': 'finished'}}).encode())


class ProbeTests(unittest.TestCase):
    def attempt(self, responses):
        hub = SimpleNamespace(host='synthetic.invalid', cloudPassword='synthetic',
                              superSecretKey='synthetic', getEncryptionMethod=lambda: None)
        with tempfile.TemporaryDirectory() as tmp, patch.object(probe, 'HttpMediaSession', FakeMedia), \
                patch.object(FakeMedia, 'responses', responses):
            output = Path(tmp) / 'test.ts'
            result = asyncio.run(probe.download(hub, {'mac': 'synthetic', 'device_id': 'synthetic'}, 1, 11, output))
            return result, output.read_bytes()

    def test_interval_bounds(self):
        with patch.object(probe.time, 'time', return_value=200000):
            probe.interval(199900, 199910)
            for start, end in [(199900, 199911), (199999, 200000), (100000, 100010), (199910, 199900)]:
                with self.assertRaises(ValueError):
                    probe.interval(start, end)

    def test_finished_nonempty_is_complete(self):
        result, data = self.attempt([video(b'video'), finished()])
        self.assertTrue(result['complete'])
        self.assertEqual(data, b'video')

    def test_early_end_is_not_complete(self):
        result, _ = self.attempt([video(b'video')])
        self.assertFalse(result['complete'])

    def test_empty_finished_is_not_complete(self):
        result, _ = self.attempt([finished()])
        self.assertFalse(result['complete'])

    def test_size_bound(self):
        with patch.object(probe, 'MAX_BYTES', 4), self.assertRaisesRegex(RuntimeError, 'size_limit'):
            self.attempt([video(b'12345')])


if __name__ == '__main__':
    unittest.main()
