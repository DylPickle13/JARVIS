"""D235 direct protocol adapter: fixed getters and confirmation-gated settings.

No arbitrary RPC, media capture, pairing, firmware operations or audible actions.
Transport is pytapo in the isolated archive worker. Never return raw responses.
"""
from dataclasses import dataclass
import re

from security_cli import ControlError, clean, load_settings, Settings


@dataclass(frozen=True)
class Setting:
    getter: str
    module: str
    section: str
    field: str
    kind: str = 'Switch'
    setter: str | None = None
    minimum: int = 0
    maximum: int = 100
    choices: tuple = ()


SPECS = {
    'privacy': Setting('getLensMaskConfig', 'lens_mask', 'lens_mask_info', 'enabled', setter='setLensMaskConfig'),
    'led': Setting('getLedStatus', 'led', 'config', 'enabled', 'Choice', 'setLedStatus', choices=('auto', 'off')),
    'battery_percent': Setting('getBatteryStatus', 'battery', 'status', 'battery_percent', 'Number'),
    'battery_low': Setting('getBatteryStatus', 'battery', 'status', 'low_battery', 'Boolean'),
    'battery_charging': Setting('getBatteryStatus', 'battery', 'status', 'battery_charging', 'Text'),
    'power_mode': Setting('getPowerMode', 'battery', 'power', 'mode', 'Text'),
    'battery_operating_mode': Setting('getBatteryOperatingMode', 'battery', 'operating', 'mode', 'Text'),
    'battery_power_save': Setting('getBatteryPowerSave', 'battery', 'power_save', 'enabled', 'Text'),
    'speaker_volume': Setting('getAudioConfig', 'audio_config', 'speaker', 'volume', 'Number', 'setSpeakerVolume'),
    'microphone_volume': Setting('getAudioConfig', 'audio_config', 'microphone', 'volume', 'Number', 'setMicrophoneVolume'),
    'microphone_mute': Setting('getAudioConfig', 'audio_config', 'microphone', 'mute', setter='setMicrophoneVolume'),
    'noise_cancelling': Setting('getAudioConfig', 'audio_config', 'microphone', 'noise_cancelling', setter='setMicrophoneVolume'),
    'record_audio': Setting('getAudioConfig', 'audio_config', 'record_audio', 'enabled', setter='setRecordAudio'),
    'pir_sensitivity': Setting('getPirSensitivity', 'pir', 'config', 'sensitivity', 'Number', 'setPirSensitivity', minimum=10),
    'night_vision_mode': Setting('getNightVisionModeConfig', 'image', 'switch', 'night_vision_mode', 'Text'),
    'ring_enabled': Setting('getRingStatus', 'ring', 'status', 'enabled'),
    'chime_schedule_enabled': Setting('getChimeRingPlan', 'chime_ring_plan', 'chn1_chime_ring_plan', 'enabled'),
    'clips_length': Setting('getClipsConfig', 'clips', 'config', 'clips_length', 'Number', maximum=120),
    'record_buffer': Setting('getClipsConfig', 'clips', 'config', 'record_buffer', 'Number'),
    'retrigger_time': Setting('getClipsConfig', 'clips', 'config', 'retrigger_time', 'Number'),
}
for _name, _getter, _module, _section in (
    ('motion', 'getDetectionConfig', 'motion_detection', 'motion_det'),
    ('person', 'getPersonDetectionConfig', 'people_detection', 'detection'),
    ('vehicle', 'getVehicleDetectionConfig', 'vehicle_detection', 'detection'),
    ('pet', 'getPetDetectionConfig', 'pet_detection', 'detection'),
    ('package', 'getPackageDetectionConfig', 'package_detection', 'detection'),
):
    _setter = 'set' + _getter[3:]
    SPECS[_name + '_detection'] = Setting(_getter, _module, _section, 'enabled', setter=_setter)
    # Motion uses a second label alongside numeric sensitivity. Do not infer a
    # safe partial write of that pair; expose motion sensitivity read-only.
    SPECS[_name + '_sensitivity'] = Setting(_getter, _module, _section,
        'digital_sensitivity' if _name == 'motion' else 'sensitivity', 'Number',
        None if _name == 'motion' else _setter, minimum=1)

WRITABLE = frozenset(name for name, spec in SPECS.items() if spec.setter)
EXTRA_READS = {
    'getAppComponentList': {'app_component': {'name': 'app_component_list'}},
    'getChimeCtrlList': {'chime_ctrl': {'get_paired_device_list': {}}},
    'getQuickRespList': {'quick_response': {}},
}
READ_METHODS = frozenset(s.getter for s in SPECS.values()) | set(EXTRA_READS) | {'getDeviceInfo', 'getRecordPlan', 'getHubStorage'}


def request_for(spec):
    # Audio getter must request all three sections, not an arbitrary field.
    sections = ['speaker', 'microphone', 'record_audio'] if spec.module == 'audio_config' else [spec.section]
    return {spec.module: {'name': sections}}


def decode(spec, response):
    try:
        value = response[spec.module][spec.section][spec.field]
    except (KeyError, TypeError):
        raise ControlError('feature_unavailable') from None
    if spec.kind == 'Switch':
        if value not in ('on', 'off'):
            raise ControlError('feature_unavailable')
        return value == 'on'
    if spec.kind == 'Boolean':
        if type(value) is not bool:
            raise ControlError('feature_unavailable')
        return value
    if spec.kind == 'Number':
        if type(value) is str and re.fullmatch(r'\d{1,4}', value):
            value = int(value)
        if type(value) is not int or not spec.minimum <= value <= spec.maximum:
            raise ControlError('feature_unavailable')
        return value
    if spec.kind == 'Choice' and value not in spec.choices:
        raise ControlError('feature_unavailable')
    if not isinstance(value, str) or clean(value) is None:
        raise ControlError('feature_unavailable')
    return value


def validate(command, name, value, confirm):
    if command in ('status', 'capabilities', 'identity'):
        return None
    if command == 'privacy':
        name = 'privacy'
    elif command != 'set':
        raise ControlError('unsupported_command')
    if confirm is not True:
        raise ControlError('confirmation_required')
    if name not in WRITABLE:
        raise ControlError('unsupported_setting')
    spec = SPECS[name]
    if spec.kind == 'Switch':
        if value not in ('on', 'off'):
            raise ControlError('expected_on_or_off')
        desired = value == 'on'
    elif spec.kind == 'Number':
        if not isinstance(value, str) or not re.fullmatch(r'\d{1,3}', value):
            raise ControlError('number_out_of_range')
        desired = int(value)
        if not spec.minimum <= desired <= spec.maximum:
            raise ControlError('number_out_of_range')
    elif spec.kind == 'Choice' and value in spec.choices:
        desired = value
    else:
        raise ControlError('invalid_feature_value')
    return name, desired


def make_client(host, settings, writable_method=None):
    from pytapo import Tapo
    from pytapo.const import MAX_LOGIN_RETRIES

    class Client(Tapo):
        def isSupportingPresets(self):
            return False

        def executeFunction(self, method, params, retry=False):
            if method not in READ_METHODS and method != writable_method:
                raise ControlError('unapproved_method')
            # retry=True prevents the upstream cruise-disable fallback.
            return super().executeFunction(method, params, retry=True)

        def performRequest(self, requestData, loginRetryCount=0):
            # No request replay after authentication/session errors, especially writes.
            return super().performRequest(requestData, loginRetryCount=MAX_LOGIN_RETRIES)

    client = Client(host, 'admin', settings.password, settings.password,
                    isKLAP=False, retryStok=False,
                    printDebugInformation=False, printWarnInformation=False)
    try:
        disable_transport_replays(client.transport)
    except Exception:
        client.close()
        raise
    return client


def disable_transport_replays(transport):
    # Pinned pytapo also retries beneath performRequest. Disable both layers on
    # this connection only, before any setter can be invoked.
    from importlib.metadata import version
    from pytapo.const import MAX_LOGIN_RETRIES
    from pytapo.transport.pytapo.pytapo import TRANSIENT_REQUEST_RETRIES
    if version('pytapo') != '3.4.19':
        raise ControlError('doorbell_dependency_unavailable')
    send = transport.send
    request = transport._request

    async def send_once(payload, retry=0):
        return await send(payload, retry=MAX_LOGIN_RETRIES)

    def request_once(method, url, **kwargs):
        kwargs['transientRetryCount'] = TRANSIENT_REQUEST_RETRIES
        kwargs['timeout'] = 5
        return request(method, url, **kwargs)

    transport.send = send_once
    transport._request = request_once


def snapshot(client):
    cache = {}
    features = {}
    for name, spec in SPECS.items():
        if spec.getter not in cache:
            try:
                cache[spec.getter] = client.executeFunction(spec.getter, request_for(spec))
            except Exception:
                cache[spec.getter] = None
        row = {'type': spec.kind, 'writable': False, 'control_verification': 'not_assessed'}
        try:
            row.update(value=decode(spec, cache[spec.getter]), status='observed',
                       writable=spec.setter is not None)
            if spec.kind == 'Number':
                row.update(minimum=spec.minimum, maximum=spec.maximum)
            if spec.kind == 'Choice':
                row['choices'] = list(spec.choices)
        except ControlError:
            row['status'] = 'unknown'
        features[name] = row
    components = {}
    try:
        response = client.executeFunction('getAppComponentList', EXTRA_READS['getAppComponentList'])
        for item in response['app_component']['app_component_list']:
            name, version = item.get('name'), item.get('version')
            if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9]{1,60}', name) and type(version) is int:
                components[name] = {'version': version, 'scope': 'device_advertised_not_control_verified'}
    except Exception:
        pass
    # API success alone cannot establish whether the response's shape is usable.
    auxiliary = {}
    for method in ('getChimeCtrlList', 'getQuickRespList'):
        try:
            response = client.executeFunction(method, EXTRA_READS[method])
            auxiliary[method] = {'result': 'read_succeeded', 'cli_control': 'not_implemented'}
        except Exception:
            auxiliary[method] = {'result': 'unavailable', 'cli_control': 'not_implemented'}
    return {'result': 'read_succeeded', 'features': features,
            'recording_commands': ['recording status', 'recording continuous', 'recording events',
                                   'recording schedule', 'recordings', 'clip'],
            'advertised_components': components, 'auxiliary_reads': auxiliary,
            'video_commands': ['live', 'snapshot'],
            'unimplemented': ['native_camera_rtsp', 'two_way_audio', 'quick_response_playback',
                'button_events', 'chime_controls', 'archive_playback_viewer',
                'power_mode_changes', 'night_vision_controls', 'spotlight_controls',
                'firmware', 'pairing', 'notifications']}


def apply_setting(client, name, desired):
    spec = SPECS[name]
    # Getter must be usable on this unit before a speculative setter is attempted.
    decode(spec, client.executeFunction(spec.getter, request_for(spec)))
    wire = ('on' if desired else 'off') if spec.kind == 'Switch' else desired
    # Match documented numeric wire representation for sensitivities/volume.
    if spec.kind == 'Number' and spec.module != 'audio_config':
        wire = str(desired)
    payload = {spec.module: {spec.section: {spec.field: wire}}}
    if spec.setter in ('setSpeakerVolume', 'setMicrophoneVolume'):
        payload['method'] = 'set'
    try:
        client.executeFunction(spec.setter, payload)
        actual = decode(spec, client.executeFunction(spec.getter, request_for(spec)))
        if type(actual) is not type(desired) or actual != desired:
            return {'result': 'readback_mismatch', 'outcome': 'unknown'}
        return {'result': 'verified', 'setting': name, 'value': actual,
                'physical_effect': 'not_verified'}
    except BaseException:
        raise ControlError('write_outcome_unknown') from None


def run(entry, env_file, command='status', name=None, value=None, confirm=False):
    operation = validate(command, name, value, confirm)
    settings = load_settings(env_file)
    if not settings.username or not settings.password:
        raise ControlError('missing_credentials')
    host = entry.get('host', '')
    Settings(host=host)
    if not host or entry.get('model') != 'D235':
        raise ControlError('invalid_device_registry')
    client = None
    try:
        client = make_client(host, settings, SPECS[operation[0]].setter if operation else None)
        info = client.basicInfo.get('device_info', {}).get('basic_info', {})
        if info.get('device_model') != 'D235' or info.get('device_type') != 'SMART.TAPODOORBELL':
            raise ControlError('device_identity_mismatch')
        # Audio needs fresh authenticated identity, not the expensive full snapshot.
        result = ({'result': 'read_succeeded'} if command == 'identity' else
                  apply_setting(client, *operation) if operation else snapshot(client))
        return {'model': 'D235', 'hardware': clean(info.get('hw_version')),
                'firmware': clean(info.get('sw_version')), 'observation_scope': 'direct_device',
                'doorbell_reachability': 'authenticated', **result}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
