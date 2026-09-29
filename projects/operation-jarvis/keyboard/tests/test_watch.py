import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cycle
import display_cycle
import watch
from test_cycle import presence, prefs


class ResponsiveTests(unittest.TestCase):
    def setUp(self):
        self.state = cycle.initial()
        self.faults = set()
        self.apply = Mock()

    def tick(self, now, location='nearby', **extra):
        cycle.tick(self.state, self.faults, now=now,
                   get_presence=lambda: presence(location, **extra),
                   get_preferences=prefs, apply=self.apply, save=Mock(),
                   choose=lambda choices: choices[0], responsive=True)

    def test_first_fresh_nearby_applies_immediately_then_rotates_only_each_minute(self):
        self.tick(100)
        self.apply.assert_called_once()
        first = self.apply.call_args.args[0]['effect']
        for now in range(103, 160, 3):
            self.tick(now)
        self.apply.assert_called_once()
        self.tick(160)
        self.assertEqual(self.apply.call_count, 2)
        self.assertNotEqual(first, self.apply.call_args.args[0]['effect'])

    def test_away_and_return_bypass_minute_timer_without_extra_debounce(self):
        self.tick(100)
        self.tick(103, 'away')
        self.assertEqual(self.apply.call_args.args[0], cycle.AWAY)
        self.assertEqual(self.apply.call_count, 2)
        self.tick(106, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.tick(109)
        self.assertEqual(self.apply.call_count, 3)
        self.assertNotEqual(self.apply.call_args.args[0]['effect'], 'ripples')
        self.assertFalse(self.state['away_applied'])
        for now in range(112, 169, 3):
            self.tick(now)
        self.assertEqual(self.apply.call_count, 3)
        self.tick(169)
        self.assertEqual(self.apply.call_count, 4)

    def test_no_catchup_or_sub_three_second_transition_writes(self):
        self.tick(100)
        self.tick(101, 'away'); self.tick(102, 'away')
        self.apply.assert_called_once()
        self.tick(103, 'away')
        self.assertEqual(self.apply.call_count, 2)

    def test_known_failure_cooldown_survives_presence_flips(self):
        self.apply.side_effect = cycle.CycleError('keyboard')
        self.tick(100, 'away')
        for now in range(103, 160, 3):
            self.tick(now, 'away' if now % 2 else 'nearby')
        self.apply.assert_called_once()
        self.apply.side_effect = None
        self.tick(160, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.assertFalse(self.faults)

    def test_uncertain_write_stays_blocked_through_restart_and_presence_flips(self):
        self.apply.side_effect = cycle.CycleError('keyboard', uncertain=True)
        self.tick(100)
        self.state = cycle.validate_state(dict(self.state))
        for now in (103, 160, 220):
            self.tick(now, 'away')
        self.apply.assert_called_once()
        self.assertTrue(self.state['pending'])

    def test_unknown_never_changes_lighting_then_first_fresh_away_applies(self):
        self.tick(100)
        self.tick(103, 'unknown', stale=True, ageSeconds=None)
        self.apply.assert_called_once()
        self.tick(106, 'away')
        self.assertEqual(self.apply.call_count, 2)
        self.assertEqual(self.apply.call_args.args[0], cycle.AWAY)

    def test_stale_at_final_deadline_sends_nothing(self):
        with patch.object(cycle.time, 'monotonic', side_effect=[0, 1, 16]):
            self.tick(100, 'away')
        self.apply.assert_not_called()
        self.assertFalse(self.state['pending'])
        self.assertIn('presence', self.faults)

    def test_black_v2_migrates_without_claiming_white_ripples_already_applied(self):
        old = cycle.initial()
        old.pop('away_applied')
        old.update(version=2, lighting_dark=True, mode='dark', pending=True, last_effect='scan')
        new = cycle.validate_state(old)
        self.assertEqual(new['version'], 4)
        self.assertFalse(new['away_applied'])
        self.assertTrue(new['pending'])
        self.assertEqual(new['last_effect'], 'scan')
        self.assertNotIn('lighting_dark', new)

    def test_away_profile_persists_without_repeated_write_after_restart(self):
        self.tick(100, 'away')
        self.state = cycle.validate_state(dict(self.state))
        self.tick(500, 'away')
        self.apply.assert_called_once_with(cycle.AWAY)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = cycle.Store(Path(self.temp.name) / 'runtime')
        self.mouse_patch = patch('mouse_cycle.send')
        self.mouse_sender = self.mouse_patch.start()
        self.addCleanup(self.mouse_patch.stop)

    def relay(self, now):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = watch.relay(self.store, now=lambda: now)
        return output.getvalue(), code

    def test_healthy_steps_and_relay_are_silent(self):
        sender = Mock()
        watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(), apply=sender)
        sender.assert_called_once()
        self.assertEqual(self.relay(103), ('', 0))

    def test_durable_error_once_and_successful_recovery_once(self):
        sender = Mock(side_effect=cycle.CycleError('keyboard'))
        for now in (100, 103, 106):
            watch.step(self.store, now=lambda: now, get_presence=lambda: presence('away'), apply=sender)
        sender.assert_called_once()
        self.assertEqual(self.relay(109), ('', 0))
        self.assertEqual(self.relay(110), ('', 0))
        watch.step(self.store, now=lambda: 157,
                   get_presence=lambda: presence('away'), apply=sender)
        # Notification state survives a relay process/store restart.
        self.store = cycle.Store(self.store.directory)
        result = self.relay(160)
        self.assertEqual(result[0].count('ERROR:'), 1)
        self.assertEqual(result[1], 1)
        self.assertEqual(self.relay(161), ('', 0))
        sender.side_effect = None
        watch.step(cycle.Store(self.store.directory), now=lambda: 160,
                   get_presence=lambda: presence('away'), apply=sender)
        result = self.relay(163)
        self.assertEqual(result[0].count('RECOVERED:'), 1)
        self.assertIn('White ripples', result[0])
        self.assertEqual(result[1], 0)
        self.assertEqual(self.relay(164), ('', 0))

    def test_missing_watcher_reports_once_then_recovers_without_hid_from_relay(self):
        self.assertEqual(self.relay(100), ('', 0))
        self.assertEqual(self.relay(159), ('', 0))
        result = self.relay(160)
        self.assertEqual(result[1], 1)
        self.assertIn('Computer presence', result[0])
        self.assertIn('keyboard, mouse, and monitor', result[0])
        self.assertEqual(self.relay(161), ('', 0))
        watch.step(self.store, now=lambda: 163, get_presence=lambda: presence(), apply=Mock())
        with patch.object(cycle, 'send', side_effect=AssertionError('No relay HID')):
            result = self.relay(166)
        self.assertIn('RECOVERED:', result[0])
        self.assertIn('not device-state verification', result[0])
        self.assertIn('Computer presence', result[0])
        self.assertIn('keyboard, mouse, and monitors', result[0])
        self.assertEqual(self.relay(169), ('', 0))

    def test_stale_heartbeat_alert_is_latched(self):
        watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(), apply=Mock())
        self.assertEqual(self.relay(131), ('', 0))
        self.assertEqual(self.relay(189), ('', 0))
        self.assertEqual(self.relay(190)[1], 1)
        self.assertEqual(self.relay(200), ('', 0))

    def event(self, component, at, recovered=False):
        name = component.capitalize()
        prefix = 'RECOVERED' if recovered else 'ERROR'
        return {'message': f'{prefix}: {name} automation checks ' +
                ('are working again.' if recovered else 'failed.'),
                'code': 0 if recovered else 1, 'at': at}

    def test_recovered_blip_and_unsolicited_recovery_are_silent(self):
        state = watch.notification_state(self.store)
        error, recovery = self.event('keyboard', 100), self.event('keyboard', 105, True)
        self.assertEqual(watch.notifications(state, [error, recovery], at=200), [])
        self.assertEqual(state['pending'], {})
        self.assertEqual(watch.notifications(state, [recovery], at=201), [])

    def test_recovery_resets_grace_for_later_failure_and_is_component_specific(self):
        state = watch.notification_state(self.store)
        messages = [self.event('keyboard', 100), self.event('keyboard', 110, True),
                    self.event('keyboard', 150), self.event('mouse', 151, True)]
        self.assertEqual(watch.notifications(state, messages, at=200), [])
        self.assertEqual(state['pending']['keyboard']['since'], 150)
        self.assertEqual(watch.notifications(state, [], at=210)[0]['code'], 1)
        self.assertEqual(watch.notifications(state, [], at=220), [])

    def test_recovery_only_for_previously_notified_component(self):
        state = watch.notification_state(self.store)
        self.assertEqual(watch.notifications(state, [self.event('keyboard', 100)], at=159), [])
        self.assertEqual(watch.notifications(state, [], at=160)[0]['code'], 1)
        output = watch.notifications(state, [self.event('mouse', 160),
            self.event('keyboard', 165, True), self.event('mouse', 166, True)], at=170)
        self.assertEqual(len(output), 1)
        self.assertIn('RECOVERED: Keyboard', output[0]['message'])
        self.assertEqual(state['pending'], {})

    def test_delayed_relay_does_not_report_already_recovered_long_failure(self):
        state = watch.notification_state(self.store)
        self.assertEqual(watch.notifications(state, [self.event('keyboard', 100),
                         self.event('keyboard', 170, True)], at=200), [])

    def test_fresh_heartbeat_recovery_before_delay_is_silent(self):
        self.assertEqual(self.relay(100), ('', 0))
        watch.step(self.store, now=lambda: 130, get_presence=lambda: presence(), apply=Mock())
        self.assertEqual(self.relay(131), ('', 0))
        self.assertNotIn('watcher', watch.notification_state(self.store)['pending'])

    def test_queue_timestamps_and_real_blip_are_silent_without_safety_change(self):
        sender = Mock()
        watch.step(self.store, now=lambda: 100,
                   get_presence=Mock(side_effect=cycle.CycleError('presence')), apply=sender)
        sender.assert_not_called()
        self.assertIn('presence', self.store.load('alerts.json', []))
        self.assertTrue(all(item['at'] == 100 for item in watch.snapshot(self.store)['alerts']))
        self.assertEqual(self.relay(110), ('', 0))
        watch.step(self.store, now=lambda: 113,
                   get_presence=lambda: presence('away'), apply=sender)
        self.assertEqual(self.relay(120), ('', 0))
        self.assertEqual(watch.notification_state(self.store)['pending'], {})

    def test_current_latches_reconcile_lost_error_and_recovery(self):
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 100, 'alerts': []})
        self.store.save('alerts.json', ['presence'])
        self.assertEqual(self.relay(100), ('', 0))
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 160, 'alerts': []})
        self.assertEqual(self.relay(160)[1], 1)
        self.store.save('alerts.json', [])
        self.assertIn('RECOVERED: Keyboard', self.relay(161)[0])
        self.assertEqual(self.relay(162), ('', 0))

    def test_legacy_events_receive_full_delay_instead_of_immediate_error(self):
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 100, 'alerts': [
            {'message': 'ERROR: Keyboard lighting command failed.', 'code': 1}]})
        self.assertEqual(self.relay(100), ('', 0))
        self.assertEqual(watch.notification_state(self.store)['pending']['keyboard']['since'], 100)

    def test_corrupt_notification_state_is_not_silently_reset(self):
        self.store.save('notifications.json', {'version': 1, 'pending': {'keyboard': {
            'since': 100, 'notified': 'false', 'message': 'ERROR: Keyboard failed.'}}})
        with self.assertRaises(cycle.CycleError):
            self.relay(160)

    def test_future_timestamp_does_not_skip_grace(self):
        state = watch.notification_state(self.store)
        self.assertEqual(watch.notifications(state, [self.event('keyboard', 200)], at=100), [])
        self.assertEqual(state['pending']['keyboard']['since'], 100)

    def test_storage_blips_and_recovery_are_silent_until_notified(self):
        def notify(failed, at):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(watch.tempfile, 'gettempdir',
                                                                  return_value=self.temp.name):
                code = watch.storage_notifications(failed, now=lambda: at)
            return output.getvalue(), code
        self.assertEqual(notify(True, 100), ('', 0))
        self.assertEqual(notify(False, 110), ('', 0))
        self.assertEqual(notify(True, 120), ('', 0))
        self.assertEqual(notify(True, 179), ('', 0))
        self.assertEqual(notify(True, 180)[1], 1)
        self.assertEqual(notify(True, 181), ('', 0))
        self.assertIn('RECOVERED:', notify(False, 182)[0])
        self.assertEqual(notify(False, 183), ('', 0))

    def test_startup_grace_preserves_queue_and_expires(self):
        self.store.save('watcher-started.json', 100)
        self.store.save('watcher.json', {'version': 1, 'heartbeat': None, 'alerts': [
            {'message': 'ERROR: Keyboard lighting command failed.', 'code': 1}]})
        self.assertEqual(self.relay(106), ('', 0))
        self.assertEqual(len(watch.snapshot(self.store)['alerts']), 1)
        self.assertEqual(self.relay(131), ('', 0))
        self.assertEqual(len(watch.snapshot(self.store)['alerts']), 0)
        self.assertEqual(self.relay(191)[1], 1)

    def test_display_fault_is_deferred_and_recovery_is_not_device_verification(self):
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 100, 'alerts': []})
        self.store.save('display-state.json', dict(display_cycle.initial(), pending=True, fault=True))
        self.assertEqual(self.relay(100), ('', 0))
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 160, 'alerts': []})
        result = self.relay(160)
        self.assertIn('ERROR: Display', result[0])
        self.assertEqual(result[1], 1)
        self.store.save('display-state.json', display_cycle.initial())
        self.assertIn('not device-state verification', self.relay(161)[0])

    def test_unresponsive_watcher_does_not_falsely_clear_controller_fault(self):
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 100, 'alerts': []})
        self.store.save('alerts.json', ['presence'])
        self.assertEqual(self.relay(100), ('', 0))
        self.store.save('alerts.json', [])  # Cached state is not recovery proof without heartbeat.
        self.assertIn('ERROR: Basement', self.relay(160)[0])
        self.assertTrue(watch.notification_state(self.store)['pending']['keyboard']['notified'])

    def test_recovery_of_notified_fault_followed_by_new_fault_gets_new_delay(self):
        state = watch.notification_state(self.store)
        self.assertEqual(watch.notifications(state, [self.event('keyboard', 100)], at=160)[0]['code'], 1)
        output = watch.notifications(state, [self.event('keyboard', 165, True),
            self.event('keyboard', 170)], at=200)
        self.assertEqual([item['code'] for item in output], [0])
        self.assertFalse(state['pending']['keyboard']['notified'])
        self.assertEqual(watch.notifications(state, [], at=230)[0]['code'], 1)

    def test_corrupt_event_timestamp_is_rejected_without_draining_queue(self):
        self.store.save('watcher.json', {'version': 1, 'heartbeat': 100, 'alerts': [
            dict(self.event('keyboard', 100), at=True)]})
        with self.assertRaises(cycle.CycleError):
            self.relay(160)
        self.assertEqual(len(self.store.load('watcher.json', {})['alerts']), 1)

    def test_backend_timeout_reason_survives_helper(self):
        with patch.object(cycle.subprocess, 'run', return_value=Mock(
                returncode=1, stdout='{"ok":false,"reason":"backend-timeout"}')):
            with self.assertRaises(cycle.CycleError) as caught:
                cycle.read_presence()
        self.assertEqual(caught.exception.reason, 'backend-timeout')

    def test_transport_failure_diagnostic_does_not_send(self):
        sender = Mock()
        watch.step(self.store, now=lambda: 100,
                   get_presence=Mock(side_effect=cycle.CycleError('presence', reason='backend-timeout')),
                   apply=sender)
        sender.assert_not_called()
        entries = self.store.load('diagnostics.json', [])
        self.assertEqual(entries[0]['reason'], 'backend-timeout')
        self.assertEqual(entries[0]['at'], 100)

    def test_diagnostics_are_bounded_and_capture_stale_age(self):
        for n in range(40):
            watch.diagnose(self.store, 'test', at=n)
        self.assertEqual(len(self.store.load('diagnostics.json', [])), 32)
        sender = Mock()
        watch.step(self.store, now=lambda: 100,
                   get_presence=lambda: presence(ageSeconds=20, stale=True), apply=sender)
        sender.assert_not_called()
        entries = self.store.load('diagnostics.json', [])
        failure = next(e for e in entries if e['event'] == 'presence-failure')
        self.assertEqual(failure['reason'], 'snapshot-stale')
        self.assertGreaterEqual(failure['ageSeconds'], 20)

    def test_corrupt_outbox_blocks_step_before_any_hid(self):
        self.store.save('watcher.json', {'alerts': []})
        sender = Mock()
        with self.assertRaises(cycle.CycleError):
            watch.step(self.store, now=lambda: 100, get_presence=lambda: presence(), apply=sender)
        sender.assert_not_called()

    def test_single_watcher_and_shared_cycle_lock(self):
        with watch.locked(self.store, 'watcher.lock'):
            with self.assertRaises(BlockingIOError):
                with watch.locked(self.store, 'watcher.lock'):
                    self.fail('second watcher acquired singleton lock')
        with watch.locked(self.store, 'cycle.lock'):
            with self.assertRaises(BlockingIOError):
                with watch.locked(self.store, 'cycle.lock'):
                    self.fail('overlapping step acquired cycle lock')


if __name__ == '__main__':
    unittest.main()
