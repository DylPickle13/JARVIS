"""Ephemeral, client-bound authorization for the two-part room conversation."""
from __future__ import annotations

import secrets
import threading
import time
from typing import Callable


class WakeFollowups:
    start_seconds = 5.0
    prompt_seconds = 30.0
    completion_seconds = 40.0  # 30-second VAD limit plus upload margin

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._tickets: dict[str, dict] = {}

    def _prune(self) -> None:
        now = self._clock()
        self._tickets = {k: v for k, v in self._tickets.items() if v['deadline'] > now}

    def issue(self, client: str, turn: str) -> str:
        if not client or not turn:
            raise ValueError('client and wake turn are required')
        with self._lock:
            self._prune()
            self._tickets = {k: v for k, v in self._tickets.items() if v['client'] != client}
            if len(self._tickets) >= 128:
                raise ValueError('too many pending wake requests')
            ticket = secrets.token_urlsafe(32)
            self._tickets[ticket] = dict(client=client, turn=turn, state='prompt',
                                         deadline=self._clock() + self.prompt_seconds)
            return ticket

    def transition(self, ticket: str, client: str, action: str) -> bool:
        with self._lock:
            self._prune()
            entry = self._tickets.get(ticket)
            if entry is None or entry['client'] != client:
                return False
            if action == 'cancel':
                del self._tickets[ticket]
                return True
            if action == 'ready' and entry['state'] == 'prompt':
                entry.update(state='listening', deadline=self._clock() + self.start_seconds)
                return True
            if action == 'claim' and entry['state'] == 'listening':
                entry.update(state='claimed', deadline=self._clock() + self.completion_seconds)
                return True
            return False

    def consume(self, ticket: str, client: str) -> bool:
        with self._lock:
            self._prune()
            entry = self._tickets.get(ticket)
            if entry is None or entry['client'] != client or entry['state'] != 'claimed':
                return False
            del self._tickets[ticket]
            return True

    def has_turn(self, turn: str) -> bool:
        with self._lock:
            self._prune()
            return any(v['turn'] == turn for v in self._tickets.values())

    def revoke_turn(self, turn: str) -> None:
        with self._lock:
            self._tickets = {k: v for k, v in self._tickets.items() if v['turn'] != turn}
