import unittest
from unittest.mock import Mock
import bridge_recovery
import cycle
import mouse_cycle
from test_cycle import presence, prefs


class BridgeRecovery(unittest.TestCase):
    def test_recovery_demands_bridge_idle_ack_with_no_hardware_write(self):
        ready={'status':'ok','device_available':True,'pending':True}
        for reply,expected in [({'status':'acknowledged','hardware_write':False},True),
                               ({'status':'blocked','reason':'operation_still_outstanding'},False),
                               ({'status':'acknowledged','hardware_write':True},False),
                               ({'status':'acknowledged'},False)]:
            request=Mock(side_effect=[ready,reply])
            self.assertEqual(bridge_recovery.reconcile(request),expected)
            self.assertEqual([x.args for x in request.call_args_list],[('status',),('acknowledge',)])

    def test_unavailable_device_never_acknowledged(self):
        request=Mock(return_value={'status':'ok','device_available':False,'pending':True})
        self.assertFalse(bridge_recovery.reconcile(request));request.assert_called_once_with('status')

    def test_mouse_recovery_is_paced_no_apply_until_new_fresh_tick(self):
        state=mouse_cycle.initial()|{'pending':True,'last_attempt':100}
        apply=Mock();reconcile=Mock(return_value=True)
        for now in (103,160):
            mouse_cycle.tick(state,set(),now=now,get_presence=presence,apply=apply,reconcile=reconcile,save=lambda _:None)
        reconcile.assert_called_once();apply.assert_not_called();self.assertFalse(state['pending'])
        mouse_cycle.tick(state,set(),now=220,get_presence=lambda:presence('away'),apply=apply,reconcile=reconcile,save=lambda _:None)
        apply.assert_called_once_with('off')

    def test_keyboard_recovery_retains_unknown_outcome_and_defers_current_intent(self):
        state=cycle.initial()|{'pending':True,'last_attempt':100}
        apply=Mock();reconcile=Mock(return_value=True)
        cycle.tick(state,set(),now=160,get_presence=presence,get_preferences=prefs,apply=apply,
                   reconcile=reconcile,save=lambda _:None)
        self.assertFalse(state['pending']);self.assertEqual(state['mode'],'paused')
        apply.assert_not_called();reconcile.assert_called_once()

    def test_outstanding_keyboard_write_stays_blocked_but_next_probe_is_allowed(self):
        state=cycle.initial()|{'pending':True,'last_attempt':100}
        apply=Mock();reconcile=Mock(return_value=False)
        for now in (160,220,280):
            cycle.tick(state,set(),now=now,get_presence=presence,get_preferences=prefs,apply=apply,
                       reconcile=reconcile,save=lambda _:None)
        self.assertTrue(state['pending']);self.assertEqual(reconcile.call_count,3);apply.assert_not_called()

class LegacyRecovery(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = Mock(side_effect=[{'status':'ok','device_available':True,'pending':True},
                                        {'status':'acknowledged','hardware_write':False}])

    def journal(self, at=1):
        import json
        (self.root / 'uncertain.json').write_text(json.dumps({'report':'00'*90,'time':at}))

    def test_legacy_retirement_keeps_unknown_history_and_never_applies(self):
        self.journal()
        original = (self.root / 'uncertain.json').read_bytes()
        self.assertTrue(bridge_recovery.retire_legacy_mouse(self.root, self.request, now=100))
        self.assertFalse((self.root / 'uncertain.json').exists())
        self.assertEqual((self.root / 'retired-uncertain.json').read_bytes(), original)
        self.assertEqual([x.args for x in self.request.call_args_list], [('status',), ('acknowledge',)])

    def test_recent_unknown_waits_without_contact(self):
        self.journal(90)
        self.assertFalse(bridge_recovery.retire_legacy_mouse(self.root, self.request, now=100))
        self.request.assert_not_called()

    def test_live_legacy_writer_blocks_retirement(self):
        import fcntl
        self.journal()
        with (self.root / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                bridge_recovery.retire_legacy_mouse(self.root, self.request, now=100)
        self.assertTrue((self.root / 'uncertain.json').exists())
        self.request.assert_not_called()

    def test_symlink_and_corrupt_journals_do_not_get_retired(self):
        self.journal()
        (self.root / 'uncertain.json').rename(self.root / 'other')
        (self.root / 'uncertain.json').symlink_to(self.root / 'other')
        with self.assertRaises(OSError):
            bridge_recovery.retire_legacy_mouse(self.root, self.request, now=100)
        (self.root / 'uncertain.json').unlink()
        (self.root / 'uncertain.json').write_text('{}')
        with self.assertRaises(RuntimeError):
            bridge_recovery.retire_legacy_mouse(self.root, self.request, now=100)
        self.request.assert_not_called()

    def test_direct_keyboard_uses_only_idle_lock_and_metadata(self):
        from unittest.mock import patch
        import ajazz
        for count in (0, 1, 2):
            with patch('bridge_client.backend', return_value='direct'), \
                 patch.object(ajazz, '__file__', str(self.root / 'ajazz.py')), \
                 patch.object(ajazz, 'hid_module', return_value=object()), \
                 patch.object(ajazz, 'keyboard_status', return_value={
                     'connected': bool(count), 'matching_interfaces': count, 'hardware_write': False}):
                self.assertEqual(bridge_recovery.keyboard(), count == 1)

if __name__=='__main__':unittest.main()
