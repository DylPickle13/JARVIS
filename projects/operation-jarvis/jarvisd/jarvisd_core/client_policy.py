"""Executable convergence policy reference, NOT wired into any live writer.

No network, persistence, environment, SDK, or dispatch operations. Evidence below
must eventually come from trusted coordinators/adapters, never caller-supplied
booleans. This model grants no authority and implements no production fence.
"""
from dataclasses import dataclass, replace
from enum import Enum
import threading

from .commands import COMMANDS


class PolicyError(ValueError):
    pass


class Cohort(Enum):
    PLUGS = "plugs"
    PURIFIER = "purifier"


class Mode(Enum):
    CLOSED = "closed"
    MIXED = "mixed-legacy"  # Describes today, NOT exclusive ownership.
    DRAINING = "draining"
    MAINTENANCE = "maintenance"
    API = "api-owned"


MAX_EPOCH = 2**53 - 1  # Exact in Python/Swift integers and JavaScript JSON numbers.


def _epoch(value):
    if type(value) is not int or not 0 <= value <= MAX_EPOCH:
        raise PolicyError("Invalid ownership epoch")


@dataclass(frozen=True)
class Ownership:
    cohort: Cohort
    epoch: int
    mode: Mode = Mode.CLOSED

    def __post_init__(self):
        _epoch(self.epoch)
        if type(self.cohort) is not Cohort or type(self.mode) is not Mode:
            raise PolicyError("Invalid ownership state")
        if self.mode is Mode.API and self.epoch in (0, MAX_EPOCH):
            # Keep headroom to close an active epoch without wrapping/resetting.
            raise PolicyError("API ownership requires an established, advanceable epoch")


@dataclass(frozen=True)
class HandoffEvidence:
    cohort: Cohort
    epoch: int
    active_writes: int | None = None
    local_workers_quiescent: bool = False
    legacy_writers_fenced: bool = False
    uncertainty_preserved: bool = False
    catalogue_validated: bool = False
    clients_compatible: bool = False
    client_transports_checked: bool = False


def request_drain(state: Ownership) -> Ownership:
    """Close admission and advance the epoch; do not cancel/replay in-flight work."""
    if state.mode is Mode.DRAINING:
        return state
    return replace(state, mode=Mode.DRAINING, epoch=state.epoch + 1)


def _require_quiescence(state, evidence):
    if (evidence.cohort is not state.cohort or type(evidence.epoch) is not int
            or evidence.epoch != state.epoch or type(evidence.active_writes) is not int
            or evidence.active_writes != 0 or evidence.local_workers_quiescent is not True
            or evidence.legacy_writers_fenced is not True or evidence.uncertainty_preserved is not True):
        raise PolicyError("Scoped drain/fence evidence is incomplete")


def enter_maintenance(state: Ownership, evidence: HandoffEvidence) -> Ownership:
    if state.mode is not Mode.DRAINING:
        raise PolicyError("Maintenance requires draining first")
    _require_quiescence(state, evidence)
    return replace(state, mode=Mode.MAINTENANCE)


def activate_api(state: Ownership, evidence: HandoffEvidence) -> Ownership:
    if state.mode is not Mode.MAINTENANCE:
        raise PolicyError("API activation requires maintenance")
    _require_quiescence(state, evidence)
    if (evidence.catalogue_validated is not True or evidence.clients_compatible is not True
            or evidence.client_transports_checked is not True):
        raise PolicyError("Client/catalogue cutover checks are incomplete")
    # Even maintenance-era observations/requests must be refreshed after activation.
    return replace(state, mode=Mode.API, epoch=state.epoch + 1)


def restart_closed(state: Ownership) -> Ownership:
    """Fail closed after restart/recovery; never replay or restore an older epoch."""
    return replace(state, mode=Mode.CLOSED, epoch=state.epoch + 1)


class Route(Enum):
    BLOCK = "block"
    API = "api"  # Deliberately no legacy/vendor fallback route.


@dataclass(frozen=True)
class Readiness:
    request_epoch: int | None = None
    observation_epoch: int | None = None
    endpoint_available: bool = False
    protocol_verified: bool = False
    transport_guarded: bool = False
    authorized: bool = False
    target_known: bool = False
    observation_fresh: bool = False
    target_uncertain: bool = True


@dataclass(frozen=True)
class WritePlan:
    cohort: Cohort
    epoch: int
    route: Route
    reason: str

    @property
    def automatic_retry(self):
        return False

    @property
    def fallback(self):
        return False

    @property
    def queue(self):
        return False


def plan_write(action: str, state: Ownership, readiness: Readiness) -> WritePlan:
    """Plan for a converged client only. Existing clients do not call this."""
    def blocked(reason):
        return WritePlan(state.cohort, state.epoch, Route.BLOCK, reason)
    spec = COMMANDS.get(action) if isinstance(action, str) else None
    if spec is None or spec.effect != "write" or spec.integration != state.cohort.value:
        return blocked("unsupported-operation")
    if state.mode is not Mode.API:
        return blocked("ownership-not-active")
    if (type(readiness.request_epoch) is not int or type(readiness.observation_epoch) is not int
            or readiness.request_epoch != state.epoch or readiness.observation_epoch != state.epoch):
        return blocked("epoch-mismatch")
    for name in ("endpoint_available", "protocol_verified", "transport_guarded", "authorized",
                 "target_known", "observation_fresh"):
        if getattr(readiness, name) is not True:
            return blocked(name.replace("_", "-"))
    if readiness.target_uncertain is not False:
        return blocked("uncertain-target")
    return WritePlan(state.cohort, state.epoch, Route.API, "ready")


class WriteAttempt:
    """Local one-intent budget, not cross-process idempotency or server admission.

    Calling claim consumes the intent even if preflight changed. A real adapter
    must claim BEFORE handing anything to the transport. Reconciliation never
    refunds it. Atomic admission against maintenance belongs in the future server.
    """
    def __init__(self, plan: WritePlan):
        self._plan = plan
        self._consumed = False
        self._lock = threading.Lock()

    def claim(self, current: Ownership) -> bool:
        with self._lock:
            if self._consumed:
                raise PolicyError("Intent already consumed; never replay")
            self._consumed = True
            return (self._plan.route is Route.API and current.mode is Mode.API
                    and current.cohort is self._plan.cohort and current.epoch == self._plan.epoch)


class Outcome(Enum):
    NOT_SUBMITTED = "not-submitted"
    REJECTED = "rejected-before-adapter"
    ACKNOWLEDGED = "acknowledged"  # Not exactly-once execution or a fresh observation.
    PENDING = "verification-pending"
    UNKNOWN = "delivery-unknown"


class Recovery(Enum):
    STATE_READ = "bounded-backend-state-read"
    FOREGROUND_READ = "foreground-or-owner-requested-backend-read"


def recovery_for(cohort: Cohort) -> Recovery:
    # Never direct SDK fallback, unsolicited cloud polling or cooldown bypass.
    if cohort is Cohort.PLUGS:
        return Recovery.STATE_READ
    if cohort is Cohort.PURIFIER:
        return Recovery.FOREGROUND_READ
    raise PolicyError("Unsupported recovery cohort")


def classify_reply(action, status, payload, *, submitted=True, authoritative=False,
                   expected_plug=None) -> Outcome:
    """Conservative current-v1 reply classification for future client adapters.

    authoritative=True requires a complete response from the intended current-v1
    peer/route AND certified single-submission transport evidence, not proxy JSON
    or just one library call. Future duplicate-reservation errors need a different
    classifier: rejecting a duplicate does not clear the original uncertainty.
    HTTP200/ok:false is ambiguous. No stream decoding, freshness or retry authority.
    """
    if submitted is False:
        return Outcome.NOT_SUBMITTED if status is None and payload is None else Outcome.UNKNOWN
    if submitted is not True or authoritative is not True or type(status) is not int:
        return Outcome.UNKNOWN
    spec = COMMANDS.get(action) if isinstance(action, str) else None
    if spec is None or spec.effect != "write" or not isinstance(payload, dict):
        return Outcome.UNKNOWN
    # Current handler rejects these before dispatch. Never infer the same from
    # arbitrary proxies, error prose, 5xx, 429, redirects or a transport exception.
    if status in {400, 401, 403, 409, 411, 413}:
        if (payload.get("ok") is False and payload.get("action") in (None, action)
                and isinstance(payload.get("error"), str) and payload["error"].strip()):
            return Outcome.REJECTED
        return Outcome.UNKNOWN
    if (status != 200 or payload.get("action") != action or payload.get("ok") is not True
            or "error" in payload):
        return Outcome.UNKNOWN
    if spec.integration == "plugs":
        plug = payload.get("plug")
        if (not isinstance(plug, dict) or not isinstance(expected_plug, str) or not expected_plug.strip()
                or plug.get("name") != expected_plug.strip().lower() or type(plug.get("is_on")) is not bool):
            return Outcome.UNKNOWN
        if action in {"plug-on", "plug-off"} and plug["is_on"] is not (action == "plug-on"):
            return Outcome.UNKNOWN
        return Outcome.ACKNOWLEDGED
    purifier = payload.get("airPurifier")
    if not isinstance(purifier, dict) or purifier.get("ok") is not True or "error" in purifier:
        return Outcome.UNKNOWN
    data = purifier.get("data")
    if (not isinstance(data, dict) or type(data.get("is_on")) is not bool
            or data.get("write_accepted") is not True or type(data.get("verification_pending")) is not bool):
        return Outcome.UNKNOWN
    return Outcome.PENDING if data["verification_pending"] else Outcome.ACKNOWLEDGED
