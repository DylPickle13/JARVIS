"""Offline recipient-selection regressions; no network, audio or credentials."""
import ast
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Tuple
import unittest
from unittest import mock
from uuid import UUID

HERE = Path(__file__).resolve().parent
PIN = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'
NAME = 'Example speaker'
HOST = '192.0.2.10'


def load_helper():
    spec = importlib.util.spec_from_file_location('cast_selection_test_helper', HERE / 'connect_chromecast.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    with mock.patch.dict(os.environ, {'OPERATION_JARVIS_CAST_SPEAKERS_UUID': PIN}, clear=True):
        spec.loader.exec_module(module)
    return module


helper = load_helper()


def cast(uuid=PIN, host=HOST, name=NAME):
    return SimpleNamespace(uuid=UUID(uuid), name=name, cast_info=SimpleNamespace(host=host),
                           disconnect=mock.Mock(), wait=mock.Mock())


class CastSelectionTests(unittest.TestCase):
    def sdk(self, listed=(), discovered=()):
        sdk = mock.Mock()
        sdk.get_listed_chromecasts.return_value = (list(listed), mock.Mock())
        sdk.get_chromecasts.return_value = (list(discovered), mock.Mock())
        return sdk

    def select(self, sdk, pin=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return helper.find_cast(sdk, NAME, HOST, 2, 2, expected_uuid=pin)

    def test_pinned_lookup_uses_uuid_not_collision_prone_name(self):
        physical = cast()
        sdk = self.sdk([physical])
        self.assertIs(self.select(sdk, PIN)[0], physical)
        kwargs = sdk.get_listed_chromecasts.call_args.kwargs
        self.assertEqual(kwargs['uuids'], [UUID(PIN)])
        self.assertNotIn('friendly_names', kwargs)
        sdk.get_chromecasts.assert_not_called()

    def test_same_named_group_cannot_win_pinned_selection(self):
        group, physical = cast(OTHER, '192.0.2.20'), cast()
        sdk = self.sdk([group, physical])
        self.assertIs(self.select(sdk, PIN)[0], physical)
        group.disconnect.assert_called_once()
        physical.disconnect.assert_not_called()

    def test_pinned_missing_never_falls_back(self):
        sdk = self.sdk([], [cast(OTHER)])
        self.assertIsNone(self.select(sdk, PIN)[0])
        sdk.get_chromecasts.assert_not_called()

    def test_pinned_wrong_uuid_is_discarded(self):
        wrong = cast(OTHER)
        sdk = self.sdk([wrong])
        self.assertIsNone(self.select(sdk, PIN)[0])
        wrong.disconnect.assert_called_once()
        sdk.get_chromecasts.assert_not_called()

    def test_pinned_wrong_name_fails_closed(self):
        wrong = cast(name='Another room')
        sdk = self.sdk([wrong])
        self.assertIsNone(self.select(sdk, PIN)[0])
        wrong.disconnect.assert_called_once()

    def test_pinned_identity_can_follow_address_drift_without_repersisting(self):
        same = cast(host='192.0.2.30')
        self.assertIs(self.select(self.sdk([same]), PIN)[0], same)

    def test_duplicate_pinned_matches_are_ambiguous(self):
        one, two = cast(), cast()
        sdk = self.sdk([one, two])
        self.assertIsNone(self.select(sdk, PIN)[0])
        one.disconnect.assert_called_once()
        two.disconnect.assert_called_once()
        sdk.get_chromecasts.assert_not_called()

    def test_invalid_pin_rejected_before_network(self):
        sdk = self.sdk()
        with self.assertRaises(ValueError):
            self.select(sdk, 'not-a-uuid')
        sdk.get_listed_chromecasts.assert_not_called()
        sdk.get_chromecasts.assert_not_called()

    def test_pinned_discovery_exception_never_falls_back(self):
        sdk = self.sdk()
        sdk.get_listed_chromecasts.side_effect = RuntimeError('offline fixture')
        self.assertIsNone(self.select(sdk, PIN)[0])
        sdk.get_chromecasts.assert_not_called()

    def test_unpinned_exact_name_and_host_still_work(self):
        selected = cast()
        sdk = self.sdk([selected])
        self.assertIs(self.select(sdk)[0], selected)
        sdk.get_chromecasts.assert_not_called()

    def test_unpinned_wrong_host_same_name_is_not_first_match(self):
        group, physical = cast(OTHER, '192.0.2.20'), cast()
        sdk = self.sdk([group], [group, physical])
        self.assertIs(self.select(sdk)[0], physical)
        sdk.get_listed_chromecasts.return_value[1].stop_discovery.assert_called_once()
        physical.disconnect.assert_not_called()

    def test_unpinned_wrong_name_at_host_is_not_accepted(self):
        wrong = cast(name='Wrong room')
        sdk = self.sdk([], [wrong])
        self.assertIsNone(self.select(sdk)[0])
        wrong.disconnect.assert_called_once()

    def test_unpinned_unrelated_first_device_refused(self):
        wrong = cast(OTHER, '192.0.2.20', 'Another device')
        self.assertIsNone(self.select(self.sdk([], [wrong]))[0])
        wrong.disconnect.assert_called_once()

    def test_unpinned_duplicate_exact_matches_refused(self):
        one, two = cast(), cast(OTHER)
        self.assertIsNone(self.select(self.sdk([], [one, two]))[0])
        one.disconnect.assert_called_once()
        two.disconnect.assert_called_once()

    def test_unpinned_discovery_exception_can_find_exact_host_and_name(self):
        selected = cast()
        sdk = self.sdk([], [selected])
        sdk.get_listed_chromecasts.side_effect = RuntimeError('offline fixture')
        self.assertIs(self.select(sdk)[0], selected)

    def test_optional_pin_loaded_and_retained_by_target_overrides(self):
        target = helper.resolve_target('speakers', host='192.0.2.99')
        self.assertEqual(target.uuid, PIN)
        self.assertEqual(target.host, '192.0.2.99')
        self.assertEqual(helper.TV_TARGET.uuid, '')

    def test_tv_adapter_forwards_pin_before_any_media_action(self):
        # Compile only this function, avoiding tv.py's real .env loader and network.
        tree = ast.parse((HERE / 'tv.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_connected_cast')
        selected, browser, sdk = cast(), mock.Mock(), mock.Mock()
        find = mock.Mock(return_value=(selected, browser))
        namespace = {'Any': Any, 'Tuple': Tuple, 'argparse': SimpleNamespace(Namespace=SimpleNamespace),
                     'apply_target_defaults': mock.Mock(return_value=SimpleNamespace(uuid=PIN)),
                     'import_pychromecast': mock.Mock(return_value=sdk), 'find_cast': find,
                     'stop_discovery': mock.Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(HERE / 'tv.py'), 'exec'), namespace)
        args = SimpleNamespace(skip_tcp_check=True, name=NAME, host=HOST, discovery_timeout=2, socket_timeout=2)
        self.assertEqual(namespace['get_connected_cast'](args), (sdk, selected, browser))
        self.assertEqual(find.call_args.kwargs['expected_uuid'], PIN)
        selected.wait.assert_called_once_with(timeout=2)

    def test_standalone_connector_forwards_pin(self):
        selected, browser = cast(), mock.Mock()
        with mock.patch.object(sys, 'argv', ['connect_chromecast.py', '--device', 'speakers', '--host', HOST, '--skip-tcp-check']), \
                mock.patch.object(helper, 'import_pychromecast', return_value=mock.Mock()), \
                mock.patch.object(helper, 'find_cast', return_value=(selected, browser)) as find, \
                mock.patch.object(helper, 'print_cast_summary'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(), 0)
        self.assertEqual(find.call_args.kwargs['expected_uuid'], PIN)
        selected.disconnect.assert_called_once()
        browser.stop_discovery.assert_called_once()


if __name__ == '__main__':
    unittest.main()
