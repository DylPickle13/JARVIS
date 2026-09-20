"""Content-free, bounded room-client telemetry and exact-turn cancellation."""
import re
import threading
import time

ID = re.compile(r"[a-f0-9]{32}\Z")

class RoomAudioControl:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.client = ""
        self.retired = []
        self.sequence = -1
        self.turn = None
        self.phase = "unavailable"
        self.updated = None
        self.cancelled = {}

    def report(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"clientID", "sequence", "turnID", "phase"}:
            raise ValueError("invalid telemetry")
        client, sequence, turn, phase = (payload[k] for k in ("clientID", "sequence", "turnID", "phase"))
        if not isinstance(client, str) or not ID.fullmatch(client):
            raise ValueError("invalid client")
        if type(sequence) is not int or not 0 <= sequence <= 2**53 - 1:
            raise ValueError("invalid sequence")
        if phase not in {"idle", "processing", "speaking", "cancelling", "unavailable"}:
            raise ValueError("invalid phase")
        if phase in {"idle", "unavailable"}:
            if turn is not None: raise ValueError("idle turn")
        elif not isinstance(turn, str) or not ID.fullmatch(turn):
            raise ValueError("invalid turn")
        with self.lock:
            if client in self.retired or (client == self.client and sequence <= self.sequence):
                raise ValueError("superseded telemetry")
            if client != self.client:
                if self.client: self.retired = (self.retired + [self.client])[-64:]
                self.client = client
            self.sequence, self.turn, self.phase, self.updated = sequence, turn, phase, self.clock()
            self._prune()
            return {"ok": True, "cancelTurnID": turn if turn in self.cancelled else None}

    def _prune(self):
        now = self.clock()
        self.cancelled = {k:v for k,v in self.cancelled.items() if now - v < 600 or k == self.turn}
        while len(self.cancelled) > 256: self.cancelled.pop(next(iter(self.cancelled)))

    def is_cancelled(self, turn):
        with self.lock:
            self._prune()
            return turn in self.cancelled

    def _status(self):
        age = self.clock() - self.updated if self.updated is not None else None
        fresh = age is not None and 0 <= age <= 6
        online = fresh and self.phase != "unavailable"
        phase = self.phase if online else "unavailable"
        if online and self.turn in self.cancelled: phase = "cancelling"
        return {"ok": True, "clientOnline": online, "phase": phase,
                "turnID": self.turn if online else None,
                "canStop": online and phase in {"processing", "speaking"},
                "ageSeconds": round(age, 2) if age is not None else None}

    def status(self):
        with self.lock: return self._status()

    def stop(self, turn):
        with self.lock:
            status = self._status()
            if not isinstance(turn, str) or turn != status["turnID"] or not status["clientOnline"]:
                raise ValueError("turn changed or client unavailable")
            self.cancelled[turn] = self.clock()
            self._prune()
            return self._status()
