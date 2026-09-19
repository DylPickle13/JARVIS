"""Dormant persistent control primitives. NOT wired into any live entry point.

Explicit local POSIX storage only; no default path, environment, SDK or network.
All identity/readiness/handoff/observation evidence must come from trusted host
code, not request booleans. This is neither authentication nor an OS privilege
boundary. See docs/control-ledger.md before integrating or changing retention.
"""
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid

from . import client_policy as policy

MAX_RECORDS = 1024
MAX_BYTES = 1024 * 1024
MAX_ACTIVE = 32
MAX_TICKETS = 128
TTL_NS = 25_000_000_000
CLOCK_SKEW_NS = 2_000_000_000
_RECORD = "record.json"
_NEXT = "record.next"
_LOCK = "owner.lock"
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_OUTCOMES = {"reserved", *(x.value for x in (policy.Outcome.ACKNOWLEDGED,
             policy.Outcome.PENDING, policy.Outcome.UNKNOWN))}


class LedgerError(RuntimeError):
    def __init__(self, code, *, prior_outcome=None):
        super().__init__(code)  # Never include paths, identifiers, payloads or exception prose.
        self.code = code
        self.prior_outcome = prior_outcome


@dataclass(frozen=True)
class Intent:
    cohort: policy.Cohort
    incarnation: str
    epoch: int
    client: str  # Host-derived opaque principal fingerprint, not caller identity assertion.
    request_id: str
    resource: str  # Host-derived canonical-resource fingerprint, never a raw host/CID.
    command: str  # Host-derived fingerprint of the validated action/parameters/target.
    action: str
    window: str


@dataclass(frozen=True)
class SubmissionWindow:
    token: str
    incarnation: str
    cohort: policy.Cohort
    epoch: int
    client: str


@dataclass(frozen=True)
class Observation:
    token: str
    incarnation: str
    cohort: policy.Cohort
    epoch: int
    resource: str
    revision: int


@dataclass(frozen=True)
class DispatchResult:
    outcome: policy.Outcome
    value: object = None  # Returned to host only, never persisted.


def _hex(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= policy.MAX_EPOCH


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _encode(data):
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(blob) > MAX_BYTES:
        raise LedgerError("store-capacity")
    return blob


def _validate(data):
    """Closed schema; corruption never falls back to an empty store."""
    if (type(data) is not dict or set(data) != {"schema", "revision", "incarnation", "cohorts", "records"}
            or type(data["schema"]) is not int or data["schema"] != 1 or not _integer(data["revision"])
            or not (data["incarnation"] is None and data["revision"] == 0
                    or data["revision"] > 0 and _hex(data["incarnation"], _HEX32))
            or type(data["cohorts"]) is not dict
            or set(data["cohorts"]) != {c.value for c in policy.Cohort}
            or type(data["records"]) is not list or len(data["records"]) > MAX_RECORDS):
        raise ValueError("invalid record")
    for name, value in data["cohorts"].items():
        if type(value) is not dict or set(value) != {"epoch", "mode"}:
            raise ValueError("invalid cohort")
        state = policy.Ownership(policy.Cohort(name), value["epoch"], policy.Mode(value["mode"]))
        if state.mode is policy.Mode.MIXED:
            raise ValueError("legacy mode is not activation")
    if data["revision"] == 0 and (data["records"] or any(
            value != {"epoch": 0, "mode": policy.Mode.CLOSED.value} for value in data["cohorts"].values())):
        raise ValueError("invalid bootstrap")
    seen = set()
    last_revision = 0
    for row in data["records"]:
        if (type(row) is not dict or set(row) != {"client", "request_id", "cohort", "incarnation", "epoch",
                "resource", "command", "action", "outcome", "unresolved", "revision"}
                or not all(_hex(row[k], _HEX64) for k in ("client", "resource", "command"))
                or not all(_hex(row[k], _HEX32) for k in ("request_id", "incarnation"))
                or type(row["cohort"]) is not str or row["cohort"] not in data["cohorts"]
                or not _integer(row["epoch"], 1) or row["epoch"] > data["cohorts"][row["cohort"]]["epoch"]
                or not _integer(row["revision"], 1) or row["revision"] > data["revision"]
                or type(row["outcome"]) is not str or row["outcome"] not in _OUTCOMES
                or type(row["unresolved"]) is not bool
                or row["outcome"] == "reserved" and row["unresolved"] is not True):
            raise ValueError("invalid reservation")
        spec = policy.COMMANDS.get(row["action"]) if type(row["action"]) is str else None
        if spec is None or spec.effect != "write" or spec.integration != row["cohort"]:
            raise ValueError("invalid action")
        key = (row["client"], row["request_id"])
        if key in seen or row["revision"] <= last_revision:
            raise ValueError("duplicate or reordered reservation")
        seen.add(key)
        last_revision = row["revision"]
    return data


class ControlLedger:
    """One local owner, nonblocking cross-process lease; atomic bounded JSON commits.

    API ownership starts CLOSED on every open. Initialization is explicit and
    refuses existing directories. No production caller imports this module yet.
    """
    def __init__(self, path, *, monotonic_ns=time.monotonic_ns, wall_ns=time.time_ns):
        self._path = Path(path)
        self._mono, self._wall = monotonic_ns, wall_ns
        self._mutex = threading.Lock()
        self._pid = os.getpid()
        self._dfd = self._lfd = None
        self._data = self._digest = None
        self._fault = False
        self._active = set()
        self._delegated = set()
        self._callback = threading.local()
        self._windows = {}
        self._observations = {}
        self._last_clock = None
        self._ticket_serial = 0

    @classmethod
    def initialize(cls, path):
        """Create a NEW dedicated private directory, never repair/reinitialize."""
        path = Path(path)
        if not path.is_absolute():
            raise LedgerError("absolute-path-required")
        try:
            path = path.parent.resolve(strict=True) / path.name
            os.mkdir(path, 0o700)
        except OSError:
            raise LedgerError("initialization-refused") from None
        store = cls(path)
        try:
            store._attach(create=True)
            data = {"schema": 1, "revision": 0, "incarnation": None,
                    "cohorts": {c.value: {"epoch": 0, "mode": policy.Mode.CLOSED.value}
                                for c in policy.Cohort}, "records": []}
            store._write(data, initial=True)
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        except (OSError, ValueError):
            raise LedgerError("initialization-failed") from None
        finally:
            store._release()

    @classmethod
    def open(cls, path, **clocks):
        store = cls(path, **clocks)
        try:
            store._attach()
            raw = store._read_file(_RECORD)
            store._data = _validate(json.loads(raw, object_pairs_hook=_pairs))
            store._digest = hashlib.sha256(raw).digest()
            # A pre-replace interrupted commit cannot have granted dispatch. The
            # old complete record is authoritative. Remove only our bounded file.
            try:
                store._read_file(_NEXT)
            except FileNotFoundError:
                pass
            else:
                os.unlink(_NEXT, dir_fd=store._dfd)
                os.fsync(store._dfd)
            data = store._copy()
            incarnation = uuid.uuid4().hex
            if (incarnation == data["incarnation"]
                    or any(r["incarnation"] == incarnation for r in data["records"])):
                raise LedgerError("incarnation-collision")
            data["incarnation"] = incarnation
            for cohort in policy.Cohort:
                closed = policy.restart_closed(store._state(cohort))
                data["cohorts"][cohort.value] = {"epoch": closed.epoch, "mode": closed.mode.value}
            for row in data["records"]:
                if row["outcome"] == "reserved":
                    row["outcome"] = policy.Outcome.UNKNOWN.value
                    row["unresolved"] = True
            store._commit(data)
            store._clock()
            return store
        except BaseException as exc:
            store._release()
            if isinstance(exc, LedgerError):
                raise
            raise LedgerError("store-open-failed") from None

    def _attach(self, create=False):
        if not self._path.is_absolute():
            raise LedgerError("absolute-path-required")
        self._path = self._path.parent.resolve(strict=True) / self._path.name
        self._dfd = os.open(self._path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(self._dfd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise LedgerError("unsafe-directory")
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_CREAT | os.O_EXCL if create else 0)
        self._lfd = os.open(_LOCK, flags, 0o600, dir_fd=self._dfd)
        self._secure_file(os.fstat(self._lfd))
        try:
            fcntl.flock(self._lfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Closing an unacquired descriptor must not issue LOCK_UN.
            os.close(self._lfd)
            self._lfd = None
            raise LedgerError("store-busy") from None
        if set(os.listdir(self._dfd)) - {_RECORD, _NEXT, _LOCK}:
            raise LedgerError("unexpected-store-files")

    @staticmethod
    def _secure_file(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > MAX_BYTES):
            raise LedgerError("unsafe-store-file")

    def _read_file(self, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._dfd)
        try:
            self._secure_file(os.fstat(fd))
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise LedgerError("unsafe-store-file")
            return raw
        finally:
            os.close(fd)

    def _verify(self):
        if os.getpid() != self._pid:
            raise LedgerError("forked-store")
        for actual, expected in ((os.stat(self._path, follow_symlinks=False), os.fstat(self._dfd)),
                                 (os.stat(_LOCK, dir_fd=self._dfd, follow_symlinks=False), os.fstat(self._lfd))):
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                raise LedgerError("store-identity-changed")
        directory = os.fstat(self._dfd)
        if stat.S_IMODE(directory.st_mode) != 0o700 or directory.st_uid != os.geteuid():
            raise LedgerError("unsafe-directory")
        self._secure_file(os.fstat(self._lfd))
        if self._digest is not None and hashlib.sha256(self._read_file(_RECORD)).digest() != self._digest:
            raise LedgerError("store-changed")

    def _write(self, data, initial=False):
        _validate(data)
        raw = _encode(data)
        if not initial:
            self._verify()
        fd = os.open(_NEXT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._dfd)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
                if hasattr(fcntl, "F_FULLFSYNC"):
                    fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
        finally:
            os.close(fd)
        os.replace(_NEXT, _RECORD, src_dir_fd=self._dfd, dst_dir_fd=self._dfd)
        os.fsync(self._dfd)
        self._data, self._digest = data, hashlib.sha256(raw).digest()

    def _commit(self, data):
        data["revision"] = self._data["revision"] + 1
        try:
            self._write(data)
        except BaseException:
            self._fault = True
            raise LedgerError("store-commit-failed") from None

    def _copy(self):
        return json.loads(_encode(self._data))

    def _state(self, cohort):
        if type(cohort) is not policy.Cohort:
            raise LedgerError("invalid-cohort")
        value = self._data["cohorts"][cohort.value]
        return policy.Ownership(cohort, value["epoch"], policy.Mode(value["mode"]))

    @contextmanager
    def _locked(self, *, reject_busy=False):
        if os.getpid() != self._pid:
            raise LedgerError("forked-store")  # Check before inherited lock acquisition.
        if not self._mutex.acquire(blocking=not reject_busy):
            # Another submission with this nonce might already be reserving it.
            raise LedgerError("admission-busy", prior_outcome=policy.Outcome.UNKNOWN)
        try:
            if self._fault or self._dfd is None or self._data is None:
                raise LedgerError("store-unavailable")
            try:
                self._verify()
            except BaseException:
                self._fault = True
                raise LedgerError("store-unavailable") from None
            yield
        finally:
            self._mutex.release()

    def _clock(self):
        try:
            now = (self._mono(), self._wall())
            if not all(type(n) is int and n >= 0 for n in now):
                raise ValueError()
            if self._last_clock is not None:
                delta = tuple(a - b for a, b in zip(now, self._last_clock))
                if min(delta) < 0 or abs(delta[0] - delta[1]) > CLOCK_SKEW_NS:
                    raise ValueError()
            self._last_clock = now
            return now
        except BaseException:
            self._fault = True
            raise LedgerError("clock-untrusted") from None

    def _ticket(self):
        # Never reissue an expired token in this incarnation, even on RNG collision.
        if self._ticket_serial >= policy.MAX_EPOCH:
            self._fault = True
            raise LedgerError("ticket-counter-exhausted")
        self._ticket_serial += 1
        return f"{self._ticket_serial:016x}" + uuid.uuid4().hex[:16]

    def _expire(self, entries, now):
        for key, (_, deadline) in list(entries.items()):
            if any(n >= d for n, d in zip(now, deadline)):
                del entries[key]

    def snapshot(self, cohort):
        with self._locked():
            return self._state(cohort)

    def context(self, cohort):
        """Immutable ownership/incarnation snapshot for trusted host construction.

        A snapshot is not admission; execute_once still rechecks authoritative state.
        """
        with self._locked():
            return self._state(cohort), self._data["incarnation"]

    def pending_resources(self, cohort):
        with self._locked():
            self._state(cohort)
            return frozenset(r["resource"] for r in self._data["records"]
                             if r["cohort"] == cohort.value and r["unresolved"])

    def active_count(self):
        """Trusted lifecycle probe; zero alone is NOT worker-drain evidence."""
        with self._locked():
            return len(self._active)

    def transition(self, cohort, destination, evidence=None):
        """Trusted host control only; no network/CLI maintenance operation exists."""
        with self._locked():
            old = self._state(cohort)
            if destination is policy.Mode.DRAINING:
                new = policy.request_drain(old)
            elif destination in (policy.Mode.MAINTENANCE, policy.Mode.API):
                if any(self._data["records"][i]["cohort"] == cohort.value for i in self._active):
                    raise LedgerError("writes-active")
                if type(evidence) is not policy.HandoffEvidence:
                    raise LedgerError("handoff-evidence-required")
                fn = policy.enter_maintenance if destination is policy.Mode.MAINTENANCE else policy.activate_api
                new = fn(old, evidence)
            else:
                raise LedgerError("invalid-transition")
            if new != old:
                data = self._copy()
                data["cohorts"][cohort.value] = {"epoch": new.epoch, "mode": new.mode.value}
                self._commit(data)
            return new

    def issue_window(self, cohort, client):
        with self._locked():
            state = self._state(cohort)
            if state.mode is not policy.Mode.API or not _hex(client, _HEX64):
                raise LedgerError("window-unavailable")
            now = self._clock()
            self._expire(self._windows, now)
            if len(self._windows) >= MAX_TICKETS:
                raise LedgerError("window-capacity")
            window = SubmissionWindow(self._ticket(), self._data["incarnation"], cohort, state.epoch, client)
            self._windows[window.token] = (window, tuple(n + TTL_NS for n in now))
            return window

    def _check_window(self, intent):
        now = self._clock()
        self._expire(self._windows, now)
        entry = self._windows.get(intent.window)
        if entry is None:
            raise LedgerError("window-expired-or-unknown")
        window = entry[0]
        if (intent.incarnation != self._data["incarnation"] or window.incarnation != intent.incarnation
                or window.cohort is not intent.cohort or window.epoch != intent.epoch or window.client != intent.client):
            raise LedgerError("window-scope-mismatch")

    def _check_intent(self, intent):
        if (type(intent) is not Intent or type(intent.cohort) is not policy.Cohort
                or not _integer(intent.epoch, 1)
                or not all(_hex(x, _HEX32) for x in (intent.incarnation, intent.request_id, intent.window))
                or not all(_hex(x, _HEX64) for x in (intent.client, intent.resource, intent.command))):
            raise LedgerError("invalid-intent")
        for row in self._data["records"]:
            if (row["client"], row["request_id"]) == (intent.client, intent.request_id):
                prior = policy.Outcome.UNKNOWN if row["outcome"] == "reserved" else policy.Outcome(row["outcome"])
                raise LedgerError("duplicate-intent", prior_outcome=prior)
        self._check_window(intent)

    def execute_once(self, intent, readiness, operation):
        """Reserve durably then call operation once, outside the ledger lock.

        readiness() is a fast, trusted, non-reentrant host check under admission,
        NOT a collector/network call. operation() returns DispatchResult and must
        retain existing dispatcher/SDK guards. A grant counts active until it exits;
        draining may begin but maintenance cannot finish while it is active.
        """
        with self._locked(reject_busy=True):
            self._check_intent(intent)
            ready = readiness()
            if type(ready) is not policy.Readiness:
                raise LedgerError("invalid-readiness")
            self._check_window(intent)  # Readiness cannot silently extend expiry.
            plan = policy.plan_write(intent.action, self._state(intent.cohort), ready)
            if plan.route is not policy.Route.API or intent.epoch != plan.epoch:
                raise LedgerError("write-not-admitted")
            if len(self._active) >= MAX_ACTIVE:
                raise LedgerError("writes-capacity")
            if any(r["cohort"] == intent.cohort.value and r["resource"] == intent.resource and r["unresolved"]
                   for r in self._data["records"]):
                raise LedgerError("resource-unresolved")
            if len(self._data["records"]) >= MAX_RECORDS:
                raise LedgerError("store-capacity")
            data = self._copy()
            index = len(data["records"])
            data["records"].append({"client": intent.client, "request_id": intent.request_id,
                "cohort": intent.cohort.value, "incarnation": intent.incarnation, "epoch": intent.epoch,
                "resource": intent.resource, "command": intent.command, "action": intent.action,
                "outcome": "reserved", "unresolved": True, "revision": data["revision"] + 1})
            self._commit(data)  # No callback/receipt before file + directory sync complete.
            self._active.add(index)
        outcome = policy.Outcome.UNKNOWN
        try:
            with self._locked():
                self._check_window(intent)  # Slow durability must not extend freshness.
                state = self._state(intent.cohort)
                if state.mode is not policy.Mode.API or state.epoch != intent.epoch:
                    raise LedgerError("write-not-admitted")
            previous = getattr(self._callback, 'active', None)
            self._callback.active = (index, intent)
            try:
                result = operation()
            finally:
                self._callback.active = previous
            if (type(result) is not DispatchResult or result.outcome not in
                    (policy.Outcome.ACKNOWLEDGED, policy.Outcome.PENDING, policy.Outcome.UNKNOWN)):
                raise LedgerError("invalid-dispatch-result")
            outcome = result.outcome
            return result
        finally:
            # Even invalid results, BaseException/cancellation, and failed completion
            # commits leave a durable unresolved reservation, never a replay candidate.
            try:
                with self._locked():
                    data = self._copy()
                    data["records"][index]["outcome"] = outcome.value
                    self._commit(data)
            finally:
                if os.getpid() == self._pid:
                    with self._mutex:
                        self._active.discard(index)
                        self._delegated.discard(index)

    def claim_delegation(self, *, cohort, resource, command, action, directory):
        """One worker delegation from the CURRENT callback thread, never a snapshot.

        Claim is consumed before publishing a file/spawning a child. No refund on
        later failures. A restart cannot revive it: open closes ownership and turns
        interrupted reservations unknown. No disk schema change or reset is needed.
        Returned timestamps retain the ORIGINAL submission-window expiry.
        """
        with self._locked():
            current = getattr(self._callback, 'active', None)
            if current is None:
                raise LedgerError('delegation-outside-callback')
            index, intent = current
            if index not in self._active or index in self._delegated:
                raise LedgerError('delegation-unavailable')
            if (cohort is not intent.cohort or resource != intent.resource
                    or command != intent.command or action != intent.action):
                raise LedgerError('delegation-binding-mismatch')
            self._check_window(intent)
            state = self._state(cohort)
            if state.mode is not policy.Mode.API or state.epoch != intent.epoch:
                raise LedgerError('delegation-ownership-closed')
            row = self._data['records'][index]
            if row['outcome'] != 'reserved' or row['unresolved'] is not True:
                raise LedgerError('delegation-unavailable')
            # A grant published beside another ledger must never borrow this
            # owner's in-memory callback authority. Compare open directory identity.
            try:
                named = os.stat(directory, follow_symlinks=False)
                opened = os.fstat(self._dfd)
                if (not stat.S_ISDIR(named.st_mode) or
                        (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)):
                    raise OSError()
            except (OSError, TypeError, ValueError):
                raise LedgerError('delegation-store-mismatch') from None
            self._delegated.add(index)
            data = {key: value for key, value in row.items() if key not in ('outcome', 'unresolved')}
            expires = self._windows[intent.window][1]
            return {**data, 'monotonic': expires[0] - TTL_NS, 'wall': expires[1] - TTL_NS}

    def begin_observation(self, cohort, resource):
        with self._locked():
            state = self._state(cohort)
            if (state.mode not in (policy.Mode.MAINTENANCE, policy.Mode.API) or not _hex(resource, _HEX64)
                    or self._resource_active(cohort, resource)):
                raise LedgerError("observation-not-admitted")
            now = self._clock()
            self._expire(self._observations, now)
            if len(self._observations) >= MAX_TICKETS:
                raise LedgerError("observation-capacity")
            ticket = Observation(self._ticket(), self._data["incarnation"], cohort, state.epoch,
                                 resource, self._data["revision"])
            self._observations[ticket.token] = (ticket, tuple(n + TTL_NS for n in now))
            return ticket

    def _resource_active(self, cohort, resource):
        return any(self._data["records"][i]["cohort"] == cohort.value
                   and self._data["records"][i]["resource"] == resource for i in self._active)

    def reconcile(self, ticket, *, reconciled):
        return self._reconcile(ticket, reconciled=reconciled, check=nullcontext)

    def reconcile_checked(self, ticket, *, command, check):
        """Trusted read-proof context holds the coordinator lock through commit.

        Lock order is ledger -> coordinator, never the reverse. Only unresolved
        reservations matching this exact command may be cleared. No row is removed.
        """
        if not _hex(command, _HEX64):
            raise LedgerError("invalid-command-proof")
        return self._reconcile(ticket, reconciled=True, check=check, command=command)

    def _reconcile(self, ticket, *, reconciled, check, command=None):
        """Consume a host-only read-start ticket; never trust client evidence.

        reconciled=True means the coordinator validated a NEW response, identity,
        freshness and applicable expectations, not merely HTTP200 or SDK cache.
        No earlier/during-write read or maintenance-era ticket can clear a barrier.
        """
        with self._locked():
            now = self._clock()
            self._expire(self._observations, now)
            entry = self._observations.pop(ticket.token, None) if type(ticket) is Observation else None
            if entry is None or entry[0] is not ticket or reconciled is not True:
                raise LedgerError("invalid-observation")
            state = self._state(ticket.cohort)
            if (ticket.incarnation != self._data["incarnation"] or ticket.epoch != state.epoch
                    or state.mode not in (policy.Mode.MAINTENANCE, policy.Mode.API)
                    or self._resource_active(ticket.cohort, ticket.resource)):
                raise LedgerError("stale-observation")
            data = self._copy()
            rows = [r for r in data["records"] if r["cohort"] == ticket.cohort.value
                    and r["resource"] == ticket.resource]
            if any(r["revision"] > ticket.revision or r["outcome"] == "reserved" for r in rows):
                raise LedgerError("stale-observation")
            if command is not None and any(r["unresolved"] and r["command"] != command for r in rows):
                raise LedgerError("command-proof-mismatch")
            with check():
                # Waiting for the state lock must not extend this read ticket.
                if any(n >= deadline for n, deadline in zip(self._clock(), entry[1])):
                    raise LedgerError("expired-observation")
                if any(r["unresolved"] for r in rows):
                    for row in rows:
                        row["unresolved"] = False
                    self._commit(data)

    def _release(self):
        if self._lfd is not None:
            # Do NOT unlock an inherited open file description in a forked child.
            if os.getpid() == self._pid:
                fcntl.flock(self._lfd, fcntl.LOCK_UN)
            os.close(self._lfd)
            self._lfd = None
        if self._dfd is not None:
            os.close(self._dfd)
            self._dfd = None

    def close(self):
        if os.getpid() != self._pid:
            raise LedgerError("forked-store")
        with self._mutex:
            if self._active:
                raise LedgerError("writes-active")
            self._release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
