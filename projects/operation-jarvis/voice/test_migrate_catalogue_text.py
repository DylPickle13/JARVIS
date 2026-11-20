from contextlib import closing
import copy
import sqlite3
import tempfile
from pathlib import Path
import unittest

from phrase_banks import catalogue, digest, encoded
from migrate_catalogue_text import migrate


def make_db(path, catalogue_hash):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('CREATE TABLE bags(event TEXT PRIMARY KEY,catalogue TEXT,remaining TEXT,last TEXT);'
                         'CREATE TABLE claims(event TEXT,key TEXT,created REAL,PRIMARY KEY(event,key));')
        db.executemany('INSERT INTO bags VALUES(?,?,?,?)', [
            ('arrival', catalogue_hash, '["arrival-dry-01"]', 'arrival-straight-01'),
            ('departure', catalogue_hash, '["departure-straight-03"]', 'departure-straight-01'),
            ('wake', catalogue_hash, '[]', 'wake-dry-02')])
        db.execute('INSERT INTO claims VALUES(?,?,?)', ('departure', 'existing', 123))


class TextMigrationTests(unittest.TestCase):
    def setUp(self):
        self.new = catalogue()
        self.old = copy.deepcopy(self.new)
        for row in self.old:
            if row['event'] in ('arrival', 'departure'):
                row['text'] = 'Old ' + row['id']

    def test_rebinds_hash_preserving_progress_and_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'selection.sqlite3'
            make_db(path, digest(encoded(self.old)))
            result = migrate(path, self.old, self.new)
            self.assertEqual((result['preserved_claims'], result['migrated_bags']), (1, 3))
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT * FROM bags ORDER BY event').fetchall(), [
                    ('arrival', digest(encoded(self.new)), '["arrival-dry-01"]', 'arrival-straight-01'),
                    ('departure', digest(encoded(self.new)), '["departure-straight-03"]', 'departure-straight-01'),
                    ('wake', digest(encoded(self.new)), '[]', 'wake-dry-02')])
                self.assertEqual(db.execute('SELECT * FROM claims').fetchall(), [('departure', 'existing', 123)])
            with self.assertRaises(ValueError):
                migrate(path, self.old, self.new)

    def test_rejects_membership_or_style_changes_and_no_op(self):
        changed = copy.deepcopy(self.new)
        changed[0]['style'] = 'dry' if changed[0]['style'] == 'straight' else 'straight'
        for old, new in [(self.new, self.new), (self.old, changed), (self.old, self.new[:-1])]:
            with self.assertRaises(ValueError):
                migrate('unused', old, new)


if __name__ == '__main__':
    unittest.main()
