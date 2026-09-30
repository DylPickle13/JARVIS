import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock

import security_cli as cli
import security_shared_status as shared


class SharedStatusTests(unittest.TestCase):
    def test_projection_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            now, tick = time.time(), time.monotonic()
            value = {'version': 1, 'observed_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                     'tick': tick, 'sensors': {'motion-sensor': {'model': 'T100', 'state': True},
                                             'door-sensor': {'model': 'T110', 'state': False}}}
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            for alias, feature, state in [('motion-sensor', 'motion_detected', True),
                                           ('door-sensor', 'is_open', False)]:
                result = shared.read(alias, path=path, now=now+1, tick=tick+1)
                self.assertEqual(result['result'], 'read_succeeded')
                self.assertIs(result['features'][feature]['value'], state)
                self.assertEqual(result['hub_snapshot_at'], value['observed_at'])
                self.assertEqual(result['radio_freshness'], 'unknown')
                self.assertIsNone(result['features']['battery_low']['value'])
                self.assertEqual(shared.read(alias, path=path, now=now+9, tick=tick+9)['reason'],
                                 'shared_snapshot_unavailable')
            path.unlink()
            self.assertEqual(shared.read('door-sensor', path=path)['result'], 'error')

    def test_status_never_calls_direct_reader_even_when_unavailable(self):
        devices = {alias: {'model': model} for alias, model in shared.ALIASES.items()}
        with patch.object(cli, 'registry', return_value=devices), \
             patch.object(cli, '_execute_once', new_callable=AsyncMock) as direct, \
             patch.object(shared, 'read', return_value={'result': 'error', 'reason': 'shared_snapshot_unavailable'}) as read:
            for alias in shared.ALIASES:
                self.assertEqual(asyncio.run(cli.execute(alias, 'status'))['reason'], 'shared_snapshot_unavailable')
            self.assertEqual(read.call_count, 2)
            direct.assert_not_called()
            direct.return_value = {'result': 'read_succeeded'}
            asyncio.run(cli.execute('door-sensor', 'capabilities'))
            direct.assert_awaited_once()

    def test_registry_mismatch_fails_closed(self):
        with patch.object(cli, 'registry', return_value={'door-sensor': {'model': 'C230'}}), \
             patch.object(shared, 'read') as read:
            with self.assertRaises(cli.ControlError):
                asyncio.run(cli.execute('door-sensor', 'status'))
            read.assert_not_called()
