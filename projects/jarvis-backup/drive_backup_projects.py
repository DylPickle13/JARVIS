#!/usr/bin/env python3
"""Back up this JARVIS checkout's projects directory to Google Drive.

The backup is a single tar.gz snapshot containing every immediate project folder under
PROJECTS_DIR. A new archive is uploaded first; only after that succeeds are older
Drive files with the same backup name removed, so a failed upload does not destroy the
last good backup.
"""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_JARVIS_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECTS_DIR = DEFAULT_JARVIS_ROOT / "projects"
DEFAULT_BACKUP_NAME = "JARVIS-projects-backup.tar.gz"
DEFAULT_DRIVE_FOLDER_NAME = "JARVIS Backups"
DEFAULT_LOCK_FILE = Path("/tmp/jarvis-projects-drive-backup.lock")


def timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def log(message: str) -> None:
    print(message, flush=True)


def format_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{num_bytes} B"


def project_summary(projects: list[Path]) -> str:
    names = [p.name for p in projects]
    return f"{len(names)} ({', '.join(names)})"


def run_gws(args: list[str], *, expect_json: bool = True, cwd: Path | None = None) -> Any:
    gws = shutil.which("gws") or "/opt/homebrew/bin/gws"
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    proc = subprocess.run(
        [gws, *args],
        text=True,
        capture_output=True,
        env=env,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        raise RuntimeError(
            "gws failed with exit code "
            f"{proc.returncode}\ncommand: {gws} {' '.join(args)}\nstdout: {stdout}\nstderr: {stderr}"
        )
    if not expect_json:
        return proc.stdout
    output = proc.stdout.strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gws returned non-JSON output: {output[:1000]}") from exc


def drive_quote(value: str) -> str:
    # Google Drive query string literals are single-quoted. Escape backslash and apostrophe.
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def list_drive_files(q: str, fields: str = "files(id,name,mimeType,size,createdTime,modifiedTime,webViewLink)") -> list[dict[str, Any]]:
    params = {"q": q, "fields": fields, "pageSize": 100, "supportsAllDrives": True, "includeItemsFromAllDrives": True}
    data = run_gws(["drive", "files", "list", "--params", json.dumps(params)])
    return list((data or {}).get("files") or [])


def create_drive_folder(name: str, parent_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        metadata["parents"] = [parent_id]
    params = {"fields": "id,name,webViewLink"}
    return run_gws([
        "drive",
        "files",
        "create",
        "--json",
        json.dumps(metadata),
        "--params",
        json.dumps(params),
    ])


def ensure_drive_folder(name: str, parent_id: str, folder_id: str | None) -> str:
    if folder_id:
        return folder_id

    parent_clause = f" and {drive_quote(parent_id)} in parents" if parent_id else ""
    q = f"mimeType = {drive_quote(FOLDER_MIME)} and name = {drive_quote(name)} and trashed = false{parent_clause}"
    folders = list_drive_files(q, fields="files(id,name,mimeType,createdTime,webViewLink)")
    if folders:
        folder = folders[0]
        return folder["id"]

    folder = create_drive_folder(name, parent_id)
    return folder["id"]


def should_exclude(projects_dir: Path, path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return False
    try:
        rel = PurePosixPath(path.relative_to(projects_dir).as_posix())
    except ValueError:
        return False
    rel_s = str(rel)
    for pattern in patterns:
        normalized = pattern.strip().strip("/")
        if not normalized:
            continue
        if fnmatch.fnmatch(rel_s, normalized) or fnmatch.fnmatch(path.name, normalized):
            return True
    return False


def make_archive(projects_dir: Path, archive_path: Path, excludes: list[str]) -> list[Path]:
    projects = sorted(p for p in projects_dir.iterdir() if p.is_dir())
    if not projects:
        raise RuntimeError(f"No project folders found in {projects_dir}")

    def tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # info.name is like projects/project-name/...
        rel = Path(*PurePosixPath(info.name).parts[1:]) if info.name.startswith("projects/") else Path(info.name)
        candidate = projects_dir / rel
        if should_exclude(projects_dir, candidate, excludes):
            return None
        return info

    with tarfile.open(archive_path, "w:gz", compresslevel=6) as tar:
        for project in projects:
            tar.add(project, arcname=f"projects/{project.name}", recursive=True, filter=tar_filter)
    return projects


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_backup(archive_path: Path, backup_name: str, folder_id: str, checksum: str, projects: list[Path]) -> dict[str, Any]:
    created = datetime.now(timezone.utc).isoformat()
    metadata = {
        "name": backup_name,
        "parents": [folder_id],
        "description": (
            "Automated JARVIS projects backup. "
            f"Created {created}. Contains: {', '.join(p.name for p in projects)}. SHA256: {checksum}"
        ),
    }
    params = {"fields": "id,name,size,createdTime,modifiedTime,webViewLink"}
    return run_gws([
        "drive",
        "files",
        "create",
        "--json",
        json.dumps(metadata),
        "--upload",
        archive_path.name,
        "--upload-content-type",
        "application/gzip",
        "--params",
        json.dumps(params),
    ], cwd=archive_path.parent)


def delete_old_backups(backup_name: str, folder_id: str, keep_id: str) -> int:
    q = f"name = {drive_quote(backup_name)} and trashed = false and {drive_quote(folder_id)} in parents"
    files = list_drive_files(q, fields="files(id,name,size,createdTime,modifiedTime,webViewLink)")
    old_files = [f for f in files if f.get("id") != keep_id]
    for old in old_files:
        run_gws(["drive", "files", "delete", "--params", json.dumps({"fileId": old["id"], "supportsAllDrives": True})], expect_json=False)
    return len(old_files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up JARVIS projects to Google Drive as a replace-in-place tar.gz snapshot.")
    parser.add_argument("--projects-dir", default=os.environ.get("PROJECTS_DIR", str(DEFAULT_PROJECTS_DIR)))
    parser.add_argument("--backup-name", default=os.environ.get("DRIVE_BACKUP_NAME", DEFAULT_BACKUP_NAME))
    parser.add_argument("--drive-folder-name", default=os.environ.get("DRIVE_BACKUP_FOLDER_NAME", DEFAULT_DRIVE_FOLDER_NAME))
    parser.add_argument("--drive-folder-id", default=os.environ.get("DRIVE_BACKUP_FOLDER_ID"))
    parser.add_argument("--drive-parent-id", default=os.environ.get("DRIVE_BACKUP_PARENT_ID", "root"))
    parser.add_argument("--tmp-dir", default=os.environ.get("BACKUP_TMPDIR"))
    parser.add_argument("--lock-file", default=os.environ.get("BACKUP_LOCK_FILE", str(DEFAULT_LOCK_FILE)))
    parser.add_argument("--exclude", action="append", default=[], help="Glob pattern relative to projects/ to skip; repeatable.")
    parser.add_argument("--keep-local", action="store_true", default=os.environ.get("KEEP_LOCAL_ARCHIVE") == "1")
    parser.add_argument("--dry-run", action="store_true", help="Create the archive and print what would upload, but do not touch Google Drive.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    projects_dir = Path(args.projects_dir).expanduser().resolve()
    lock_path = Path(args.lock_file)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if not projects_dir.is_dir():
        raise RuntimeError(f"Projects directory does not exist: {projects_dir}")

    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Projects Drive Backup: skipped\nReason: another backup is already running.")
            return 0

        tmp_root = Path(args.tmp_dir).expanduser() if args.tmp_dir else None
        with tempfile.TemporaryDirectory(prefix="jarvis-projects-drive-backup-", dir=str(tmp_root) if tmp_root else None) as tmp:
            archive_path = Path(tmp) / args.backup_name
            projects = make_archive(projects_dir, archive_path, args.exclude)
            size = archive_path.stat().st_size
            checksum = sha256_file(archive_path)

            if args.dry_run:
                log(
                    "Projects Drive Backup: dry run\n"
                    f"Projects: {project_summary(projects)}\n"
                    f"Archive: {args.backup_name} ({format_size(size)})\n"
                    f"SHA-256: {checksum}\n"
                    "Google Drive: not modified"
                )
                return 0

            folder_id = ensure_drive_folder(args.drive_folder_name, args.drive_parent_id, args.drive_folder_id)
            uploaded = upload_backup(archive_path, args.backup_name, folder_id, checksum, projects)
            deleted_count = delete_old_backups(args.backup_name, folder_id, uploaded["id"])

            local_copy_note = ""
            if args.keep_local:
                local_copy = Path.cwd() / args.backup_name
                shutil.copy2(archive_path, local_copy)
                local_copy_note = f"\nLocal copy: {local_copy}"

            log(
                "Projects Drive Backup: completed\n"
                f"Projects: {project_summary(projects)}\n"
                f"Archive: {uploaded.get('name', args.backup_name)} ({format_size(int(uploaded.get('size') or size))})\n"
                f"Replaced: {deleted_count} previous backup file(s)\n"
                f"Drive link: {uploaded.get('webViewLink', 'unavailable')}\n"
                f"Completed: {timestamp()}"
                f"{local_copy_note}"
            )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - top-level CLI error reporting
        log(f"Projects Drive Backup: failed\nCompleted: {timestamp()}\nError: {exc}")
        raise SystemExit(1)
