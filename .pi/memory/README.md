# Durable memory

Local SQLite/FTS5 storage behind `.pi/extensions/35-memory.ts`. Recall remains
explicit: no prompt hooks, embeddings, external services, or automatic rewriting.

## What belongs here

Store stable preferences, reusable lessons, and concise current knowledge. Use
project documentation or session history for build logs and implementation detail.
Aim for a short paragraph and a documentation link, not a transcript. Search before
writing. Memory is historical context, **not live state or authorization**.

- `project`: an exact subproject key, e.g. `operation-jarvis` or `music`.
- `topic`: an exact topic key, e.g. `room-audio-architecture`.
- `tags`: search/list requires every supplied tag.
- `source`: evidence/documentation reference; unspecified new sources are `unknown`.
- `verified_at`: actual evidence date (`YYYY-MM-DD`), not the date a note was added.
  Editing text without supplying a new verification date clears the old date.
  Confidence is a stored assertion, not proof of accuracy.

`scope` remains a global/project label within this repository-local database. It
is not a cross-repository store or access boundary. Existing entries are not
assigned project keys or verification dates by guesswork; project-filtered searches
will not find unclassified legacy entries. Search broadly too when needed.

## Replacing old knowledge

For a small correction, `update` the existing entry (including its `source`). For
materially changed knowledge, `remember` the new entry with `supersedes: [old IDs]`.
This atomically creates the replacement and marks the old entries `superseded`.
Normal search/list excludes them. `include_superseded: true` includes history.
Supersession requires existing active IDs and does not infer relationships from
prose. Topic keys are filters, not uniqueness constraints.

Example tool arguments:

```json
{"action":"search","query":"room audio","project":"operation-jarvis","topic":"room-audio-architecture"}
```

```json
{"action":"remember","kind":"project","scope":"project","project":"operation-jarvis","topic":"room-audio-architecture","text":"Concise evidence-backed current architecture; see path/to/docs.md.","source":"path/to/docs.md","supersedes":["OLD_ID"]}
```

Repeated identical text (case-insensitive and trimmed) with the same kind, scope,
project, and topic returns the existing active entry without adding an event.
This does **not** merge new tags, source, or verification; use `update` for those.
Near-duplicates and contradictions still require review. No bulk consolidation
or deletion runs automatically.

`forget` permanently purges a row, its FTS entry, and its own event history, then
compacts SQLite. Forgetting a replacement does not reactivate its obsolete
predecessors. This cannot erase copies outside the database (backups, session
transcripts, filesystem snapshots); handle those separately when required.

## Retrieval and migration

Search uses safely quoted FTS terms, drops common English filler, prefers matches
containing all meaningful terms, then backfills partial matches ranked by BM25.
There is no semantic/embedding search. Stopword/punctuation-only searches return
nothing instead of unrelated recent notes. Results include status, freshness,
source, and confidence. `list` is for recent entries and has no retrieval side effect.

Schema v4 is additive and migrates on the next runner connection. Existing text,
source, IDs, timestamps, and events are preserved. Existing rows start `active`;
no prose-based supersession is inferred. New `last_retrieved_at` measures search
exposure only. Legacy `last_used_at` remains untouched for compatibility and must
not be interpreted as demonstrated usefulness. There is no actual-use metric yet.

Secrets are rejected using best-effort patterns across text and free-text metadata;
this is not comprehensive DLP. Never intentionally supply sensitive data. Files
remain private (0600), and the default memory directory remains 0700.

## Validation

Tests use temporary databases and mocked extension execution, never production
memory or `.env`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s .pi/tests -p test_memory.py -v
node --test .pi/tests/memory.test.mjs
```

Both suites are included in `.pi/smoke-test.sh`. After changing the extension,
reload Pi (`/reload`) or start a new session to load its new schema and formatting.
The Python runner changes take effect on its next invocation.
