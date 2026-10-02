"""Synthetic device/filesystem tests. Never contacts phones."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import collect as c


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dest = self.root / 'capture'
        self.pending = self.root / 'pending-take.json'
        self.phone = {'VID_old.mp4': b'personal', 'VID_new.mp4': b'synthetic video'}
        self.deleted = []
        self.failure = None
        self.take = {'id': 'take', 'before': {'lg': ['VID_old.mp4']}, 'files': {}}
        c.save(self.pending, self.take)
        self.target = self.dest / 'take/lg/VID_new.mp4'
        patcher = patch.object(c, 'verify_video', return_value={'format': {'duration': '2'}})
        self.verify = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(c.subprocess, 'run', side_effect=self.pull)
        self.pull_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def adb(self, phone, *args, **kwargs):
        if args[:3] == ('shell', 'ls', '-1'):
            return '\n'.join(self.phone)
        name = args[-1].split('/')[-1]
        if args[:2] == ('shell', 'stat'):
            return str(len(self.phone[name]))
        if args[:2] == ('shell', 'sha256sum'):
            return hashlib.sha256(self.phone[name]).hexdigest() + '  file'
        if args[:2] == ('shell', 'rm'):
            record = json.loads(self.pending.read_text())['files']['lg/' + name]
            self.assertTrue(record['verified'] and record['delete_intent'])
            self.assertEqual(c.digest(Path(record['path'])), record['sha256'])
            if self.failure == 'before':
                raise TimeoutError('Delete not sent')
            self.deleted.append(name)
            del self.phone[name]
            if self.failure == 'after':
                raise TimeoutError('Lost delete acknowledgement')
            return ''
        raise AssertionError(args)

    def pull(self, args, **kwargs):
        self.assertEqual(args[0], 'fake-adb')
        Path(args[-1]).write_bytes(self.phone[args[-2].split('/')[-1]])
        return subprocess.CompletedProcess(args, 0)

    def transfer(self):
        return c.transfer(self.root, {'lg': 'fake'}, self.adb, 'fake-adb', self.dest)

    def test_pending_prevents_new_take(self):
        with self.assertRaises(RuntimeError):
            c.begin(self.root, {'lg': 'fake'}, self.adb)

    def test_no_manifest_no_sweep(self):
        self.pending.unlink()
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])

    def test_android_collector_cannot_finalize_incomplete_iphone(self):
        self.take.update(iphone_before={}, iphone_complete=False)
        c.save(self.pending, self.take)
        self.assertFalse(self.transfer()['ok'])
        self.assertTrue(self.pending.exists())

    def test_verified_transfer_deletes_only_new_clip(self):
        self.assertTrue(self.transfer()['ok'])
        self.assertEqual(self.deleted, ['VID_new.mp4'])
        self.assertEqual(set(self.phone), {'VID_old.mp4'})
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.target.read_bytes(), b'synthetic video')
        self.verify.assert_called_once()

    def test_hash_failure_retains_phone_original(self):
        self.pull_mock.side_effect = lambda args, **kw: Path(args[-1]).write_bytes(b'bad data')
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])
        self.assertTrue(self.pending.exists())

    def test_invalid_new_media_retains_original(self):
        self.verify.side_effect = RuntimeError('decode failure')
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])
        self.assertFalse(self.target.exists())

    def test_existing_destination_must_decode(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.phone['VID_new.mp4'])
        self.verify.side_effect = RuntimeError('not video')
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])
        self.verify.assert_called_once_with(self.target)
        self.pull_mock.assert_not_called()

    def test_existing_destination_conflict_is_never_overwritten(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'other recording')
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.target.read_bytes(), b'other recording')
        self.assertEqual(self.deleted, [])

    def test_lost_delete_ack_reconciles_without_repeating_delete(self):
        self.failure = 'after'
        self.assertFalse(self.transfer()['ok'])
        self.failure = None
        self.assertTrue(self.transfer()['ok'])
        self.assertEqual(self.deleted, ['VID_new.mp4'])

    def retained_receipt(self, deleted=False):
        self.failure = 'before'
        self.assertFalse(self.transfer()['ok'])
        self.failure = None
        if deleted:
            take = json.loads(self.pending.read_text())
            take['files']['lg/VID_new.mp4']['deleted'] = True
            c.save(self.pending, take)
            del self.phone['VID_new.mp4']

    def test_missing_completed_copy_blocks_finalization(self):
        self.retained_receipt(deleted=True)
        self.target.unlink()
        self.assertFalse(self.transfer()['ok'])
        self.assertTrue(self.pending.exists())

    def test_corrupt_completed_copy_blocks_finalization(self):
        self.retained_receipt(deleted=True)
        self.target.write_bytes(b'corrupted')
        self.assertFalse(self.transfer()['ok'])
        self.assertTrue(self.pending.exists())

    def test_changed_retained_copy_never_deletes_phone(self):
        self.retained_receipt()
        self.target.write_bytes(b'corrupted')
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])

    def test_absence_without_intent_is_not_success(self):
        self.retained_receipt()
        take = json.loads(self.pending.read_text())
        del take['files']['lg/VID_new.mp4']['delete_intent']
        c.save(self.pending, take)
        del self.phone['VID_new.mp4']
        self.assertFalse(self.transfer()['ok'])
        self.assertTrue(self.pending.exists())

    def test_reappeared_deleted_path_is_not_deleted_again(self):
        self.retained_receipt(deleted=True)
        self.phone['VID_new.mp4'] = b'new recording at same path'
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])

    def test_changed_phone_after_decode_never_deletes(self):
        def decode(path):
            self.phone['VID_new.mp4'] = b'changed after copy'
            return {'format': {'duration': '2'}}
        self.verify.side_effect = decode
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])

    def test_new_file_after_discovery_is_not_swept(self):
        self.retained_receipt()
        self.phone['VID_later.mp4'] = b'unrelated newer recording'
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])

    def test_legacy_receipt_requires_decode_upgrade(self):
        self.retained_receipt(deleted=True)
        take = json.loads(self.pending.read_text())
        record = take['files']['lg/VID_new.mp4']
        record.pop('verified'); record.pop('bytes'); record.pop('metadata')
        c.save(self.pending, take)
        self.verify.reset_mock()
        self.assertTrue(self.transfer()['ok'])
        self.verify.assert_called_once_with(self.target)

    def test_media_directory_flushed_before_delete_intent(self):
        events = []
        original_sync = c.sync_directory
        original_save = c.save
        def sync(path):
            events.append(('sync', path))
            original_sync(path)
        def save(path, take):
            if take.get('files', {}).get('lg/VID_new.mp4', {}).get('delete_intent'):
                events.append(('intent', path))
            original_save(path, take)
        with patch.object(c, 'sync_directory', side_effect=sync), patch.object(c, 'save', side_effect=save):
            self.assertTrue(self.transfer()['ok'])
        self.assertLess(events.index(('sync', self.target.parent)), events.index(('intent', self.pending)))

    def test_destination_symlink_blocks_copy_and_deletion(self):
        other=self.root/'other';other.mkdir()
        self.dest.symlink_to(other)
        self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])
        self.pull_mock.assert_not_called()

    def test_media_directory_fsync_failure_retains_phone(self):
        original=c.sync_directory
        def sync(path):
            if path == self.target.parent:
                raise OSError('disk flush failed')
            original(path)
        with patch.object(c,'sync_directory',side_effect=sync):
            self.assertFalse(self.transfer()['ok'])
        self.assertEqual(self.deleted, [])
        self.assertTrue(self.transfer()['ok'])

    def test_process_exit_after_atomic_media_rename_recovers(self):
        original=Path.replace
        target=self.target
        def replace(path, destination):
            result=original(path,destination)
            if Path(destination) == target:
                raise SystemExit('crash after final media rename')
            return result
        with patch.object(Path,'replace',replace),self.assertRaises(SystemExit):
            self.transfer()
        self.assertTrue(self.target.exists())
        self.assertEqual(self.deleted, [])
        self.verify.reset_mock()
        self.assertTrue(self.transfer()['ok'])
        self.verify.assert_called_once_with(self.target)
        self.assertEqual(self.deleted, ['VID_new.mp4'])

    def test_process_exit_at_each_journal_boundary_recovers(self):
        # Simulate process death rather than an ordinary caught IO exception.
        for boundary in ('plan', 'verified', 'intent', 'deleted', 'archive'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temp:
                self.root = Path(temp); self.pending = self.root / 'pending-take.json'
                self.dest = self.root / 'capture'; self.target = self.dest / 'take/lg/VID_new.mp4'
                self.phone = {'VID_old.mp4': b'personal', 'VID_new.mp4': b'synthetic video'}
                self.deleted = []
                c.save(self.pending, {'id': 'take', 'before': {'lg': ['VID_old.mp4']}, 'files': {}})
                original = c.save
                def crash(path, take):
                    record = take.get('files', {}).get('lg/VID_new.mp4', {})
                    stage = ('archive' if path.name == 'transfer-manifest.json' else
                             'deleted' if record.get('deleted') else
                             'intent' if record.get('delete_intent') else
                             'verified' if record.get('verified') else 'plan')
                    if stage == boundary:
                        raise SystemExit('simulated crash before ' + stage + ' save')
                    original(path, take)
                with patch.object(c, 'save', side_effect=crash), self.assertRaises(SystemExit):
                    self.transfer()
                self.assertTrue(self.transfer()['ok'])
                self.assertEqual(self.deleted, ['VID_new.mp4'])
