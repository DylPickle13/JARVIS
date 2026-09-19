"""Reviewed Vital 200S mutation path. No SDK/configuration I/O on import.

These are application-request guards, not an exactly-once/cloud-cancellation
promise. All SDK imports/source checks happen inside explicit operations.
"""
from contextlib import contextmanager, ExitStack
from typing import Any


class WriteSafetyError(RuntimeError):
    pass


_AUDITED_SOURCE_SHA256 = {'aiohttp/client.py': 'a5467752c13ae51bf5731a8e3997d5f8b44ab1c0c54b11a906e878ff3cc31701',
 'aiohttp/client_reqrep.py': '456c97cee222d0d11335eb8d00331b58f19dfa6c5ca552ec550334379f36a54f',
 'pyvesync/auth.py': '4ea2b6aa183bcad83e2b6a2daec517e43c9f35aab90311e60a9eae3dfeb438ed',
 'pyvesync/base_devices/purifier_base.py': '0fd5c8ef98ffafaa303ada0c4cbdc6cf34e38e51fbfb789bf533c175c2410a3a',
 'pyvesync/base_devices/vesyncbasedevice.py': 'd8f3fab74380f386016e6b56c7ae3df3a6cb9a0d5dd7b11e1804c1102ff5d66b',
 'pyvesync/const.py': '52e79bc7b4340aef368352833a2b17c858b293ffbfa88d118a587e00e3f85bef',
 'pyvesync/device_map.py': 'dac81a8aa020e085628cdeade476525cc5d7d04d52573de398233fffab837e95',
 'pyvesync/devices/vesyncpurifier.py': '122d1ff4940bf412ba8c784b5356a77acdd5f89031cde32267d657dc7c8903b5',
 'pyvesync/models/base_models.py': '3244361a8d35c4cc391249f0fccddf69e793f48ce677b3d1d6f9992f14211da7',
 'pyvesync/models/bypass_models.py': '224c2a20c520563c79637b7d720fdfbec4915365e84dc46f1a26fb14763f4d6f',
 'pyvesync/models/purifier_models.py': '79d6375a9af62ce12f9f974cd7a1d1849ab285de14a4a662ec79c52ed62560cc',
 'pyvesync/utils/device_mixins.py': '01e3996c2ba83999e06abd3eba534a3960fc18caed33c6f3a9448adacf7fdc78',
 'pyvesync/utils/errors.py': 'bcced053f12bd002dd4dc16af2169e3c57b4d385c25ac7cc13c4277af8488204',
 'pyvesync/utils/helpers.py': 'f4df673784708b977b1c02112df0c2ea898c09ae1907f75d86504e111e2c62dc',
 'pyvesync/vesync.py': '6b971010f4fc4c9156821707d7bef6b65be36ca3c7fee16cdf3065e9982147ec'}


def require_reviewed_stack():
    import hashlib
    import importlib.metadata
    from pathlib import Path
    import aiohttp
    import pyvesync
    if (importlib.metadata.version("pyvesync"), aiohttp.__version__) != ("3.4.2", "3.14.3"):
        raise WriteSafetyError("Unaudited purifier SDK stack; writes disabled pending review")
    roots = {"pyvesync": Path(pyvesync.__file__).parent, "aiohttp": Path(aiohttp.__file__).parent}
    for name, expected in _AUDITED_SOURCE_SHA256.items():
        package, relative = name.split("/", 1)
        try:
            actual = hashlib.sha256((roots[package] / relative).read_bytes()).hexdigest()
        except OSError as exc:
            raise WriteSafetyError("Purifier SDK source audit unavailable; writes disabled") from exc
        if actual != expected:
            raise WriteSafetyError("Purifier SDK source changed; writes disabled pending review")


@contextmanager
def temporary_attribute(obj, name, value):
    # SDK device/manager objects use slots, while aiohttp sessions use __dict__.
    namespace = getattr(obj, "__dict__", None)
    inherited = namespace is not None and name not in namespace
    previous = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if inherited:
            delattr(obj, name)
        else:
            setattr(obj, name, previous)


def _review_target(target, expected_cid=None):
    require_reviewed_stack()
    import aiohttp
    from pyvesync import VeSync
    from pyvesync.devices.vesyncpurifier import VeSyncAirBaseV2
    from .vesync_client import SUPPORTED_VITAL_200S_MODELS
    manager = getattr(target, "manager", None)
    if type(target) is not VeSyncAirBaseV2 or target.device_type not in SUPPORTED_VITAL_200S_MODELS:
        raise WriteSafetyError("Unsupported purifier write device; no mutation attempted")
    if not isinstance(target.cid, str) or not target.cid or (expected_cid is not None and target.cid != expected_cid):
        raise WriteSafetyError("Purifier identity changed before mutation")
    if type(manager) is not VeSync or not manager.enabled or not manager._close_session:
        raise WriteSafetyError("Nonstandard purifier manager; no mutation attempted")
    session = manager.session
    if (type(session) is not aiohttp.ClientSession or session.closed or session._middlewares
            or session._trace_configs or type(getattr(session, "_retry_connection", None)) is not bool
            or getattr(session.request, "__func__", None) is not aiohttp.ClientSession.request):
        raise WriteSafetyError("Nonstandard purifier HTTP session; no mutation attempted")
    return manager


def _plan(target, method, args, kwargs):
    """Mirror only existing reviewed setter payloads, never construct a new API."""
    from pyvesync.const import DeviceStatus
    state = target.state
    if method in {"turn_on", "turn_off", "toggle_switch"}:
        on = method == "turn_on" if method != "toggle_switch" else not bool(state.device_status)
        return "setSwitch", {"powerSwitch": int(on), "switchIdx": 0}, type(state.device_status) is DeviceStatus and bool(state.device_status) == on
    if method == "set_mode" and args[0] != "manual":
        return "setPurifierMode", {"workMode": args[0]}, False
    if method in {"set_fan_speed", "set_mode"}:
        level = args[0] if method == "set_fan_speed" else (
            1 if state.fan_set_level is None or state.fan_level == 0 else state.fan_set_level)
        return "setLevel", {"levelIdx": 0, "manualSpeedLevel": level, "levelType": "wind"}, False
    if method in {"turn_on_display", "turn_off_display"}:
        on = method == "turn_on_display"
        return "setDisplay", {"screenSwitch": int(on)}, type(state.display_set_status) is DeviceStatus and bool(state.display_set_status) == on
    if method in {"turn_on_child_lock", "turn_off_child_lock"}:
        return "setChildLock", {"childLockSwitch": int(method == "turn_on_child_lock")}, False
    if method in {"turn_on_light_detection", "turn_off_light_detection"}:
        on = method == "turn_on_light_detection"
        # The SDK compares ambient detection, not the configured switch, when
        # skipping. Never accept that skip unless the requested switch also matches.
        noop = (type(state.light_detection_status) is DeviceStatus
                and type(state.light_detection_switch) is DeviceStatus
                and bool(state.light_detection_status) == on and bool(state.light_detection_switch) == on)
        return "setLightDetection", {"lightDetectionSwitch": int(on)}, noop
    if method == "set_auto_preference":
        return "setAutoPreference", {"autoPreference": args[0], "roomSize": kwargs["room_size"]}, False
    if method == "set_timer":
        from pyvesync.models.purifier_models import PurifierV2TimerPayloadData, PurifierV2TimerActionItems, PurifierV2EventTiming
        payload = PurifierV2TimerPayloadData(enabled=True,
            startAct=[PurifierV2TimerActionItems(type="powerSwitch", act=0)],
            tmgEvt=PurifierV2EventTiming(clkSec=args[0]))
        return "addTimerV2", payload.to_dict(), False
    if method == "clear_timer":
        return "delTimerV2", {"id": getattr(state.timer, "id", None), "subDeviceNo": 0}, False
    raise WriteSafetyError("Unsupported purifier mutation; no request attempted")


def _zero(value):
    return type(value) in (int, str) and value in (0, "0")


def _check_reply(reply):
    from pyvesync.utils.helpers import Helpers
    if not isinstance(reply, dict) or not _zero(reply.get("code")):
        raise WriteSafetyError("Purifier reply did not explicitly acknowledge success; outcome is uncertain")
    if Helpers.parse_error_code(reply).code != 0:
        raise WriteSafetyError("Purifier reported a device error; outcome is uncertain")


class _ManagerView:
    """Device-local view: unbound SDK API method runs with guarded self dispatch.

    Calling the original *bound* API method for mutations would let its recursive
    token retry bypass this view. Reads deliberately keep that original behavior.
    """
    def __init__(self, target, manager, method, data, *, mutation):
        self.target, self.manager = target, manager
        self.cid, self.method, self.data = target.cid, method, data
        self.mutation = mutation
        self.calls = 0
        self.http_calls = 0
        self.completed = False
        self.endpoint = "/cloud/v2/deviceManaged/bypassV2"
        self.url = manager._api_base_url_for_current_region() + self.endpoint

    def __getattr__(self, name):
        return getattr(self.manager, name)

    def __dir__(self):
        # SDK request builders enumerate attributes, rather than only getattr.
        return dir(self.manager)

    @property
    def enabled(self):
        return self.manager.enabled

    @enabled.setter
    def enabled(self, value):
        self.manager.enabled = value

    def validate_body(self, body):
        if hasattr(body, "to_dict"):
            body = body.to_dict()
        if (not isinstance(body, dict) or self.target.cid != self.cid
                or body.get("cid") != self.cid or body.get("deviceId") != self.cid
                or body.get("method") != "bypassV2"
                or body.get("payload") != {"method": self.method, "source": "APP", "data": self.data}):
            raise WriteSafetyError("Purifier target or operation changed; request blocked")

    async def async_call_api(self, api, method, json_object=None, headers=None, device=None):
        from pyvesync import VeSync
        self.calls += 1
        if self.calls != 1:
            raise WriteSafetyError("Additional purifier request blocked; outcome is uncertain")
        if api != self.endpoint or method.lower() != "post":
            raise WriteSafetyError("Unexpected purifier API endpoint; request blocked")
        self.validate_body(json_object)
        from pyvesync.utils.errors import VeSyncAPIStatusCodeError, VeSyncRateLimitError
        try:
            if self.mutation:
                reply, status = await VeSync.async_call_api(self, api, method, json_object, headers, device)
            else:
                reply, status = await self.manager.async_call_api(api, method, json_object, headers, device)
        except VeSyncAPIStatusCodeError as exc:
            # This pinned SDK discards the numeric status attribute. Normalize
            # its exact 429 form so the existing account-wide backoff sees it.
            if str(exc) == "VeSync API returned status code 429":
                raise VeSyncRateLimitError from exc
            raise
        _check_reply(reply)
        if status != 200:
            raise WriteSafetyError("Purifier response status was not confirmed")
        if not self.mutation:
            validate_observation(reply, self.target, self.method)
        self.completed = True
        return reply, status

    async def _api_response_wrapper(self, *args, **kwargs):
        from pyvesync import VeSync
        return await VeSync._api_response_wrapper(self, *args, **kwargs)

    async def _reauthenticate(self):
        from pyvesync.utils.errors import VeSyncTokenError
        raise VeSyncTokenError("Token rejected during purifier mutation; outcome is uncertain; no replay")



def validate_observation(reply, target, method="getPurifierStatus"):
    _check_reply(reply)
    from pyvesync.models.purifier_models import PurifierVitalDetailsResult
    from pyvesync.models.bypass_models import ResultV2GetTimer
    outer = reply.get("result")
    if not isinstance(outer, dict) or not _zero(outer.get("code")) or not isinstance(outer.get("result"), dict):
        raise WriteSafetyError("Purifier observation was malformed; state remains uncertain")
    body = outer["result"]
    try:
        if method == "getTimer":
            if not isinstance(body.get("timers"), list):
                raise ValueError("missing timers")
            ResultV2GetTimer.from_dict(body)
        else:
            observed = PurifierVitalDetailsResult.from_dict(body)
            if observed.powerSwitch not in (0, 1) or observed.timerRemain < 0:
                raise ValueError("invalid observed state")
            # SDK _set_state otherwise retains an optimistic timer at zero.
            if observed.timerRemain == 0:
                target.state.timer = None
    except Exception as exc:
        raise WriteSafetyError("Purifier observation was incomplete; state remains uncertain") from exc


async def execute_write(target: Any, method: str, *args, expected_cid=None, **kwargs) -> bool:
    manager = _review_target(target, expected_cid)
    from pyvesync.devices.vesyncpurifier import VeSyncAirBaseV2
    operation, data, noop = _plan(target, method, args, kwargs)
    callback = getattr(target, method)
    if getattr(callback, "__func__", None) is not getattr(VeSyncAirBaseV2, method):
        raise WriteSafetyError("Nonstandard purifier mutation method; request blocked")
    view = _ManagerView(target, manager, operation, data, mutation=True)
    session, request = manager.session, manager.session.request

    def request_once(method, url, **request_kwargs):
        view.http_calls += 1
        if view.http_calls != 1:
            raise WriteSafetyError("Additional purifier HTTP request blocked; outcome is uncertain")
        if method.lower() != "post" or str(url) != view.url:
            raise WriteSafetyError("Purifier HTTP endpoint changed; request blocked")
        view.validate_body(request_kwargs.get("json"))
        request_kwargs["allow_redirects"] = False
        return request(method, url=url, **request_kwargs)

    with ExitStack() as stack:
        stack.enter_context(temporary_attribute(target, "manager", view))
        stack.enter_context(temporary_attribute(session, "request", request_once))
        stack.enter_context(temporary_attribute(session, "_retry_connection", False))
        ok = await callback(*args, **kwargs)
        if view.calls > 1 or view.http_calls > 1:
            raise WriteSafetyError("Purifier attempted an additional request; outcome is uncertain")
        if ok is True and not (view.calls == view.http_calls == 1 and view.completed):
            if not (noop and view.calls == view.http_calls == 0):
                raise WriteSafetyError("Purifier mutation lacked a guarded acknowledgement")
        return ok is True


async def observe(target: Any, *, timer=False, expected_cid=None):
    """A valid new observation, not the SDK's optimistic state after a setter.

    Only explicit write preparation/verification uses this helper. Ordinary
    collectors, credential recovery, cooldown policy and read scheduling stay put.
    """
    manager = _review_target(target, expected_cid)
    view = _ManagerView(target, manager, "getTimer" if timer else "getPurifierStatus", {}, mutation=False)
    with temporary_attribute(target, "manager", view):
        result = await (target.get_timer() if timer else target.update())
        if view.calls != 1 or not view.completed:
            raise WriteSafetyError("Purifier refresh did not produce a valid observation")
        return result
