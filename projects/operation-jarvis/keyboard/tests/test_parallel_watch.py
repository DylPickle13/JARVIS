"""Mocked concurrency tests: no Bluetooth, HID, display or network operations."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import cycle
import display_cycle
import led_cycle
import mouse_cycle
import watch
from test_cycle import presence


class ParallelWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = cycle.Store(Path(self.temp.name) / 'runtime')
        self.store.save('display-config.json', {'enabled': True})
        self.store.save('display-state.json', dict(display_cycle.initial(), mode='away'))
        self.store.save('led-config.json', {'enabled': True})
        self.keyboard, self.mouse, self.display = Mock(), Mock(), Mock()
        self.led = Mock(return_value=True)

    def step(self, at=100, mode='nearby', **kwargs):
        defaults = dict(now=lambda: at, get_presence=lambda: presence(mode),
                        apply=self.keyboard, mouse_apply=self.mouse,
                        display_apply=self.display, led_apply=self.led)
        defaults.update(kwargs)
        return watch.step(self.store, **defaults)

    def test_all_commands_overlap_after_durable_reservation(self):
        barrier = threading.Barrier(4, timeout=5)
        entered = set()
        lock = threading.Lock()
        files = {'keyboard': 'state.json', 'mouse': 'mouse-state.json',
                 'display': 'display-state.json', 'led': 'led-state.json'}
        def sender(name):
            def send(*_args):
                self.assertTrue(self.store.load(files[name], {})['pending'])
                with lock:
                    entered.add(name)
                barrier.wait()  # Sequential dispatch cannot pass this barrier.
                return True if name == 'led' else None
            return send
        fetch = Mock(return_value=presence())
        self.step(get_presence=fetch, apply=sender('keyboard'), mouse_apply=sender('mouse'),
                  display_apply=sender('display'), led_apply=sender('led'))
        self.assertEqual(entered, set(files))
        fetch.assert_called_once()
        for filename in files.values():
            self.assertFalse(self.store.load(filename, {})['pending'])
        self.assertEqual(self.store.load('display-state.json', {})['mode'], 'nearby')

    def test_monitor_wakes_while_usb_and_led_commands_are_still_busy(self):
        release = threading.Event()
        entered = {name: threading.Event() for name in ('keyboard', 'mouse', 'led')}
        woke = threading.Event()
        def busy(name):
            def send(*_args):
                entered[name].set()
                if not release.wait(5):
                    raise RuntimeError('Test release timed out')
                return True if name == 'led' else None
            return send
        with ThreadPoolExecutor(max_workers=1) as coordinator:
            future = coordinator.submit(self.step, apply=busy('keyboard'),
                mouse_apply=busy('mouse'), led_apply=busy('led'),
                display_apply=lambda action: woke.set())
            try:
                for event in entered.values():
                    self.assertTrue(event.wait(5))
                self.assertTrue(woke.wait(5))
                self.assertFalse(release.is_set())
                self.assertFalse(future.done())  # Pass still owns the remaining work.
            finally:
                release.set()
            future.result(timeout=5)

    def test_cycle_lock_survives_worker_exception_until_all_workers_settle(self):
        entered, release = threading.Event(), threading.Event()
        def busy_led(*_args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test release timed out')
            return True
        with ThreadPoolExecutor(max_workers=4) as workers, ThreadPoolExecutor(max_workers=1) as coordinator:
            def locked_step():
                with watch.locked(self.store, 'cycle.lock'):
                    self.step(executor=workers, led_apply=busy_led)
            with patch.object(cycle, 'run_once', side_effect=OSError('Test storage failure')):
                future = coordinator.submit(locked_step)
                try:
                    self.assertTrue(entered.wait(5))
                    with self.assertRaises(BlockingIOError):
                        with watch.locked(self.store, 'cycle.lock'):
                            self.fail('Cycle lock released before worker completion')
                    self.assertFalse(future.done())
                finally:
                    release.set()
                with self.assertRaises(OSError):
                    future.result(timeout=5)
            self.display.assert_called_once_with('wake')
            with watch.locked(self.store, 'cycle.lock'):
                pass

    def test_one_failed_presence_fetch_and_one_diagnostic_for_all_workers(self):
        fetch = Mock(side_effect=cycle.CycleError('presence', reason='backend-timeout'))
        self.step(get_presence=fetch)
        fetch.assert_called_once()
        for sender in (self.keyboard, self.mouse, self.display, self.led):
            sender.assert_not_called()
        events = self.store.load('diagnostics.json', [])
        failures = [event for event in events if event['event'] == 'presence-failure']
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['reason'], 'backend-timeout')

    def test_presence_payloads_are_independent_copies(self):
        original = presence()
        fetch = Mock(return_value=original)
        barrier = threading.Barrier(4, timeout=5)
        def controller(_store, *, get_presence, **_kwargs):
            payload = get_presence()
            payload['zones'][0]['state'] = 'away'
            barrier.wait()
            self.assertEqual(get_presence()['zones'][0]['state'], 'nearby')
            return '', 0
        with patch.object(cycle, 'run_once', side_effect=controller), patch.object(
                mouse_cycle, 'run_once', side_effect=controller), patch.object(
                display_cycle, 'run_once', side_effect=controller), patch.object(
                led_cycle, 'run_once', side_effect=controller):
            self.step(get_presence=fetch)
        fetch.assert_called_once()
        self.assertEqual(original['zones'][0]['state'], 'nearby')

    def test_alerts_are_merged_serially_in_controller_order(self):
        barrier = threading.Barrier(4, timeout=5)
        messages = ['ERROR: Keyboard lighting command failed.',
                    'ERROR: Mouse lighting command failed.',
                    'ERROR: Display automation blocked.',
                    'ERROR: LED strip automation blocked.']
        owner = threading.get_ident()
        diagnose = watch.diagnose
        def merge(*args, **kwargs):
            self.assertEqual(threading.get_ident(), owner)
            return diagnose(*args, **kwargs)
        def controller(message):
            def run(*_args, **_kwargs):
                barrier.wait()
                return message, 1
            return run
        with patch.object(watch, 'diagnose', side_effect=merge), patch.object(
                cycle, 'run_once', side_effect=controller(messages[0])), patch.object(
                mouse_cycle, 'run_once', side_effect=controller(messages[1])), patch.object(
                display_cycle, 'run_once', side_effect=controller(messages[2])), patch.object(
                led_cycle, 'run_once', side_effect=controller(messages[3])):
            self.step()
        self.assertEqual([item['message'] for item in watch.snapshot(self.store)['alerts']], messages)
        self.assertEqual(len(self.store.load('diagnostics.json', [])), 4)

    def test_pending_keyboard_fault_survives_restart_without_replay(self):
        self.keyboard.side_effect = cycle.CycleError('keyboard', uncertain=True)
        self.step()
        self.store = cycle.Store(self.store.directory)
        self.step(at=160)
        self.keyboard.assert_called_once()
        self.mouse.assert_called_once_with('steady')
        self.display.assert_called_once_with('wake')
        self.led.assert_called_once()
        self.assertTrue(self.store.load('state.json', {})['pending'])
        self.assertFalse(self.store.load('display-state.json', {})['pending'])

    def test_pending_display_fault_does_not_block_other_devices_or_retry(self):
        self.display.side_effect = RuntimeError('Uncertain wake')
        self.step()
        self.store = cycle.Store(self.store.directory)
        self.step(at=103)
        self.display.assert_called_once_with('wake')
        self.keyboard.assert_called_once()
        self.mouse.assert_called_once_with('steady')
        self.led.assert_called_once()
        state = self.store.load('display-state.json', {})
        self.assertTrue(state['pending'])
        self.assertTrue(state['fault'])

    def test_worker_exception_preserves_sibling_alerts_without_fresh_heartbeat(self):
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 90, 'alerts': []})
        messages = ['ERROR: Mouse lighting command failed.',
                    'ERROR: Display automation blocked.',
                    'ERROR: LED strip automation blocked.']
        with patch.object(cycle, 'run_once', side_effect=OSError('Test failure')), patch.object(
                mouse_cycle, 'run_once', return_value=(messages[0], 1)), patch.object(
                display_cycle, 'run_once', return_value=(messages[1], 1)), patch.object(
                led_cycle, 'run_once', return_value=(messages[2], 1)), patch.object(
                watch.arrival_cycle, 'run_once') as arrival:
            with self.assertRaises(OSError):
                self.step()
            arrival.assert_not_called()
        state = watch.snapshot(self.store)
        self.assertEqual(state['heartbeat'], 90)
        self.assertEqual([item['message'] for item in state['alerts']], messages)

    def test_corrupt_outbox_starts_no_controllers(self):
        self.store.save('watcher.json', {'alerts': []})
        fetch = Mock(return_value=presence())
        with self.assertRaises(cycle.CycleError):
            self.step(get_presence=fetch)
        fetch.assert_not_called()
        for sender in (self.keyboard, self.mouse, self.display, self.led):
            sender.assert_not_called()

    def test_initial_nearby_never_causes_startup_wake(self):
        self.store.save('display-state.json', display_cycle.initial())
        self.step()
        self.display.assert_not_called()
        self.keyboard.assert_called_once()
        self.mouse.assert_called_once_with('steady')
        self.led.assert_called_once()

    def test_departure_still_needs_three_consecutive_fresh_checks(self):
        self.store.save('display-state.json', dict(display_cycle.initial(), mode='nearby'))
        self.step(mode='away')
        self.display.assert_not_called()
        self.step(at=103, mode='away')
        self.display.assert_not_called()
        self.step(at=106, mode='away')
        self.display.assert_called_once_with('lock-sleep')
        self.step(at=109, mode='away')
        self.display.assert_called_once_with('lock-sleep')

    def test_reused_pool_does_not_repeat_successful_transitions(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            self.step(executor=workers)
            self.step(at=103, executor=workers)
        self.keyboard.assert_called_once()
        self.mouse.assert_called_once_with('steady')
        self.display.assert_called_once_with('wake')
        self.led.assert_called_once()

    def test_partial_submission_failure_waits_for_started_work(self):
        entered, release = threading.Event(), threading.Event()
        def keyboard(*_args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test release timed out')
        with ThreadPoolExecutor(max_workers=4) as workers, ThreadPoolExecutor(max_workers=1) as coordinator:
            class FailingExecutor:
                submissions = 0
                def submit(self, run):
                    self.submissions += 1
                    if self.submissions > 1:
                        raise RuntimeError('Test executor failure')
                    return workers.submit(run)
            future = coordinator.submit(self.step, executor=FailingExecutor(), apply=keyboard)
            try:
                self.assertTrue(entered.wait(5))
                self.assertFalse(future.done())
            finally:
                release.set()
            with self.assertRaises(RuntimeError):
                future.result(timeout=5)
        self.assertFalse(self.store.load('state.json', {})['pending'])
        self.mouse.assert_not_called()
        self.display.assert_not_called()
        self.led.assert_not_called()

    def test_stale_snapshot_never_sends_any_command(self):
        self.step(get_presence=lambda: presence(ageSeconds=16, stale=True))
        for sender in (self.keyboard, self.mouse, self.display, self.led):
            sender.assert_not_called()
