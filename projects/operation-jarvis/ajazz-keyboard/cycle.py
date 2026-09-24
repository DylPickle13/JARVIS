#!/usr/bin/env python3
"""Bounded presence-gated lighting: liked-effect rotation nearby, purple ripples away."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import subprocess
import sys
import tempfile
import time

import ajazz

ROOT = Path(__file__).resolve().parent
RUNTIME = Path.home() / 'Library/Application Support/JARVIS/ajazz-keyboard'
INTERVAL = 60
MAX_GAP = 150
# Owner-requested away profile via the unchanged, tested global-lighting CLI.
AWAY = {'effect': 'ripples', 'color': '#9933FF', 'brightness': 'highest',
        'speed': 'fastest', 'direction': 'left_to_right'}
FAULTS = {'presence', 'preferences', 'keyboard', 'state'}
MESSAGES = {
    'presence': 'Basement presence unavailable or stale; keyboard cycling paused.',
    'preferences': 'Keyboard preferences invalid; cycling paused.',
    'keyboard': 'Keyboard lighting command failed; see automation status. No immediate retry.',
    'state': 'Keyboard automation state unavailable or invalid; cycling paused.',
}


class CycleError(Exception):
    def __init__(self, kind, *, uncertain=False, reason=None):
        super().__init__(MESSAGES[kind])
        self.kind, self.uncertain, self.reason = kind, uncertain, reason


def initial():
    return dict(version=3, last_tick=None, near_count=0, away_count=0,
                last_effect=None, last_attempt=None, pending=False,
                away_applied=False, mode='paused')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_state(s):
    if type(s) is not dict:
        raise CycleError('state')
    if type(s.get('version')) is int and s['version'] == 1:
        if set(s) != set(initial()) - {'away_count', 'away_applied'}:
            raise CycleError('state')
        # Preserve prior uncertain-attempt marker and fault latch; migration sends nothing.
        s = s | {'version': 2, 'away_count': 0, 'lighting_dark': False}
    if type(s.get('version')) is int and s['version'] == 2:
        if (set(s) != (set(initial()) - {'away_applied'}) | {'lighting_dark'}
                or type(s['lighting_dark']) is not bool):
            raise CycleError('state')
        # Prior black RGB is NOT the new purple-ripples profile. Never clear pending.
        s = {k: v for k, v in s.items() if k != 'lighting_dark'}
        s.update(version=3, away_applied=False)
        if s['mode'] == 'dark':
            s['mode'] = 'paused'
    if set(s) != set(initial()) or type(s['version']) is not int or s['version'] != 3:
        raise CycleError('state')
    if any(v is not None and not finite(v) for v in (s['last_tick'], s['last_attempt'])):
        raise CycleError('state')
    if any(type(s[k]) is not int or not 0 <= s[k] <= 2 for k in ('near_count', 'away_count')):
        raise CycleError('state')
    if type(s['away_applied']) is not bool:
        raise CycleError('state')
    if s['last_effect'] is not None and s['last_effect'] not in ajazz.EFFECTS:
        raise CycleError('state')
    if type(s['pending']) is not bool or s['mode'] not in ('paused', 'debouncing', 'cycling', 'away', 'blocked'):
        raise CycleError('state')
    return s


def preferences(text):
    """Single source of truth: the existing liked-effects.md, never its row numbers."""
    if not isinstance(text, str) or len(text) > 16384:
        raise CycleError('preferences')
    values = {}
    for label in ('Color', 'Brightness', 'Speed'):
        found = re.findall(r'^' + label + r': `([^`]+)`', text, re.M)
        if len(found) != 1:
            raise CycleError('preferences')
        values[label.lower()] = found[0]
    sections = re.findall(r'^## Liked \(\d+\)\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if len(sections) != 1:
        raise CycleError('preferences')
    effects = re.findall(r'^\|\s*\d+\s*\|\s*([a-z_]+)\s*\|\s*$', sections[0], re.M)
    if not 2 <= len(effects) <= 17 or len(set(effects)) != len(effects):
        raise CycleError('preferences')
    try:
        for effect in effects:
            ajazz.report(values | {'effect': effect})
    except (ValueError, TypeError):
        raise CycleError('preferences') from None
    return effects, values


def basement(payload):
    if type(payload) is not dict or payload.get('ok') is not True:
        raise CycleError('presence')
    zones = payload.get('zones')
    if type(zones) is not list:
        raise CycleError('presence')
    matches = [z for z in zones if type(z) is dict and z.get('zone') == 'basement']
    if len(matches) != 1:
        raise CycleError('presence')
    zone = matches[0]
    age = zone.get('ageSeconds')
    if (zone.get('subject') != 'dylan' or zone.get('stale') is not False
            or not finite(age) or age > 15 or zone.get('state') not in ('nearby', 'away')):
        raise CycleError('presence')
    return zone['state']


def read_presence():
    # Reuse the authenticated, sanitized backend client; never scan BLE or read enrollment.
    script = ROOT.parent / 'presence/status.py'
    try:
        p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=8)
        if p.returncode != 0 or len(p.stdout) > 16384:
            raise ValueError()
        return json.loads(p.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise CycleError('presence') from None


def send(config):
    command = [sys.executable, str(ROOT / 'ajazz.py'), 'set']
    for key, value in config.items():
        command += ['--' + key, value]
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        raise CycleError('keyboard', uncertain=True) from None
    except OSError:
        raise CycleError('keyboard') from None
    if p.returncode != 0:
        # Only known pre-write failures may be attempted again on a later scheduled tick.
        prewrite = ('Expected exactly one matching AK820 RGB vendor interface',
                    'open failed', 'Another lighting command is running',
                    'shared-access support; no device opened', 'refusing exclusive access')
        reason = next((message for message in prewrite if message in p.stderr), None)
        raise CycleError('keyboard', uncertain=reason is None, reason=reason)
    try:
        result = json.loads(p.stdout)
        if result.get('bytes_written') != 65 or result.get('hardware_write') is not True:
            raise ValueError()
    except (ValueError, AttributeError):
        raise CycleError('keyboard', uncertain=True) from None


def tick(state, faults, *, now, get_presence, get_preferences, apply, save, choose=random.choice,
         responsive=False, on_error=lambda exc: None):
    """Injected dependencies allow tests without HTTP/HID. Mutates state under one lock."""
    state.update(validate_state(state))
    if not finite(now):
        raise CycleError('state')
    previous = state['last_tick']
    if previous is not None and now < previous:
        raise CycleError('state')
    if previous is not None and now - previous < (3 if responsive else INTERVAL):
        return  # No overlapping/manual/catch-up tick can cause a faster write.
    state['last_tick'] = now
    if previous is None or now - previous > MAX_GAP:
        state.update(near_count=0, away_count=0)
    save(state)  # Reserve tick durably before any backend/device request.
    faults.discard('state')
    observed = time.monotonic()
    try:
        payload = get_presence()
        location = basement(payload)
        age = next(z['ageSeconds'] for z in payload['zones'] if type(z) is dict and z.get('zone') == 'basement')
        deadline = observed + 15 - age  # Conservatively include the HTTP/helper latency.
        if time.monotonic() > deadline:
            raise CycleError('presence')
        faults.discard('presence')
    except CycleError:
        state.update(near_count=0, away_count=0, mode='paused')
        faults.add('presence')
        save(state)
        return
    if state['pending']:
        state.update(near_count=0, away_count=0, mode='blocked')
        faults.add('keyboard')
        save(state)
        return  # Prior attempt outcome uncertain: never replay automatically.
    going_away = location == 'away'
    effect = None
    if going_away:
        state.update(near_count=0, away_count=min(2, state['away_count'] + 1))
        if state['away_applied']:
            state['mode'] = 'away'
            save(state)
            return  # Already applied for this away period; do not repeat it.
        if not responsive and state['away_count'] < 2:
            state['mode'] = 'debouncing'
            save(state)
            return
        config = dict(AWAY)
    else:
        state.update(away_count=0, near_count=min(2, state['near_count'] + 1))
        if not responsive and state['near_count'] < 2:
            state['mode'] = 'debouncing'
            save(state)
            return
        try:
            effects, values = get_preferences()
            faults.discard('preferences')
        except CycleError:
            faults.add('preferences')
            state['mode'] = 'paused'
            save(state)
            return
        effect = choose([e for e in effects if e != state['last_effect']])
        config = ajazz.DEFAULT | values | {'effect': effect}
    # Only successful lighting-state transitions bypass the rotation timer. A known
    # pre-write failure must still cool down for a full minute, even if presence flips.
    transition = going_away != state['away_applied']
    cooldown = 3 if responsive and transition and 'keyboard' not in faults else INTERVAL
    if state['last_attempt'] is not None and now - state['last_attempt'] < cooldown:
        save(state)
        return
    state.update(last_attempt=now, pending=True, mode='blocked')
    save(state)  # Crash/timeout after this point blocks later writes until acknowledged.
    if time.monotonic() > deadline:
        state.update(pending=False, near_count=0, away_count=0, mode='paused')
        faults.add('presence')
        save(state)
        return  # Presence aged out while validating preferences/persisting state.
    try:
        apply(config)
    except CycleError as exc:
        faults.add('keyboard')
        state.update(pending=exc.uncertain, mode='blocked' if exc.uncertain else 'paused')
        on_error(exc)  # Only sanitized known error classes, never raw child stderr.
    else:
        state.update(pending=False, away_applied=going_away,
                     mode='away' if going_away else 'cycling')
        if not going_away:
            state['last_effect'] = effect
        faults.discard('keyboard')
    save(state)


def alert_transition(old, new, mode):
    if not old and new:
        kind = next(k for k in ('state', 'presence', 'preferences', 'keyboard') if k in new)
        return 'ERROR: ' + MESSAGES[kind], 1
    if old and not new:
        suffix = (' Cycling resumed.' if mode == 'cycling' else
                  ' Purple ripples applied while away.' if mode == 'away' else
                  ' Cycling remains paused pending proximity.')
        return 'RECOVERED: Keyboard automation checks are working again.' + suffix, 0
    return '', 0  # Suppressed failures are successful monitor ticks, not device successes.


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise CycleError('state')

    def open_private(self, name, flags):
        fd = os.open(self.directory / name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            os.close(fd)
            raise CycleError('state')
        return fd

    def load(self, name, default):
        try:
            fd = self.open_private(name, os.O_RDONLY)
        except FileNotFoundError:
            return default
        with os.fdopen(fd, 'r') as f:
            raw = f.read(16385)
        if len(raw) > 16384:
            raise CycleError('state')
        return json.loads(raw)

    def save(self, name, value):
        fd, temp = tempfile.mkstemp(dir=self.directory, prefix='.atomic-')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(value, f, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.directory / name)
            d = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(d)
            finally:
                os.close(d)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


def run_once(store, *, now=time.time, get_presence=read_presence, apply=send, responsive=False):
    old = store.load('alerts.json', [])
    if type(old) is not list or any(type(f) is not str or f not in FAULTS for f in old):
        raise CycleError('state')
    old, faults = set(old), set(old)
    state = initial()
    try:
        state = validate_state(store.load('state.json', initial()))
        def get_preferences():
            try:
                return preferences((ROOT / 'liked-effects.md').read_text())
            except OSError:
                raise CycleError('preferences') from None
        tick(state, faults, now=now(), get_presence=get_presence, get_preferences=get_preferences,
             apply=apply, save=lambda s: store.save('state.json', s), responsive=responsive,
             on_error=lambda exc: store.save('last-command-error.json',
                 {'kind': exc.kind, 'uncertain': exc.uncertain, 'reason': exc.reason, 'at': now()}))
    except (CycleError, OSError, ValueError, TypeError, KeyError):
        faults.add('state')
    output, code = alert_transition(old, faults, state.get('mode', 'paused'))
    store.save('alerts.json', sorted(faults))  # Separate latch also survives corrupt cycle state.
    return output, code


def bootstrap_path():
    # Independent of the main runtime directory: suppress repeated permission/latch failures.
    return Path(tempfile.gettempdir()) / f'jarvis-ajazz-bootstrap-{os.getuid()}.fault'


def bootstrap_exists():
    try:
        fd = os.open(bootstrap_path(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or f.read(7) != b'fault\n'):
            raise CycleError('state')
    return True


def bootstrap_error():
    if bootstrap_exists():
        return '', 0
    fd = os.open(bootstrap_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(b'fault\n')
        f.flush()
        os.fsync(f.fileno())
    return 'ERROR: Keyboard automation cannot access its private state; cycling paused. Repair state access before resuming.', 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--once', action='store_true', help='One scheduled tick; may change lighting when near')
    modes.add_argument('--status', action='store_true', help='Local automation state only; no presence/HID request')
    modes.add_argument('--acknowledge-uncertain', action='store_true',
                       help='Explicitly clear uncertain-write block; sends nothing, resets proximity debounce')
    args = parser.parse_args()
    try:
        store = Store(RUNTIME)
        fd = store.open_private('cycle.lock', os.O_RDWR | os.O_CREAT)
        with os.fdopen(fd, 'r+'):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            if args.status:
                print(json.dumps({'state': store.load('state.json', initial()),
                                  'faults': store.load('alerts.json', []), 'away_profile': AWAY, 'lighting_readback': False}, indent=2))
                return 0
            if args.acknowledge_uncertain:
                state = validate_state(store.load('state.json', initial()))
                state.update(pending=False, near_count=0, away_count=0, away_applied=False,
                             mode='paused', last_tick=time.time())
                store.save('state.json', state)
                print('Uncertain attempt acknowledged; no keyboard command sent. Fresh proximity checks required.')
                return 0
            if bootstrap_exists():
                alerts = store.load('alerts.json', [])
                if type(alerts) is not list or any(type(f) is not str or f not in FAULTS for f in alerts):
                    raise CycleError('state')
                store.save('alerts.json', sorted(set(alerts) | {'state'}))
                bootstrap_path().unlink()
            output, code = run_once(store)
            if output:
                print(output)
            return code
    except (OSError, ValueError, TypeError, CycleError):
        try:
            output, code = bootstrap_error()
        except (OSError, CycleError):
            # No process can durably deduplicate when BOTH stores are inaccessible.
            output, code = 'ERROR: Keyboard automation cannot persist its failure latch; disable the job and repair storage.', 1
        if output:
            print(output)
        return code


if __name__ == '__main__':
    raise SystemExit(main())
