"""Opt-in, serial sensor polling. Read adapter owns retries and write exclusion.

No credentials/registry reads at import. No parallel hub traffic, catch-up bursts,
alerts, persistent history, or automatic control operations.
"""
import re
import threading
import time


def aliases_from_config(raw):
    values = tuple(part.strip() for part in raw.split(',') if part.strip())
    if (len(values) > 8 or len(set(values)) != len(values) or
            any(not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', value) for value in values)):
        raise ValueError('Invalid security polling aliases')
    return values


class SecurityPoller:
    def __init__(self, cli_path, aliases, *, reader, interval=60.0, clock=time.monotonic):
        if not 30 <= interval <= 300:
            raise ValueError('Security poll interval must be 30 to 300 seconds')
        self.cli_path, self.aliases = cli_path, tuple(aliases)
        self.reader, self.interval, self.clock = reader, interval, clock
        self._stop = threading.Event()
        self._thread = None
        self._due = {alias: 0.0 for alias in self.aliases}

    def tick(self):
        """A bounded fair sweep. Completion-relative cadence; no overlapping reads."""
        for alias in self.aliases:
            if self._stop.is_set():
                return
            if self.clock() < self._due[alias]:
                continue
            try:
                self.reader(self.cli_path, alias)
            except Exception:
                # Reader normally sanitizes failures; an unexpected bug must not
                # silently leave an old success fresh or terminate the worker.
                from .read_health import SECURITY_HEALTH
                SECURITY_HEALTH.record(alias, False)
            finally:
                self._due[alias] = self.clock() + self.interval

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(1.0)

    def start(self):
        if self._thread is not None or not self.aliases:
            return
        self._thread = threading.Thread(target=self._run, name='jarvisd-security-poll', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            # An in-flight subprocess is bounded by the adapter's 65s deadline.
            self._thread.join(timeout=66)
