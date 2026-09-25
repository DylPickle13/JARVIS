import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import activate_bridge as activate
import cycle


class ActivationTests(unittest.TestCase):
    def test_refuses_unavailable_or_pending_bridge_without_restart(self):
        for pending, available in ((True, True), (False, False)):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                with patch.object(activate, 'ROOT', root), patch.object(cycle, 'RUNTIME', root / 'state'), \
                     patch.object(activate.bridge_client, 'request', return_value=dict(pending=pending, device_available=available, lighting_readback=False)), \
                     patch.object(activate.subprocess, 'run') as restart, patch('sys.argv', ['activate', '--activate']):
                    with self.assertRaises(SystemExit): activate.main()
                    self.assertFalse((root / 'transport.json').exists())
                    restart.assert_not_called()

    def test_refuses_local_uncertainty_without_contacting_bridge(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            state = cycle.initial(); state['pending'] = True
            cycle.Store(root / 'state').save('state.json', state)
            with patch.object(activate, 'ROOT', root), patch.object(cycle, 'RUNTIME', root / 'state'), \
                 patch.object(activate.bridge_client, 'request') as request, patch('sys.argv', ['activate', '--activate']):
                with self.assertRaises(SystemExit): activate.main()
                request.assert_not_called()

    def test_bootstrap_is_explicit_and_does_not_spawn_a_second_process(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(activate, 'ROOT', root), patch.object(cycle, 'RUNTIME', root / 'state'), \
                 patch.object(activate.bridge_client, 'request', return_value=dict(pending=False, device_available=True, lighting_readback=False)), \
                 patch.object(activate.subprocess, 'run') as start, \
                 patch('sys.argv', ['activate', '--activate', '--bootstrap-watcher']), \
                 contextlib.redirect_stdout(io.StringIO()):
                start.return_value.returncode = 0
                activate.main()
                start.assert_called_once()
                self.assertEqual(start.call_args.args[0][:2], ['launchctl', 'bootstrap'])

    def test_activation_preserves_safety_state_and_only_checks_status(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            state = cycle.initial()
            cycle.Store(root / 'state').save('state.json', state)
            with patch.object(activate, 'ROOT', root), patch.object(cycle, 'RUNTIME', root / 'state'), \
                 patch.object(activate.bridge_client, 'request', return_value=dict(pending=False, device_available=True, lighting_readback=False)) as request, \
                 patch.object(activate.subprocess, 'run') as restart, patch('sys.argv', ['activate', '--activate']), \
                 contextlib.redirect_stdout(io.StringIO()):
                restart.return_value.returncode = 0
                activate.main()
                request.assert_called_once_with('status')
                restart.assert_called_once()
            self.assertEqual(json.loads((root / 'transport.json').read_text()), {'backend': 'karabiner'})
            self.assertEqual(cycle.Store(root / 'state').load('state.json', None), state)
