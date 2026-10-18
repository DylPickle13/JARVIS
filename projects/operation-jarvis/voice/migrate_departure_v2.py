"""Explicit offline selector migration for the approved 24-to-12 farewell update.

Caller MUST pause every selector consumer and back up the database first.
No automatic invocation, playback, service control or deletion of claims.
"""
from contextlib import closing
import json
import sqlite3
from phrase_banks import digest, encoded


def migrate(path, old_rows, new_rows):
    old = {row['id']: row for row in old_rows}
    new = {row['id']: row for row in new_rows}
    retired = {f'departure-dry-{n:02d}' for n in range(1, 13)}
    retained = {f'departure-straight-{n:02d}' for n in range(1, 13)}
    if (set(old) - set(new) != retired or set(new) - set(old)
            or {key for key, row in new.items() if row['event'] == 'departure'} != retained
            or any(row != new[key] for key, row in old.items() if row['event'] != 'departure')
            or any(new[key]['style'] != 'dry' for key in retained)):
        raise ValueError('unexpected_catalogue_migration')
    old_hash, new_hash = digest(encoded(old_rows)), digest(encoded(new_rows))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        before = db.execute('SELECT event,catalogue,remaining,last FROM bags ORDER BY event').fetchall()
        claims = db.execute('SELECT * FROM claims ORDER BY event,key').fetchall()
        changes = []
        for event, catalogue_hash, remaining_raw, last in before:
            if catalogue_hash != old_hash:
                raise ValueError('unexpected_selector_catalogue')
            remaining = json.loads(remaining_raw)
            old_ids = {key for key, row in old.items() if row['event'] == event}
            if (not isinstance(remaining, list) or len(set(remaining)) != len(remaining)
                    or not set(remaining) <= old_ids or last not in old_ids):
                raise ValueError('invalid_selector_state')
            if event == 'departure':
                remaining = [key for key in remaining if key not in retired]
                # Retired last ID maps to its retained ordinal for conservative
                # boundary-repeat suppression. Original value remains in audit.
                new_last = last.replace('departure-dry-', 'departure-straight-')
                db.execute('UPDATE bags SET catalogue=?,remaining=?,last=? WHERE event=?',
                           (new_hash, json.dumps(remaining), new_last, event))
                changes.append(dict(event=event, previous_last=last, last=new_last,
                                    remaining=remaining))
            else:
                db.execute('UPDATE bags SET catalogue=? WHERE event=?', (new_hash, event))
        if claims != db.execute('SELECT * FROM claims ORDER BY event,key').fetchall():
            raise ValueError('claims_changed')
    return dict(old_catalogue=old_hash, new_catalogue=new_hash,
                preserved_claims=len(claims), migrated_bags=len(before), changes=changes)
