import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jarvisd_core import device_health as health
from jarvisd_core.monitor_store import MonitorStore


def entry(key='hub', kind='tcp', **kwargs):
    return dict(id=key, name=key, kind=kind, expectation='always', **kwargs)


def registry(*rows):
    return health.validate({'version': 1, 'devices': list(rows)})


class RegistryTests(unittest.TestCase):
    def test_empty_opt_in(self):
        self.assertEqual(health.load_registry(''), ())

    def test_private_file_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'devices.json'
            path.write_text(json.dumps({'version': 1, 'devices': [entry(host='192.168.1.1', port=443)]}))
            path.chmod(0o600)
            self.assertEqual(len(health.load_registry(str(path))), 1)
            path.chmod(0o644)
            with self.assertRaises(ValueError): health.load_registry(str(path))
            path.chmod(0o600)
            link = Path(tmp) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError): health.load_registry(str(link))

    def test_rejects_unsafe_and_ambiguous_registry(self):
        valid = entry(host='192.168.1.1', port=443)
        for bad in [dict(valid, host='example.com'), dict(valid, host='8.8.8.8'),
                    dict(valid, host='224.0.0.1'), dict(valid, host='0.0.0.0'),
                    dict(valid, port=True), dict(valid, command='anything'),
                    dict(valid, id='../escape'), dict(valid, name='secret\ntext'),
                    dict(valid, dependsOn=['missing']), dict(valid, dependsOn=['hub'])]:
            with self.subTest(bad=bad), self.assertRaises(ValueError): registry(bad)
        with self.assertRaises(ValueError): registry(valid, valid)
        with self.assertRaises(ValueError): registry(*[entry(str(i), kind='unmonitored') for i in range(41)])
        with self.assertRaises(ValueError):
            registry(dict(valid, dependsOn=['other']), entry('other', 'unmonitored', dependsOn=['hub']))

    def test_no_configuration_io_on_import(self):
        # Default construction neither probes nor enumerates devices.
        with patch.object(health, 'probe_tcp', side_effect=AssertionError):
            health.ProbeWorker(())
            self.assertEqual(health.project((), {}, {}, {}, {})['summary']['total'], 0)


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.reg = registry(entry('lamp', 'plug', selector='lamp'),
            entry('purifier', 'purifier', selector='opaque'),
            entry('door', 'security', selector='door-sensor', dependsOn=['hub']),
            entry(host='192.168.1.2', port=443),
            entry('camera', 'unmonitored'))
        self.state = {'subsystems': {
            'plugs': {'plugs': {'lamp': {'ok': True, 'stale': False, 'isOn': False}}},
            'purifier': {'devices': {'opaque': {'ok': True, 'stale': False, 'ageSeconds': 5}}}},
            'subsystemsMeta': {k: {'ok': True, 'ageSeconds': 5, 'stale': False,
                                  'updatedAt': '2026-10-01T00:00:00Z'} for k in ('plugs', 'purifier')}}
        self.security = {'door-sensor': {'availability': 'available', 'ageSeconds': 10,
            'consecutiveFailures': 0, 'lastAttemptAt': '2026-10-01T00:00:00Z'}}
        self.probes = {'hub': {'ok': True, 'ageSeconds': 10, 'consecutiveFailures': 0}}

    def project(self, **kwargs):
        return health.project(self.reg, self.state, self.security, {}, self.probes,
                              security_aliases=('door-sensor',), **kwargs)

    def test_coverage_and_no_raw_or_contact_data(self):
        d = self.project()
        self.assertEqual(d['summary'], {'total': 5, 'background': 4, 'onDemand': 0,
            'unmonitored': 1, 'available': 4, 'unavailable': 0, 'unknown': 1})
        raw = json.dumps(d)
        for forbidden in ('192.168', 'opaque', 'isOn', 'motionDetected', 'isOpen'):
            self.assertNotIn(forbidden, raw)
        self.assertEqual(d['devices'][3]['scope'], 'tcp_reachability')

    def test_latest_failure_wins_over_last_good(self):
        self.state['subsystemsMeta']['plugs']['ok'] = False
        row = self.project()['devices'][0]
        self.assertEqual(row['state'], 'unavailable')
        self.assertEqual(row['reason'], 'collector_read_failed')
        self.assertIsNone(row['lastAttemptAt'])

    def test_stale_missing_and_nonfinite_not_green(self):
        for age in (31, None, float('nan'), True, -1):
            with self.subTest(age=age):
                self.state['subsystemsMeta']['plugs']['ageSeconds'] = age
                self.assertEqual(self.project()['devices'][0]['state'], 'unknown')
        self.state['subsystemsMeta']['plugs']['ageSeconds'] = 5
        self.state['subsystems']['plugs']['plugs'] = {}
        self.assertEqual(self.project()['devices'][0]['state'], 'unknown')

    def test_purifier_judged_per_device_not_by_default_mirror(self):
        # Meta mirrors the default purifier; its failure must not fail a healthy peer.
        reg = registry(entry('a', 'purifier', selector='a'), entry('b', 'purifier', selector='b'))
        self.state['subsystems']['purifier']['devices'] = {
            'a': {'ok': False, 'stale': True, 'ageSeconds': 130, 'error': 'Device refresh unavailable'},
            'b': {'ok': True, 'stale': False, 'ageSeconds': 4}}
        self.state['subsystemsMeta']['purifier'].update(ok=False, stale=True, ageSeconds=130, error=None)
        a, b = health.project(reg, self.state, {}, {}, {})['devices']
        self.assertEqual((a['state'], a['reason']), ('unavailable', 'integration_read_failed'))
        self.assertEqual((b['state'], b['reason'], b['ageSeconds']), ('available', 'current', 4))
        # A collector-wide error still fails every purifier.
        self.state['subsystemsMeta']['purifier']['error'] = 'Purifier refresh unavailable'
        b = health.project(reg, self.state, {}, {}, {})['devices'][1]
        self.assertEqual((b['state'], b['reason']), ('unavailable', 'collector_read_failed'))
        # Per-device staleness/age still expire a purifier.
        self.state['subsystemsMeta']['purifier']['error'] = None
        self.state['subsystems']['purifier']['devices']['b'].update(stale=True, ageSeconds=95)
        b = health.project(reg, self.state, {}, {}, {})['devices'][1]
        self.assertEqual(b['state'], 'unknown')

    def test_purifier_pending_not_green_no_retry(self):
        self.state['subsystems']['purifier']['devices']['opaque']['verificationPending'] = True
        self.assertEqual(self.project()['devices'][1]['state'], 'unavailable')

    def test_dependency_suppresses_incidents_not_read_success(self):
        self.probes['hub'].update(ok=False, reason='connection_timeout')
        d = self.project()
        self.assertEqual(d['devices'][2]['blockedBy'], [])
        self.security['door-sensor']['availability'] = 'unavailable'
        d = self.project()
        self.assertEqual(d['devices'][2]['blockedBy'], ['hub'])
        incidents = health.incident_observations(d)
        self.assertIsNone(incidents['devices/door'])
        self.assertFalse(incidents['devices/hub'])
        self.assertNotIn('devices/camera', incidents)

    def test_optional_and_on_demand_do_not_open_incidents(self):
        reg = registry(dict(entry(host='192.168.1.2', port=443), expectation='optional'),
                       entry('door', 'security', selector='door-sensor'))
        d = health.project(reg, {}, self.security, {}, {'hub': {'ok': False, 'ageSeconds': 1}})
        self.assertEqual(d['devices'][0]['state'], 'unknown')
        self.assertEqual(d['devices'][1]['coverage'], 'on_demand')
        self.assertEqual(health.incident_observations(d), {})

    def test_disabled_is_unmonitored(self):
        d = self.project(enabled=False)
        self.assertEqual(d['summary']['unmonitored'], 5)
        self.assertEqual(d['summary']['available'], 0)

    def test_omlx_uses_health_not_fast_ui_expiry(self):
        reg = registry(entry('mac', 'omlx', selector='mac-mini-64'))
        omlx = {'subsystems': {'mac-mini-64': {'ok': True, 'stale': True}},
                'subsystemsMeta': {'mac-mini-64': {'ok': True, 'ageSeconds': 60, 'stale': True}}}
        d = health.project(reg, {}, {}, omlx, {})
        self.assertEqual(d['devices'][0]['state'], 'available')
        omlx['subsystemsMeta']['mac-mini-64']['ageSeconds'] = 121
        self.assertEqual(health.project(reg, {}, {}, omlx, {})['devices'][0]['state'], 'unknown')


class WorkerTests(unittest.TestCase):
    def test_serial_single_attempt_bounded_cache_and_usb_enumeration(self):
        reg = registry(entry(host='192.168.1.2', port=443),
                       entry('keyboard', 'usb', vendorID=1, productID=2),
                       entry('mouse', 'usb', vendorID=1, productID=3),
                       entry('door', 'security', selector='door-sensor'))
        calls = []
        tick = [0]
        def tcp(row):
            calls.append(row['id'])
            return False, 'connection_timeout'
        def usb():
            calls.append('usb'); return {(1, 2)}
        w = health.ProbeWorker(reg, tcp=tcp, usb=usb, clock=lambda: tick[0], wall=lambda: 100)
        w.tick()
        self.assertEqual(calls, ['hub', 'usb'])
        self.assertEqual(w.snapshot()['hub']['consecutiveFailures'], 1)
        self.assertTrue(w.snapshot()['keyboard']['ok'])
        self.assertFalse(w.snapshot()['mouse']['ok'])
        self.assertNotIn('door', w.snapshot())
        tick[0] = 200
        d = health.project(reg, {}, {}, {}, w.snapshot())
        self.assertTrue(all(row['state'] == 'unknown' for row in d['devices']))
        w.tcp = lambda row: (True, None)
        w.tick()
        self.assertEqual(w.snapshot()['hub']['consecutiveFailures'], 0)
        self.assertIsNotNone(w.snapshot()['hub']['lastSuccessAt'])

    def test_private_heartbeat_expiry_and_fault(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            row = entry('watcher', 'heartbeat', path=str(path), timestampKey='heartbeat', faultKey='fault', maxAge=30)
            registry(row)
            def save(value):
                path.write_text(json.dumps(value)); path.chmod(0o600)
            save({'heartbeat': 100, 'fault': None})
            self.assertEqual(health.probe_heartbeat(row, 110), (True, None))
            self.assertEqual(health.probe_heartbeat(row, 131), (False, 'heartbeat_expired'))
            self.assertEqual(health.probe_heartbeat(row, 99), (False, 'heartbeat_expired'))
            save({'heartbeat': 100, 'fault': 'private diagnostic'})
            self.assertEqual(health.probe_heartbeat(row, 110), (False, 'process_fault'))
            save({'heartbeat': '2026-10-01T00:00:00', 'fault': None})
            with self.assertRaises(ValueError): health.probe_heartbeat(row, 110)
            path.chmod(0o644)
            with self.assertRaises(ValueError): health.probe_heartbeat(row, 110)

    def test_owner_pause_marker_makes_stopped_heartbeat_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, marker = Path(tmp) / 'state.json', Path(tmp) / 'paused.json'
            row = entry('keyboard-watcher', 'heartbeat', path=str(path), timestampKey='heartbeat',
                        faultKey='fault', maxAge=30, pauseMarker=str(marker))
            reg = registry(row)
            def save(target, value, mode=0o600):
                target.write_text(json.dumps(value)); target.chmod(mode)
            save(path, {'heartbeat': 100, 'fault': None})
            # No marker / unpaused / unsafe or malformed marker: normal alerting.
            self.assertEqual(health.probe_heartbeat(row, 131), (False, 'heartbeat_expired'))
            save(marker, {'version': 1, 'paused': False})
            self.assertEqual(health.probe_heartbeat(row, 131), (False, 'heartbeat_expired'))
            save(marker, {'version': 1, 'paused': True}, 0o644)
            self.assertEqual(health.probe_heartbeat(row, 131), (False, 'heartbeat_expired'))
            save(marker, {'version': 2, 'paused': True})
            self.assertEqual(health.probe_heartbeat(row, 131), (False, 'heartbeat_expired'))
            # Valid pause: expired, faulted or missing heartbeat reports paused.
            save(marker, {'version': 1, 'paused': True})
            self.assertEqual(health.probe_heartbeat(row, 131), (False, 'paused'))
            save(path, {'heartbeat': 100, 'fault': 'stale'})
            self.assertEqual(health.probe_heartbeat(row, 110), (False, 'paused'))
            path.unlink()
            self.assertEqual(health.probe_heartbeat(row, 110), (False, 'paused'))
            # A fresh heartbeat always wins over a leftover marker.
            save(path, {'heartbeat': 100, 'fault': None})
            self.assertEqual(health.probe_heartbeat(row, 110), (True, None))
            # Projection: neutral, no incident, failures not accumulated.
            clock = [131.0]
            worker = health.ProbeWorker(reg, wall=lambda: clock[0])
            worker.tick(); worker.tick()
            snap = worker.snapshot()['keyboard-watcher']
            self.assertEqual((snap['reason'], snap['consecutiveFailures']), ('paused', 0))
            d = health.project(reg, {}, {}, {}, worker.snapshot())
            device = d['devices'][0]
            self.assertEqual((device['coverage'], device['state'], device['reason']),
                             ('unmonitored', 'unknown', 'paused'))
            self.assertEqual(health.incident_observations(d), {})
            # Resume: marker cleared and heartbeat expired again is a real failure.
            save(marker, {'version': 1, 'paused': False})
            worker.tick()
            d = health.project(reg, {}, {}, {}, worker.snapshot())
            self.assertEqual(d['devices'][0]['reason'], 'heartbeat_expired')
            self.assertEqual(health.incident_observations(d), {'devices/keyboard-watcher': False})

    def test_pause_marker_only_valid_for_heartbeat(self):
        with self.assertRaises(ValueError):
            registry(entry(host='192.168.1.2', port=443, pauseMarker='/tmp/paused.json'))
        with self.assertRaises(ValueError):
            registry(entry('w', 'heartbeat', path='/tmp/s.json', timestampKey='heartbeat',
                           faultKey='fault', maxAge=30, pauseMarker='relative.json'))

    def test_probe_failure_sanitized(self):
        reg = registry(entry(host='192.168.1.2', port=443))
        def explode(row): raise ValueError('private secret')
        worker = health.ProbeWorker(reg, tcp=explode)
        worker.tick()
        d = health.project(reg, {}, {}, {}, worker.snapshot())
        self.assertNotIn('private secret', json.dumps(d))
        self.assertEqual(d['devices'][0]['reason'], 'check_failed')

    def test_tcp_timeout_does_not_retry(self):
        with patch.object(health.socket, 'create_connection', side_effect=TimeoutError) as connect:
            self.assertEqual(health.probe_tcp({'host': '192.168.1.2', 'port': 443}), (False, 'connection_timeout'))
            connect.assert_called_once_with(('192.168.1.2', 443), timeout=2)

    def test_dependency_suppression_never_false_recovery(self):
        now = [0]
        with tempfile.TemporaryDirectory() as tmp:
            store = MonitorStore(Path(tmp) / 'history.sqlite3', ['devices/door'], clock=lambda: now[0])
            for tick in (0, 60, 120):
                now[0] = tick; store.observe({'devices/door': False})
            self.assertTrue(store.status()['devices/door']['incidentOpen'])
            now[0] = 180; store.observe({'devices/door': None})
            self.assertTrue(store.status()['devices/door']['incidentOpen'])
            self.assertEqual(len(store.history()), 1)
            now[0] = 240; store.observe({'devices/door': True})
            self.assertFalse(store.status()['devices/door']['incidentOpen'])
            store.close()


if __name__ == '__main__':
    unittest.main()
