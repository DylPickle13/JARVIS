"""Offline health/history contracts: fake clocks, temp DBs, no hardware access."""
from contextlib import ExitStack
import http.client
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from jarvisd_core import system_health as health, system_history as history
from jarvisd_core.monitor_worker import MonitorWorker
from test_jarvisd import jarvisd as daemon

BASE = 1700000000.0
RUN = 'a' * 32


def snapshot(now=BASE, age=0):
    source = health.stamp(now-age)
    return {'ok': True, 'generatedAt': health.stamp(now),
        'subsystemsMeta': {key: {'ok': True, 'stale': False, 'error': None,
            'ageSeconds': age, 'updatedAt': source} for key in health.COMPONENTS[:6]},
        'subsystems': {
            'services': {'services': {
                'audio': {'ok': True, 'critical': True, 'configured': True,
                    'executionMode': 'continuous', 'running': True},
                'jobs': {'ok': True, 'critical': True, 'executionMode': 'periodic',
                    'loaded': True, 'running': False, 'lastExitCode': 0}}},
            'plugs': {'plugs': {'private-device-id': {'ok': True, 'stale': False, 'isOn': False}}},
            'purifier': {'devices': {'private-cloud-id': {'ok': True, 'stale': False}}}}}


def row(state='healthy', reason='current', until=BASE+10000):
    return health.observation(state, reason, source=BASE, valid_until=until)


class ProjectionTests(unittest.TestCase):
    def test_current_periodic_idle_and_off_devices_are_healthy(self):
        rows = health.project(snapshot(), BASE)
        self.assertTrue(all(r['state'] == 'healthy' for r in rows.values()))
        self.assertEqual(rows['services']['validUntil'], BASE+660)
        self.assertEqual(rows['devices']['validUntil'], BASE+30)
        self.assertEqual(rows['overall']['validUntil'], BASE+30)
        self.assertEqual(rows['service:jobs']['sourceObservedAt'], BASE)

    def test_optional_inactive_is_not_an_overall_failure(self):
        value = snapshot()
        value['subsystems']['services']['services']['audio'].update(critical=False, running=False)
        rows = health.project(value, BASE)
        self.assertEqual(rows['service:audio']['state'], 'inactive')
        self.assertEqual(rows['services']['state'], 'healthy')
        self.assertEqual(rows['overall']['state'], 'healthy')

    def test_service_semantics(self):
        cases = [
            ({'configured': False}, 'unavailable', 'required_service_missing'),
            ({'running': False}, 'unavailable', 'required_service_stopped'),
            ({'ok': False}, 'unavailable', 'service_read_failed'),
            ({'executionMode': None, 'running': False}, 'unknown', 'service_state_unknown')]
        for delta, state, reason in cases:
            value = snapshot()
            value['subsystems']['services']['services']['audio'].update(delta)
            with self.subTest(delta=delta):
                rows = health.project(value, BASE)
                self.assertEqual((rows['service:audio']['state'], rows['service:audio']['reason']), (state, reason))
                self.assertEqual(rows['overall']['state'], state)

    def test_periodic_failures_are_not_hidden_by_a_running_next_check(self):
        for delta, state in [({'lastExitCode': 9, 'running': True}, 'degraded'),
                             ({'lastExitSignal': 15, 'running': True}, 'degraded'),
                             ({'lastExitCode': None}, 'unknown'),
                             ({'lastExitCode': '0'}, 'unknown'),
                             ({'loaded': False}, 'unavailable'),
                             ({'loaded': None}, 'unknown'),
                             ({'running': True, 'lastExitCode': None}, 'healthy')]:
            value = snapshot()
            value['subsystems']['services']['services']['jobs'].update(delta)
            with self.subTest(delta=delta):
                self.assertEqual(health.project(value, BASE)['service:jobs']['state'], state)

    def test_missing_invalid_future_and_expired_evidence_is_never_healthy(self):
        for delta, reason in [({'updatedAt': None}, 'timestamp_invalid'),
                              ({'updatedAt': 'tomorrow'}, 'timestamp_invalid'),
                              ({'updatedAt': health.stamp(BASE+1)}, 'timestamp_invalid'),
                              ({'ageSeconds': -1}, 'timestamp_invalid'),
                              ({'ageSeconds': float('nan')}, 'timestamp_invalid'),
                              ({'ageSeconds': float('inf')}, 'timestamp_invalid'),
                              ({'ageSeconds': True}, 'timestamp_invalid'),
                              ({'ageSeconds': 10**1000}, 'timestamp_invalid'),
                              ({'stale': True}, 'observation_expired'),
                              ({'stale': None}, 'metadata_missing'),
                              ({'ok': None}, 'metadata_missing'),
                              ({'refreshing': True, 'ageSeconds': None}, 'loading')]:
            value = snapshot()
            value['subsystemsMeta']['services'].update(delta)
            with self.subTest(delta=delta):
                rows = health.project(value, BASE)
                self.assertEqual(rows['services']['reason'], reason)
                self.assertEqual(rows['service:audio']['state'], 'unknown')
                self.assertNotEqual(rows['overall']['state'], 'healthy')
        for generated in (None, '2023-11-14T22:13:20', health.stamp(BASE+1)):
            value = snapshot()
            value['generatedAt'] = generated
            self.assertEqual(health.project(value, BASE)['pi']['state'], 'unknown')

    def test_each_freshness_limit_and_frozen_generation(self):
        for name in health.COMPONENTS[:6]:
            value = snapshot()
            self.assertEqual(health.project(value, BASE+health.LIMITS[name])[name]['state'], 'healthy')
            self.assertEqual(health.project(value, BASE+health.LIMITS[name]+.001)[name]['state'], 'unknown')
            # Replacing generatedAt does not revive the old source timestamp.
            value['generatedAt'] = health.stamp(BASE+2000)
            self.assertEqual(health.project(value, BASE+2000)[name]['state'], 'unknown')

    def test_collector_failure_keeps_source_but_not_raw_error_or_green_inventory(self):
        value = snapshot()
        value['subsystemsMeta']['services']['error'] = 'PRIVATE token=secret'
        rows = health.project(value, BASE)
        self.assertEqual(rows['services']['state'], 'unavailable')
        self.assertEqual(rows['service:audio']['state'], 'unavailable')
        self.assertEqual(rows['service:audio']['sourceObservedAt'], BASE)
        self.assertNotIn('PRIVATE', json.dumps(rows))
        self.assertNotIn('private-device-id', json.dumps(rows))
        self.assertNotIn('private-cloud-id', json.dumps(rows))

    def test_per_device_failure_missing_and_pending_observations(self):
        for name, field, key in [('plugs', 'plugs', 'private-device-id'), ('purifier', 'devices', 'private-cloud-id')]:
            for delta, state in [({'ok': False}, 'unavailable'), ({'stale': True}, 'unavailable'),
                                 ({'ok': None}, 'unknown'), ({'stale': None}, 'unknown')]:
                value = snapshot()
                value['subsystems'][name][field][key].update(delta)
                with self.subTest(name=name, delta=delta):
                    rows = health.project(value, BASE)
                    self.assertEqual(rows[name]['state'], state)
                    self.assertEqual(rows['devices']['state'], state)
                    self.assertEqual(rows['overall']['state'], state)
        value = snapshot()
        value['subsystems']['purifier']['devices']['private-cloud-id']['verificationPending'] = True
        self.assertEqual(health.project(value, BASE)['purifier']['state'], 'unknown')

    def test_malformed_details_and_bounded_inventory(self):
        for value in (None, {}, {'subsystems': [], 'subsystemsMeta': []}):
            self.assertTrue(all(r['state'] == 'unknown' for r in health.project(value, BASE).values()))
        value = snapshot()
        value['subsystems']['services']['services'] = {'s%d' % i: {'ok': True, 'running': True} for i in range(1000)}
        rows = health.project(value, BASE)
        self.assertEqual(len(rows), health.MAX_COMPONENTS)
        self.assertEqual(rows['services']['reason'], 'inventory_limit')
        value['subsystems']['services']['services'] = {'../secret': {'ok': True, 'running': True}}
        self.assertNotIn('../secret', json.dumps(health.project(value, BASE)))
        self.assertEqual(health.project({'ok': False}, BASE)['overall']['reason'], 'snapshot_failed')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'chart' / 'history.sqlite3'
        self.store = history.HistoryStore(self.path)
        self.addCleanup(self.store.close)

    def read(self, now=BASE+3600, window='1h', component='pi', run=RUN):
        return self.store.read(window=window, component=component, now=now, run_id=run)

    def append(self, at=BASE, state='healthy', reason='current', until=BASE+10000, run=RUN):
        value = {**row(state, reason, until), 'sourceObservedAt': min(BASE, at)}
        self.store.append({'pi': value}, at=at, run_id=run)

    def test_empty_history_has_no_invented_healthy_coverage(self):
        response = self.read()
        self.assertIsNone(response['earliestSampleAt'])
        self.assertEqual(len(response['series'][0]['buckets']), 60)
        self.assertTrue(all(b['state'] == 'unknown' and b['coverageSeconds'] == 0
                            for b in response['series'][0]['buckets']))

    def test_fixed_windows_bounded_output_and_defaults(self):
        for window, count, resolution in [('1h', 60, 60), ('24h', 288, 300), ('7d', 336, 1800)]:
            response = self.store.read(window=window, now=BASE, run_id=RUN)
            self.assertEqual([r['id'] for r in response['series']], list(history.DEFAULT_SERIES))
            self.assertEqual(response['resolutionSeconds'], resolution)
            self.assertTrue(all(len(r['buckets']) == count for r in response['series']))
            self.assertLess(len(json.dumps(response)), 500000)

    def test_coverage_stops_at_freshness_and_recording_lease(self):
        self.append(until=BASE+20)
        buckets = self.read()['series'][0]['buckets']
        self.assertEqual(buckets[0]['coverageSeconds'], 20)
        self.assertEqual(buckets[0]['missingSeconds'], 40)
        self.assertEqual(buckets[0]['state'], 'unknown')
        self.assertTrue(buckets[0]['mixed'])
        self.assertEqual(sum(b['coverageSeconds'] for b in buckets), 20)
        self.append(at=BASE+120)
        buckets = self.read()['series'][0]['buckets']
        self.assertEqual(sum(b['coverageSeconds'] for b in buckets), 110)
        self.assertEqual(buckets[2]['state'], 'healthy')
        self.assertEqual(buckets[3]['coverageSeconds'], 30)
        self.assertEqual(buckets[3]['missingSeconds'], 30)
        self.assertEqual(buckets[4]['coverageSeconds'], 0)

    def test_short_failure_survives_five_minute_aggregation(self):
        self.append()
        self.append(at=BASE+60, state='unavailable', reason='collector_failed')
        self.append(at=BASE+120)
        response = self.read(now=BASE+86400, window='24h')
        first = response['series'][0]['buckets'][0]
        self.assertEqual(first['state'], 'unavailable')
        self.assertIn('collector_failed', first['reasonCodes'])
        self.assertTrue(first['mixed'])
        self.assertEqual(first['coverageSeconds'], 210)
        self.assertEqual(first['stateSeconds'], {'healthy': 150, 'unavailable': 60})
        self.assertEqual(first['missingSeconds'], 90)
        self.assertEqual(first['sourceObservedAt'], health.stamp(BASE))

    def test_restart_never_bridges_the_previous_final_sample(self):
        self.append()
        self.append(at=BASE+60)
        other = 'b'*32
        self.append(at=BASE+120, run=other)
        buckets = self.read(run=other)['series'][0]['buckets']
        self.assertEqual(buckets[0]['coverageSeconds'], 60)
        self.assertEqual(buckets[1]['coverageSeconds'], 0)
        self.assertEqual(buckets[2]['coverageSeconds'], 60)
        self.store.close()
        self.store = history.HistoryStore(self.path)
        self.addCleanup(self.store.close)
        buckets = self.read(run='c'*32)['series'][0]['buckets']
        self.assertEqual(buckets[2]['coverageSeconds'], 0)
        self.assertEqual(buckets[0]['coverageSeconds'], 60)

    def test_left_edge_clips_preceding_sample_and_no_future_coverage(self):
        self.append(at=BASE-30)
        response = self.read()
        self.assertEqual(response['series'][0]['buckets'][0]['coverageSeconds'], 60)
        self.append(at=BASE+3600)
        self.assertEqual(self.read()['series'][0]['buckets'][-1]['coverageSeconds'], 0)

    def test_private_permissions_schema_and_page_journal_caps(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store._db.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(self.store._db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
        self.assertEqual(self.store._db.execute('PRAGMA max_page_count').fetchone()[0], history.MAX_PAGES)
        self.assertEqual(self.store._db.execute('PRAGMA page_size').fetchone()[0], 4096)
        self.assertFalse(Path(str(self.path)+'-wal').exists())

    def test_time_row_and_payload_budget_pruning(self):
        for i in range(5):
            self.append(at=BASE+i*60)
        with patch.object(history, 'MAX_SAMPLES', 3):
            self.append(at=BASE+300)
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM samples').fetchone()[0], 3)
        with patch.object(history, 'PAYLOAD_BUDGET', 450):
            self.append(at=BASE+360)
        self.assertLessEqual(self.store._db.execute('SELECT sum(bytes) FROM samples').fetchone()[0], 450)
        self.append(at=BASE+history.RETENTION+1000)
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM samples').fetchone()[0], 1)

    def test_full_retention_and_max_component_capacity_remain_bounded(self):
        ids = list(health.COMPONENTS) + ['service:s%d' % i for i in range(health.MAX_COMPONENTS-len(health.COMPONENTS))]
        def payload(at):
            return json.dumps({key: health.observation('healthy', 'current', source=at, valid_until=at+90)
                               for key in ids}, separators=(',', ':'))
        size = len(payload(BASE).encode()) + 128
        count = min(history.MAX_SAMPLES, history.PAYLOAD_BUDGET//size)
        with self.store._db:
            self.store._db.executemany('INSERT INTO samples VALUES (?,?,?,?)',
                ((int((BASE+i*60)*1000), RUN, payload(BASE+i*60), size) for i in range(count)))
        at = BASE+count*60
        self.store.append(json.loads(payload(at)), at=at, run_id=RUN)
        response = self.read(now=at+30, window='7d', component=None)
        self.assertEqual(len(response['series']), 5)
        self.assertTrue(all(len(s['buckets']) == 336 for s in response['series']))
        self.assertLess(len(json.dumps(response)), 500000)
        self.assertLessEqual(self.store._db.execute('SELECT sum(bytes) FROM samples').fetchone()[0], history.PAYLOAD_BUDGET)
        self.assertLessEqual(self.store._db.execute('PRAGMA page_count').fetchone()[0], history.MAX_PAGES)
        self.assertLessEqual(self.path.stat().st_size, 32*1024*1024)
        for series in response['series']:
            for bucket in series['buckets']:
                self.assertGreaterEqual(bucket['missingSeconds'], 0)
                self.assertAlmostEqual(bucket['coverageSeconds']+bucket['missingSeconds'], 1800, places=2)
                self.assertAlmostEqual(sum(bucket['stateSeconds'].values()), bucket['coverageSeconds'], places=2)

    def test_nonregular_storage_is_rejected_without_blocking(self):
        fifo = self.path.parent / 'fifo.sqlite3'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            history.HistoryStore(fifo)

    def test_validation_no_private_fields_and_backward_time_no_overwrite(self):
        value = row()
        value.update(error='PRIVATE', token='secret', devices={'private': True})
        self.store.append({'pi': value}, at=BASE, run_id=RUN)
        payload = self.store._db.execute('SELECT payload FROM samples').fetchone()[0]
        self.assertNotIn('PRIVATE', payload)
        self.assertNotIn('secret', payload)
        self.assertNotIn('devices', payload)
        for at in (BASE, BASE-1):
            with self.assertRaises(history.HistoryUnavailable):
                self.append(at=at)
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM samples').fetchone()[0], 1)
        for rows in ({'../secret': row()}, {'pi': row('bogus')}, {'pi': row(reason='PRIVATE')},
                     {'pi': {**row(), 'sourceObservedAt': BASE+1}},
                     {'pi': {**row(), 'validUntil': float('nan')}}):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.store.append(rows, at=BASE, run_id=RUN)
        with self.assertRaises(KeyError):
            self.read(component='service:missing')

    def test_reject_symlink_hardlink_and_future_schema(self):
        link = self.path.parent / 'link.sqlite3'
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            history.HistoryStore(link)
        parent_link = Path(self.temp.name) / 'alias'
        parent_link.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            history.HistoryStore(parent_link / 'other.sqlite3')
        hard = self.path.parent / 'hard.sqlite3'
        os.link(self.path, hard)
        with self.assertRaises(ValueError):
            history.HistoryStore(hard)
        hard.unlink()
        self.store._db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):
            history.HistoryStore(self.path)

    def test_database_contention_and_failure_do_not_wait_indefinitely(self):
        ready, done = threading.Event(), threading.Event()
        def holder():
            with self.store._lock:
                ready.set()
                done.wait(2)
        t = threading.Thread(target=holder)
        t.start()
        try:
            self.assertTrue(ready.wait(1))
            with self.assertRaises(history.HistoryUnavailable):
                self.read()
        finally:
            done.set()
            t.join(2)
        other = sqlite3.connect(self.path, timeout=.01)
        try:
            other.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError):
                self.append()
            other.rollback()
            self.append()
        finally:
            other.close()
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM samples').fetchone()[0], 1)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.now, self.mono = [BASE], [0.0]
        self.store = Mock()
        self.reader = Mock(side_effect=lambda: snapshot(self.now[0]))
        self.recorder = history.HistoryRecorder(self.store, self.reader,
            clock=lambda: self.now[0], monotonic=lambda: self.mono[0])

    def advance(self, delta=60):
        self.now[0] += delta
        self.mono[0] += delta

    def test_one_record_per_cycle_no_catchup_or_foreground_work(self):
        self.recorder.tick()
        self.recorder.tick()
        self.assertEqual(self.reader.call_count, 1)
        self.advance(59)
        self.recorder.tick()
        self.assertEqual(self.reader.call_count, 1)
        self.advance(10000)
        self.recorder.tick()
        self.assertEqual(self.reader.call_count, 2)
        self.assertEqual(self.store.append.call_count, 2)
        self.assertEqual(self.store.append.call_args.kwargs['at'], self.now[0])
        self.recorder.read('24h')
        self.assertEqual(self.reader.call_count, 2)
        self.store.read.assert_called_once()

    def test_snapshot_failure_records_sanitized_unavailability_not_storage_failure(self):
        self.reader.side_effect = RuntimeError('PRIVATE')
        self.recorder.tick()
        rows = self.store.append.call_args.args[0]
        self.assertEqual(rows['overall']['state'], 'unavailable')
        self.assertNotIn('PRIVATE', json.dumps(rows))
        self.assertTrue(self.recorder.storage_available)

    def test_write_failure_leaves_gap_and_next_cycle_can_recover_without_replay(self):
        self.store.append.side_effect = RuntimeError('PRIVATE')
        initial = self.recorder.run_id
        self.recorder.tick()
        self.assertFalse(self.recorder.storage_available)
        self.assertNotEqual(initial, self.recorder.run_id)
        with self.assertRaises(history.HistoryUnavailable):
            self.recorder.read('1h')
        self.advance()
        self.store.append.side_effect = None
        self.recorder.tick()
        self.assertTrue(self.recorder.storage_available)
        self.assertEqual(self.store.append.call_count, 2)

    def test_clock_jumps_start_new_coverage_run(self):
        self.recorder.tick()
        initial = self.recorder.run_id
        self.advance()
        self.now[0] += 15
        self.recorder.tick()
        self.assertNotEqual(initial, self.recorder.run_id)
        initial = self.recorder.run_id
        self.advance()
        self.now[0] -= 15
        self.recorder.tick()
        self.assertNotEqual(initial, self.recorder.run_id)

    def test_read_clock_jump_invalidates_coverage_before_next_tick_without_writes(self):
        self.recorder.tick()
        initial = self.recorder.run_id
        self.advance(10)
        self.now[0] += 15
        self.recorder.read('1h')
        self.assertIsNone(self.store.read.call_args.kwargs['run_id'])
        self.assertEqual(self.store.append.call_count, 1)
        self.assertEqual(self.reader.call_count, 1)
        self.assertEqual(self.recorder.run_id, initial)

    def test_read_concurrency_is_bounded_and_does_not_block_controls(self):
        self.recorder._reads.acquire()
        self.recorder._reads.acquire()
        try:
            with self.assertRaises(history.HistoryUnavailable):
                self.recorder.read('7d')
            self.store.read.assert_not_called()
        finally:
            self.recorder._reads.release()
            self.recorder._reads.release()
        self.recorder.read('7d')
        self.store.read.assert_called_once()

    def test_stop_closes_and_never_records_again(self):
        self.recorder.close()
        self.recorder.tick()
        self.reader.assert_not_called()
        self.store.close.assert_called_once()
        with self.assertRaises(history.HistoryUnavailable):
            self.recorder.read('24h')

    def test_chart_and_incident_failures_are_independent(self):
        incident, collector, chart = Mock(), Mock(return_value={}), Mock()
        worker = MonitorWorker(incident, collector, on_tick=chart)
        chart.side_effect = RuntimeError('PRIVATE')
        worker.tick()
        self.assertTrue(worker.storage_available)
        incident.observe.assert_called_once_with({})
        incident.observe.side_effect = RuntimeError('PRIVATE')
        chart.side_effect = None
        worker.tick()
        self.assertFalse(worker.storage_available)
        self.assertEqual(chart.call_count, 2)
        self.assertEqual(collector.call_count, 2)


class CompositionTests(unittest.TestCase):
    def run_main(self, enabled='true', storage_error=False, missing_monitoring=False,
                 recorder_error=False, close_error=False):
        with tempfile.TemporaryDirectory() as raw, ExitStack() as stack:
            root = Path(raw).resolve()
            stack.enter_context(patch.dict(os.environ, {
                'JARVISD_MONITORING_ENABLED': 'false' if missing_monitoring else 'true',
                'JARVISD_SYSTEM_HISTORY_ENABLED': enabled,
                'JARVISD_SECURITY_POLL_ALIASES': '', 'JARVISD_SECURITY_POLL_INTERVAL': '60',
                'JARVISD_MONITOR_NOTIFICATIONS': 'false', 'JARVISD_MONITOR_INTEGRATIONS': 'plugs'}))
            for name, value in [('EVENTS', Mock()), ('MONITOR_WORKER', None),
                    ('SYSTEM_HISTORY_RECORDER', None), ('SYSTEM_HISTORY_ENABLED', False),
                    ('MONITORING_ENABLED', False), ('SECURITY_POLL_ALIASES', ()),
                    ('API_TOKEN', 'fixture-token'), ('SECURITY_CLI', '')]:
                stack.enter_context(patch.object(daemon, name, value))
            stack.enter_context(patch.object(daemon, 'EventStore', return_value=Mock()))
            stack.enter_context(patch.object(daemon, 'validate_config'))
            stack.enter_context(patch.object(daemon, 'configure_bounded_stderr', return_value=None))
            stack.enter_context(patch.object(daemon.sys, 'stderr', io.StringIO()))
            for name in ('STATE_COORDINATOR', 'OMLX_COORDINATOR', 'OMLX_UPDATE_COORDINATOR', 'HOST_MEMORY_COORDINATOR'):
                stack.enter_context(patch.object(daemon, name))
            state = daemon.STATE_COORDINATOR
            state.snapshot.side_effect = lambda **kw: snapshot(time.time())
            poller_cls = stack.enter_context(patch('jarvisd_core.security_polling.SecurityPoller'))
            monitor_store = stack.enter_context(patch('jarvisd_core.monitor_store.MonitorStore'))
            worker_cls = stack.enter_context(patch('jarvisd_core.monitor_worker.MonitorWorker'))
            server_cls = stack.enter_context(patch.object(daemon, 'ThreadingHTTPServer'))
            server = server_cls.return_value
            server.serve_forever.side_effect = KeyboardInterrupt
            stack.enter_context(patch.object(daemon.Path, 'home', return_value=root))
            original_store, created = history.HistoryStore, []
            def make_store(path):
                store = original_store(path)
                created.append(store)
                return store
            store_cls = stack.enter_context(patch.object(history, 'HistoryStore', side_effect=make_store))
            if storage_error:
                store_cls.side_effect = RuntimeError('PRIVATE path=secret')
            if recorder_error:
                stack.enter_context(patch.object(history, 'HistoryRecorder', side_effect=RuntimeError('PRIVATE')))
            def start():
                callback = worker_cls.call_args.kwargs['on_tick']
                if callback:
                    callback()
                    if close_error:
                        created[-1].close = Mock(side_effect=RuntimeError('PRIVATE'))
            worker_cls.return_value.start.side_effect = start
            if missing_monitoring or enabled not in ('true', 'false'):
                with self.assertRaises(ValueError):
                    daemon.main()
                state.start.assert_not_called()
                store_cls.assert_not_called()
                server_cls.assert_not_called()
                return
            self.assertEqual(daemon.main(), 0)
            worker_cls.return_value.start.assert_called_once()
            worker_cls.return_value.stop.assert_called_once()
            poller_cls.return_value.stop.assert_called_once()
            state.stop.assert_called_once()
            server.server_close.assert_called_once()
            self.assertIsNone(daemon.SYSTEM_HISTORY_RECORDER)
            self.assertIsNone(daemon.MONITOR_WORKER)
            monitor_store.assert_called_once()
            if enabled == 'true' and not storage_error and not recorder_error:
                store_cls.assert_called_once()
                state.snapshot.assert_called_once_with(client_active=False, start_collectors=False)
                path = root / 'Library/Application Support/JARVIS/system-history/history.sqlite3'
                db = sqlite3.connect(path)
                try:
                    self.assertEqual(db.execute('SELECT count(*) FROM samples').fetchone()[0], 1)
                finally:
                    db.close()
                state.request_refresh.assert_not_called()
                state.activate_client.assert_not_called()
                if close_error:
                    original_store.close(created[-1])
            else:
                state.snapshot.assert_not_called()
                self.assertIsNone(worker_cls.call_args.kwargs['on_tick'])
                if enabled == 'false':
                    store_cls.assert_not_called()
                if recorder_error:
                    self.assertEqual(len(created), 1)
                    with self.assertRaises(sqlite3.ProgrammingError):
                        created[0]._db.execute('SELECT 1')

    def test_actual_startup_wires_cache_only_recording_and_cleanup(self):
        self.run_main()

    def test_history_disabled_does_not_open_storage_or_sample(self):
        self.run_main(enabled='false')

    def test_optional_storage_failure_does_not_prevent_existing_backend(self):
        self.run_main(storage_error=True)

    def test_partial_history_startup_failure_closes_owned_store(self):
        self.run_main(recorder_error=True)

    def test_history_close_failure_cannot_skip_other_backend_cleanup(self):
        self.run_main(close_error=True)

    def test_history_requires_monitoring_before_any_startup_work(self):
        self.run_main(missing_monitoring=True)

    def test_invalid_feature_flag_rejected_before_any_startup_work(self):
        self.run_main(enabled='yes')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.recorder = Mock()
        self.recorder.read.return_value = {'ok': True, 'scope': 'cached_status_health', 'series': []}
        self.coordinator = Mock()
        self.coordinator.snapshot.side_effect = AssertionError('HTTP history must not sample')
        for name, value in [('API_TOKEN', 'fixture-token'), ('AUTH_MODE', 'trusted-network'),
                ('TRUSTED_CIDRS_RAW', '127.0.0.0/8'), ('ALLOWED_ORIGINS', set()), ('SYSTEM_HISTORY_ENABLED', True),
                ('SYSTEM_HISTORY_RECORDER', self.recorder), ('STATE_COORDINATOR', self.coordinator)]:
            p = patch.object(daemon, name, value)
            p.start()
            self.addCleanup(p.stop)
        from http.server import ThreadingHTTPServer
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), daemon.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, query='', token='fixture-token', origin=None, method='GET', duplicate=False):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        try:
            conn.putrequest(method, '/api/v1/system/history'+query)
            if token is not None:
                conn.putheader('x-jarvis-token', token)
            if duplicate:
                conn.putheader('x-jarvis-token', 'fixture-token')
            if origin:
                conn.putheader('Origin', origin)
            conn.endheaders()
            response = conn.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            conn.close()

    def test_history_uses_existing_trusted_network_policy_without_a_token(self):
        for token in (None, '', 'wrong', 'fixture-token'):
            self.assertEqual(self.request(token=token)[0], 200)
        self.assertEqual(self.recorder.read.call_count, 4)
        self.coordinator.snapshot.assert_not_called()
        self.recorder.tick.assert_not_called()

    def test_untrusted_network_cannot_read_history_even_with_a_token(self):
        with patch.object(daemon, 'TRUSTED_CIDRS_RAW', '192.0.2.0/24'):
            for token in (None, 'fixture-token'):
                self.assertEqual(self.request(token=token)[0], 403)
        self.recorder.read.assert_not_called()

    def test_token_mode_still_requires_existing_api_token(self):
        with patch.object(daemon, 'AUTH_MODE', 'token'):
            for token in ('', None, 'wrong'):
                self.assertEqual(self.request(token=token)[0], 401)
            self.recorder.read.assert_not_called()
            self.assertEqual(self.request()[0], 200)
        self.coordinator.snapshot.assert_not_called()

    def test_origin_and_duplicate_headers_rejected_before_read_in_both_modes(self):
        for mode in ('trusted-network', 'token'):
            with patch.object(daemon, 'AUTH_MODE', mode):
                self.assertEqual(self.request(duplicate=True)[0], 401)
                self.assertEqual(self.request(origin='https://unapproved.invalid')[0], 403)
        self.recorder.read.assert_not_called()
        self.coordinator.snapshot.assert_not_called()

    def test_bounded_queries_no_refresh_and_existing_no_store_headers(self):
        code, body, headers = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.recorder.read.assert_called_once_with('24h', None)
        for query in ('?window=1h', '?window=7d&component=service:jobs', '?component=devices'):
            self.assertEqual(self.request(query)[0], 200)
        self.coordinator.snapshot.assert_not_called()
        self.coordinator.request_refresh.assert_not_called()
        self.recorder.tick.assert_not_called()
        self.recorder.read.reset_mock()
        for query in ('?window=1h&window=1h', '?window=', '?window=100y', '?refresh=purifier',
                      '?resolution=1', '?component=../secret', '?component=', '?window=24h&',
                      '?window=24h&component=pi&extra=x', '?'+'x'*300, '?window'):
            with self.subTest(query=query):
                self.assertEqual(self.request(query)[0], 400)
        self.recorder.read.assert_not_called()

    def test_real_history_http_round_trip_is_cache_only_and_preserves_coverage(self):
        with tempfile.TemporaryDirectory() as raw:
            store = history.HistoryStore(Path(raw).resolve() / 'chart' / 'history.sqlite3')
            now, mono = [BASE], [0.0]
            reader = Mock(side_effect=lambda: snapshot(now[0]))
            recorder = history.HistoryRecorder(store, reader,
                clock=lambda: now[0], monotonic=lambda: mono[0])
            try:
                recorder.tick()
                now[0] += 60
                mono[0] += 60
                recorder.tick()
                now[0] += 10
                mono[0] += 10
                with patch.object(daemon, 'SYSTEM_HISTORY_RECORDER', recorder):
                    code, body, _ = self.request('?window=1h')
                    self.assertEqual(code, 200)
                    self.assertEqual(body['scope'], 'cached_status_health')
                    network = next(s for s in body['series'] if s['id'] == 'network')
                    self.assertEqual(network['buckets'][-1]['state'], 'healthy')
                    overall = next(s for s in body['series'] if s['id'] == 'overall')
                    self.assertEqual(overall['buckets'][-1]['state'], 'unknown')
                    self.assertEqual(overall['buckets'][-1]['coverageSeconds'], 30)
                    self.assertEqual(overall['buckets'][-1]['missingSeconds'], 30)
                    code, body, _ = self.request('?window=1h&component=service:jobs')
                    self.assertEqual(code, 200)
                    self.assertEqual(body['series'][0]['buckets'][-1]['state'], 'healthy')
                    self.assertNotIn('private-cloud-id', json.dumps(body))
                self.assertEqual(reader.call_count, 2)
                self.coordinator.snapshot.assert_not_called()
                self.coordinator.request_refresh.assert_not_called()
            finally:
                recorder.close()

    def test_disabled_storage_failure_unknown_component_sanitized(self):
        with patch.object(daemon, 'SYSTEM_HISTORY_ENABLED', False):
            self.assertEqual(self.request()[1]['error'], 'system_history_disabled')
        with patch.object(daemon, 'SYSTEM_HISTORY_RECORDER', None):
            self.assertEqual(self.request()[0], 503)
        self.recorder.read.assert_not_called()
        self.recorder.read.side_effect = RuntimeError('PRIVATE /path token=secret')
        code, body, _ = self.request()
        self.assertEqual(code, 503)
        self.assertNotIn('PRIVATE', json.dumps(body))
        self.recorder.read.side_effect = KeyError('PRIVATE')
        self.assertEqual(self.request('?component=service:missing')[0], 404)

    def test_post_cannot_sample_or_change_devices(self):
        self.assertEqual(self.request(method='POST')[0], 404)
        self.recorder.read.assert_not_called()
        self.recorder.tick.assert_not_called()
        self.coordinator.request_refresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
