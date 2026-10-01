"""Opt-in, at-most-once Mac arrival notices; never control another speaker."""
import json
from collections import deque
import threading
import time
import urllib.request
from pathlib import Path

import cycle

BOOT = str(time.time_ns())
ENV = Path.home() / 'Library/Application Support/JARVIS/room-audio-mac/environment.json'
URL = 'http://127.0.0.1:8793/control/arrival'
_worker = None
_results = deque(maxlen=8)


def dispatch():
    """Bounded background request; no retry, fallback, or sensitive logging."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    def send():
        try:
            env = json.loads(ENV.read_text())
            token = env['JARVIS_ROOM_AUDIO_TOKEN']
            if not isinstance(token, str) or not token:
                return
            request = urllib.request.Request(URL, data=b'{}', method='POST', headers={
                'Content-Type': 'application/json', 'x-jarvis-room-token': token})
            with urllib.request.urlopen(request, timeout=2) as response:
                result = json.loads(response.read(2048))
                _results.append({'at': time.time(), 'result': 'accepted' if result.get('accepted') is True else 'skipped'})
        except Exception:
            _results.append({'at': time.time(), 'result': 'uncertain'})  # Never replay.
    _worker = threading.Thread(target=send, name='arrival-notice', daemon=True)
    _worker.start()


def run_once(store, *, get_presence, now=time.time, apply=dispatch):
    try:
        if store.load('arrival-config.json', {}) != {'enabled': True}:
            return
        if _results:
            history = store.load('arrival-results.json', [])
            if not isinstance(history, list):
                return
            while _results:
                history.append(_results.popleft())
            store.save('arrival-results.json', history[-16:])
        at = now()
        state = store.load('arrival-state.json', {})
        if not isinstance(state, dict):
            return  # Corrupt state fails closed.
        if state.get('boot') != BOOT:
            state = {'boot': BOOT, 'awaySince': None, 'lastCheck': None, 'lastAttempt': None}
        try:
            payload = get_presence()
            mode = cycle.basement(payload)
            zone = next(z for z in payload['zones'] if z.get('zone') == 'basement')
            if zone['ageSeconds'] < 0:
                raise cycle.CycleError('presence')
        except cycle.CycleError:
            state['awaySince'] = None
            state['lastCheck'] = None
            store.save('arrival-state.json', state)
            return
        previous = state.get('lastCheck')
        if not cycle.finite(previous) or not 0 <= at - previous <= 15:
            state['awaySince'] = None
        since = state.get('awaySince')
        greet = mode == 'nearby' and cycle.finite(since) and at - since >= 30
        state['awaySince'] = (since if cycle.finite(since) else at) if mode == 'away' else None
        state['lastCheck'] = at
        if greet:
            state['lastAttempt'] = at
        store.save('arrival-state.json', state)  # Consume before dispatch, including crashes.
        if greet:
            apply()
    except Exception:
        return  # Optional audio must never block the desk controllers.
