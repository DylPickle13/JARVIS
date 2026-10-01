"""Offline lighting regressions: no LAN access or device writes."""
import copy
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from security_cli import ControlError, _execute_once, inventory, operate, parser
from security_lighting import pattern, segment_write


def feature(kind, value, choices=None, minimum=0, maximum=100):
    f = NS(type=NS(name=kind), value=value, choices=choices,
           minimum_value=minimum, maximum_value=maximum,
           container=NS(_last_update_error=None, disabled=False, _last_update_time=123))
    async def set_value(value):
        f.value = value
    f.set_value = AsyncMock(side_effect=set_value)
    return f


def device(features=None):
    return NS(features=features or {}, modules={}, sys_info={},
              protocol=NS(query=AsyncMock()), update=AsyncMock(), disconnect=AsyncMock(),
              model='L930', device_type=NS(value='lightstrip'),
              _components={'segment': 1, 'segment_effect': 1})


class LightingTests(unittest.IsolatedAsyncioTestCase):
    async def test_temperature_and_legacy_alias(self):
        for name in ('color_temp', 'color_temperature'):
            f = feature('Number', 3500, minimum=2500, maximum=6500)
            d = device({'color_temperature': f})
            result = await operate(d, 'L930-5', 'set', name, '4000')
            self.assertEqual(result, {'result': 'verified', 'setting': name, 'value': 4000})
            f.set_value.assert_awaited_once_with(4000)
            d.update.assert_awaited_once_with(update_children=False)
            self.assertIn('color_temperature', inventory(d, 'L930-5'))

    async def test_temperature_rejects_bounds_and_active_effect(self):
        for text in ('0', '2499', '6501', 'NaN'):
            f = feature('Number', 3500, minimum=2500, maximum=6500)
            with self.assertRaises(ControlError):
                await operate(device({'color_temperature': f}), 'L930-5', 'set', 'color_temp', text)
            f.set_value.assert_not_awaited()
        for key in ('lighting_effect', 'segment_effect'):
            d = device({'color_temperature': feature('Number', 3500, minimum=2500, maximum=6500)})
            d.sys_info[key] = {'enable': 1}
            self.assertEqual((await operate(d, 'L930-5', 'set', 'color_temp', '3500'))['result'], 'readback_mismatch')

    async def test_real_sdk_temperature_feature_id(self):
        from kasa.smart import SmartDevice
        from kasa.smart.modules.colortemperature import ColorTemperature
        d = SmartDevice('127.0.0.1')  # construction only; no connection
        module = ColorTemperature(d, 'color_temperature')
        module._initialize_features()
        self.assertIn('color_temperature', module._module_features)
        self.assertNotIn('color_temp', module._module_features)

    async def test_named_effects_identity_not_just_name(self):
        from kasa.smart.effects import EFFECT_MAPPING
        for effect in (*EFFECT_MAPPING, 'Off'):
            for mismatch in (False, True):
                f = feature('Choice', 'Off', choices=[*EFFECT_MAPPING, 'Off'])
                d = device({'light_effect': f})
                async def update(**kwargs):
                    d.sys_info['lighting_effect'] = ({'enable': 0 if not mismatch else 1}
                        if effect == 'Off' else {'enable': 1, 'name': effect,
                            'id': 'wrong' if mismatch else EFFECT_MAPPING[effect]['id']})
                d.update.side_effect = update
                result = await operate(d, 'L930-5', 'set', 'light_effect', effect)
                self.assertEqual(result['result'], 'readback_mismatch' if mismatch else 'verified')
                f.set_value.assert_awaited_once_with(effect)

    async def test_effect_unknown_and_unhealthy_do_not_write(self):
        f = feature('Choice', 'Off', choices=['Off', 'Aurora'])
        d = device({'light_effect': f})
        for text in ('not-real', 'Aurora; echo secret'):
            with self.assertRaises(ControlError):
                await operate(d, 'L930-5', 'set', 'light_effect', text)
        f.container.disabled = True
        with self.assertRaises(ControlError):
            await operate(d, 'L930-5', 'set', 'light_effect', 'Aurora')
        f.set_value.assert_not_awaited()

    async def test_effect_brightness_preserves_identity(self):
        for changed in (False, True):
            f = feature('Choice', 'Aurora', choices=['Aurora', 'Off'])
            d = device({'light_effect': f})
            d.sys_info['lighting_effect'] = {'id': 'effect-id', 'enable': 1, 'brightness': 90}
            async def change(value):
                d.sys_info['lighting_effect']['brightness'] = value
                if changed:
                    d.sys_info['lighting_effect']['id'] = 'other'
            f.container.set_brightness = AsyncMock(side_effect=change)
            result = await operate(d, 'L930-5', 'set', 'effect_brightness', '25')
            self.assertEqual(result['result'], 'readback_mismatch' if changed else 'verified')
            f.container.set_brightness.assert_awaited_once_with(25)
            f.set_value.assert_not_awaited()
        d.sys_info['lighting_effect']['enable'] = 0
        with self.assertRaisesRegex(ControlError, 'active_lighting_effect_required'):
            await operate(d, 'L930-5', 'set', 'effect_brightness', '25')

    async def test_transition_features_and_ranges(self):
        for name, kind, text, expected in (
                ('smooth_transitions', 'Switch', 'on', True),
                ('smooth_transition_on', 'Number', '4', 4),
                ('smooth_transition_off', 'Number', '0', 0)):
            f = feature(kind, False if kind == 'Switch' else 0, maximum=60)
            d = device({name: f})
            self.assertEqual((await operate(d, 'L930-5', 'set', name, text))['value'], expected)
            with self.assertRaises(ControlError):
                await operate(d, 'L930-5', 'set', name, '61')
            self.assertEqual(f.set_value.await_count, 1)

    def test_pattern_validation(self):
        good = {'type': 'none', 'colors': [[0, 100, 50]], 'brightness': 50}
        self.assertEqual(pattern(json.dumps(good)), good)
        invalid = [None, [], {}, {**good, 'host': 'private'}, {**good, 'type': 'arbitrary'},
                   {**good, 'brightness': True}, {**good, 'brightness': 0},
                   {**good, 'colors': []}, {**good, 'colors': [[361, 50, 50]]},
                   {**good, 'colors': [[0, True, 50]]}, {**good, 'colors': [[0, 50]]},
                   {**good, 'colors': [[0, 50, 50]] * 51}]
        for value in invalid:
            with self.assertRaises(ControlError):
                pattern(json.dumps(value))
        for text in ('x' * 4097, '{"type":"none","type":"breathe"}', 'NaN'):
            with self.assertRaises(ControlError):
                pattern(text)

    async def test_segment_single_write_exact_readback(self):
        for fail in ('none', 'summary', 'mismatch', 'timeout', 'getter', 'count', 'summary_preflight'):
            d = device()
            saved = {}
            async def query(request):
                if 'get_device_segment' in request:
                    if fail == 'getter':
                        raise ValueError('PRIVATE')
                    return {'get_device_segment': {'segment': 0 if fail == 'count' else 50},
                            'get_segment_effect_rule': ({'enable': 0} if fail == 'summary_preflight' else
                                {'enable': 0, 'brightness': 50, 'custom': 1, 'id': 'old',
                                 'segments': [50], 'states': [[0,100,50,0]], 'type': 'none'})}
                if 'apply_segment_effect_rule' in request:
                    saved.update(copy.deepcopy(request['apply_segment_effect_rule']))
                    if fail == 'timeout':
                        raise TimeoutError('PRIVATE')
                    return {}
                actual = copy.deepcopy(saved)
                if fail == 'summary':
                    actual.pop('states')
                if fail == 'mismatch':
                    actual['brightness'] = 1
                return {'get_segment_effect_rule': actual}
            d.protocol.query.side_effect = query
            progress = {}
            text = '{"type":"none","colors":[[0,100,50],[240,100,50]],"brightness":50}'
            if fail in ('timeout', 'getter', 'count', 'summary_preflight'):
                with self.assertRaises((ControlError, ValueError, TimeoutError)):
                    await segment_write(d, text, progress)
            else:
                result = await segment_write(d, text, progress)
                self.assertEqual(result['result'], 'verified' if fail == 'none' else 'readback_mismatch')
            writes = [c for c in d.protocol.query.call_args_list if 'apply_segment_effect_rule' in c.args[0]]
            self.assertEqual(len(writes), 0 if fail in ('getter', 'count', 'summary_preflight') else 1)
            self.assertEqual(bool(progress.get('write_started')), fail not in ('getter', 'count', 'summary_preflight'))
            if saved:
                self.assertEqual(saved['segments'], [50])
                self.assertEqual(saved['states'], [[0,100,50,0],[240,100,50,0]])

    async def test_execute_gates_and_unknown_outcome_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / 'registry.json'
            registry.write_text(json.dumps({'led-strip': {'model': 'L930-5', 'host': '192.168.1.2'}}))
            d = device({'light_effect': feature('Choice', 'Off', choices=['Aurora'])})
            d.protocol.query.return_value = {'get_device_info': {'model': 'L930'}}
            d.features['light_effect'].set_value.side_effect = TimeoutError('PRIVATE')
            with patch('kasa.Discover.discover_single', new=AsyncMock(return_value=d)) as discover, \
                 patch('security_cli.device_lock', return_value=nullcontext()), \
                 patch('security_cli.load_settings', return_value=NS(username='u', password='p')):
                for args in ({'name': 'segment_effect', 'value': '{}', 'confirm': True},
                             {'name': 'effect', 'value': 'Aurora', 'confirm': False},
                             {'name': 'effect', 'value': 'Aurora', 'confirm': True, 'experimental': True}):
                    with self.assertRaises(ControlError):
                        await _execute_once('led-strip', 'light-set', registry_path=registry, **args)
                discover.assert_not_awaited()
                with self.assertRaisesRegex(ControlError, '^write_outcome_unknown$'):
                    await _execute_once('led-strip', 'light-set', name='effect', value='Aurora',
                                        confirm=True, registry_path=registry)
                discover.assert_awaited_once()
                d.features['light_effect'].set_value.assert_awaited_once()
                d.disconnect.assert_awaited_once()

    def test_stale_effect_inventory_stays_unknown(self):
        f = feature('Choice', 'Aurora', choices=['Aurora', "Grandma's Christmas Lights"])
        d = device({'light_effect': f})
        d.sys_info['lighting_effect'] = {'brightness': 50, 'enable': 1}
        self.assertIn("Grandma's Christmas Lights", inventory(d, 'L930-5')['light_effect']['choices'])
        f.container.disabled = True
        self.assertEqual(inventory(d, 'L930-5')['effect_brightness'], {'status': 'unknown'})

    def test_cli_preflight_error_is_sanitized_without_network(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / 'registry.json'
            registry.write_text(json.dumps({'strip': {'model': 'L930-5', 'host': '192.168.1.2'}}))
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('security_cli.py')),
                '--json', '--registry', str(registry), 'light-set', 'strip', 'segment_effect',
                '{"PRIVATE":"SECRET"}', '--experimental', '--confirm'],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['reason'], 'invalid_segment_effect')
            self.assertNotIn('SECRET', result.stdout + result.stderr)

    def test_parser_experimental_explicit(self):
        args = parser().parse_args(['light-set', 'led-strip', 'segment_effect', '{}', '--confirm', '--experimental'])
        self.assertTrue(args.experimental)
        self.assertFalse(parser().parse_args(['light-set', 'led-strip', 'state', 'on']).experimental)


if __name__ == '__main__':
    unittest.main()
