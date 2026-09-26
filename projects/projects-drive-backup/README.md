# JARVIS encrypted Drive backups

Restic 0.19+ through rclone Google Drive. Replaces the legacy full-tarball job.
The old `drive_backup_projects.py` is retained for rollback only; do not schedule
both implementations. Migration keeps the existing Drive tarball untouched.

## Installed layout

- Source: `/Users/dylanrapanan/JARVIS` (whole checkout, not just projects).
- Repository: `rclone:jarvis-drive:restic-mac-mini-64`.
- Drive parent: [JARVIS Backups](https://drive.google.com/drive/folders/1L6arvVqmmmELCcnzMtkcxAgjwLIFuCAZ).
- Local config: `~/.config/jarvis-backup/config.json`.
- Dedicated rclone credentials: `~/.config/jarvis-backup/rclone.conf`.
- Encryption password: `~/.config/jarvis-backup/restic-password`.
- Private staging, cache, lock and status: `~/.local/state/jarvis-backup/`.

Config/key files are owner-only, outside the checkout, and never printed by the
wrapper. The dedicated rclone configuration reuses an existing authorized Drive
connection but pins its root to the exact JARVIS Backups folder ID. The original
rclone configuration and other remotes are not changed. Root-folder pinning is
an operational boundary, not a restriction on the OAuth token's permissions.

**Recovery requirement:** copy `restic-password` into a password manager or
separate offline storage. Its only initial copy is on this Mac. Losing the Mac
and password makes the encrypted backup unrecoverable. Do not store the password
in this repository, the same Drive folder, logs, a chat, or only inside the
encrypted backup. New Drive OAuth credentials can be authorized after a loss;
the original Restic encryption password cannot be recreated.

## Scope and exclusions

`policy.json` is the reviewable policy used by both inventory and Restic.
Included: project files/data, custom models, `.env`, root files, Git history,
attachments, `.pi` configuration/extensions/memory/scheduler, and custom runtime
source. `.gitignore` is deliberately NOT the backup policy.

Excluded: named virtual environments, node_modules, Python caches, Swift `.build`,
log files, selected Karabiner build outputs/pkgroot, assessment `.runtime`,
regenerable pi-lazy-tools releases, scheduler session logs, transient special
files, and the old tarball. Project `temp` itself, model weights and vendor source
are NOT blanket-excluded. Symlinks are saved as links, not followed outside the
source tree. Dependencies can be reinstalled from project manifests/lockfiles.

This is not a whole-machine backup: home-directory configuration outside JARVIS,
macOS Keychain, external symlink targets, other machines and media libraries
require separate coverage. Add an independent Time Machine/external-disk copy
for protection against loss of the Drive account or destructive access.

## SQLite consistency

Included `.sqlite`, `.sqlite3`, and `.db` files with SQLite headers are copied
using the SQLite online-backup API; copies use DELETE journal mode and pass
`quick_check`. Live database files and their WAL/SHM/journal companions are
excluded from the file backup. No source database is modified by the wrapper.

The repository stores two absolute directory trees:

1. `/Users/dylanrapanan/JARVIS` — ordinary source files.
2. `/Users/dylanrapanan/.local/state/jarvis-backup/sqlite` — consistent database
   copies, preserving their paths relative to JARVIS, plus `manifest.json`.

The manifest records SHA-256 values of database copies and sample files. These
copies are individually consistent, not one atomic transaction across apps.
Other live files are read normally by Restic, not through an APFS snapshot.
SQLite databases with unconventional filename extensions need explicit support.

## Automation

One direct Python job, not a model prompt:

- `projects-restic-drive-backup` (`job_2a993986b841`): `0 7 * * *` UTC — 3 AM EDT / 2 AM EST.

The `backup` command performs the verified backup, then runs maintenance if its
last successful completion was at least seven days ago (or has never completed).
Missed/failed maintenance is retried after the next successful nightly backup.
Both phases share the same lock and timeout budget. Either phase failing exits
nonzero for scheduler error reporting. The separate maintenance and hourly
health jobs have been removed.

There is no independent missed-run watchdog now: if the job or scheduler never
runs, this job cannot alert on its own absence. The manual `health` command still
checks whether the last verified backup is under 36 hours old.

The legacy `projects-drive-backup` job (`job_07a151c1f636`) is disabled, not deleted;
its history and last tarball remain available for rollback.

The backup job uploads incremental encrypted data, runs a repository structural
check, then restores and verifies all staged databases and selected sample files
in a temporary private directory. Only after those checks does it record success.
Unreadable/incomplete sources (Restic exit 3) are failures, not healthy backups.

Maintenance within the nightly job checks a rotating quarter of repository data (1/4 through
4/4), repeats the restore test, then applies retention and prunes unreferenced
packs. A post-prune structural check must also pass. Retention is scoped to
`mac-mini-64` and `jarvis-recovery-v1`, grouped by host/tags:

- 14 daily, 8 weekly, 12 monthly recovery points;
- additionally the latest 3 snapshots and everything within 2 days of the newest.

These policies overlap: counts are not additive. Maintenance refuses to prune
without a recent recorded verified snapshot still present in the repository.
A failed backup never triggers pruning. Drive's normal trash semantics remain
in effect; pruned objects may remain in Drive trash until its normal expiration.
Do not empty Drive trash automatically or run rclone sync on the repository.

Operations use an owner-only advisory lock plus Restic's repository locks,
bounded retries, network timeouts and a default 780-second total subprocess
budget (below the scheduler's default 900 seconds). Lock conflicts are errors,
not silent success. Initial/full checks can use a longer manual budget. No
automatic `unlock`, repair, repository reinitialization or credential rotation.

## Commands

From the JARVIS checkout:

```bash
SCRIPT=projects/projects-drive-backup/restic_backup.py
/opt/homebrew/bin/python3 "$SCRIPT" plan
/opt/homebrew/bin/python3 "$SCRIPT" backup
/opt/homebrew/bin/python3 "$SCRIPT" snapshots
/opt/homebrew/bin/python3 "$SCRIPT" health
/opt/homebrew/bin/python3 "$SCRIPT" verify
/opt/homebrew/bin/python3 "$SCRIPT" check --full --timeout 6000
/opt/homebrew/bin/python3 "$SCRIPT" maintenance --dry-run
```

`plan` is read-only for source/Drive (creates only a local lock/state directory).
`maintenance --dry-run` still performs remote checks and a temporary restore,
but does not forget or prune. `init` is an explicit one-time setup operation,
never attempted automatically after connection failures.

Run tests, including an isolated local Restic repository and WAL recovery:

```bash
/opt/homebrew/bin/python3 -m unittest discover \
  -s projects/projects-drive-backup -p 'test_*.py' -v
```

## Restore to a scratch directory

Install `restic`, `rclone`, and Python 3 (`brew install restic rclone python`).
Recover the password from independent storage. If necessary authorize a new
rclone Drive remote named `jarvis-drive`, rooted at the JARVIS Backups folder
shown above. On the current Mac:

```bash
export RCLONE_CONFIG="$HOME/.config/jarvis-backup/rclone.conf"
export RESTIC_REPOSITORY='rclone:jarvis-drive:restic-mac-mini-64'
export RESTIC_PASSWORD_FILE="$HOME/.config/jarvis-backup/restic-password"
restic snapshots --host mac-mini-64 --tag jarvis-recovery-v1
umask 077
RESTORE=$(mktemp -d "$HOME/jarvis-restore.XXXXXX")
# Choose an explicit verified snapshot ID; do not overwrite live directories.
restic restore SNAPSHOT_ID --target "$RESTORE" --verify
```

Files appear under `$RESTORE/Users/dylanrapanan/JARVIS/`. Consistent databases
appear separately under
`$RESTORE/Users/dylanrapanan/.local/state/jarvis-backup/sqlite/`.
Use that directory's `manifest.json` to identify their original relative paths.
Validate restored database checksums and `PRAGMA quick_check`, then stop the
relevant application before copying each database to its original location.
Remove stale live WAL/SHM companions only while the application is stopped and
a separate rollback copy exists. Review before restoring secrets or scheduler
state (which could re-enable jobs). Do not blindly overwrite a running system.

A partial restore can use `restic restore SNAPSHOT_ID --target "$RESTORE"
--include '/Users/dylanrapanan/JARVIS/projects/PROJECT' --verify`.

## Failure recovery

Read scheduler results and private `status.json`. Confirm connectivity/Drive
auth, free space and source readability, then rerun `backup`. A failure preserves
previous snapshots and the legacy tarball. Staging is replaceable, but never
remove a lock file while a process might still hold it. Restic locks may need
manual review after an externally killed process; do not force-unlock an active
backup. Restore tests cover samples/databases, not a complete disaster-recovery
rehearsal; full periodic drills and an independent copy remain recommended.
