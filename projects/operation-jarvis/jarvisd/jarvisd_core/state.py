"""Single-flight cache and freshness policies with explicit collector dependencies.

No host configuration, collector construction, network calls, or threads occur
on import. The composition root supplies collectors and runtime identity.
"""
from __future__ import annotations

import concurrent.futures
from contextlib import contextmanager
from dataclasses import dataclass, field
import copy
import datetime as dt
import re
import threading
import time
from typing import Any, Callable

from .diagnostics import _safe_error
from .devices import _purifier_state, _purifier_id, _purifier_matches, _purifier_pending_command


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class ControlReadFence:
    owner: object = field(repr=False)
    subsystem: str
    device_id: str
    identity: str = field(repr=False)
    epoch: tuple[str, int] = field(repr=False)
    revision: int


class StateCoordinator:
    """Background, single-flight subsystem cache for the state endpoint."""

    NONCRITICAL_SUBSYSTEMS = frozenset({"codexQuota"})
    DEFAULT_INTERVALS = {
        # Foreground clients read this shared single-flight cache, never fan
        # out to hardware per request. Cloud purifier reads remain bounded.
        "pi": 2.0,
        "plugs": 5.0,
        "services": 5.0,
        "purifier": float("inf"),  # Foreground requests schedule bounded reads below.
        "network": 60.0,
        "codexQuota": 60.0,
    }
    DEFAULT_IDLE_INTERVALS = {
        "pi": 60.0,
        # Hardware state stays warm on the always-on Mac even when no native
        # client is visible. These are bounded host reads, not app polling.
        "plugs": 10.0,
        "services": 300.0,
        "purifier": float("inf"),
        "network": 600.0,
        "codexQuota": 300.0,
    }
    # A recent last-good control value remains usable while its next collection
    # is in flight. Sustained age, missing data, pending write verification, or
    # an expired failure grace remains fail-closed.
    DEFAULT_FRESHNESS_LIMITS = {
        "plugs": 30.0,
        "purifier": 90.0,
        "codexQuota": 900.0,
    }
    CONTROL_SUBSYSTEMS = frozenset({"plugs", "purifier"})
    DEFAULT_ACTIVE_LEASE_SECONDS = 45.0
    DEFAULT_ACTIVATION_WAIT_SECONDS = 0.0

    def __init__(
        self,
        collectors: dict[str, Callable[[], dict]],
        intervals: dict[str, float] | None = None,
        idle_intervals: dict[str, float] | None = None,
        freshness_limits: dict[str, float] | None = None,
        active_lease_seconds: float = DEFAULT_ACTIVE_LEASE_SECONDS,
        activation_wait_seconds: float = DEFAULT_ACTIVATION_WAIT_SECONDS,
        now: Callable[[], float] = time.time,
        *,
        version: str,
        started_at: float,
        retry_collectors: dict[str, Callable[[bool], dict]] | None = None,
    ):
        self.collectors = collectors
        self._version = version
        self._started_at = started_at
        self._retry_collectors = retry_collectors or {}
        self.intervals = {**self.DEFAULT_INTERVALS, **(intervals or {})}
        self.idle_intervals = {**self.DEFAULT_IDLE_INTERVALS, **(idle_intervals or {})}
        self.freshness_limits = {**self.DEFAULT_FRESHNESS_LIMITS, **(freshness_limits or {})}
        self.active_lease_seconds = max(1.0, float(active_lease_seconds))
        self.activation_wait_seconds = max(0.0, float(activation_wait_seconds))
        self._now = now
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._records: dict[str, dict[str, Any]] = {
            name: {
                "data": None,
                "updatedAt": None,
                "lastGoodAt": None,
                "error": None,
                "stale": True,
                "refreshing": False,
                "nextDue": float("inf") if name == "purifier" else 0.0,
                "lastRequestedAt": None,
                "revision": 0,
                "completionCount": 0,
                "pending": None,
                # Used only by the aggregate plug collector so one device can
                # retain and expire its own last-good value independently.
                "itemLastGoodAt": {},
                "writeBarriers": {},
            }
            for name in self.collectors
        }
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._scheduler: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False
        # Populate a newly launched daemon at active cadence before allowing it
        # to settle into idle mode when no client ever requests state.
        self._active_until = self._now() + self.active_lease_seconds

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            self._started = True
            self._stop.clear()
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(2, len(self.collectors)))
            self._scheduler = threading.Thread(target=self._run_scheduler, name="jarvisd-state", daemon=True)
            self._scheduler.start()
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            if not self._started:
                return
            self._stop.set()
            executor = self._executor
            scheduler = self._scheduler
            self._started = False
            self._executor = None
            self._scheduler = None
            self._condition.notify_all()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if scheduler is not None:
            scheduler.join(timeout=0.5)

    def _is_active_locked(self, now: float) -> bool:
        if now < self._active_until:
            return True
        return any(isinstance(record.get("pending"), dict) for record in self._records.values())

    def _interval_locked(self, name: str, now: float) -> float:
        source = self.intervals if self._is_active_locked(now) else self.idle_intervals
        fallback = self.intervals.get(name, 30.0)
        return max(0.5, float(source.get(name, fallback)))

    def _freshness_limit(self, name: str) -> float | None:
        raw = self.freshness_limits.get(name)
        return max(0.5, float(raw)) if raw is not None else None

    def _plug_item_is_stale(
        self,
        record: dict[str, Any],
        plug_name: str,
        state: Any,
        now: float,
    ) -> bool:
        if not isinstance(state, dict) or not isinstance(state.get("isOn"), bool):
            return True
        if plug_name in record.get("writeBarriers", {}):
            return True
        timestamps = record.get("itemLastGoodAt")
        last_good = timestamps.get(plug_name) if isinstance(timestamps, dict) else None
        if last_good is None:
            last_good = record.get("lastGoodAt")
        limit = self._freshness_limit("plugs")
        if last_good is None or (limit is not None and max(0.0, now - float(last_good)) > limit):
            return True
        return state.get("ok") is not True or state.get("stale") is True

    def _purifier_item_is_stale(self, record: dict, device_id: str, item: dict, now: float) -> bool:
        last_good = record["itemLastGoodAt"].get(device_id)
        limit = self._freshness_limit("purifier")
        return (item.get("ok") is not True or item.get("stale") is True
                or last_good is None or (limit is not None and now - last_good > limit)
                or item.get("verificationPending") is True or bool(record.get("error"))
                or device_id in record.get("writeBarriers", {}))

    def capture_revision(self, subsystem: str) -> int:
        with self._lock:
            return self._records[subsystem]["revision"]

    @staticmethod
    def _valid_control_epoch(epoch) -> bool:
        return (type(epoch) is tuple and len(epoch) == 2 and type(epoch[0]) is str
                and re.fullmatch(r"[0-9a-f]{32}", epoch[0]) is not None
                and type(epoch[1]) is int and 0 < epoch[1] < 2**53 - 1)

    def arm_control_epoch(self, subsystem: str, epoch: tuple[str, int], *, catalogue: str) -> None:
        """Host-only opt-in read fence; no collection, ownership grant or public field.

        Incrementing revision discards collections started before activation. Only
        subsequent successful aggregate observations can supply epoch evidence.
        Re-arming the same epoch is idempotent; older/different same-number epochs
        cannot replace it. Existing callers never arm this dormant fence.
        """
        if (subsystem not in self.CONTROL_SUBSYSTEMS or not self._valid_control_epoch(epoch)
                or type(catalogue) is not str or not re.fullmatch(r"[0-9a-f]{64}", catalogue)):
            raise ValueError("Invalid control epoch")
        with self._condition:
            record = self._records[subsystem]
            old = record.get("controlEpoch")
            if old == epoch:
                if record.get("controlCatalogue") != catalogue:
                    raise ValueError("Catalogue changes require a new control epoch")
                return
            if old is not None and epoch[1] <= old[1]:
                raise ValueError("Control epoch must advance")
            record["controlEpoch"] = epoch
            record["controlCatalogue"] = catalogue
            record["controlObserved"] = {}
            record["revision"] += 1
            self._condition.notify_all()

    def inspect_device(self, subsystem: str, device_id: str, *, control_epoch=None) -> dict:
        """Pure cache inspection under its lock; NEVER starts collectors or waits."""
        with self._lock:
            record = self._records.get(subsystem)
            if record is None or subsystem not in self.CONTROL_SUBSYSTEMS:
                return {"known": False, "fresh": False, "epochObserved": False, "identity": None}
            data = record.get("data") or {}
            key = "plugs" if subsystem == "plugs" else "devices"
            item = data.get(key, {}).get(device_id, {})
            identity = item.get("host") if subsystem == "plugs" else device_id if item else None
            identity = identity.strip().lower() if isinstance(identity, str) else None
            fresh = (not self._plug_item_is_stale(record, device_id, item, self._now())
                     if subsystem == "plugs" else not self._purifier_item_is_stale(record, device_id, item, self._now()))
            observed = (bool(identity) and self._valid_control_epoch(control_epoch)
                        and record.get("controlEpoch") == control_epoch
                        and record.get("controlObserved", {}).get(device_id) == identity)
            return {"known": bool(identity), "identity": identity, "fresh": fresh,
                    "epochObserved": observed}

    def begin_control_read(self, subsystem, device_id, *, identity, control_epoch):
        """Host-only fence BEFORE an ordinary scheduled/explicit aggregate read.

        No collection is started here. Bumping revision rejects an already-running
        read; a new successful completion is required. Caller supplies scheduling
        under the existing single-flight/foreground/cooldown policy.
        """
        with self._condition:
            view = self.inspect_device(subsystem, device_id, control_epoch=control_epoch)
            record = self._records.get(subsystem)
            if (not self._valid_control_epoch(control_epoch) or record is None
                    or record.get("controlEpoch") != control_epoch or not view["known"]
                    or view["identity"] != identity or "inflight" in record["writeBarriers"].values()):
                raise ValueError("Control read not admitted")
            record["revision"] += 1
            record["controlObserved"] = {}
            return ControlReadFence(self, subsystem, device_id, identity, control_epoch, record["revision"])

    @contextmanager
    def checked_control_read(self, fence, expected):
        """Ledger must acquire its own lock BEFORE entering this state context.

        Hold state through ledger commit so no intervening write/cache replacement
        can invalidate the checked evidence. No state path calls back to the ledger.
        """
        with self._condition:
            if type(fence) is not ControlReadFence or fence.owner is not self or not expected:
                raise ValueError("Invalid control read proof")
            record = self._records[fence.subsystem]
            view = self.inspect_device(fence.subsystem, fence.device_id, control_epoch=fence.epoch)
            if (record["revision"] != fence.revision or record.get("controlReadRevision") != fence.revision
                    or not view["epochObserved"] or not view["fresh"] or view["identity"] != fence.identity):
                raise ValueError("Stale control read proof")
            key = "plugs" if fence.subsystem == "plugs" else "devices"
            item = record["data"][key][fence.device_id]
            for name, value in expected.items():
                observed = (item.get("fanSetLevel"), item.get("fanLevel")) if name == "fanLevel" else (item.get(name),)
                if not any(type(actual) is type(value) and actual == value for actual in observed):
                    raise ValueError("Control observation does not match intent")
            yield

    def control_read_ready(self, subsystem: str) -> bool:
        """Cache-only scheduling probe. It grants no observation/write authority."""
        with self._condition:
            record = self._records.get(subsystem)
            if (subsystem not in self.CONTROL_SUBSYSTEMS or record is None
                    or record['refreshing'] or 'inflight' in record['writeBarriers'].values()):
                return False
            now = self._now()
            # Do not replace a foreground/periodic collection already due.
            if record['nextDue'] <= now:
                return False
            last = record.get('lastRequestedAt')
            return subsystem != 'purifier' or last is None or now - last >= 60.0

    def schedule_control_read(self, fence: ControlReadFence) -> bool:
        """Schedule ONE ordinary aggregate read, never force cloud cooldown.

        Admission/fence must already be minted by the owner, in ledger→state order.
        Recheck scheduling atomically. A raced/refused request earns no proof.
        """
        with self._condition:
            if (type(fence) is not ControlReadFence or fence.owner is not self
                    or not self.control_read_ready(fence.subsystem)):
                return False
            record = self._records[fence.subsystem]
            if record['revision'] != fence.revision or record.get('controlEpoch') != fence.epoch:
                return False
            now = self._now()
            if fence.subsystem == 'purifier':
                record['lastRequestedAt'] = now
                record['retryCooldown'] = False
            record['nextDue'] = 0.0
            self._active_until = max(self._active_until, now + self.active_lease_seconds)
            self._condition.notify_all()
        self.start()
        return True

    def control_read_completed(self, fence: ControlReadFence) -> bool:
        """A polling hint only; checked_control_read remains the durable proof."""
        with self._condition:
            if type(fence) is not ControlReadFence or fence.owner is not self:
                return False
            record = self._records[fence.subsystem]
            return (record['revision'] == fence.revision
                    and record.get('controlReadRevision') == fence.revision)

    def _stamp_control_observations_locked(self, name: str, result: dict) -> None:
        record = self._records[name]
        if "controlEpoch" not in record:
            return
        key = "plugs" if name == "plugs" else "devices"
        observed = {}
        for device_id, incoming in result.get(key, {}).items():
            if not isinstance(incoming, dict) or incoming.get("ok") is not True or not isinstance(incoming.get("isOn"), bool):
                continue
            view = self.inspect_device(name, device_id)
            if view["known"] and view["fresh"]:
                observed[device_id] = view["identity"]
        # Failures/retained cached successes do not inherit a prior read stamp.
        record["controlObserved"] = observed
        record["controlReadRevision"] = record["revision"]

    def begin_device_write(self, subsystem: str, device_id: str, *, identity: str | None = None,
                           control_epoch: tuple[str, int] | None = None):
        """Atomically recheck freshness and fence reads before a device write.

        Returns the observed state and affected logical IDs, or None if unsafe.
        The caller must already hold the process-local canonical resource gate.
        """
        with self._condition:
            record = self._records.get(subsystem)
            if record is None:
                return None
            data = record.get("data") or {}
            now = self._now()
            if control_epoch is not None:
                view = self.inspect_device(subsystem, device_id, control_epoch=control_epoch)
                if not view["epochObserved"] or view["identity"] != identity:
                    return None
            if subsystem == "plugs":
                items = data.get("plugs", {})
                item = items.get(device_id)
                if self._plug_item_is_stale(record, device_id, item, now):
                    return None
                host = item.get("host")
                if not isinstance(host, str) or host.strip().lower() != identity:
                    return None
                affected = tuple(key for key, value in items.items()
                                 if isinstance(value, dict) and isinstance(value.get("host"), str)
                                 and value["host"].strip().lower() == identity)
            elif subsystem == "purifier":
                item = data.get("devices", {}).get(device_id, {})
                if self._purifier_item_is_stale(record, device_id, item, now):
                    return None
                affected = (device_id,)
            else:
                return None
            barriers = record["writeBarriers"]
            if any(key in barriers for key in affected):
                return None
            observation = copy.deepcopy(item)
            barriers.update({key: "inflight" for key in affected})
            for key in affected:
                record.get("controlObserved", {}).pop(key, None)
            record["revision"] += 1
            self._condition.notify_all()
            return observation, affected

    def finish_device_write(self, subsystem: str, device_ids: tuple[str, ...], *, applied_to: str | None):
        """Fence during-write reads and quarantine unconfirmed device state.

        No write is retried. Only a successful post-write observation may clear
        an uncertain barrier. Purifier reads remain foreground/explicit-only.
        """
        with self._condition:
            record = self._records[subsystem]
            for device_id in device_ids:
                record.get("controlObserved", {}).pop(device_id, None)
                if device_id == applied_to:
                    record["writeBarriers"].pop(device_id, None)
                else:
                    record["writeBarriers"][device_id] = "uncertain"
            record["revision"] += 1
            record["nextDue"] = float("inf") if subsystem == "purifier" else 0.0
            self._condition.notify_all()

    @staticmethod
    def _write_error(record: dict, device_id: str) -> str | None:
        phase = record.get("writeBarriers", {}).get(device_id)
        if phase == "inflight":
            return "A device change is in progress."
        if phase == "uncertain":
            return "Command outcome is uncertain; refresh before another change."
        return None

    def _record_is_stale(self, name: str, record: dict[str, Any], now: float) -> bool:
        data = record.get("data")
        if data is None or record.get("lastGoodAt") is None:
            return True
        if isinstance(record.get("pending"), dict):
            return True
        if name == "plugs" and isinstance(data, dict) and isinstance(data.get("plugs"), dict):
            plugs = data["plugs"]
            # One expired or failed device must not stale fresh peers. The
            # subsystem itself is stale only when no configured plug is fresh.
            return bool(plugs) and all(
                self._plug_item_is_stale(record, plug_name, state, now)
                for plug_name, state in plugs.items()
            )
        limit = self._freshness_limit(name)
        if limit is not None and max(0.0, now - float(record["lastGoodAt"])) > limit:
            return True
        return bool(record.get("stale"))

    def activate_client(self, wait_timeout: float | None = None) -> None:
        """Renew active cadence and refresh stale control state before use.

        A transition from idle wakes every collector immediately, but recent
        last-good control data remains usable. The default state read never
        blocks; explicit callers may still wait for one bounded completion when
        a control subsystem is genuinely beyond its freshness limit.
        """
        now = self._now()
        targets: dict[str, int] = {}
        with self._condition:
            was_active = self._is_active_locked(now)
            self._active_until = max(self._active_until, now + self.active_lease_seconds)
            # App foreground state reads drive one shared cloud refresh per
            # minute. No timer/lease tail polls VeSync after clients stop reading.
            # Use the explicit-refresh debounce too, including failed attempts;
            # automatic reads never bypass the VeSync cooldown.
            purifier = self._records.get("purifier")
            if purifier is not None:
                last = purifier.get("lastRequestedAt")
                if not purifier["refreshing"] and (last is None or now - last >= 60.0):
                    purifier["lastRequestedAt"] = now
                    purifier["nextDue"] = 0.0
            if not was_active:
                for name, record in self._records.items():
                    if name != "purifier":
                        record["nextDue"] = 0.0
                    if name == "plugs" and self._record_is_stale(name, record, now):
                        targets[name] = int(record.get("completionCount", 0))
            self._condition.notify_all()
        self.start()

        timeout = self.activation_wait_seconds if wait_timeout is None else max(0.0, float(wait_timeout))
        if not targets or timeout <= 0:
            return
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                pending = [
                    name
                    for name, baseline in targets.items()
                    if int(self._records[name].get("completionCount", 0)) <= baseline
                ]
                if not pending:
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self._condition.wait(timeout=remaining)

    def request_refresh(self, name: str, *, retry_cooldown: bool = False) -> None:
        now = self._now()
        with self._condition:
            if name in self._records:
                record = self._records[name]
                if name == "purifier":
                    last = record.get("lastRecoveryRequestedAt" if retry_cooldown else "lastRequestedAt")
                    if record["refreshing"] or (last is not None and now - last < 60.0):
                        return
                    record["lastRequestedAt"] = now
                    record["retryCooldown"] = bool(retry_cooldown)
                    if retry_cooldown:
                        record["lastRecoveryRequestedAt"] = now
                record["nextDue"] = 0.0
            self._active_until = max(self._active_until, now + self.active_lease_seconds)
            self._condition.notify_all()
        self.start()

    def _apply_authoritative_locked(self, name: str, data: dict) -> None:
        record = self._records[name]
        now = self._now()
        record["data"] = copy.deepcopy(data)
        record["updatedAt"] = _iso_now()
        record["lastGoodAt"] = now
        record["error"] = None
        record["stale"] = False
        record["nextDue"] = float("inf") if name == "purifier" else 0.0
        record["revision"] += 1

    def apply_plug_result(self, plug: Any) -> bool:
        """Merge an authoritative desired-state command into the cache."""
        if not isinstance(plug, dict):
            return False
        name = plug.get("name")
        is_on = plug.get("is_on")
        if not isinstance(name, str) or not name or not isinstance(is_on, bool):
            return False
        with self._condition:
            record = self._records.get("plugs")
            if record is None:
                return False
            data = copy.deepcopy(record["data"]) if isinstance(record["data"], dict) else {"ok": True, "plugs": {}}
            plugs = copy.deepcopy(data.get("plugs")) if isinstance(data.get("plugs"), dict) else {}
            state = copy.deepcopy(plugs.get(name)) if isinstance(plugs.get(name), dict) else {}
            state.update({"ok": True, "stale": False, "isOn": is_on, "error": None})
            for source, target in (("host", "host"), ("rssi", "rssi"), ("alias", "alias")):
                if source in plug:
                    state[target] = copy.deepcopy(plug[source])
            plugs[name] = state
            data.update({
                "ok": True,
                "count": len(plugs),
                "onCount": sum(1 for value in plugs.values() if isinstance(value, dict) and value.get("isOn") is True),
                "plugs": plugs,
            })
            self._apply_authoritative_locked("plugs", data)
            record["itemLastGoodAt"][name] = record["lastGoodAt"]
            self._condition.notify_all()
        self.start()
        return True

    def apply_purifier_result(self, data: Any, expected: dict | None = None,
                              *, read_revision: int | None = None) -> bool:
        if not isinstance(data, dict):
            return False
        state = _purifier_state(data)
        with self._condition:
            record = self._records.get("purifier")
            if record is None:
                return False
            if read_revision is not None and (
                read_revision != record["revision"] or "inflight" in record["writeBarriers"].values()
                or data.get("verification_pending") is True
            ):
                return False
            collection = record.get("data") or {}
            cid = data.get("cid")
            device_id = _purifier_id(cid) if isinstance(cid, str) else None
            if read_revision is not None and (
                record.get("pending") or record.get("itemPending", {}).get(device_id)
            ):
                # A direct status response has no pending-write reconciliation
                # policy. Keep that job with the authoritative batch collector.
                return False
            if isinstance(collection.get("devices"), dict):
                if device_id not in collection["devices"]:
                    return False
                pending = data.get("verification_pending") is True and bool(expected)
                state.update(deviceID=device_id, updatedAt=_iso_now(), stale=pending, refreshing=False)
                state["verificationPending"] = pending
                if pending:
                    record.setdefault("itemPending", {})[device_id] = {"expected": copy.deepcopy(expected), "deadline": self._now() + 90.0}
                    state["pendingCommand"] = _purifier_pending_command(expected)
                else:
                    record.setdefault("itemPending", {}).pop(device_id, None)
                collection["devices"][device_id] = state
                if read_revision is not None and not state["verificationPending"]:
                    record["writeBarriers"].pop(device_id, None)
                record["itemLastGoodAt"][device_id] = self._now()
                record["revision"] += 1
                record["nextDue"] = float("inf")
                self._sync_purifier_default_locked()
                self._condition.notify_all()
                return True
            if data.get("verification_pending") is True and expected:
                # VeSync accepted the write but returned old cloud state. Keep
                # that data visible only as stale until an explicit refresh;
                # do not start a background verification loop.
                record["data"] = copy.deepcopy(state)
                record["updatedAt"] = _iso_now()
                record["error"] = None
                record["stale"] = True
                record["nextDue"] = float("inf")
                record["pending"] = {
                    "expected": copy.deepcopy(expected),
                    "deadline": self._now() + 90.0,
                }
                record["revision"] += 1
            else:
                record["pending"] = None
                self._apply_authoritative_locked("purifier", state)
            self._condition.notify_all()
        self.start()
        return True

    def _run_scheduler(self) -> None:
        while True:
            with self._condition:
                if self._stop.is_set():
                    return
                now = self._now()
                executor = self._executor
                if executor is None:
                    return
                for name, record in self._records.items():
                    if not record["refreshing"] and now >= record["nextDue"]:
                        record["refreshing"] = True
                        revision = record["revision"]
                        future = executor.submit(self._collect_one, name)
                        future.add_done_callback(lambda f, n=name, r=revision: self._complete(n, f, r))

                due_times = [
                    float(record["nextDue"])
                    for record in self._records.values()
                    if not record["refreshing"]
                ]
                if not due_times:
                    self._condition.wait()
                    continue
                wait_seconds = max(0.0, min(due_times) - self._now())
                if wait_seconds <= 0:
                    # A zero-due item can remain only when its submission raced
                    # a callback. Yield on the condition rather than spinning.
                    self._condition.wait(timeout=0.01)
                else:
                    self._condition.wait(timeout=min(wait_seconds, 60.0))

    def _collect_one(self, name: str) -> dict:
        try:
            if name in self._retry_collectors:
                with self._condition:
                    retry = self._records[name].pop("retryCooldown", False)
                return self._retry_collectors[name](retry)
            return self.collectors[name]()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": _safe_error(exc)}

    def _sync_purifier_default_locked(self) -> None:
        record = self._records["purifier"]
        data = record["data"]
        devices = data.get("devices", {})
        default_id = data.get("defaultDeviceID")
        default = copy.deepcopy(devices.get(default_id, {"ok": False, "error": "Default purifier unavailable"}))
        record["data"] = {**default, "devices": devices, "defaultDeviceID": default_id}

    def _complete_purifier_collection_locked(self, result: dict, now: float) -> None:
        record = self._records["purifier"]
        previous = (record.get("data") or {}).get("devices", {})
        pending = record.setdefault("itemPending", {})
        merged = {}
        for device_id, item in result["devices"].items():
            if item.get("ok") is True:
                record["writeBarriers"].pop(device_id, None)
                item = copy.deepcopy(item)
                item.update(stale=False, updatedAt=_iso_now(), refreshing=False)
                record["itemLastGoodAt"][device_id] = now
                pending_info = pending.get(device_id) or {}
                expected = pending_info.get("expected")
                if expected and not _purifier_matches(item, expected) and now < pending_info.get("deadline", 0):
                    item.update(verificationPending=True, stale=True, pendingCommand=_purifier_pending_command(expected))
                else:
                    pending.pop(device_id, None)
                    item["verificationPending"] = False
                    if expected and not _purifier_matches(item, expected):
                        item["lastError"] = "Previous change could not be confirmed; current reading shown."
            else:
                item = {**copy.deepcopy(previous.get(device_id, {})), **item,
                        "stale": True, "lastError": item.get("error", "Refresh failed")}
            merged[device_id] = item
        record["writeBarriers"] = {key: value for key, value in record["writeBarriers"].items() if key in merged}
        record["data"] = {"devices": merged, "defaultDeviceID": result.get("defaultDeviceID")}
        self._sync_purifier_default_locked()
        record.update(updatedAt=_iso_now(), lastGoodAt=now, stale=False, error=None, nextDue=float("inf"))

    def _complete_plug_collection_locked(self, result: dict[str, Any], now: float) -> None:
        """Merge aggregate plug reads without letting one device poison peers."""
        record = self._records["plugs"]
        previous_data = record.get("data") if isinstance(record.get("data"), dict) else {}
        previous_plugs = previous_data.get("plugs") if isinstance(previous_data.get("plugs"), dict) else {}
        incoming_plugs = result.get("plugs") if isinstance(result.get("plugs"), dict) else {}
        prior_timestamps = record.get("itemLastGoodAt")
        timestamps = dict(prior_timestamps) if isinstance(prior_timestamps, dict) else {}
        aggregate_last_good = record.get("lastGoodAt")
        limit = self._freshness_limit("plugs")
        merged: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        live_success = False

        for plug_name, raw_state in incoming_plugs.items():
            state = copy.deepcopy(raw_state) if isinstance(raw_state, dict) else {}
            if state.get("ok") is True and isinstance(state.get("isOn"), bool):
                record["writeBarriers"].pop(plug_name, None)
                state["stale"] = False
                state["error"] = None
                merged[plug_name] = state
                timestamps[plug_name] = now
                live_success = True
                continue

            error = _safe_error(state.get("error") or "plug status unavailable", 300)
            errors.append(f"{plug_name}: {error}")
            previous = previous_plugs.get(plug_name)
            last_good = timestamps.get(plug_name, aggregate_last_good)
            if isinstance(previous, dict) and isinstance(previous.get("isOn"), bool):
                retained = copy.deepcopy(previous)
                expired = last_good is None or (
                    limit is not None and max(0.0, now - float(last_good)) > limit
                )
                retained.update({"ok": True, "stale": expired, "error": error})
                merged[plug_name] = retained
                if last_good is not None:
                    timestamps[plug_name] = last_good
            else:
                state.update({"ok": False, "stale": True, "error": error})
                merged[plug_name] = state
                timestamps.pop(plug_name, None)

        timestamps = {plug_name: timestamps[plug_name] for plug_name in merged if plug_name in timestamps}
        data = copy.deepcopy(result)
        data.update({
            "ok": not merged or any(isinstance(state.get("isOn"), bool) for state in merged.values()),
            "count": len(merged),
            "onCount": sum(1 for state in merged.values() if state.get("isOn") is True),
            "plugs": merged,
        })
        record["data"] = data
        record["updatedAt"] = _iso_now()
        record["itemLastGoodAt"] = timestamps
        record["writeBarriers"] = {key: value for key, value in record["writeBarriers"].items() if key in merged}
        if live_success or (not merged and result.get("ok") is True):
            record["lastGoodAt"] = now
        record["error"] = "; ".join(errors) if errors else None
        record["stale"] = self._record_is_stale("plugs", record, now)

    def _complete(self, name: str, future: concurrent.futures.Future, revision: int) -> None:
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": _safe_error(exc)}
        now = self._now()
        with self._condition:
            record = self._records[name]
            record["refreshing"] = False
            record["completionCount"] += 1
            if revision != record["revision"]:
                # A command supplied newer authoritative data while this
                # collection was in flight. Discard the old read and collect
                # again rather than reverting the UI to pre-command state.
                record["nextDue"] = float("inf") if name == "purifier" else 0.0
                self._condition.notify_all()
                return
            if "inflight" in record["writeBarriers"].values():
                # A read completed while a write is outstanding. It is not
                # authoritative post-write evidence, even if it looks healthy.
                record["nextDue"] = now + self._interval_locked(name, now)
                self._condition.notify_all()
                return
            record.get("controlObserved", {}).clear()
            if name == "plugs" and isinstance(result, dict) and isinstance(result.get("plugs"), dict):
                record["nextDue"] = now + self._interval_locked(name, now)
                self._complete_plug_collection_locked(result, now)
                self._stamp_control_observations_locked(name, result)
                self._condition.notify_all()
                return
            if name == "purifier" and isinstance(result, dict) and isinstance(result.get("devices"), dict):
                self._complete_purifier_collection_locked(result, now)
                self._stamp_control_observations_locked(name, result)
                self._condition.notify_all()
                return
            pending = record.get("pending")
            if (
                name == "purifier"
                and isinstance(pending, dict)
                and isinstance(result, dict)
                and result.get("ok") is True
            ):
                expected = pending.get("expected")
                if isinstance(expected, dict) and _purifier_matches(result, expected):
                    record["pending"] = None
                elif now < float(pending.get("deadline", 0.0)):
                    record["data"] = copy.deepcopy(result)
                    record["updatedAt"] = _iso_now()
                    record["error"] = None
                    record["stale"] = True
                    record["nextDue"] = float("inf")
                    self._condition.notify_all()
                    return
                else:
                    record["data"] = copy.deepcopy(result)
                    record["updatedAt"] = _iso_now()
                    record["error"] = "purifier write verification is still pending"
                    record["stale"] = True
                    record["pending"] = None
                    record["nextDue"] = now + self._interval_locked(name, now)
                    self._condition.notify_all()
                    return
            record["nextDue"] = now + self._interval_locked(name, now)
            if isinstance(result, dict) and result.get("ok") is True:
                record["data"] = copy.deepcopy(result)
                record["updatedAt"] = _iso_now()
                record["lastGoodAt"] = now
                record["error"] = None
                record["stale"] = False
            else:
                record["error"] = _safe_error(result.get("error") if isinstance(result, dict) else result)
                limit = self._freshness_limit(name)
                last_good = record.get("lastGoodAt")
                recent_last_good = (
                    limit is not None
                    and record.get("data") is not None
                    and last_good is not None
                    and not isinstance(record.get("pending"), dict)
                    and max(0.0, now - float(last_good)) <= limit
                )
                # One transient read failure must not disable a recently
                # confirmed control. Age expiry and pending verification still
                # become stale through _record_is_stale.
                record["stale"] = not recent_last_good
            self._condition.notify_all()

    def snapshot(self, client_active: bool = False, wait_timeout: float | None = None) -> dict:
        if client_active:
            self.activate_client(wait_timeout=wait_timeout)
        else:
            self.start()
        with self._lock:
            records = copy.deepcopy(self._records)
        subsystems: dict[str, dict] = {}
        metadata: dict[str, dict] = {}
        effective_stale: dict[str, bool] = {}
        now = self._now()
        for name, record in records.items():
            data = copy.deepcopy(record["data"]) if record["data"] is not None else {
                "ok": False,
                "error": record["error"] or "loading",
            }
            stale = self._record_is_stale(name, record, now)
            effective_stale[name] = stale
            data["stale"] = stale
            if name == "plugs" and isinstance(data.get("plugs"), dict):
                for plug_name, state in data["plugs"].items():
                    if isinstance(state, dict):
                        state["stale"] = self._plug_item_is_stale(record, plug_name, state, now)
                        if error := self._write_error(record, plug_name):
                            state["error"] = error
            data["refreshing"] = bool(record["refreshing"])
            if record["updatedAt"]:
                data["updatedAt"] = record["updatedAt"]
            if record["error"]:
                data["lastError"] = record["error"]
            if name == "purifier" and isinstance(data.get("devices"), dict):
                for device_id, item in data["devices"].items():
                    item["stale"] = self._purifier_item_is_stale(record, device_id, item, now)
                    if error := self._write_error(record, device_id):
                        item["lastError"] = error
                    item["refreshing"] = bool(record["refreshing"])
                    if record["error"]:
                        item["lastError"] = record["error"]
                        item["stale"] = True
                default = data["devices"].get(data.get("defaultDeviceID"), {"ok": False, "stale": True})
                data = {**default, "devices": data["devices"], "defaultDeviceID": data.get("defaultDeviceID")}
                effective_stale[name] = data.get("stale", True)
                stale = effective_stale[name]
            if name == "purifier" and not isinstance(data.get("devices"), dict):
                pending = record.get("pending")
                if isinstance(pending, dict):
                    data["verificationPending"] = True
                    pending_command = _purifier_pending_command(pending.get("expected"))
                    if pending_command is not None:
                        data["pendingCommand"] = pending_command
                else:
                    data["verificationPending"] = False
                    data.pop("pendingCommand", None)
            subsystems[name] = data
            age = None if record["lastGoodAt"] is None else max(0.0, now - record["lastGoodAt"])
            if name == "purifier" and isinstance(data.get("devices"), dict):
                default_last_good = record["itemLastGoodAt"].get(data.get("defaultDeviceID"))
                age = None if default_last_good is None else max(0.0, now - default_last_good)
            metadata[name] = {
                "ok": data.get("ok") is True,
                "updatedAt": record["updatedAt"],
                "ageSeconds": round(age, 1) if age is not None else None,
                "stale": stale,
                "refreshing": bool(record["refreshing"]),
                "error": record["error"],
            }

        plugs = subsystems.get("plugs", {})
        purifier = subsystems.get("purifier", {})
        pi = subsystems.get("pi", {})
        critical_records = {
            name: record for name, record in records.items() if name not in self.NONCRITICAL_SUBSYSTEMS
        }
        ages = [
            metadata[name]["ageSeconds"]
            for name in critical_records
            if metadata[name]["ageSeconds"] is not None
        ]
        return {
            "ok": True,
            "loading": any(record["data"] is None for record in critical_records.values()),
            "refreshing": any(record["refreshing"] for record in critical_records.values()),
            "stale": any(effective_stale[name] for name in critical_records),
            "generatedAt": _iso_now(),
            "ageSeconds": round(max(ages), 1) if ages else None,
            "version": self._version,
            "uptimeSeconds": round(time.time() - self._started_at, 1),
            "subsystems": subsystems,
            "subsystemsMeta": metadata,
            "summary": {
                "plugsOn": plugs.get("onCount") if plugs.get("ok") else None,
                "plugsTotal": plugs.get("count") if plugs.get("ok") else None,
                "purifierOn": purifier.get("isOn") if purifier.get("ok") else None,
                "pm25": purifier.get("pm25") if purifier.get("ok") else None,
                "piActive": pi.get("active") if pi.get("ok") else None,
            },
        }
