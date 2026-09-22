"""Explicit, single-flight local internet diagnostic. No import-time I/O."""
from __future__ import annotations

import copy
import json
import math
import os
import selectors
import signal
import subprocess
import threading
import time
import uuid

COMMAND = ["/usr/bin/networkQuality", "-c", "-M", "60"]
TIMEOUT = 75.0
MAX_OUTPUT = 64 * 1024
COOLDOWN = 300.0
WARNING = "Uses substantial internet data and may interrupt streaming. Measures this Mac, not your phone."


def parse_result(text: str) -> dict:
    value = json.loads(text)
    if not isinstance(value, dict) or value.get("error"):
        raise ValueError("invalid result")
    result = {}
    for source, target, divisor in (
        ("dl_throughput", "downloadMbps", 1_000_000),
        ("ul_throughput", "uploadMbps", 1_000_000),
        ("base_rtt", "idleLatencyMs", 1),
    ):
        number = value.get(source)
        if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
            raise ValueError("missing or invalid measurement")
        result[target] = round(number / divisor, 3)
    return result


def collect() -> dict:
    deadline = time.monotonic() + TIMEOUT
    with subprocess.Popen(COMMAND, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, start_new_session=True) as process:
        try:
            data = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError()
                    chunk = os.read(process.stdout.fileno(), min(4096, MAX_OUTPUT + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_OUTPUT:
                        raise ValueError("output limit")
            if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                raise ValueError("test failed")
            return parse_result(data.decode("utf-8"))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


class SpeedTest:
    def __init__(self, collector=collect, clock=time.monotonic):
        self._collector = collector
        self._clock = clock
        self._lock = threading.Lock()
        self._next_start = 0.0
        self._state = {"status": "idle", "testID": None, "startedAt": None,
                       "finishedAt": None, "result": None, "error": None}

    def _snapshot(self):
        return {"ok": True, "hostID": "mac-mini-64", "label": "Home internet — mac-mini-64",
                "provider": "networkQuality", "warning": WARNING,
                "cooldownSeconds": max(0, math.ceil(self._next_start - self._clock())),
                **copy.deepcopy(self._state)}

    def snapshot(self):
        with self._lock:
            return self._snapshot()

    def start(self):
        with self._lock:
            if self._state["status"] == "running":
                return 409, self._snapshot()
            if self._clock() < self._next_start:
                return 429, self._snapshot()
            self._state = {"status": "running", "testID": uuid.uuid4().hex,
                           "startedAt": time.time(), "finishedAt": None,
                           "result": None, "error": None}
            self._next_start = self._clock() + COOLDOWN
            try:
                threading.Thread(target=self._run, name="network-speed", daemon=True).start()
            except Exception:
                self._state.update(status="failed", finishedAt=time.time(), error="Unable to start network test.")
                return 503, self._snapshot()
            return 202, self._snapshot()

    def _run(self):
        try:
            result = self._collector()
            error = None
        except Exception:
            result = None
            error = "Network test unavailable or failed; retry after cooldown."
        with self._lock:
            self._state.update(status="failed" if error else "completed", result=result,
                               error=error, finishedAt=time.time())


SPEED_TEST = SpeedTest()
