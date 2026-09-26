#!/usr/bin/env python3
"""Owner-authorized three-second presence watcher and silent scheduler alert relay."""
import argparse
import contextlib
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import threading
import time

import cycle
import copy
import mouse_cycle

POLL = 3
HEALTH_AGE = 30  # Includes bounded presence + HID calls; not presence freshness.
QUEUE_LIMIT = 64


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
        if (type(item) is not dict or set(item) != {'message', 'code'}
                or type(item['message']) is not str or len(item['message']) > 512
                or not item['message'].startswith(('ERROR:', 'RECOVERED:'))
                or type(item['code']) is not int or item['code'] not in (0, 1)):
            raise cycle.CycleError('state')
    return value


def step(store, *, now=time.time, get_presence=cycle.read_presence, apply=cycle.send,
         mouse_apply=None):
    """Called with cycle.lock held. Share one age-adjusted presence snapshot."""
    value = snapshot(store)  # Corrupt outbox blocks both devices before any writes.
    cached = None
    fetched = False
    observed = None
    failure = None

    def shared_presence():
        nonlocal cached, fetched, observed, failure
        if not fetched:
            observed = time.monotonic()
            fetched = True
            try:
                cached = get_presence()
            except cycle.CycleError as exc:
                failure = exc
        if failure is not None:
            raise failure
        payload = copy.deepcopy(cached)
        if isinstance(payload, dict) and isinstance(payload.get('zones'), list):
            for zone in payload['zones']:
                if isinstance(zone, dict) and cycle.finite(zone.get('ageSeconds')):
                    zone['ageSeconds'] += max(0, time.monotonic() - observed)
        return payload

    for run in (
        lambda: cycle.run_once(store, now=now, get_presence=shared_presence,
                               apply=apply, responsive=True),
        lambda: mouse_cycle.run_once(store, now=now, get_presence=shared_presence,
                                     apply=mouse_apply),
    ):
        output, code = run()
        if output:
            value['alerts'].append({'message': output, 'code': code})
            value['alerts'] = value['alerts'][-QUEUE_LIMIT:]
    value['heartbeat'] = now()
    store.save('watcher.json', value)


def relay(store, *, now=time.time):
    """Scheduler-only reporting; never reads presence or sends lighting commands."""
    value = snapshot(store)
    old = store.load('watcher-health.json', False)
    if type(old) is not bool:
        raise cycle.CycleError('state')
    heartbeat = value['heartbeat']
    age = None if heartbeat is None else now() - heartbeat
    failed = age is None or not 0 <= age <= HEALTH_AGE
    messages = list(value['alerts'])
    if failed and not old:
        messages.append({'message': 'ERROR: Keyboard/mouse presence watcher is not responding; lighting may remain unchanged.', 'code': 1})
    elif old and not failed:
        messages.append({'message': 'RECOVERED: Keyboard/mouse presence watcher is responding again (not lighting readback).', 'code': 0})
    # Called under the same lock as the producer. Healthy cycles emit nothing.
    for item in messages:
        print(item['message'], flush=True)
    value['alerts'] = []
    store.save('watcher.json', value)
    store.save('watcher-health.json', failed)
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
    with locked(store, 'watcher.lock'):
        failing = False
        while not stop.is_set():
            try:
                with locked(store, 'cycle.lock'):
                    step(store)
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
                print('RECOVERED: Keyboard alert storage is accessible again.', flush=True)
            return result
    except BlockingIOError:
        return 0  # Next scheduler tick can drain the durable queue.
    except (OSError, ValueError, TypeError, KeyError, cycle.CycleError):
        try:
            message, code = cycle.bootstrap_error()
        except (OSError, cycle.CycleError):
            message, code = 'ERROR: Keyboard alert relay cannot persist its failure latch; repair storage.', 1
        if message:
            print(message, flush=True)
        return code


if __name__ == '__main__':
    raise SystemExit(main())
