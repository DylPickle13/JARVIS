#!/usr/bin/env python3
"""Encrypted Restic backups. No credentials in source or command output."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = Path.home() / '.config/jarvis-backup/config.json'
TAG = 'jarvis-recovery-v1'
SQLITE_HEADER = b'SQLite format 3\x00'


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def literal_pattern(path):
    # Restic uses Go filepath-style patterns; quote literal metacharacters.
    return ''.join('\\' + ch if ch in '\\*?[]' else ch for ch in str(path))


def excluded(rel, policy):
    return rel.name in policy['exclude_names'] or any(
        fnmatch.fnmatchcase(rel.as_posix(), pattern) for pattern in policy['exclude_globs'])


def inventory(root, policy):
    """Never follow symlink directories; keep symlinks themselves in Restic."""
    omitted, databases, total, count = [], [], 0, 0
    def onerror(error):
        raise error
    for base, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        for name in list(dirs):
            path = Path(base) / name
            if excluded(path.relative_to(root), policy):
                omitted.append(path)
                dirs.remove(name)
        for name in files:
            path = Path(base) / name
            if excluded(path.relative_to(root), policy):
                omitted.append(path)
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            if not stat.S_ISREG(mode):
                omitted.append(path)  # sockets/FIFOs are runtime state, not documents
                continue
            size = path.stat().st_size
            total += size
            count += 1
            if path.suffix in ('.db', '.sqlite', '.sqlite3'):
                with path.open('rb') as f:
                    if f.read(16) == SQLITE_HEADER:
                        databases.append(path)
    return omitted, databases, total, count


def snapshot_database(source, target, deadline):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = target.with_name(target.name + '.tmp')
    def progress(status, remaining, total):
        if time.monotonic() >= deadline:
            raise TimeoutError('SQLite backup deadline exceeded')
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=15)) as src:
            with closing(sqlite3.connect(temp)) as dst:
                src.backup(dst, pages=256, progress=progress, sleep=0.05)
                # Produce a standalone file, without requiring WAL/SHM on restore.
                dst.execute('PRAGMA journal_mode=DELETE')
                result = dst.execute('PRAGMA quick_check').fetchall()
                if result != [('ok',)]:
                    raise RuntimeError(f'SQLite quick_check failed: {source.name}')
        temp.chmod(0o600)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


class Backup:
    def __init__(self, config_path, timeout):
        self.config = json.loads(Path(config_path).expanduser().read_text())
        self.root = Path(self.config['source']).expanduser().resolve()
        self.state = Path(self.config['state_dir']).expanduser().resolve()
        if self.state == self.root or self.root in self.state.parents:
            raise ValueError('State directory must be outside the backed-up source')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state.chmod(0o700)
        self.stage = self.state / 'sqlite'
        self.policy = json.loads((HERE / 'policy.json').read_text())
        self.deadline = time.monotonic() + timeout
        self.lock_fd = None
        self.env = os.environ.copy()
        # Do not allow ambient variables to select a different repository/key/Drive root.
        for key in list(self.env):
            if key.startswith(('RESTIC_', 'RCLONE_')):
                self.env.pop(key)
        self.env.update({
            'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
            'RESTIC_REPOSITORY': self.config['repository'],
            'RESTIC_PASSWORD_FILE': str(Path(self.config['password_file']).expanduser()),
            'RESTIC_CACHE_DIR': str(self.state / 'cache'),
            'RCLONE_CONFIG': str(Path(self.config['rclone_config']).expanduser()),
            'RCLONE_RETRIES': '3', 'RCLONE_LOW_LEVEL_RETRIES': '10',
            'RCLONE_CONTIMEOUT': '30s', 'RCLONE_TIMEOUT': '2m',
            'TZ': 'America/Toronto',
        })
        self.base = [self.config.get('restic', '/opt/homebrew/bin/restic'),
                     '--retry-lock', '30s', '--stuck-request-timeout', '2m']
        self.state_file = self.state / 'status.json'

    def load_state(self):
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def record(self, **fields):
        state = self.load_state()
        state.update(fields)
        save_json(self.state_file, state)

    @contextmanager
    def locked(self):
        with (self.state / 'backup.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another backup/maintenance operation is running')
            self.lock_fd = lock.fileno()
            try:
                yield
            finally:
                self.lock_fd = None

    def run(self, args, retries=1):
        for attempt in range(retries):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Backup operation exceeded its time budget')
            # Pass the local lock to the child so an externally killed wrapper cannot
            # allow a second job to replace SQLite staging while Restic still reads it.
            proc = subprocess.Popen(self.base + args, env=self.env, cwd=self.root,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, start_new_session=True,
                                    pass_fds=(() if self.lock_fd is None else (self.lock_fd,)))
            try:
                out, err = proc.communicate(timeout=remaining)
            except BaseException:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate()
                except ProcessLookupError:
                    pass
                raise
            if proc.returncode == 0:
                return out
            # Exit 3 is incomplete data, not success; never prune or mark it healthy.
            if proc.returncode in (3, 10, 12) or attempt + 1 == retries:
                raise RuntimeError(f'Restic {args[0]} failed (exit {proc.returncode}):\n{err[-3000:]}\n{out[-1000:]}')
            print(f'Retrying Restic {args[0]} after exit {proc.returncode}', flush=True)
            time.sleep(min(10 * (attempt + 1), max(0, self.deadline - time.monotonic())))
        raise RuntimeError('Restic did not run')

    def validate_source(self):
        for rel in self.policy['required_paths']:
            if not (self.root / rel).exists():
                raise RuntimeError(f'Required source missing: {rel}; refusing an incomplete backup')
        key = Path(self.env['RESTIC_PASSWORD_FILE'])
        if key.stat().st_mode & 0o077:
            raise RuntimeError('Password file must be owner-only (chmod 600)')
        if self.root in key.resolve().parents:
            raise RuntimeError('Recovery password must not be inside backup source')

    def plan(self):
        self.validate_source()
        omitted, databases, total, count = inventory(self.root, self.policy)
        print(json.dumps({'source': str(self.root), 'files': count,
                          'source_bytes_before_sqlite_staging': total,
                          'sqlite_databases': [str(p.relative_to(self.root)) for p in databases],
                          'excluded_paths': [str(p.relative_to(self.root)) for p in omitted]}, indent=2))

    def backup(self):
        self.validate_source()
        omitted, databases, total, count = inventory(self.root, self.policy)
        # Only ephemeral staging is removed; never touch source databases.
        if self.stage.exists():
            shutil.rmtree(self.stage)
        self.stage.mkdir(mode=0o700)
        manifest = {'created_at': utcnow(), 'source': str(self.root), 'databases': [], 'samples': []}
        for db in databases:
            rel = db.relative_to(self.root)
            target = self.stage / rel
            snapshot_database(db, target, min(self.deadline, time.monotonic() + 120))
            manifest['databases'].append({'relative_path': rel.as_posix(), 'sha256': digest(target)})
            omitted.extend([db, Path(str(db) + '-wal'), Path(str(db) + '-shm'), Path(str(db) + '-journal')])
        for rel in self.policy['restore_samples']:
            manifest['samples'].append({'relative_path': rel, 'sha256': digest(self.root / rel)})
        save_json(self.stage / 'manifest.json', manifest)
        excludes = self.state / 'excludes.txt'
        excludes.write_text('\n'.join(literal_pattern(p) for p in omitted) + '\n')
        # These top-level paths remain stable, enabling parent snapshot reuse.
        print(f'Backing up {count} files (~{total / 1024**3:.2f} GiB), {len(databases)} SQLite snapshots', flush=True)
        output = self.run(['backup', '--json', '--host', self.config['host'], '--tag', TAG,
                           '--group-by', 'host,tags', '--exclude-file', str(excludes),
                           str(self.root), str(self.stage)], retries=3)
        summaries = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
        summary = next((s for s in reversed(summaries) if s.get('message_type') == 'summary'), {})
        snapshot = summary.get('snapshot_id')
        if not snapshot:
            raise RuntimeError('Restic returned no snapshot ID')
        self.run(['check'], retries=2)
        self.verify(snapshot)
        self.record(last_success_at=utcnow(), snapshot_id=snapshot, summary=summary, last_error=None)
        print(f'JARVIS Restic Backup: completed\nSnapshot: {snapshot}\n'
              f'Processed: {summary.get("total_bytes_processed", 0):,} bytes\n'
              f'Added (stored): {summary.get("data_added_packed", 0):,} bytes\n'
              'SQLite copies, repository structure and sample restore verified.', flush=True)

    def snapshots(self):
        return json.loads(self.run(['snapshots', '--json', '--host', self.config['host'], '--tag', TAG], retries=2))

    def verified_snapshot(self):
        state = self.load_state()
        snapshot = state.get('snapshot_id')
        if not snapshot or not any(s['id'].startswith(snapshot) for s in self.snapshots()):
            raise RuntimeError('No recorded verified snapshot exists in the repository')
        return snapshot

    def verify(self, snapshot):
        # Restoring exact snapshot paths keeps this bounded; never restore over live data.
        with tempfile.TemporaryDirectory(prefix='restore-', dir=self.state) as tmp:
            args = ['restore', snapshot, '--target', tmp, '--verify', '--include', str(self.stage)]
            for rel in self.policy['restore_samples']:
                args.extend(['--include', str(self.root / rel)])
            self.run(args, retries=2)
            restored_stage = Path(tmp) / str(self.stage).lstrip('/')
            manifest = json.loads((restored_stage / 'manifest.json').read_text())
            for item in manifest['databases']:
                path = restored_stage / item['relative_path']
                if digest(path) != item['sha256']:
                    raise RuntimeError('Restored SQLite checksum mismatch')
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                        raise RuntimeError('Restored SQLite integrity check failed')
            for item in manifest['samples']:
                path = Path(tmp) / str(self.root).lstrip('/') / item['relative_path']
                if digest(path) != item['sha256']:
                    raise RuntimeError('Restored sample checksum mismatch')
        self.record(last_restore_test_at=utcnow())

    def nightly(self):
        """One scheduled entry point; maintenance catches up after seven days."""
        self.backup()
        last = self.load_state().get('last_maintenance_at')
        age = ((datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
               if last else None)
        if age is None or age >= 7 * 24 * 3600:
            self.maintain()
        elif age < -360:
            raise RuntimeError('Maintenance timestamp is in the future; check the clock')
        else:
            print('Weekly maintenance: not yet due', flush=True)

    def maintain(self, dry_run=False):
        snapshot = self.verified_snapshot()
        self.health(silent=True)
        state = self.load_state()
        part = int(state.get('check_part', 0)) % 4 + 1
        self.run(['check', '--read-data-subset', f'{part}/4'], retries=2)
        self.verify(snapshot)
        args = ['forget', '--host', self.config['host'], '--tag', TAG,
                '--group-by', 'host,tags', '--keep-last', '3', '--keep-daily', '14',
                '--keep-weekly', '8', '--keep-monthly', '12', '--keep-within', '2d']
        if dry_run:
            print(self.run(args + ['--dry-run']))
            return
        print(self.run(args))
        self.run(['prune', '--max-unused', '10%', '--max-repack-size', '256M'])
        self.run(['check'], retries=2)
        self.record(last_maintenance_at=utcnow(), check_part=part)
        print(f'JARVIS Restic Maintenance: completed; data partition {part}/4 checked')

    def health(self, silent=False):
        state = self.load_state()
        last = state.get('last_success_at')
        if not last:
            raise RuntimeError('No successful verified backup recorded')
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
        if age < -0.1 or age > 36:
            raise RuntimeError(f'Backup is stale or clock is wrong: age {age:.1f} hours (limit 36h)')
        if not silent:
            print(f'JARVIS Restic Backup: healthy; verified backup age {age:.1f}h')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'init', 'backup', 'snapshots', 'verify', 'check', 'maintenance', 'health'])
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--timeout', type=int, default=780, help='Total operation budget in seconds (below scheduler timeout)')
    parser.add_argument('--dry-run', action='store_true', help='Preview retention during maintenance; checks still run')
    parser.add_argument('--silent', action='store_true', help='Silent healthy watchdog result')
    parser.add_argument('--full', action='store_true', help='Read all repository data during check')
    args = parser.parse_args()
    backup = Backup(args.config, args.timeout)
    if args.action == 'health':
        backup.health(silent=args.silent)
        return
    with backup.locked():
        try:
            if args.action == 'plan':
                backup.plan()
            elif args.action == 'init':
                backup.validate_source()
                print(backup.run(['init']))
            elif args.action == 'backup':
                backup.nightly()
            elif args.action == 'snapshots':
                print(json.dumps(backup.snapshots(), indent=2))
            elif args.action == 'verify':
                backup.verify(backup.verified_snapshot())
                print('JARVIS Restic Restore Test: passed')
            elif args.action == 'check':
                print(backup.run(['check'] + (['--read-data'] if args.full else []), retries=2))
            elif args.action == 'maintenance':
                backup.maintain(args.dry_run)
        except Exception as exc:
            backup.record(last_error_at=utcnow(), last_error=str(exc)[-4000:])
            raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'JARVIS Restic Backup: failed\n{exc}', file=sys.stderr)
        sys.exit(1)
