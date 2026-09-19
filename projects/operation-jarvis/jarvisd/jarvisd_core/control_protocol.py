"""Dormant v2 control boundary; no listener, runtime wiring or default storage.

The host supplies authentication, immutable catalogue binding, rechecked readiness
and an existing guarded dispatcher. Nothing in JSON confers these authorities.
See docs/control-protocol.md before wiring any route or using these receipts.
"""
from dataclasses import dataclass, field
import hashlib
import json
import re

from . import client_policy as policy
from . import control_ledger as ledger
from .commands import COMMANDS, PLUG_NAME_RE, PURIFIER_MODES, PURIFIER_AUTO_PREFERENCES

PROTOCOL = "jarvis-control/2"
CONTENT_TYPE = "application/vnd.jarvis.control+json;version=2"
WINDOW_PATH = "/api/v2/control/window"
COMMAND_PATH = "/api/v2/control/command"
MAX_BODY = 16_384
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DEVICE_ID = re.compile(r"[0-9a-f]{24}\Z")
_OUTCOMES = (policy.Outcome.ACKNOWLEDGED, policy.Outcome.PENDING, policy.Outcome.UNKNOWN)
_CONFLICTS = frozenset({"duplicate-intent", "admission-busy", "write-not-admitted",
    "resource-unresolved", "window-expired-or-unknown", "window-scope-mismatch",
    "window-unavailable", "window-capacity", "writes-capacity", "store-capacity"})


class ProtocolError(ValueError):
    pass


def _hex(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def _epoch(value):
    return type(value) is int and 0 < value < policy.MAX_EPOCH


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("invalid-body")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ProtocolError("invalid-body")


def _decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BODY:
        raise ProtocolError("invalid-body")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_invalid_constant)
    except (ValueError, RecursionError):
        raise ProtocolError("invalid-body") from None
    if type(result) is not dict or result.get("protocol") != PROTOCOL:
        raise ProtocolError("invalid-body")
    return result


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _fingerprint(domain, value):
    # Stable resource domain intentionally excludes epoch/catalogue/protocol version:
    # new ownership/catalogue generations must NOT escape old resource barriers.
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + _encode(value)).hexdigest()


@dataclass(frozen=True)
class Access:
    """Trusted listener input, never decoded from request JSON.

    principal is a stable host-derived authenticated identity fingerprint (including
    across credential rotation); scopes and transport certification are host facts.
    This type does not itself authenticate or certify a transport.
    """
    principal: str = field(repr=False)
    cohorts: frozenset
    transport_verified: bool = False

    def __post_init__(self):
        if (not _hex(self.principal, _HEX64) or type(self.cohorts) is not frozenset
                or any(type(c) is not policy.Cohort for c in self.cohorts)
                or type(self.transport_verified) is not bool):
            raise ProtocolError("invalid-access")


@dataclass(frozen=True)
class Command:
    action: str
    params: tuple  # Sorted immutable pairs; values are strictly strings or integers.

    @property
    def cohort(self):
        return policy.Cohort(COMMANDS[self.action].integration)


@dataclass(frozen=True)
class Request:
    request_id: str
    incarnation: str
    epoch: int
    window: str = field(repr=False)
    command: Command

    @property
    def fingerprint(self):
        # Public request correlation only, not authentication or a private target ID.
        return _fingerprint("jarvis-request/2", (self.request_id, self.incarnation,
            self.epoch, self.window, self.command.action, self.command.params))


@dataclass(frozen=True)
class BoundWrite:
    """Host-prepared immutable target; host must recheck before real dispatch.

    target=(cohort, canonical identity), e.g. observed plug host or purifier opaque
    ID. No caller-supplied fingerprint can choose a ledger quarantine key. Catalogue
    identifies the trusted immutable mapping generation, not a permission grant.
    """
    command: Command
    target: tuple = field(repr=False)
    catalogue: str = field(repr=False)
    context: object = field(default=None, repr=False, compare=False)  # Host-only, never serialized/hashed.

    def __post_init__(self):
        if (type(self.command) is not Command or type(self.target) is not tuple
                or len(self.target) != 2 or self.target[0] != self.command.cohort.value
                or type(self.target[1]) is not str or not 0 < len(self.target[1]) <= 256
                or any(not 33 <= ord(c) <= 126 for c in self.target[1])
                or not _hex(self.catalogue, _HEX64)):
            raise ProtocolError("invalid-binding")

    @property
    def resource(self):
        return _fingerprint("jarvis-resource/1", self.target)

    @property
    def fingerprint(self):
        return _fingerprint("jarvis-command/2", (self.command.action, self.command.params,
                                                 self.target, self.catalogue))


def _command(action, params):
    spec = COMMANDS.get(action) if type(action) is str else None
    if spec is None or spec.effect != "write" or type(params) is not dict:
        raise ProtocolError("invalid-body")
    if spec.integration == "plugs":
        name = params.get("plug")
        if (set(params) != {"plug"} or type(name) is not str or not 0 < len(name) <= 128
                or not PLUG_NAME_RE.fullmatch(name) or name != name.lower()):
            raise ProtocolError("invalid-body")
    else:
        if not _hex(params.get("deviceID"), _DEVICE_ID):
            raise ProtocolError("invalid-body")
        setting = params.get("setting")
        base = {"deviceID", "setting"}
        keys = set(params)
        value = params.get("value")
        if setting in ("power", "display", "child-lock", "light-detection"):
            choices = ("on", "off", "toggle") if setting == "power" else ("on", "off")
            valid = keys == base | {"value"} and type(value) is str and value in choices
        elif setting == "mode":
            valid = keys == base | {"value"} and type(value) is str and value in PURIFIER_MODES
        elif setting == "speed":
            level = params.get("level")
            valid = keys == base | {"level"} and type(level) is int and 1 <= level <= 4
        elif setting == "auto-preference":
            size = params.get("roomSize")
            valid = (keys in (base | {"value"}, base | {"value", "roomSize"})
                     and type(value) is str and value in PURIFIER_AUTO_PREFERENCES
                     and ("roomSize" not in params or type(size) is int and 1 <= size <= 10000))
        elif setting == "timer":
            minutes = params.get("minutes")
            valid = ((keys == base | {"value"} and value == "clear")
                     or (keys == base | {"minutes"} and type(minutes) is int and 1 <= minutes <= 1440))
        else:
            valid = False
        if not valid:
            raise ProtocolError("invalid-body")
    return Command(action, tuple(sorted(params.items())))


def parse_request(raw):
    data = _decode(raw)
    if (set(data) != {"protocol", "requestID", "incarnation", "epoch", "window", "operation"}
            or not all(_hex(data[k], _HEX32) for k in ("requestID", "incarnation", "window"))
            or not _epoch(data["epoch"]) or type(data["operation"]) is not dict
            or set(data["operation"]) != {"action", "params"}):
        raise ProtocolError("invalid-body")
    # No top-level v1 action/params: even a misrouted unmodified v2 body must
    # not be executable by an old daemon that ignores unknown guard metadata.
    operation = data["operation"]
    return Request(data["requestID"], data["incarnation"], data["epoch"], data["window"],
                   _command(operation["action"], operation["params"]))


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes

    @property
    def headers(self):
        return (("Content-Type", CONTENT_TYPE), ("Cache-Control", "no-store"))


def _reply(status, **body):
    return Reply(status, _encode({"protocol": PROTOCOL, **body}))


def _error(status, code, request_id=None, prior=None):
    # Every error preserves uncertainty about ORIGINAL delivery. A new handling
    # rejection cannot erase a prior request, response loss or hidden resubmission.
    return _reply(status, kind="error", code=code, requestID=request_id,
                  disposition=policy.Outcome.UNKNOWN.value,
                  priorDisposition=prior.value if prior in _OUTCOMES else None)


class ControlProtocol:
    """Framework-neutral boundary, not a server or authorization implementation.

    host.prepare(command, access) -> BoundWrite (no mutation/IO side effects).
    host.readiness(bound, access, epoch) -> Readiness (fast under ledger lock).
    host.execute(bound) -> DispatchResult (existing device admission/binding/SDK
    checks MUST remain; no background work may outlive this callback).
    No route activates ownership, edits a catalogue, reconciles or runs a read.
    """
    def __init__(self, store, host, *, after_dispatch=None):
        if after_dispatch is not None and not callable(after_dispatch):
            raise ValueError('invalid-post-dispatch-hook')
        self._store, self._host = store, host
        self._after_dispatch = after_dispatch

    def handle(self, *, method, path, content_type, body, access=None):
        # The future listener must enforce framing/auth/body limits BEFORE buffering
        # or calling here. No redirect, path normalization, v1 alias or fallback.
        if path not in (WINDOW_PATH, COMMAND_PATH):
            return _error(404, "unsupported-route")
        if method != "POST":
            return _error(405, "unsupported-method")
        if content_type != CONTENT_TYPE:
            return _error(415, "unsupported-media-type")
        if type(access) is not Access:
            return _error(401, "authentication-required")
        if access.transport_verified is not True:
            return _error(403, "transport-not-certified")
        if type(body) is bytes and len(body) > MAX_BODY:
            return _error(413, "body-too-large")
        request_id = None
        validated = False
        try:
            if path == WINDOW_PATH:
                data = _decode(body)
                if set(data) != {"protocol", "cohort"} or type(data["cohort"]) is not str:
                    raise ProtocolError("invalid-body")
                try:
                    cohort = policy.Cohort(data["cohort"])
                except ValueError:
                    raise ProtocolError("invalid-body") from None
                if cohort not in access.cohorts:
                    return _error(403, "scope-denied")
                window = self._store.issue_window(cohort, access.principal)
                return _reply(200, kind="window", cohort=cohort.value, incarnation=window.incarnation,
                              epoch=window.epoch, window=window.token, maxAgeMs=ledger.TTL_NS // 1_000_000)
            request = parse_request(body)
            request_id = request.request_id
            validated = True
            if request.command.cohort not in access.cohorts:
                return _error(403, "scope-denied", request_id)
            bound = self._host.prepare(request.command, access)
            if type(bound) is not BoundWrite or bound.command is not request.command:
                raise RuntimeError("host-binding-invalid")
            intent = ledger.Intent(request.command.cohort, request.incarnation, request.epoch,
                access.principal, request.request_id, bound.resource, bound.fingerprint,
                request.command.action, request.window)
            started = False
            def execute():
                nonlocal started
                started = True
                return self._host.execute(bound)
            try:
                result = self._store.execute_once(intent,
                    lambda: self._host.readiness(bound, access, request.epoch), execute)
            finally:
                if started and self._after_dispatch is not None:
                    # execute_once has completed its durable outcome/active-slot
                    # cleanup. Never queue a read for a duplicate/rejected request.
                    # A failed read scheduler must not relabel a delivered receipt.
                    try:
                        self._after_dispatch(bound)
                    except Exception:
                        pass  # Quarantine remains; this hook has no write callback.
            # Do not forward arbitrary vendor values, paths, IDs, errors or summaries.
            return _reply(200, kind="receipt", requestID=request_id, incarnation=request.incarnation,
                          epoch=request.epoch, action=request.command.action,
                          requestDigest=request.fingerprint, disposition=result.outcome.value)
        except ProtocolError:
            return _error(503 if validated else 400,
                          "control-unavailable" if validated else "invalid-body", request_id)
        except ledger.LedgerError as exc:
            code = exc.code if type(exc.code) is str and exc.code in _CONFLICTS else "control-unavailable"
            return _error(409 if code in _CONFLICTS else 503, code, request_id, exc.prior_outcome)
        except Exception:
            return _error(503, "control-unavailable", request_id)
        # BaseException/cancellation propagates; ledger finally retains uncertainty.


def classify_receipt(request, *, status, content_type, body,
                     intended_peer=False, single_submission=False):
    """Conservative pure client check, NOT transport certification or permission.

    Old v1 responses, duplicate errors and missing peer/single-submission evidence
    never become acknowledgement or definitive original non-delivery. No outcome
    from this function authorizes replay or releases a resource barrier.
    """
    if (type(request) is not Request or type(status) is not int or status != 200
            or content_type != CONTENT_TYPE or intended_peer is not True or single_submission is not True):
        return policy.Outcome.UNKNOWN
    try:
        data = _decode(body)
        if (set(data) != {"protocol", "kind", "requestID", "incarnation", "epoch", "action", "requestDigest", "disposition"}
                or data["kind"] != "receipt" or data["requestID"] != request.request_id
                or data["incarnation"] != request.incarnation or not _epoch(data["epoch"])
                or data["epoch"] != request.epoch or data["action"] != request.command.action
                or not _hex(data["requestDigest"], _HEX64) or data["requestDigest"] != request.fingerprint):
            return policy.Outcome.UNKNOWN
        outcome = policy.Outcome(data["disposition"])
        return outcome if outcome in _OUTCOMES else policy.Outcome.UNKNOWN
    except (ProtocolError, ValueError, TypeError):
        return policy.Outcome.UNKNOWN
