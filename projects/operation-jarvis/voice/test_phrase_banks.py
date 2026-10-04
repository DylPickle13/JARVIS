"""Offline fixtures and regressions. No Piper/model/network/speaker operations."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

import phrase_banks as banks


def fixture_bundle(root, *, seconds=0.1):
    root = banks.private_dir(root)
    rows = banks.catalogue()
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\x20\0' * int(16000 * seconds))
    data = output.getvalue()
    recordings = {}
    for row in rows:
        path = root / (row['id'] + '.wav')
        path.write_bytes(data)
        path.chmod(0o600)
        recordings[row['id']] = {'file': path.name, 'text': row['text'], 'sha256': banks.digest(data),
            'audio': banks.wav_info(data), 'quality': {'peak': 32, 'clipped_samples': 0}}
    manifest = {'version': 1, 'reviewed': True, 'catalogue_sha256': banks.digest(banks.encoded(rows)),
        'settings': {}, 'settings_sha256': banks.digest(banks.encoded({})),
        'limits_seconds': dict.fromkeys(banks.COUNTS, 4.5), 'recordings': recordings}
    return save_manifest(root, manifest), manifest


def save_manifest(root, manifest):
    path = root / 'manifest.json'
    path.write_text(json.dumps(manifest))
    path.chmod(0o600)
    return banks.digest(path.read_bytes())


def process_reservations(directory, pin, database, start):
    bundle = banks.Bundle(directory, pin)
    selector = banks.Selector(database)
    return [selector.reserve(bundle, 'wake', str(n)).id for n in range(start, start + 12)]


class BankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.assets = self.root / 'assets'
        self.pin, self.manifest = fixture_bundle(self.assets)
        self.bundle = banks.Bundle(self.assets, self.pin)
        self.db = self.root / 'state' / 'selection.sqlite3'
        self.selector = banks.Selector(self.db)

    def test_catalogue_matches_review_and_balance(self):
        rows = banks.catalogue()
        draft = banks.CATALOGUE.with_name('PHRASE-BANKS-DRAFT.md').read_text()
        for row in rows:
            self.assertIn(row['text'], draft)
        self.assertEqual(len(rows), 84)
        import voice_lines
        for event, text in [('wake', voice_lines.WAKE_ACK), ('processing', voice_lines.PROCESSING_ACK),
                            ('arrival', voice_lines.ARRIVAL_GREETING), ('departure', 'Have a good day, sir')]:
            self.assertEqual(self.bundle.default(event).text, text)
        self.assertFalse(any(row['text'] in (voice_lines.REQUEST_FAILURE, voice_lines.RENDER_FAILURE) for row in rows))

    def test_complete_cycles_are_unique_balanced_and_boundary_safe(self):
        styles = {row['id']: row['style'] for row in banks.catalogue()}
        for event, count in banks.COUNTS.items():
            previous = None
            for cycle in range(3):
                ids = [self.selector.reserve(self.bundle, event, f'{cycle}:{n}').id for n in range(count)]
                self.assertEqual(len(set(ids)), count)
                self.assertEqual(sum(styles[item] == 'dry' for item in ids), count // 2)
                self.assertNotEqual(ids[0], previous)
                previous = ids[-1]

    def test_progress_survives_new_instances_and_deduplicates(self):
        first = self.selector.reserve(self.bundle, 'wake', 'same-event')
        restored = banks.Selector(self.db)
        self.assertIsNone(restored.reserve(self.bundle, 'wake', 'same-event'))
        rest = [restored.reserve(self.bundle, 'wake', str(n)).id for n in range(23)]
        self.assertNotIn(first.id, rest)
        self.assertEqual(len(set(rest)), 23)

    def test_concurrent_rooms_consume_one_shared_bag(self):
        other = banks.Selector(self.db)
        def choose(n):
            selector = self.selector if n % 2 else other
            return selector.reserve(self.bundle, 'processing', str(n)).id
        with ThreadPoolExecutor(max_workers=4) as workers:
            chosen = list(workers.map(choose, range(24)))
        self.assertEqual(len(set(chosen)), 24)

    def test_independent_processes_share_one_cycle(self):
        with ProcessPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(process_reservations, self.assets, self.pin, self.db, start)
                       for start in (0, 12)]
            selected = [item for future in futures for item in future.result(timeout=15)]
        self.assertEqual(len(set(selected)), 24)

    def test_same_key_concurrently_is_reserved_once(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            chosen = list(workers.map(lambda _: self.selector.reserve(self.bundle, 'wake', 'one'), range(8)))
        self.assertEqual(sum(clip is not None for clip in chosen), 1)

    def test_private_state_and_assets(self):
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.db.parent.stat().st_mode & 0o777, 0o700)
        target = self.root / 'symlink.sqlite'
        target.symlink_to(self.db)
        with self.assertRaises(OSError):
            banks.Selector(target)
        self.assets.chmod(0o755)
        with self.assertRaises(banks.BankError):
            banks.Bundle(self.assets, self.pin)

    def test_asset_hash_and_file_permissions_enforced(self):
        path = self.assets / 'wake-straight-01.wav'
        path.chmod(0o644)
        with self.assertRaises(banks.BankError): banks.Bundle(self.assets, self.pin)
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b'tamper')
        with self.assertRaises(banks.BankError): banks.Bundle(self.assets, self.pin)

    def test_asset_symlinks_rejected(self):
        path = self.assets / 'wake-straight-01.wav'
        path.unlink()
        path.symlink_to(self.assets / 'wake-straight-02.wav')
        with self.assertRaises(OSError): banks.Bundle(self.assets, self.pin)

    def test_manifest_pin_review_and_settings_enforced(self):
        with self.assertRaises(banks.BankError): banks.Bundle(self.assets, '0' * 64)
        with self.assertRaises(banks.BankError): banks.Bundle(self.assets, self.pin, expected_settings={'different': 1})
        self.manifest['reviewed'] = False
        pin = save_manifest(self.assets, self.manifest)
        with self.assertRaises(banks.BankError): banks.Bundle(self.assets, pin)

    def test_incomplete_traversal_text_duration_and_clipping_rejected(self):
        import copy
        for mutation in ('missing', 'traversal', 'text', 'duration', 'clipped', 'nan'):
            with self.subTest(mutation=mutation):
                manifest = copy.deepcopy(self.manifest)
                entry = manifest['recordings']['wake-straight-01']
                if mutation == 'missing': del manifest['recordings']['wake-straight-01']
                if mutation == 'traversal': entry['file'] = '../outside.wav'
                if mutation == 'text': entry['text'] = 'unapproved'
                if mutation == 'duration': manifest['limits_seconds']['wake'] = 0.01
                if mutation == 'clipped': entry['quality']['clipped_samples'] = 1
                if mutation == 'nan': manifest['limits_seconds']['wake'] = float('nan')
                pin = save_manifest(self.assets, manifest)
                with self.assertRaises(banks.BankError): banks.Bundle(self.assets, pin)

    def test_departure_duration_cannot_be_relaxed_by_manifest(self):
        assets = self.root / 'long'
        pin, manifest = fixture_bundle(assets, seconds=4.6)
        manifest['limits_seconds'] = dict.fromkeys(banks.COUNTS, 10)
        pin = save_manifest(assets, manifest)
        with self.assertRaises(banks.BankError): banks.Bundle(assets, pin, events=('departure',))

    def test_malformed_and_truncated_wav_rejected(self):
        data = self.bundle.default('wake').audio
        for invalid in (b'invalid', data[:-2]):
            with self.assertRaises(banks.BankError): banks.wav_info(invalid)

    def test_temporary_copy_cleanup_cannot_delete_master(self):
        clip = self.bundle.default('processing')
        path = clip.temporary()
        self.assertEqual(path.read_bytes(), clip.audio)
        path.unlink()
        self.assertTrue((self.assets / (clip.id + '.wav')).is_file())

    def test_warm_status_and_padding_do_not_reserve(self):
        selector = mock.Mock(wraps=self.selector)
        room = banks.RoomBanks(self.bundle, selector, wake_padding=450, padding=100)
        self.assertTrue(room.status()['enabled'])
        selector.reserve.assert_not_called()
        import base64
        clip = self.bundle.default('wake')
        self.assertAlmostEqual(banks.wav_info(base64.b64decode(room.audio[clip.id]))['seconds'], 0.55)

    def test_lock_contention_is_bounded_and_suppresses_without_retry(self):
        room = banks.RoomBanks(self.bundle, self.selector)
        with closing(sqlite3.connect(self.db)) as lock:
            lock.execute('BEGIN IMMEDIATE')
            clip = room.choose('wake', 'blocked')
            lock.rollback()
        self.assertIsNone(clip)
        self.assertEqual(room.status()['selectionFailures'], 1)
        self.assertIsNotNone(self.selector.reserve(self.bundle, 'wake', 'blocked'))

    def test_catalogue_migration_fails_closed(self):
        self.selector.reserve(self.bundle, 'wake', 'first')
        self.bundle.catalogue_hash = 'different'
        with self.assertRaises(banks.BankError): self.selector.reserve(self.bundle, 'wake', 'second')

    def test_disabled_env_does_not_create_state(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(banks, 'Selector') as selector:
            self.assertIsNone(banks.room_banks_from_env(SimpleNamespace()))
        selector.assert_not_called()


if __name__ == '__main__':
    unittest.main()
