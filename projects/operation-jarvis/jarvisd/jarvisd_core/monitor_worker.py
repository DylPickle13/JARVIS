"""In-process cache-health sampler; optional local Notification Center delivery."""
import subprocess
import threading


def notify_local(kind):
    # Generic lock-screen text: never expose aliases, occupancy or raw failures.
    texts = {
        'unavailable': 'A JARVIS status check remains unavailable. Ask JARVIS for details.',
        'recovered': 'A JARVIS status check has recovered.',
    }
    text = texts[kind]
    result = subprocess.run(['/usr/bin/osascript', '-e',
        f'display notification "{text}" with title "JARVIS monitoring"'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=5, check=False)
    return result.returncode == 0  # Submitted, not proof of visible delivery.


class MonitorWorker:
    def __init__(self, store, collector):
        self.store, self.collector = store, collector
        self._stop = threading.Event()
        self._thread = None
        self.storage_available = True

    def tick(self):
        try:
            observations = self.collector()
        except Exception:
            observations = {}
        try:
            self.store.observe(observations)
            self.storage_available = True
        except Exception:
            # No raw SQLite/filesystem/collector errors in public responses/logs.
            self.storage_available = False

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(60)

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='jarvisd-monitor', daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=330)
        self.store.close()
