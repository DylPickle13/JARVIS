"""Dormant protocol-to-device-dispatch bridge. No production caller imports this.

Explicit immutable catalogue + existing coordinator/admission/runner dependencies;
no environment, listener, credentials, SDK construction, collection or fallback.
The authorizer is a trusted, fast host probe, never client-supplied evidence.
"""
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
import hashlib
import json
import re
from types import MappingProxyType

from . import client_policy as policy
from .control import DeviceCommandDispatcher
from .control_ledger import DispatchResult
from .control_protocol import Access, BoundWrite, Command
from .commands import PLUG_NAME_RE
from .devices import _purifier_command_data, _purifier_id, _purifier_expectation


class HostError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogueEntry:
    cohort: policy.Cohort
    name: str  # Lowercase plug alias or opaque purifier ID.
    identity: str = field(repr=False)  # Canonical host or opaque purifier ID.
    selector: str | None = field(default=None, repr=False)  # Private exact CID, purifier only.

    def __post_init__(self):
        if (type(self.cohort) is not policy.Cohort or type(self.name) is not str
                or type(self.identity) is not str or not 0 < len(self.identity) <= 256
                or any(not 33 <= ord(c) <= 126 for c in self.identity)):
            raise HostError("invalid-catalogue")
        if self.cohort is policy.Cohort.PLUGS:
            if (not 0 < len(self.name) <= 128 or not PLUG_NAME_RE.fullmatch(self.name)
                    or self.name != self.name.lower() or self.identity != self.identity.lower()
                    or self.selector is not None):
                raise HostError("invalid-catalogue")
        elif (not re.fullmatch(r"[0-9a-f]{24}", self.name) or self.identity != self.name
                or type(self.selector) is not str or not 0 < len(self.selector) <= 256
                or any(not 33 <= ord(c) <= 126 for c in self.selector)
                or _purifier_id(self.selector) != self.name):
            raise HostError("invalid-catalogue")


@dataclass(frozen=True)
class Catalogue:
    generation: str = field(repr=False)  # Trusted owner/catalogue generation, not a wire assertion.
    entries: tuple[CatalogueEntry, ...] = field(repr=False)

    def __post_init__(self):
        if (type(self.generation) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.generation)
                or type(self.entries) is not tuple or not 0 < len(self.entries) <= 128
                or any(type(e) is not CatalogueEntry for e in self.entries)
                or len({(e.cohort, e.name) for e in self.entries}) != len(self.entries)):
            raise HostError("invalid-catalogue")

    @property
    def fingerprint(self):
        rows = sorted((e.cohort.value, e.name, e.identity, e.selector) for e in self.entries)
        blob = json.dumps([self.generation, rows], separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return hashlib.sha256(b"jarvis-catalogue/1\x00" + blob).hexdigest()


@dataclass(frozen=True)
class _Context:
    owner: object = field(repr=False)
    command: Command
    access: Access = field(repr=False)
    epoch: tuple[str, int] = field(repr=False)


@dataclass(frozen=True)
class Readback:
    owner: object = field(repr=False)
    bound: BoundWrite = field(repr=False)
    ticket: object = field(repr=False)
    fence: object = field(repr=False)


class DeviceControlHost:
    """Construct only after trusted cohort handoff, never from HTTP/config switches.

    Constructor snapshots API ownership and arms epoch read fences; it never opens
    a store, activates ownership or starts collectors. Cached pre-activation state
    cannot pass readiness. State/ledger locks are never held in reverse order.
    authorize(access, command) must return exactly True and may not perform IO,
    re-enter the ledger, or acquire a lock held by a caller waiting on this host.
    """
    def __init__(self, *, store, state, admission, runner, cli, catalogue: Catalogue,
                 authorize, purifier_wait_seconds, delegation=None):
        if (type(catalogue) is not Catalogue or not callable(authorize)
                or delegation is not None and delegation is not runner):
            raise HostError("invalid-host-configuration")
        entries = {(e.cohort, e.name): e for e in catalogue.entries}
        epochs = {}
        for cohort in sorted({e.cohort for e in catalogue.entries}, key=lambda c: c.value):
            ownership, incarnation = store.context(cohort)
            if ownership.mode is not policy.Mode.API:
                raise HostError("ownership-not-active")
            epochs[cohort] = (incarnation, ownership.epoch)
        self._catalogue = catalogue.fingerprint
        self._entries = MappingProxyType(entries)
        self._epochs = MappingProxyType(epochs)
        self._store, self._state, self._authorize = store, state, authorize
        self._delegation = delegation
        self._owner = object()
        # Uses a FROZEN selector map, not the legacy default/alias resolver.
        selectors = {e.name: e.selector for e in catalogue.entries if e.cohort is policy.Cohort.PURIFIER}
        self._dispatcher = DeviceCommandDispatcher(state=state, admission=admission, cli=cli,
            run=runner, selected_purifier=selectors.__getitem__, purifier_wait_seconds=purifier_wait_seconds)
        for cohort, epoch in epochs.items():
            state.arm_control_epoch(cohort.value, epoch, catalogue=self._catalogue)

    def _entry(self, command):
        if type(command) is not Command:
            raise HostError("invalid-command")
        params = dict(command.params)
        name = params.get("plug") if command.cohort is policy.Cohort.PLUGS else params.get("deviceID")
        entry = self._entries.get((command.cohort, name))
        if entry is None:
            raise HostError("unknown-target")
        return entry

    def _allowed(self, access, command):
        return (type(access) is Access and access.transport_verified is True
                and command.cohort in access.cohorts and self._authorize(access, command) is True)

    def prepare(self, command, access):
        if not self._allowed(access, command):
            raise HostError("not-authorized")
        entry = self._entry(command)
        context = _Context(self._owner, command, access, self._epochs[entry.cohort])
        return BoundWrite(command, (entry.cohort.value, entry.identity), self._catalogue, context)

    def _binding(self, bound):
        if type(bound) is not BoundWrite or type(bound.context) is not _Context:
            raise HostError("invalid-binding")
        context = bound.context
        entry = self._entry(bound.command)
        if (context.owner is not self._owner or context.command is not bound.command
                or context.epoch != self._epochs[entry.cohort]
                or bound.catalogue != self._catalogue or bound.target != (entry.cohort.value, entry.identity)):
            raise HostError("invalid-binding")
        return entry, context

    def readiness(self, bound, access, epoch):
        entry, context = self._binding(bound)
        allowed = access is context.access and self._allowed(access, bound.command)
        view = self._state.inspect_device(entry.cohort.value, entry.name, control_epoch=context.epoch)
        observed = view["epochObserved"] and view["identity"] == entry.identity
        return policy.Readiness(request_epoch=epoch,
            observation_epoch=context.epoch[1] if observed else None,
            endpoint_available=True, protocol_verified=True,
            transport_guarded=access.transport_verified is True, authorized=allowed,
            target_known=view["known"] and view["identity"] == entry.identity,
            observation_fresh=view["fresh"], target_uncertain=not (observed and view["fresh"]))

    @staticmethod
    def _expectation(bound):
        if bound.command.action in ("plug-on", "plug-off"):
            return {"isOn": bound.command.action == "plug-on"}
        if bound.command.action == "purifier-set":
            expected = _purifier_expectation(dict(bound.command.params))
            if expected:
                return expected
        raise HostError("explicit-recovery-required")

    def begin_reconciliation(self, bound):
        """Internal owner action BEFORE a NEW read, never a network route/collector.

        The caller retains existing scheduling/cooldown rules. Toggle/unmodeled
        settings and changed-catalogue uncertainty require separate recovery.
        """
        entry, context = self._binding(bound)
        self._expectation(bound)
        if not self._allowed(context.access, bound.command):
            raise HostError("not-authorized")
        ticket = self._store.begin_observation(entry.cohort, bound.resource)
        try:
            if (ticket.incarnation, ticket.epoch) != context.epoch:
                raise HostError("stale-ownership")
            fence = self._state.begin_control_read(entry.cohort.value, entry.name,
                identity=entry.identity, control_epoch=context.epoch)
            return Readback(self._owner, bound, ticket, fence)
        except BaseException:
            try:
                self._store.reconcile(ticket, reconciled=False)
            except Exception:
                pass  # Discard only ephemeral evidence; never clear uncertainty.
            raise

    def abandon_reconciliation(self, readback):
        """Discard only an ephemeral ticket; never clear/refund an intent."""
        if type(readback) is not Readback or readback.owner is not self._owner:
            raise HostError("invalid-readback")
        self._store.reconcile(readback.ticket, reconciled=False)

    def finish_reconciliation(self, readback):
        if type(readback) is not Readback or readback.owner is not self._owner:
            raise HostError("invalid-readback")
        _, context = self._binding(readback.bound)
        expected = self._expectation(readback.bound)

        @contextmanager
        def check():
            if not self._allowed(context.access, readback.bound.command):
                raise HostError("not-authorized")
            with self._state.checked_control_read(readback.fence, expected):
                yield

        self._store.reconcile_checked(readback.ticket, command=readback.bound.fingerprint, check=check)

    def execute(self, bound):
        entry, context = self._binding(bound)
        if not self._allowed(context.access, bound.command):
            raise HostError("not-authorized")
        scope = self._delegation.scope(bound, entry) if self._delegation is not None else nullcontext()
        with scope:
            result = self._dispatcher.execute_bound(bound.command.action, dict(bound.command.params),
                resource=bound.target, control_epoch=context.epoch,
                authorize=lambda: self._allowed(context.access, bound.command))
        outcome = policy.Outcome.UNKNOWN
        if type(result) is dict and result.get("ok") is True:
            outcome = policy.Outcome.ACKNOWLEDGED
            if entry.cohort is policy.Cohort.PURIFIER:
                data = _purifier_command_data(result)
                if type(data) is not dict:
                    outcome = policy.Outcome.UNKNOWN
                elif data.get("verification_pending") is True:
                    outcome = (policy.Outcome.PENDING if data.get("write_accepted") is True
                               else policy.Outcome.UNKNOWN)
                elif data.get("verification_pending") is not None and data.get("verification_pending") is not False:
                    outcome = policy.Outcome.UNKNOWN
        # No raw result leaves this bridge; the protocol produces its own receipt.
        return DispatchResult(outcome)
