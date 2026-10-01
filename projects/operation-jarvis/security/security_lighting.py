"""Bounded L930 controls. No credentials, networking setup or retry policy here.

Experimental segment payload shape follows tapo's SegmentEffect API. It is not
physical zone verification and must be explicitly opted into until commissioned.
"""
import json

ALIASES = {'color_temp': 'color_temperature', 'effect': 'light_effect'}
SETTINGS = {'state', 'brightness', 'hsv', 'color_temperature', 'color_temp',
            'light_effect', 'effect', 'effect_brightness', 'smooth_transitions',
            'smooth_transition_on', 'smooth_transition_off', 'segment_effect'}
SEGMENT_TYPES = ('none', 'circulating', 'breathe', 'chasing', 'flicker', 'bloom', 'stacking')


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def pattern(text):
    """Only a bounded palette, animation type and brightness; never arbitrary RPC."""
    from security_cli import ControlError
    try:
        if not isinstance(text, str) or len(text) > 4096:
            raise ValueError
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        data = json.loads(text, object_pairs_hook=unique)
        if (type(data) is not dict or set(data) != {'type', 'colors', 'brightness'}
                or data['type'] not in SEGMENT_TYPES
                or not integer(data['brightness'], 1, 100)
                or type(data['colors']) is not list or not 1 <= len(data['colors']) <= 50):
            raise ValueError
        for color in data['colors']:
            if (type(color) is not list or len(color) != 3
                    or not all(integer(v, 0, hi) for v, hi in zip(color, (360, 100, 100)))):
                raise ValueError
        return data
    except (ValueError, TypeError):
        raise ControlError('invalid_segment_effect') from None


def effects_idle(device):
    """Missing legacy effect fields are tolerated; explicit active effects are not."""
    return all(device.sys_info.get(key, {}).get('enable', 0) == 0
               for key in ('lighting_effect', 'segment_effect'))


async def refresh(device):
    for module in device.modules.values():
        module._last_update_time = None
    await device.update(update_children=False)


def mismatch():
    return {'result': 'readback_mismatch', 'outcome': 'unknown'}


async def effect_write(device, name, text, progress):
    """One SDK write; verify effect identity and brightness from fresh raw state."""
    from security_cli import ControlError, healthy_feature, parse_value
    feature = healthy_feature(device, 'light_effect')
    module = feature.container
    before = device.sys_info.get('lighting_effect', {})
    if name == 'effect_brightness':
        if (not isinstance(text, str) or not text.isascii() or not text.isdigit()
                or not 1 <= int(text) <= 100):
            raise ControlError('number_out_of_range')
        if before.get('enable') != 1 or not before.get('id'):
            raise ControlError('active_lighting_effect_required')
        desired = int(text)
        expected = {'enable': 1, 'id': before['id'], 'brightness': desired}
        progress['write_started'] = True
        await module.set_brightness(desired)
    else:
        desired = parse_value(feature, text)
        if desired == 'Off':
            expected = {'enable': 0}
        else:
            from kasa.smart.effects import EFFECT_MAPPING
            definition = EFFECT_MAPPING.get(desired)
            if definition is None:
                raise ControlError('unsupported_effect')
            expected = {'enable': 1, 'id': definition['id'], 'name': desired}
        progress['write_started'] = True
        await feature.set_value(desired)
    await refresh(device)
    healthy_feature(device, 'light_effect')
    actual = device.sys_info.get('lighting_effect', {})
    if any(type(actual.get(k)) is not type(v) or actual.get(k) != v for k, v in expected.items()):
        return mismatch()
    if device.sys_info.get('segment_effect', {}).get('enable', 0) != 0:
        return mismatch()
    return {'result': 'verified', 'setting': name, 'value': desired}


async def segment_write(device, text, progress):
    """Experimental pattern write, with preflight capability/readback support checks.

    Does not turn power on or issue a second write to disable competing effects.
    A mismatch/timeout is uncertain and must not trigger a replay or rollback.
    """
    from security_cli import ControlError
    data = pattern(text)
    components = getattr(device, '_components', {})
    if not all(components.get(key, 0) >= 1 for key in ('segment', 'segment_effect')):
        raise ControlError('unsupported_feature')
    # Require the getter to work BEFORE allowing the write.
    response = await device.protocol.query({'get_device_segment': None,
                                             'get_segment_effect_rule': None})
    count = response.get('get_device_segment', {}).get('segment')
    current = response.get('get_segment_effect_rule')
    keys = ('brightness', 'custom', 'enable', 'id', 'segments', 'states', 'type')
    if (not integer(count, 1, 50) or type(current) is not dict
            or not all(key in current for key in keys)):
        # Summary-only firmware cannot establish full readback support. Do not write.
        raise ControlError('segment_readback_unavailable')
    if len(data['colors']) > count:
        raise ControlError('invalid_segment_effect')
    states = [color + [0] for color in data['colors']]
    payload = {'brightness': data['brightness'], 'custom': 1, 'deviceType': 'strip',
               'display_colors': states, 'enable': 1, 'id': 'jarvis_segment_pattern',
               'name': 'JARVIS pattern', 'segments': [count], 'states': states,
               'type': data['type']}
    progress['write_started'] = True
    await device.protocol.query({'apply_segment_effect_rule': payload})
    response = await device.protocol.query({'get_segment_effect_rule': None})
    actual = response.get('get_segment_effect_rule', {})
    # Some firmware may return only a summary. That is NOT enough for verification.
    if any(json.dumps(actual.get(k), sort_keys=True) != json.dumps(payload[k], sort_keys=True)
           for k in keys):
        return mismatch()
    await refresh(device)
    if device.sys_info.get('lighting_effect', {}).get('enable', 0) != 0:
        return mismatch()
    return {'result': 'verified', 'setting': 'segment_effect', 'value': data,
            'verification_scope': 'device_configuration', 'physical_effect': 'not_verified',
            'experimental': True}
