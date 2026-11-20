"""Explicit offline selector migration for text-only catalogue replacements.

Used for the approved arrival/departure v3 wording. Event/ID/style membership
must be identical; only text may change. Remaining/last progress and claims are
preserved; only each bag's catalogue hash is rebound. Caller MUST pause every
selector consumer and back up the database first. No automatic invocation,
playback, service control or deletion of claims.
"""
from contextlib import closing
import json
import sqlite3
from phrase_banks import digest, encoded


def migrate(path, old_rows, new_rows):
    shape = lambda rows: {row['id']: (row['event'], row['style']) for row in rows}
    if (len(old_rows) != len(new_rows) or shape(old_rows) != shape(new_rows)
            or [row['id'] for row in old_rows] != [row['id'] for row in new_rows]
            or all(a['text'] == b['text'] for a, b in zip(old_rows, new_rows))):
        raise ValueError('unexpected_catalogue_migration')
    ids = shape(new_rows)
    old_hash, new_hash = digest(encoded(old_rows)), digest(encoded(new_rows))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        before = db.execute('SELECT event,catalogue,remaining,last FROM bags ORDER BY event').fetchall()
        claims = db.execute('SELECT * FROM claims ORDER BY event,key').fetchall()
        for event, catalogue_hash, remaining_raw, last in before:
            if catalogue_hash != old_hash:
                raise ValueError('unexpected_selector_catalogue')
            remaining = json.loads(remaining_raw)
            event_ids = {key for key, (row_event, _) in ids.items() if row_event == event}
            if (not isinstance(remaining, list) or len(set(remaining)) != len(remaining)
                    or not set(remaining) <= event_ids or last not in event_ids):
                raise ValueError('invalid_selector_state')
            db.execute('UPDATE bags SET catalogue=? WHERE event=?', (new_hash, event))
        after = db.execute('SELECT event,remaining,last FROM bags ORDER BY event').fetchall()
        if (after != [(event, remaining, last) for event, _, remaining, last in before]
                or claims != db.execute('SELECT * FROM claims ORDER BY event,key').fetchall()):
            raise ValueError('selector_progress_changed')
    return dict(old_catalogue=old_hash, new_catalogue=new_hash,
                preserved_claims=len(claims), migrated_bags=len(before))
