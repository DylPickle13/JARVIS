#!/usr/bin/env python3
"""Owner-authorized three-second presence watcher and silent scheduler alert relay."""
import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor, wait
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import threading
import time
import tempfile
from pathlib import Path

import cycle
import copy
import mouse_cycle
import display_cycle
import led_cycle
import arrival_cycle

POLL = 3
HEALTH_AGE = 30  # Includes bounded presence + HID calls; not presence freshness.
QUEUE_LIMIT = 64
STARTUP_GRACE = 30
FAILURE_DELAY = 60
COMPONENTS = {'keyboard', 'mouse', 'display', 'led', 'watcher', 'storage'}


def diagnose(store, event, *, at, **details):
    """Bounded private history; callers supply sanitized fields, never raw responses."""
    history = store.load('diagnostics.json', [])
    if not isinstance(history, list):
        raise cycle.CycleError('state')
    history.append({'at': at, 'event': event, **details})
    store.save('diagnostics.json', history[-32:])


def alert_component(message):
    for component, prefix in (
        ('keyboard', 'Keyboard '), ('mouse', 'Mouse '), ('display', 'Display '),
        ('led', 'LED strip '),
        ('watcher', 'Computer presence watcher '),
        ('storage', 'Computer presence alert '),
    ):
        if message.split(': ', 1)[-1].startswith(prefix):
            return component
    if 'Basement presence' in message:
        return 'mouse' if 'mouse' in message else 'keyboard'
    return None


def notification_state(store):
    value = store.load('notifications.json', {'version': 1, 'pending': {}})
    if (type(value) is not dict or set(value) != {'version', 'pending'}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['pending']) is not dict
            or not set(value['pending']) <= COMPONENTS):
        raise cycle.CycleError('state')
    for component, entry in value['pending'].items():
        if (type(entry) is not dict or set(entry) != {'since', 'notified', 'message'}
                or not cycle.finite(entry['since']) or type(entry['notified']) is not bool
                or type(entry['message']) is not str or len(entry['message']) > 512
                or not entry['message'].startswith('ERROR:')
                or alert_component(entry['message']) != component):
            raise cycle.CycleError('state')
    return value


def notifications(value, messages, *, at, active=None):
    """Defer unresolved faults only; never emit an error already followed by recovery."""
    if not cycle.finite(at):
        raise cycle.CycleError('state')
    pending = value['pending']
    result = []

    def recover(component, message):
        entry = pending.pop(component, None)
        if entry is not None and entry['notified']:
            result.append({'message': message, 'code': 0})

    for item in messages:
        component = alert_component(item['message'])
        if component is None:
            raise cycle.CycleError('state')
        if item['code']:
            # Legacy/future-dated events start their grace period at this relay.
            since = min(at, item.get('at', at))
            if component not in pending:
                pending[component] = {'since': since, 'notified': False,
                                      'message': item['message']}
            else:
                pending[component]['message'] = item['message']
        else:
            recover(component, item['message'])

    # Reconcile durable controller latches so a truncated outbox cannot leave a
    # recovered fault pending or hide an ongoing failure. None means unknown.
    for component, status in (active or {}).items():
        if status is None:
            continue
        error, recovery = status
        if error is None:
            recover(component, recovery)
        elif component not in pending:
            pending[component] = {'since': at, 'notified': False, 'message': error}

    for entry in pending.values():
        if not entry['notified'] and at - entry['since'] >= FAILURE_DELAY:
            result.append({'message': entry['message'], 'code': 1})
            entry['notified'] = True
    return result


def controller_status(store):
    result = {}
    for component, filename, faults, descriptions in (
        ('keyboard', 'alerts.json', cycle.FAULTS, cycle.MESSAGES),
        ('mouse', 'mouse-alerts.json', mouse_cycle.FAULTS, mouse_cycle.MESSAGES),
        ('led', 'led-alerts.json', led_cycle.FAULTS, led_cycle.MESSAGES),
    ):
        latch = store.load(filename, None)
        if latch is None:
            continue
        if type(latch) is not list or any(type(f) is not str or f not in faults for f in latch):
            raise cycle.CycleError('state')
        fault = next((f for f in ('state', 'presence', component, 'preferences') if f in latch), None)
        result[component] = (
            'ERROR: ' + descriptions[fault] if fault else None,
            f'RECOVERED: {"LED strip" if component == "led" else component.capitalize()} automation checks are working again.',
        )
    display = store.load('display-state.json', None)
    if display is not None:
        if type(display) is not dict or type(display.get('fault')) is not bool:
            raise cycle.CycleError('state')
        result['display'] = (
            'ERROR: Display automation blocked after an uncertain action; owner review required.'
            if display['fault'] else None,
            'RECOVERED: Display automation fault cleared (not device-state verification).',
        )
    return result


@contextlib.contextmanager
def locked(store, name):
    fd = store.open_private(name, os.O_RDWR | os.O_CREAT)
    with os.fdopen(fd, 'r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def snapshot(store):
    value = store.load('watcher.json', {'version': 1, 'heartbeat': None, 'alerts': []})
    if (type(value) is not dict or set(value) != {'version', 'heartbeat', 'alerts'}
            or type(value['version']) is not int or value['version'] != 1
            or (value['heartbeat'] is not None and not cycle.finite(value['heartbeat']))
            or type(value['alerts']) is not list or len(value['alerts']) > QUEUE_LIMIT):
        raise cycle.CycleError('state')
    for item in value['alerts']:
        if (type(item) is not dict or set(item) not in ({'message', 'code'}, {'message', 'code', 'at'})
                or type(item['message']) is not str or len(item['message']) > 512
                or not item['message'].startswith(('ERROR:', 'RECOVERED:'))
                or type(item['code']) is not int or item['code'] not in (0, 1)
                or bool(item['code']) != item['message'].startswith('ERROR:')
                or alert_component(item['message']) is None
                or ('at' in item and not cycle.finite(item['at']))):
            raise cycle.CycleError('state')
    return value


def step(store, *, now=time.time, get_presence=cycle.read_presence, apply=cycle.send,
         mouse_apply=None, display_apply=None, led_apply=None, executor=None):
    """One locked pass; independent controllers run concurrently and all settle.

    Keep cycle.lock held until this returns/raises. Workers own distinct controller
    files; only the coordinator merges alerts after every worker has finished.
    """
    value = snapshot(store)  # Corrupt outbox blocks all controllers before any writes.
    led_cycle.probe_once(store)  # Owner-requested status only; never clears a write latch.
    cached = None
    fetched = False
    observed = None
    failure = None
    diagnosed = False
    presence_lock = threading.Lock()

    def shared_presence():
        # Serialize only snapshot fetch/copy/validation, never device execution.
        # This also makes the single-fetch and single diagnostic guarantees atomic.
        with presence_lock:
            return aged_presence()

    def aged_presence():
        nonlocal cached, fetched, observed, failure, diagnosed
        if not fetched:
            observed = time.monotonic()
            fetched = True
            try:
                cached = get_presence()
            except cycle.CycleError as exc:
                failure = exc
        if failure is not None:
            if not diagnosed:
                diagnose(store, 'presence-failure', at=now(), reason=failure.reason or 'unclassified')
                diagnosed = True
            raise failure
        payload = copy.deepcopy(cached)
        if isinstance(payload, dict) and isinstance(payload.get('zones'), list):
            for zone in payload['zones']:
                if isinstance(zone, dict) and cycle.finite(zone.get('ageSeconds')):
                    zone['ageSeconds'] += max(0, time.monotonic() - observed)
        try:
            cycle.basement(payload)
        except cycle.CycleError as exc:
            if not diagnosed:
                zones = payload.get('zones', []) if isinstance(payload, dict) else []
                zone = next((z for z in zones if isinstance(z, dict) and z.get('zone') == 'basement'), {}) if isinstance(zones, list) else {}
                age = zone.get('ageSeconds')
                reason = zone.get('reason')
                diagnose(store, 'presence-failure', at=now(), reason=exc.reason or 'snapshot-invalid',
                         ageSeconds=age if cycle.finite(age) else None,
                         listenerReason=reason if reason in ('listener-stale', 'listener-unavailable', 'not-ready', 'not-enrolled', 'ble-proximity') else None)
                diagnosed = True
            raise
        return payload

    runners = (
        lambda: cycle.run_once(store, now=now, get_presence=shared_presence,
                               apply=apply, responsive=True),
        lambda: mouse_cycle.run_once(store, now=now, get_presence=shared_presence,
                                     apply=mouse_apply),
        lambda: display_cycle.run_once(store, now=now, get_presence=shared_presence,
                                       apply=display_apply),
        lambda: led_cycle.run_once(store, now=now, get_presence=shared_presence,
                                   apply=led_apply),
    )
    context = (contextlib.nullcontext(executor) if executor is not None else
               ThreadPoolExecutor(max_workers=4, thread_name_prefix='presence-controller'))
    with context as workers:
        futures = []
        try:
            for run in runners:
                futures.append(workers.submit(run))
        finally:
            # Even submission/worker failure must not release cycle.lock while
            # another controller is still executing. Never cancel/replay writes.
            wait(futures)
        results, worker_errors = [], []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:
                worker_errors.append(exc)
    for output, code in results:
        if output:
            diagnose(store, 'controller-alert', at=now(), message=output)
            value['alerts'].append({'message': output, 'code': code, 'at': now()})
            value['alerts'] = value['alerts'][-QUEUE_LIMIT:]
    if worker_errors:
        # Preserve sibling alerts, but never advertise a failed pass as healthy.
        # Every started task is already settled; caller may now safely release its lock.
        store.save('watcher.json', value)
        raise worker_errors[0]
    arrival_cycle.run_once(store, now=now, get_presence=shared_presence)
    value['heartbeat'] = now()
    store.save('watcher.json', value)


def relay(store, *, now=time.time):
    """Computer presence alert relay; never reads presence or controls devices."""
    value = snapshot(store)
    old = store.load('watcher-health.json', False)
    if type(old) is not bool:
        raise cycle.CycleError('state')
    current = now()
    if not cycle.finite(current):
        raise cycle.CycleError('state')
    heartbeat = value['heartbeat']
    age = None if heartbeat is None else current - heartbeat
    started = store.load('watcher-started.json', None)
    initializing = cycle.finite(started) and 0 <= current - started < STARTUP_GRACE
    if initializing:
        return 0  # Defer notifications only; retain the outbox and all safety latches.
    failed = age is None or not 0 <= age <= HEALTH_AGE
    state = notification_state(store)
    messages = list(value['alerts'])
    watcher_error = 'ERROR: Computer presence watcher is not responding; keyboard, mouse, and monitor automation may not respond to presence changes.'
    watcher_recovery = 'RECOVERED: Computer presence watcher is responding again for keyboard, mouse, and monitors (not device-state verification).'
    if failed:
        since = heartbeat + HEALTH_AGE if heartbeat is not None and heartbeat <= current else current
        messages.append({'message': watcher_error, 'code': 1, 'at': since})
    # Controller latches cannot prove recovery while the producer is unresponsive.
    active = controller_status(store) if not failed else {}
    active['watcher'] = (watcher_error if failed else None, watcher_recovery)
    messages = notifications(state, messages, at=current, active=active)
    # Called under the same lock as the producer. Persist before publishing; no
    # exactly-once guarantee across a crash between persistence and delivery.
    store.save('notifications.json', state)
    value['alerts'] = []
    store.save('watcher.json', value)
    store.save('watcher-health.json', failed)
    for item in messages:
        print(item['message'], flush=True)
    return max((item['code'] for item in messages), default=0)


def watch():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    store = cycle.Store(cycle.RUNTIME)
    logger = logging.getLogger('ajazz-watcher')
    log_path = store.directory / 'watcher.log'
    fd = store.open_private('watcher.log', os.O_WRONLY | os.O_CREAT)
    os.close(fd)
    handler = RotatingFileHandler(log_path, maxBytes=65536, backupCount=1)
    logger.addHandler(handler)
    with locked(store, 'watcher.lock'), ThreadPoolExecutor(
            max_workers=4, thread_name_prefix='presence-controller') as workers:
        store.save('watcher-started.json', time.time())
        diagnose(store, 'watcher-start', at=time.time())
        failing = False
        while not stop.is_set():
            try:
                with locked(store, 'cycle.lock'):
                    step(store, executor=workers)
                failing = False
            except BlockingIOError:
                pass  # Another bounded operation holds the shared safety lock.
            except (OSError, ValueError, TypeError, KeyError, cycle.CycleError):
                if not failing:
                    logger.error('Watcher state/alert storage unavailable; no automatic recovery write. Check local status.')
                failing = True
            # No catch-up writes. Slow operations lengthen the check interval.
            stop.wait(POLL)
    return 0


def storage_notifications(failed, *, now=time.time):
    """Independent private fallback keeps runtime-storage blips silent too."""
    directory = Path(tempfile.gettempdir()) / f'jarvis-computer-presence-notifications-{os.getuid()}'
    if not failed and not directory.exists():
        return 0
    store = cycle.Store(directory)
    with locked(store, 'notifications.lock'):
        state = notification_state(store)
        error = ('ERROR: Computer presence alert relay cannot access its private state; '
                 'keyboard, mouse, and monitor status is unavailable. Repair state access.')
        recovery = ('RECOVERED: Computer presence alert storage is accessible again '
                    'for keyboard, mouse, and monitors.')
        messages = [{'message': error, 'code': 1}] if failed else []
        output = notifications(state, messages, at=now(),
                               active={'storage': (error if failed else None, recovery)})
        store.save('notifications.json', state)
    for item in output:
        print(item['message'], flush=True)
    return max((item['code'] for item in output), default=0)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--watch', action='store_true')
    group.add_argument('--alerts', action='store_true')
    args = parser.parse_args()
    if args.watch:
        return watch()
    try:
        store = cycle.Store(cycle.RUNTIME)
        with locked(store, 'cycle.lock'):
            result = relay(store)
            if cycle.bootstrap_exists():
                cycle.bootstrap_path().unlink()
                print('RECOVERED: Computer presence alert storage is accessible again for keyboard, mouse, and monitors.', flush=True)
            return max(result, storage_notifications(False))
    except BlockingIOError:
        return 0  # Next scheduler tick can drain the durable queue.
    except (OSError, ValueError, TypeError, KeyError, cycle.CycleError):
        try:
            return storage_notifications(True)
        except BlockingIOError:
            return 0
        except (OSError, ValueError, TypeError, KeyError, cycle.CycleError):
            # Both independent storage locations failed: durable delay/deduplication
            # is impossible. Preserve the fail-loud last-resort safety behavior.
            print('ERROR: Computer presence alert relay cannot persist its failure latch; keyboard, mouse, and monitor status is unavailable. Repair storage.', flush=True)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
