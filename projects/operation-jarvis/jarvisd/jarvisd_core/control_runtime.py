"""Explicit v2 runtime assembly and drain lifecycle; no automatic handoff.

A trusted transition owner must supply an already-open, API-owned ledger AFTER
real fence/drain/source/invocation checks. Neither imports nor this constructor
open/provision/activate a store. No live entry selects this assembly yet.
"""
from pathlib import Path
import sys
import threading
import time

from . import client_policy as policy, control_credentials as credentials
from .control_ledger import ControlLedger
from .control_identity import IdentityRegistry
from .control_protocol import ControlProtocol
from .control_http import ControlEndpoint, ControlHTTPServer
from .device_host import Catalogue, DeviceControlHost
from .device_transport import DeviceAdapterRunner
from .control_delegation import DelegatingRunner
from .control_readback import ReadbackQueue
from .control_closed import verify_fences
from . import vendor_fence


class RuntimeErrorClosed(RuntimeError):
    pass


class ControlRuntime:
    def __init__(self, *, store, bundle, catalogue, state, admission, adapter,
                 purifier_wait_seconds, vendor_pins, root=None, port=8790):
        if (type(store) is not ControlLedger or type(bundle) is not credentials.Bundle
                or type(catalogue) is not Catalogue or type(adapter) is not DeviceAdapterRunner
                or not bundle.certificate.valid()):
            raise RuntimeErrorClosed('control-runtime-not-approved')
        root = vendor_fence.root_directory() if root is None else Path(root)
        if not root.is_absolute() or root.is_symlink():
            raise RuntimeErrorClosed('control-runtime-layout-mismatch')
        root = root.parent.resolve(strict=True) / root.name
        worker = Path(__file__).resolve().parents[1] / 'control-worker.py'
        if (adapter.worker.is_symlink() or not adapter.worker.is_file() or adapter.worker.resolve() != worker
                or Path(adapter.python).resolve() != Path(sys.executable).resolve()
                or not root.is_absolute() or store._path != root / 'ledger'):
            raise RuntimeErrorClosed('control-runtime-layout-mismatch')
        verify_fences(adapter.operation_root, vendor_pins)
        cohorts = frozenset(entry.cohort for entry in catalogue.entries)
        if not cohorts <= bundle.enrollment.cohorts:
            raise RuntimeErrorClosed('control-runtime-scope-mismatch')
        self.store = store
        self._operation_root = adapter.operation_root
        self._vendor_pins = dict(vendor_pins)
        self.registry = IdentityRegistry(enrollments=(bundle.enrollment,), certificate=bundle.certificate, port=port)
        self.runner = DelegatingRunner(store=store, runner=adapter, root=root)
        self.host = DeviceControlHost(store=store, state=state, admission=admission,
            runner=self.runner, delegation=self.runner, cli=adapter.cli, catalogue=catalogue,
            authorize=self.registry.authorize, purifier_wait_seconds=purifier_wait_seconds)
        self.readbacks = ReadbackQueue(host=self.host, state=state)
        self.protocol = ControlProtocol(store, self.host, after_dispatch=self.readbacks.submit)
        self.endpoint = ControlEndpoint(registry=self.registry, api=self.protocol)
        self._cohorts = cohorts
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._installed = self._draining = self._closed = False

    def install(self, server):
        with self._lock:
            if self._installed or self._draining or self._closed or type(server) is not ControlHTTPServer:
                raise RuntimeErrorClosed('control-runtime-install-refused')
            if server.server_port != self.registry._port:
                raise RuntimeErrorClosed('control-runtime-port-mismatch')
            if not self.registry._certificate.valid():
                raise RuntimeErrorClosed('control-runtime-source-drift')
            verify_fences(self._operation_root, self._vendor_pins)
            for cohort in self._cohorts:
                ownership, incarnation = self.store.context(cohort)
                if (ownership.mode is not policy.Mode.API
                        or (incarnation, ownership.epoch) != self.host._epochs[cohort]):
                    raise RuntimeErrorClosed('control-runtime-ownership-changed')
            self.endpoint.install(server)  # Permanent process-local v1 closure first.
            self._installed = True
            self._thread = threading.Thread(target=self._run, name='jarvisd-control-readback', daemon=True)
            try:
                self._thread.start()
            except BaseException:
                self.begin_drain()
                raise

    def _run(self):
        while not self._stop.wait(.1):
            try:
                self.readbacks.tick()
            except Exception:
                # A broken owner loop cannot silently leave write admission open.
                try:
                    self.begin_drain()
                finally:
                    return

    def begin_drain(self):
        """Close new windows/grants, never cancel/replay already-dispatched work."""
        with self._lock:
            if not self._closed:
                self._begin_drain()

    def _begin_drain(self):
        self._stop.set()
        self._draining = True
        # Revoke even if a damaged ledger prevents persisting every transition.
        self.registry.revoke(next(iter(self.registry._enrollments)))
        errors = []
        for cohort in sorted(self._cohorts, key=lambda item: item.value):
            try:
                self.store.transition(cohort, policy.Mode.DRAINING)
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeErrorClosed('control-runtime-drain-incomplete') from None

    def close(self, *, timeout=35.0):
        with self._close_lock:
            self._close(timeout=timeout)

    def _close(self, *, timeout):
        if type(timeout) not in (int, float) or not 0 <= timeout <= 120:
            raise ValueError('invalid-control-drain-timeout')
        if self._closed:
            return
        self.begin_drain()
        deadline = time.monotonic() + timeout
        while self.store.active_count():
            if time.monotonic() >= deadline:
                # Keep the store lease: elapsed time is not completion/cancellation.
                raise RuntimeErrorClosed('control-runtime-writes-still-active')
            time.sleep(min(.05, max(0, deadline - time.monotonic())))
        thread = self._thread
        if thread is not None and thread.ident is not None and thread is not threading.current_thread():
            thread.join(max(0, deadline - time.monotonic()))
            if thread.is_alive():
                raise RuntimeErrorClosed('control-runtime-readback-still-active')
        self.readbacks.close()
        with self._lock:
            self.store.close()
            self._closed = True
