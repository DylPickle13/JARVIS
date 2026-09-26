import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import ajazz
import cycle


def presence(state='nearby', **extra):
    zone = dict(subject='dylan', zone='basement', state=state, stale=False, ageSeconds=1)
    zone.update(extra)
    return {'ok': True, 'zones': [zone, dict(zone='living room', state='nearby')]}


def prefs():
    return cycle.preferences((cycle.ROOT / 'liked-effects.md').read_text())


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.state = cycle.initial()
        self.faults = set()
        self.apply = Mock()
        self.save = Mock()

    def tick(self, now, payload=None, **kwargs):
        cycle.tick(self.state, self.faults, now=now,
                   get_presence=lambda: payload if payload is not None else presence(),
                   get_preferences=kwargs.get('get_preferences', prefs),
                   apply=self.apply, save=kwargs.get('save', self.save), choose=lambda choices: choices[0])

    def test_preferences_only_liked_names_and_saved_settings(self):
        effects, values = prefs()
        self.assertEqual(effects, ['corrugated','cloud','serpentine','breath','stars','wave','cartoon','rain','scan'])
        self.assertEqual(values, {'color':'#FFFFFF','brightness':'highest','speed':'fastest'})
        for text in ('', (cycle.ROOT/'liked-effects.md').read_text().replace('corrugated', 'firmware')):
            with self.assertRaises(cycle.CycleError): cycle.preferences(text)

    def test_two_nearby_observations_then_one_write_each_minute(self):
        self.tick(100)
        self.apply.assert_not_called()
        self.tick(160)
        self.apply.assert_called_once()
        self.assertEqual(self.state['mode'], 'cycling')
        self.tick(219)
        self.assertEqual(self.apply.call_count, 1)
        self.tick(220)
        self.assertEqual(self.apply.call_count, 2)
        self.assertNotEqual(self.apply.call_args_list[0].args[0]['effect'], self.apply.call_args_list[1].args[0]['effect'])
        self.assertEqual(self.apply.call_args.args[0]['color'], '#FFFFFF')

    def test_away_applies_once_after_legacy_debounce_and_requires_nearby_reentry(self):
        self.tick(100); self.tick(160)
        self.tick(220, presence('away'))
        self.assertEqual(self.apply.call_count, 1)
        self.tick(280, presence('away'))
        self.assertEqual(self.apply.call_count, 2)
        self.assertEqual(self.apply.call_args.args[0], cycle.AWAY)
        self.assertTrue(self.state['away_applied'])
        self.tick(340, presence('away'))
        self.assertEqual(self.apply.call_count, 2)
        self.tick(400)
        self.assertEqual(self.apply.call_count, 2)
        self.tick(460)
        self.assertEqual(self.apply.call_count, 3)
        self.assertEqual(self.apply.call_args.args[0]['color'], '#FFFFFF')
        self.assertFalse(self.state['away_applied'])

    def test_away_configuration_matches_requested_white_ripples(self):
        self.assertEqual(cycle.AWAY, dict(effect='ripples', color='#FFFFFF', brightness='highest',
                                         speed='fastest', direction='left_to_right'))
        self.assertEqual(ajazz.report(cycle.AWAY)[13:17], bytes([0, 0xff, 0xff, 0xff]))
        self.assertEqual(len(ajazz.report(cycle.AWAY)), 65)

    def test_unknown_never_applies_away_or_counts_as_an_away_check(self):
        self.tick(100, presence('away'))
        self.tick(160, presence('unknown', stale=True, ageSeconds=None))
        self.tick(220, presence('away'))
        self.apply.assert_not_called()
        self.tick(280, presence('away'))
        self.apply.assert_called_once_with(cycle.AWAY)

    def test_either_device_near_prevents_away_profile(self):
        for source in ('iphone', 'watch'):
            state=cycle.initial(); apply=Mock()
            for now in (100,160):
                cycle.tick(state,set(),now=now,get_presence=lambda:presence(sources=[source]),
                           get_preferences=prefs,apply=apply,save=Mock(),choose=lambda c:c[0])
            self.assertNotEqual(apply.call_args.args[0]['effect'],'ripples')

    def test_applied_away_survives_unknown_gap_without_repeat(self):
        self.tick(100,presence('away'));self.tick(160,presence('away'))
        self.tick(220,presence('unknown',stale=True,ageSeconds=None))
        self.tick(400,presence('away'));self.tick(460,presence('away'))
        self.apply.assert_called_once_with(cycle.AWAY)

    def test_failed_away_command_is_not_marked_applied(self):
        self.apply.side_effect=cycle.CycleError('keyboard')
        self.tick(100,presence('away'));self.tick(160,presence('away'))
        self.assertFalse(self.state['away_applied'])
        self.assertEqual(self.faults,{'keyboard'})
        self.apply.side_effect=None
        self.tick(220,presence('away'))
        self.assertTrue(self.state['away_applied'])
        self.assertFalse(self.faults)
        self.tick(280,presence('away'))
        self.assertEqual(self.apply.call_count,2)

    def test_uncertain_away_command_is_not_repeated(self):
        self.apply.side_effect=cycle.CycleError('keyboard',uncertain=True)
        self.tick(100,presence('away'));self.tick(160,presence('away'));self.tick(220,presence('away'))
        self.apply.assert_called_once()
        self.assertTrue(self.state['pending'])
        self.assertFalse(self.state['away_applied'])

    def test_v1_state_migration_preserves_pending_and_prior_effect(self):
        old=cycle.initial()
        old.pop('away_count');old.pop('away_applied');old['version']=1
        old.update(pending=True,last_effect='scan',last_attempt=99)
        upgraded=cycle.validate_state(old)
        self.assertEqual(upgraded['version'],4)
        self.assertTrue(upgraded['pending'])
        self.assertEqual(upgraded['last_effect'],'scan')
        self.assertFalse(upgraded['away_applied'])
        self.assertEqual(old['version'],1)

    def test_unknown_is_not_away_and_resets_near_debounce(self):
        self.tick(100)
        self.tick(160, presence('unknown', stale=True, ageSeconds=None))
        self.assertEqual(self.faults, {'presence'})
        self.assertEqual(self.state['near_count'], 0)
        self.tick(220)
        self.apply.assert_not_called()

    def test_missing_duplicate_wrong_subject_or_stale_zones_fail_closed(self):
        bad = [presence(stale=True), presence(ageSeconds=16), presence(ageSeconds=-1),
               presence(ageSeconds=float('nan')), presence(ageSeconds=True),
               presence(subject='other'), {'ok':True,'zones':[]}, {'ok':False},
               {'ok':True, 'zones':presence()['zones'][:1]*2}]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(cycle.CycleError): cycle.basement(data)
        self.assertEqual(cycle.basement(presence()), 'nearby')  # Other room doesn't override basement.

    def test_gap_requires_debounce_again(self):
        self.tick(100); self.tick(300)
        self.apply.assert_not_called()
        self.tick(360)
        self.apply.assert_called_once()

    def test_presence_that_ages_during_tick_never_writes(self):
        self.tick(100)
        with patch.object(cycle.time, 'monotonic', side_effect=[0, 1, 16]):
            self.tick(160)
        self.apply.assert_not_called()
        self.assertIn('presence', self.faults)
        self.assertFalse(self.state['pending'])

    def test_clock_rollback_refuses_work(self):
        self.tick(100)
        with self.assertRaises(cycle.CycleError): self.tick(99)
        self.apply.assert_not_called()

    def test_prewrite_failures_retry_only_on_later_tick(self):
        self.apply.side_effect = cycle.CycleError('keyboard')
        self.tick(100); self.tick(160); self.tick(170); self.tick(220)
        self.assertEqual(self.apply.call_count, 2)
        self.assertEqual(self.faults, {'keyboard'})
        self.assertFalse(self.state['pending'])
        self.apply.side_effect = None
        self.tick(280)
        self.assertFalse(self.faults)

    def test_timeout_or_uncertain_outcome_blocks_following_writes(self):
        self.apply.side_effect = cycle.CycleError('keyboard', uncertain=True)
        self.tick(100); self.tick(160); self.tick(220); self.tick(280)
        self.apply.assert_called_once()
        self.assertTrue(self.state['pending'])
        self.assertEqual(self.state['mode'], 'blocked')

    def test_crash_marker_is_durable_before_sender(self):
        saves=[]
        self.tick(100, save=lambda s:saves.append(dict(s)))
        def sender(config):
            self.assertTrue(saves[-1]['pending'])
            self.assertEqual(saves[-1]['last_attempt'],160)
        self.apply.side_effect=sender
        self.tick(160, save=lambda s:saves.append(dict(s)))
        self.assertFalse(saves[-1]['pending'])

    def test_save_failure_before_sender_never_writes(self):
        self.tick(100)
        with self.assertRaises(OSError):
            self.tick(160, save=Mock(side_effect=OSError('disk')))
        self.apply.assert_not_called()

    def test_failed_preferences_do_not_send(self):
        self.tick(100)
        self.tick(160,get_preferences=Mock(side_effect=cycle.CycleError('preferences')))
        self.apply.assert_not_called()
        self.assertIn('preferences',self.faults)

    def test_error_and_recovery_transitions(self):
        self.assertEqual(cycle.alert_transition(set(),set(),'cycling'),('',0))
        self.assertEqual(cycle.alert_transition({'keyboard'},{'keyboard'},'paused'),('',0))
        self.assertEqual(cycle.alert_transition({'keyboard'},{'presence','keyboard'},'paused'),('',0))
        message,code=cycle.alert_transition(set(),{'keyboard'},'paused')
        self.assertTrue(message.startswith('ERROR:')); self.assertEqual(code,1)
        message,code=cycle.alert_transition({'keyboard'},set(),'cycling')
        self.assertTrue(message.startswith('RECOVERED:')); self.assertEqual(code,0)

    def test_absence_does_not_claim_keyboard_recovery(self):
        self.faults.add('keyboard')
        self.tick(100,presence('away'))
        self.assertEqual(self.faults,{'keyboard'})

    def test_sender_uses_only_existing_cli_once(self):
        response=Mock(returncode=0,stdout=json.dumps({'bytes_written':65,'hardware_write':True}),stderr='')
        config=ajazz.DEFAULT | {'effect':'wave'}
        with patch.object(cycle.subprocess,'run',return_value=response) as run:
            cycle.send(config)
        run.assert_called_once()
        args=run.call_args.args[0]
        self.assertEqual(args[1:3],[str(cycle.ROOT/'ajazz.py'),'set'])
        self.assertEqual(run.call_args.kwargs['timeout'],10)
        self.assertNotIn('--path-hex',args)

    def test_sender_classifies_failures_and_never_echoes_stderr(self):
        for error,uncertain in [('open failed',False),('Short HID write',True),('private token goes here',True)]:
            p=Mock(returncode=1,stdout='',stderr=error)
            with patch.object(cycle.subprocess,'run',return_value=p),self.assertRaises(cycle.CycleError) as caught:
                cycle.send(ajazz.DEFAULT)
            self.assertEqual(caught.exception.uncertain,uncertain)
            self.assertNotIn(error,str(caught.exception))
        with patch.object(cycle.subprocess,'run',side_effect=subprocess.TimeoutExpired('x',10)),self.assertRaises(cycle.CycleError) as caught:
            cycle.send(ajazz.DEFAULT)
        self.assertTrue(caught.exception.uncertain)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=cycle.Store(Path(self.temp.name)/'runtime')

    def test_private_atomic_store(self):
        self.store.save('state.json',cycle.initial())
        self.assertEqual(self.store.load('state.json',None),cycle.initial())
        self.assertEqual((self.store.directory/'state.json').stat().st_mode & 0o777,0o600)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777,0o700)
        self.assertFalse(list(self.store.directory.glob('.atomic-*')))

    def test_symlink_state_is_refused(self):
        target=Path(self.temp.name)/'other';target.write_text('{}')
        (self.store.directory/'state.json').symlink_to(target)
        with self.assertRaises((OSError,cycle.CycleError)):self.store.load('state.json',None)

    def test_persisted_latch_silent_failures_and_single_recovery(self):
        failing=Mock(side_effect=cycle.CycleError('presence'))
        first=cycle.run_once(self.store,now=lambda:100,get_presence=failing,apply=Mock())
        self.assertEqual(first[1],1)
        for now in (160,220):
            self.assertEqual(cycle.run_once(cycle.Store(self.store.directory),now=lambda:now,get_presence=failing,apply=Mock()),('',0))
        output,code=cycle.run_once(self.store,now=lambda:280,get_presence=lambda:presence('away'),apply=Mock())
        self.assertTrue(output.startswith('RECOVERED:'));self.assertEqual(code,0)
        self.assertEqual(cycle.run_once(self.store,now=lambda:340,get_presence=lambda:presence('away'),apply=Mock()),('',0))

    def test_corrupt_state_fails_closed_and_only_reports_once(self):
        p=self.store.directory/'state.json';p.write_text('invalid');p.chmod(0o600)
        sender=Mock(); reader=Mock()
        a=cycle.run_once(self.store,now=lambda:100,get_presence=reader,apply=sender)
        b=cycle.run_once(self.store,now=lambda:160,get_presence=reader,apply=sender)
        self.assertEqual(a[1],1);self.assertEqual(b,('',0))
        sender.assert_not_called();reader.assert_not_called()

    def test_overlapping_tick_is_silent_without_work(self):
        fd=self.store.open_private('cycle.lock',os.O_RDWR|os.O_CREAT)
        try:
            cycle.fcntl.flock(fd,cycle.fcntl.LOCK_EX|cycle.fcntl.LOCK_NB)
            with patch.object(cycle,'RUNTIME',self.store.directory), \
                 patch.object(cycle.sys,'argv',['cycle','--once']), \
                 patch.object(cycle,'run_once') as run:
                self.assertEqual(cycle.main(),0)
                run.assert_not_called()
        finally: os.close(fd)

    def test_main_state_bootstrap_failure_is_latched_separately(self):
        marker=Path(self.temp.name)/'bootstrap.fault'
        output=io.StringIO()
        with patch.object(cycle,'bootstrap_path',return_value=marker), \
             patch.object(cycle,'Store',side_effect=cycle.CycleError('state')), \
             patch.object(cycle.sys,'argv',['cycle','--once']), contextlib.redirect_stdout(output):
            self.assertEqual(cycle.main(),1)
            self.assertEqual(cycle.main(),0)
        self.assertEqual(output.getvalue().count('ERROR:'),1)
        self.assertEqual(marker.stat().st_mode & 0o777,0o600)
        with patch.object(cycle,'bootstrap_path',return_value=marker), \
             patch.object(cycle,'RUNTIME',self.store.directory), \
             patch.object(cycle.sys,'argv',['cycle','--once']), \
             patch.object(cycle,'run_once',return_value=('RECOVERED: mock',0)) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cycle.main(),0)
            run.assert_called_once()
        self.assertFalse(marker.exists())
        self.assertIn('state',self.store.load('alerts.json',[]))

    def test_full_tick_error_absence_and_real_sender_recovery(self):
        sender=Mock(side_effect=cycle.CycleError('keyboard'))
        for now in (100,160):
            out=cycle.run_once(self.store,now=lambda:now,get_presence=lambda:presence(),apply=sender)
        self.assertEqual(out[1],1)
        self.assertEqual(cycle.run_once(self.store,now=lambda:220,get_presence=lambda:presence('away'),apply=sender),('',0))
        sender.side_effect=None
        self.assertEqual(cycle.run_once(self.store,now=lambda:280,get_presence=lambda:presence(),apply=sender),('',0))
        out=cycle.run_once(self.store,now=lambda:340,get_presence=lambda:presence(),apply=sender)
        self.assertTrue(out[0].startswith('RECOVERED:'))


if __name__=='__main__':unittest.main()
