import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ajazz
import bridge_client as bridge


class BridgeClientTests(unittest.TestCase):
    def response(self, status, code=0):
        return subprocess.CompletedProcess([], code, json.dumps({'status': status}), '')

    def test_success_sends_only_settings_once(self):
        with patch.object(bridge.subprocess, 'run', return_value=self.response('success')) as run:
            self.assertEqual(bridge.send(ajazz.report({'effect': 'ripples', 'color': '#9933FF'})), 65)
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[:2], [str(bridge.CLI), '--jarvis-ak820'])
        body = json.loads(args[2])
        self.assertEqual(body['settings']['rgb'], [153, 51, 255])
        self.assertEqual(body['settings']['effect'], 8)
        self.assertEqual(set(body), {'operation_type', 'action', 'id', 'sent_at', 'settings'})
        self.assertEqual(len(body['id']), 32)

    def test_failures_never_retry_or_fallback(self):
        cases = [(self.response('rejected', 2), False),
                 (self.response('blocked', 3), True),
                 (self.response('uncertain', 3), True),
                 (self.response('success', 1), True),
                 (subprocess.CompletedProcess([], 0, 'not json', ''), True),
                 (subprocess.CompletedProcess([], 0, '{}', ''), True)]
        for result, uncertain in cases:
            with self.subTest(result=result), patch.object(bridge.subprocess, 'run', return_value=result) as run:
                with self.assertRaises(bridge.BridgeError) as caught:
                    bridge.send(ajazz.report({}))
                self.assertEqual(caught.exception.uncertain, uncertain)
                run.assert_called_once()

    def test_timeout_is_uncertain_missing_binary_is_prewrite(self):
        for error, uncertain in [(subprocess.TimeoutExpired('cli', 6), True), (FileNotFoundError(), False)]:
            with patch.object(bridge.subprocess, 'run', side_effect=error) as run:
                with self.assertRaises(bridge.BridgeError) as caught:
                    bridge.request('apply', {})
                self.assertEqual(caught.exception.uncertain, uncertain)
                run.assert_called_once()

    def test_backend_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(bridge, 'ROOT', Path(d)):
            self.assertEqual(bridge.backend(), 'direct')
            p = Path(d) / 'transport.json'
            p.write_text('{"backend":"karabiner"}')
            self.assertEqual(bridge.backend(), 'karabiner')
            p.write_text('{"backend":"other"}')
            with self.assertRaises(ValueError): bridge.backend()

    def test_status_and_acknowledgment_do_not_send_settings(self):
        for action, status in [('status', 'ok'), ('acknowledge', 'acknowledged')]:
            with patch.object(bridge.subprocess, 'run', return_value=self.response(status)) as run:
                bridge.request(action)
                self.assertIsNone(json.loads(run.call_args.args[0][2])['settings'])
