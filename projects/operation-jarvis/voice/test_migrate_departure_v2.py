from contextlib import closing
import copy
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from phrase_banks import catalogue, digest, encoded
from migrate_departure_v2 import migrate


class MigrationTests(unittest.TestCase):
    def test_filters_only_retired_ids_preserving_other_bags_and_claims(self):
        new = catalogue()
        old = copy.deepcopy(new)
        old += [dict(id=f'departure-dry-{n:02d}', event='departure', style='dry',
                     text=f'Old farewell {n}') for n in range(1, 13)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'selection.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('CREATE TABLE bags(event TEXT PRIMARY KEY,catalogue TEXT,remaining TEXT,last TEXT);'
                                 'CREATE TABLE claims(event TEXT,key TEXT,created REAL,PRIMARY KEY(event,key));')
                h = digest(encoded(old))
                db.executemany('INSERT INTO bags VALUES(?,?,?,?)', [
                    ('arrival', h, '["arrival-dry-01"]', 'arrival-straight-01'),
                    ('departure', h, '["departure-dry-02", "departure-straight-03"]', 'departure-dry-01')])
                db.execute('INSERT INTO claims VALUES(?,?,?)', ('departure', 'existing', 123))
            result = migrate(path, old, new)
            self.assertEqual(result['preserved_claims'], 1)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT remaining,last FROM bags WHERE event="arrival"').fetchone(),
                                 ('["arrival-dry-01"]', 'arrival-straight-01'))
                self.assertEqual(db.execute('SELECT remaining,last FROM bags WHERE event="departure"').fetchone(),
                                 ('["departure-straight-03"]', 'departure-straight-01'))
                self.assertEqual(db.execute('SELECT * FROM claims').fetchall(), [('departure', 'existing', 123)])
            with self.assertRaises(ValueError): migrate(path, old, new)

    def test_rejects_unrelated_catalogue_changes(self):
        rows = catalogue()
        with self.assertRaises(ValueError): migrate('unused', rows, rows)


if __name__ == '__main__':
    unittest.main()
