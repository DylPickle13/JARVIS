#!/usr/bin/env python3
"""Explicit offline SQLite relocation. Stop all writers before invoking.

Never removes the source, changes schedules, dispatches work, or merges stores.
Use once for the private rollback snapshot and again for the new runtime copy.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def fingerprint(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for line in conn.iterdump():
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def copy_database(source: Path, destination: Path) -> dict:
    source, destination = source.absolute(), destination.absolute()
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source must be an existing regular SQLite file")
    if destination.is_symlink() or destination.exists() or any(
        Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise ValueError("Destination or SQLite sidecar already exists; refusing to overwrite")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as src:
            # Hold one read snapshot for backup and logical verification, including WAL data.
            src.execute("BEGIN")
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Copied database failed integrity check")
                if fingerprint(src) != fingerprint(dst):
                    raise ValueError("Copied database differs from the source snapshot")
                tables = [row[0] for row in dst.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )]
                counts = {
                    table: dst.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                    for table in tables
                }
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = Path(str(destination) + suffix)
            if path.exists():
                path.chmod(0o600)
        return {"ok": True, "tables": counts}
    except BaseException:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(destination) + suffix).unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(copy_database(args.source, args.destination)))


if __name__ == "__main__":
    main()
