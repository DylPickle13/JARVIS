# Audit hardening

## Implemented

1. **Durable deletion authorization:** a separate SQLite approval table binds job
   ID, take, scope, media checksums, phone-review identity and applicable Resolve
   import receipt. Worker execution rechecks approval after acquiring the
   preparation/import locks. Phone discard also rechecks its approved review under
   the controller lock. Reusing a job ID with a different scope is rejected.
2. **Retained-copy validation:** Android retries check path, size and SHA-256 even
   for entries already marked deleted. Missing/corrupt copies cannot finalize a
   take. Legacy receipts receive full decode validation before upgrade.
3. **Playable-media checks:** shared Android/iPhone validation requires finite
   positive duration, a valid video stream, and full video/available-audio decoding.
   The iPhone's native-4K requirement remains intact. Existing destination files
   take the same validation path as newly transferred media.
4. **Crash-safe Android deletion:** verified receipts and deletion intent are
   durably saved before removal. Lost acknowledgements reconcile absence only with
   the intact verified copy and intent. Reappeared deleted paths, unexplained
   disappearance and additional files outside a frozen transfer plan are blocked.
5. **Filesystem durability:** finalized Android files and destination directory
   entries are flushed before deletion intent. Unique partials never overwrite a
   conflicting final file; ordinary failures remove only that attempt's partial.
6. **Closed deletion inventory:** recursive deletion refuses unexpected files,
   directories, media or symlinks. Only manifest footage and exact known generated
   filenames are allowed; this applies to both capture and editing folders.
7. **Separate hashing budgets:** Android SHA-256 uses stat-derived, bounded
   60–3600-second timeouts, including review/discard fingerprints. Camera-control
   commands keep their 15-second timeout and single-send behavior.
8. **Install/test reproducibility:** OpenTimelineIO is declared; Python 3.13.14 is
   recorded. A disposable source-copy test runner supplies synthetic configuration
   instead of reading private transport/pairing/job state.
9. **Repository/docs:** JARVIS now permits this project while ignoring private
   runtime/configuration, environments, migration snapshots and local validation
   evidence. README and OPERATIONS.md are the current entry points; previous
   implementation history is retained separately. Single-clip limitations are
   visible in the dashboard's readiness/safety text.

## Validation

- Fresh Python 3.13 virtual environment installed successfully using only
  `requirements-sync.txt`; `pip check` reports no broken requirements.
- **229 Python tests**, including offline browser fixtures and real FFmpeg decoding
  of a tiny generated video/audio clip. No phones or Resolve were contacted.
- Regressions cover scope expansion after confirmation, changed fingerprints,
  unexpected footage, missing/corrupt completed copies, lost deletion acknowledgements,
  invalid existing media, legacy receipts, and SQLite history preservation.
- Fault injection simulates process exit before plan/verification/intent/deleted/
  archive journal writes and after final media rename. Directory-fsync failure is
  also covered. Recovery does not repeat a deletion already observed as completed.
- JavaScript syntax and OBS/tool-retirement checks pass.
- Private runtime/configuration remains ignored; obvious literal-credential scan
  of newly trackable source found no matches (not a comprehensive secret audit).
- An initial existing-environment run hit an intermittent macOS headless-Chrome
  process-group cleanup PermissionError. Subsequent fresh-environment full runs
  passed; this is not evidence of live camera/browser-server validation.

Run current checks with:

```sh
.sync-venv/bin/python tests/run_isolated.py
node --check dashboard/app.js
node tests/test_tool_retirement.mjs
```

## Deliberately unchanged / remaining work

- Existing phone-original move/deletion policy is unchanged. Capture and editing
  folders on one Mac are **not independent backups**. A mandatory independent
  backup needs an explicitly selected destination and retention policy.
- No automatic segmented-take concatenation, drift correction or guessed sync.
  Review/sync remain single-clip-per-camera; long-session limits remain visible.
- No wholesale formatting rewrite of unrelated controller/UI code. New safety
  helpers and the rewritten collector use conventional, readable functions.
- No live recording, real-footage deletion, Resolve mutation, service restart,
  pairing or camera configuration change was performed for this implementation.
- Restart the dashboard deliberately only when idle to load one consistent code
  version. Existing unapproved queued deletion jobs fail closed; already-attempted
  jobs retain observation-only recovery.
- A deliberately authorized bounded live recording/recovery/Resolve test remains
  required before relying on this for important sessions.
