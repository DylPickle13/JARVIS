"""Device coverage over existing caches plus bounded, read-only reachability probes.

No discovery, controls, cloud recovery, sensor reads or retries. The optional
frame worker performs only the already-approved identity/package read.
The private registry selects fixed checks at startup; HTTP reads only project caches.
Reachability and USB attachment are deliberately NOT integration/physical health.
"""
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import plistlib
import re
import socket
import stat
import subprocess
import threading
import time

MAX_DEVICES = 40
KINDS = {'plug', 'purifier', 'security', 'omlx', 'tcp', 'usb', 'heartbeat', 'frame', 'unmonitored'}
SCOPES = {'plug': 'integration_read', 'purifier': 'integration_read',
          'security': 'status_read', 'omlx': 'integration_read',
          'tcp': 'tcp_reachability', 'usb': 'usb_attachment', 'heartbeat': 'process_heartbeat',
          'frame': 'frame_identity_read', 'unmonitored': 'none'}
LIMITS = {'plug': 30, 'purifier': 90, 'security': 120, 'omlx': 120}


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate(value):
    if type(value) is not dict or set(value) != {'version', 'devices'} or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Invalid device monitoring registry')
    devices = value['devices']
    if type(devices) is not list or not 1 <= len(devices) <= MAX_DEVICES:
        raise ValueError('Invalid device monitoring inventory')
    seen = set()
    for row in devices:
        if type(row) is not dict or not {'id', 'name', 'kind', 'expectation'} <= set(row) or set(row) - {'id', 'name', 'kind', 'expectation', 'selector', 'host', 'port', 'vendorID', 'productID', 'dependsOn', 'path', 'timestampKey', 'maxAge', 'faultKey'}:
            raise ValueError('Invalid device entry')
        key = row['id']
        if type(key) is not str or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', key) or key in seen:
            raise ValueError('Invalid device identifier')
        seen.add(key)
        if type(row['name']) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 '\-()]{0,79}", row['name']):
            raise ValueError('Invalid device display name')
        kind = row['kind']
        if type(kind) is not str or kind not in KINDS or row['expectation'] not in ('always', 'optional'):
            raise ValueError('Invalid device check')
        fields = set(row) - {'id', 'name', 'kind', 'expectation', 'dependsOn'}
        expected = {'host', 'port'} if kind == 'tcp' else {'vendorID', 'productID'} if kind == 'usb' else {'path', 'timestampKey', 'maxAge', 'faultKey'} if kind == 'heartbeat' else set() if kind in ('unmonitored', 'frame') else {'selector'}
        if fields != expected:
            raise ValueError('Invalid check configuration')
        if kind == 'tcp':
            # Numeric unicast LAN/loopback only: no DNS stalls, arbitrary URLs or public scans.
            try:
                address = ipaddress.IPv4Address(row['host'])
            except (ValueError, TypeError):
                raise ValueError('Invalid probe address') from None
            if not (address.is_private or address in ipaddress.ip_network('100.64.0.0/10')) or address.is_multicast or address.is_unspecified or address.is_reserved or str(address).endswith('.255'):
                raise ValueError('Probe must target a configured local unicast address')
            if type(row['port']) is not int or not 1 <= row['port'] <= 65535:
                raise ValueError('Invalid probe port')
        elif kind == 'usb':
            if any(type(row[k]) is not int or not 1 <= row[k] <= 65535 for k in ('vendorID', 'productID')):
                raise ValueError('Invalid USB identity')
        elif kind == 'heartbeat':
            if type(row['path']) is not str or not Path(row['path']).is_absolute():
                raise ValueError('Absolute heartbeat path required')
            if type(row['maxAge']) is not int or not 30 <= row['maxAge'] <= 300:
                raise ValueError('Invalid heartbeat expiry')
            if any(type(row[k]) is not str or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,47}', row[k]) for k in ('timestampKey', 'faultKey')):
                raise ValueError('Invalid heartbeat fields')
        elif kind not in ('unmonitored', 'frame'):
            if type(row['selector']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', row['selector']):
                raise ValueError('Invalid cache selector')
        deps = row.get('dependsOn', [])
        if type(deps) is not list or len(deps) > 4 or any(type(x) is not str for x in deps) or len(set(deps)) != len(deps):
            raise ValueError('Invalid dependencies')
    if sum(row['kind'] == 'frame' for row in devices) > 1:
        raise ValueError('Only one commissioned picture-frame check is supported')
    graph = {row['id']: row.get('dependsOn', []) for row in devices}
    visited = set()
    def visit(key, path):
        if key not in graph or key in path:
            raise ValueError('Unknown or cyclic device dependency')
        if key in visited:
            return
        for dep in graph[key]:
            visit(dep, path | {key})
        visited.add(key)
    for key in graph:
        visit(key, set())
    return tuple(dict(row) for row in devices)


def load_registry(path):
    if not path:
        return ()
    if not Path(path).is_absolute():
        raise ValueError('Absolute device registry path required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Private device registry required')
        raw = stream.read(32769)
    if len(raw) > 32768:
        raise ValueError('Device registry too large')
    return validate(json.loads(raw))


def probe_tcp(row):
    try:
        with socket.create_connection((row['host'], row['port']), timeout=2):
            return True, None
    except TimeoutError:
        return False, 'connection_timeout'
    except ConnectionRefusedError:
        return False, 'connection_refused'
    except OSError:
        return False, 'network_unreachable'


def usb_inventory():
    """One bounded local attachment enumeration per cycle; never opens HID handles."""
    # ioreg output is local OS metadata, not a device command. No shell or selectors.
    with subprocess.Popen(['/usr/sbin/ioreg', '-a', '-r', '-c', 'IOUSBHostDevice'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL) as process:
        # Drain bounded output without communicate's unlimited capture.
        import selectors
        raw = bytearray()
        deadline = time.monotonic() + 5
        try:
            os.set_blocking(process.stdout.fileno(), False)
            with selectors.DefaultSelector() as poller:
                poller.register(process.stdout, selectors.EVENT_READ)
                while poller.get_map():
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    for key, _ in poller.select(.1):
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            poller.unregister(key.fileobj)
                        else:
                            raw.extend(chunk)
                            if len(raw) > 2 * 1024 * 1024:
                                raise ValueError('USB output limit')
            process.wait(timeout=max(.01, deadline - time.monotonic()))
            if process.returncode:
                raise ValueError('USB enumeration failed')
            values = plistlib.loads(bytes(raw))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    found = set()
    def walk(value):
        if isinstance(value, dict):
            vendor, product = value.get('idVendor'), value.get('idProduct')
            if type(vendor) is int and type(product) is int:
                found.add((vendor, product))
            for child in value.get('IORegistryEntryChildren', []):
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(values)
    return found


def probe_heartbeat(row, now):
    fd = os.open(row['path'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Private heartbeat required')
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Heartbeat size limit')
    value = json.loads(raw)
    observed = value[row['timestampKey']]
    if type(observed) is str:
        date = datetime.fromisoformat(observed)
        if date.utcoffset() is None:
            raise ValueError('Aware heartbeat required')
        observed = date.timestamp()
    if not finite(observed) or not 0 <= now - observed <= row['maxAge']:
        return False, 'heartbeat_expired'
    if value.get(row['faultKey']) not in (None, False, ''):
        return False, 'process_fault'
    return True, None


class ProbeWorker:
    """One serial worker, 60s AFTER completion, no catch-up/retry. <=40 probes."""
    def __init__(self, registry, *, tcp=probe_tcp, usb=usb_inventory, frame=None,
                 clock=time.monotonic, wall=time.time):
        self.registry, self.tcp, self.usb, self.frame = registry, tcp, usb, frame
        self.clock, self.wall = clock, wall
        self._rows, self._lock = {}, threading.Lock()
        self._stop, self._thread = threading.Event(), None

    def tick(self):
        usb = None
        for row in self.registry:
            if self._stop.is_set():
                break
            kind = row['kind']
            if kind not in ('tcp', 'usb', 'heartbeat', 'frame'):
                continue
            try:
                if kind == 'tcp':
                    ok, reason = self.tcp(row)
                elif kind == 'frame':
                    ok, reason = self.frame(row) if self.frame is not None else (None, 'configuration_unavailable')
                elif kind == 'heartbeat':
                    ok, reason = probe_heartbeat(row, self.wall())
                else:
                    if usb is None:
                        try:
                            usb = self.usb()
                        except Exception:
                            usb = False
                    if usb is False:
                        ok, reason = False, 'check_failed'
                    else:
                        ok = (row['vendorID'], row['productID']) in usb
                        reason = None if ok else 'usb_not_attached'
            except Exception:
                ok, reason = (None if kind == 'frame' else False), 'check_failed'
            now, tick = self.wall(), self.clock()
            with self._lock:
                old = self._rows.get(row['id'], {})
                self._rows[row['id']] = {'ok': ok if kind == 'frame' else ok is True,
                    'reason': reason, 'tick': tick, 'lastAttemptAt': stamp(now),
                    'lastSuccessAt': stamp(now) if ok is True else old.get('lastSuccessAt'),
                    'consecutiveFailures': (0 if ok is True else old.get('consecutiveFailures', 0)
                        if kind == 'frame' and ok is None else old.get('consecutiveFailures', 0) + 1)}

    def snapshot(self):
        with self._lock:
            return {key: {**row, 'ageSeconds': max(0, self.clock() - row['tick'])}
                    for key, row in self._rows.items()}

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(60)

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='jarvisd-device-probes', daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=8)


def project(registry, state, security, omlx, probes, *, enabled=True, security_aliases=(), security_ttl=120, incidents=None):
    """Pure projection: no network, clock reads, files or last-good substitution."""
    rows = []
    incidents = incidents or {}
    for spec in registry:
        kind, key = spec['kind'], spec['id']
        row = {'id': key, 'name': spec['name'], 'scope': SCOPES[kind],
               'expectation': spec['expectation'], 'coverage': 'background',
               'state': 'unknown', 'reason': 'not_checked', 'ageSeconds': None,
               'lastAttemptAt': None, 'lastSuccessAt': None, 'consecutiveFailures': None,
               'freshnessLimitSeconds': security_ttl if kind == 'security' else LIMITS.get(kind, 150),
               'dependsOn': spec.get('dependsOn', []), 'blockedBy': [],
               'incidentOpen': incidents.get('devices/' + key, {}).get('incidentOpen', False),
               'incidentStartedAt': incidents.get('devices/' + key, {}).get('incidentStartedAt')}
        if not enabled or kind == 'unmonitored':
            row.update(coverage='unmonitored', reason='monitoring_disabled' if not enabled else 'no_check_configured')
            rows.append(row)
            continue
        item, meta, limit = {}, {}, 150.0
        if kind in ('plug', 'purifier', 'omlx'):
            category = {'plug': 'plugs', 'purifier': 'purifier', 'omlx': spec['selector']}[kind]
            source = omlx if kind == 'omlx' else state
            meta = source.get('subsystemsMeta', {}).get(category, {})
            parent = source.get('subsystems', {}).get(category, {})
            item = (parent.get('plugs', {}) if kind == 'plug' else parent.get('devices', {}) if kind == 'purifier' else {spec['selector']: parent}).get(spec['selector'], {})
            limit = LIMITS[kind]
            row.update(ageSeconds=meta.get('ageSeconds'), lastSuccessAt=meta.get('updatedAt'))
            if kind == 'purifier' and item.get('updatedAt'):
                row['lastSuccessAt'] = item['updatedAt']
            # Retained cache timestamps describe last-good data, NOT last attempts.
            if meta.get('ok') is False or meta.get('error') not in (None, '', 'loading'):
                row.update(state='unavailable', reason='collector_read_failed')
            elif item.get('ok') is False or item.get('verificationPending') is True:
                row.update(state='unavailable', reason='integration_read_failed')
            elif finite(row['ageSeconds']) and (row['ageSeconds'] > limit or (kind != 'omlx' and (meta.get('stale') is True or item.get('stale') is True))):
                row.update(reason='observation_expired')
            elif item.get('ok') is True and meta.get('ok') is True and finite(row['ageSeconds']) and (kind == 'omlx' or (meta.get('stale') is False and item.get('stale') is False)):
                row.update(state='available', reason='current')
        else:
            if kind == 'security':
                if spec['selector'] not in security_aliases:
                    row.update(coverage='on_demand')
                item = security.get(spec['selector'], {})
                limit = security_ttl
            else:
                item = probes.get(key, {})
            for field in ('ageSeconds', 'lastAttemptAt', 'lastSuccessAt', 'consecutiveFailures'):
                row[field] = item.get(field)
            if finite(row['ageSeconds']):
                if row['ageSeconds'] > limit or item.get('reason') == 'observation_expired':
                    row.update(reason='observation_expired')
                elif item.get('ok') is True or item.get('availability') == 'available':
                    row.update(state='available', reason='current')
                elif kind == 'frame' and item.get('ok') is None:
                    from .frame_health import UNKNOWN_REASONS
                    reason = item.get('reason')
                    row.update(reason=reason if type(reason) is str and reason in UNKNOWN_REASONS else 'check_failed')
                else:
                    safe = item.get('reason')
                    row.update(state='unavailable', reason=safe if safe in {
                        'connection_timeout', 'connection_refused', 'network_unreachable',
                        'usb_not_attached', 'check_failed', 'read_failed', 'heartbeat_expired', 'process_fault'} else 'read_failed')
        if row['expectation'] == 'optional' and row['state'] == 'unavailable':
            row.update(state='unknown', reason='optional_device_unreachable')
        rows.append(row)
    by_id = {row['id']: row for row in rows}
    # Dependencies explain failures; never hide a successful independent check.
    for row in rows:
        row['blockedBy'] = [key for key in row['dependsOn'] if by_id[key]['state'] != 'available'] if row['state'] != 'available' else []
    return {'version': 1, 'scope': 'device_check_coverage', 'devices': rows,
            'summary': {'total': len(rows),
                'background': sum(r['coverage'] == 'background' for r in rows),
                'onDemand': sum(r['coverage'] == 'on_demand' for r in rows),
                'unmonitored': sum(r['coverage'] == 'unmonitored' for r in rows),
                'available': sum(r['state'] == 'available' for r in rows),
                'unavailable': sum(r['state'] == 'unavailable' for r in rows),
                'unknown': sum(r['state'] == 'unknown' for r in rows)}}


def incident_observations(coverage):
    # Missing checks are data-unavailability incidents, not claims of physical outage.
    # Optional/sleeping devices never create incidents. Blocked children are omitted:
    # MonitorStore holds any prior incident without reporting a false recovery.
    return {'devices/' + row['id']: (None if row['blockedBy'] or
                (row['scope'] == 'frame_identity_read' and row['state'] == 'unknown') else row['state'] == 'available')
            for row in coverage['devices']
            if row['coverage'] == 'background' and row['expectation'] == 'always'}
