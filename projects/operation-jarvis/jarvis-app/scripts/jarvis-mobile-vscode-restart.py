#!/usr/bin/env python3
"""Restart the six local Pi processes without losing their conversations.

This is intentionally a host-only maintenance command for the local VS Code
workspace. It restarts each Pi command in its existing fixed tmux pane; it does
not kill a tmux session/server, attach a client, resize a pane, or guess a
session with ``--continue``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[4]
TMUX_BIN = Path("/opt/homebrew/bin/tmux")
TMUX_SOCKET = "jarvis-mobile"
TMUX_CONFIG = PROJECT_ROOT / "projects/operation-jarvis/jarvis-app/config/jarvis-mobile.tmux.conf"
PI_BIN = Path("/opt/homebrew/bin/pi")
STATUS_DIR = PROJECT_ROOT / ".pi/runtime/local-pi-sessions"
SESSION_DIR = (
    Path.home()
    / ".pi/agent/sessions"
    / ("--" + str(PROJECT_ROOT).strip("/").replace("/", "-") + "--")
)
LOCK_PATH = PROJECT_ROOT / ".pi/runtime/jarvis-mobile-vscode-restart.lock"

SLOT_NAMES = {
    1: "jarvis-ios",
    2: "jarvis-ios-2",
    3: "jarvis-ios-3",
    4: "jarvis-ios-4",
    5: "jarvis-ios-5",
    6: "jarvis-ios-6",
}
VALID_LIFECYCLES = frozenset({"idle", "running", "waiting", "compacting"})
STATUS_SOURCE = "pi-extension-local-session-status"
MAX_STATUS_BYTES = 16 * 1024
MAX_STATUS_FILES_PER_PID = 8
MAX_STATUS_AGE_SECONDS = 10.0
MAX_STATUS_FUTURE_SKEW_SECONDS = 5.0
READY_TIMEOUT_SECONDS = 30.0
POLL_SECONDS = 0.10

# These are removed because a tmux server originally created through SSH can
# retain the original connection environment for later local respawns. TMUX
# itself is deliberately preserved and is supplied by tmux to the child.
STALE_SSH_VARIABLES = (
    "SSH_CONNECTION",
    "SSH_CLIENT",
    "SSH_TTY",
    "SSH_ORIGINAL_COMMAND",
)


class RestartError(RuntimeError):
    """A fail-closed preflight, tmux, or postcondition error."""


@dataclass(frozen=True)
class PaneEvidence:
    name: str
    window_index: str
    pane_index: str
    pane_id: str
    pane_dead: str
    pane_pid: int
    width: int
    height: int


@dataclass(frozen=True)
class SessionEvidence:
    slot: int
    name: str
    pane_id: str
    pane_pid: int
    session_file: Path
    lifecycle: str
    updated_at: dt.datetime
    status_path: Path
    width: int
    height: int


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_timestamp(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise RestartError("Pi status timestamp is invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RestartError("Pi status timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise RestartError("Pi status timestamp has no timezone")
    return parsed.astimezone(dt.timezone.utc)


def _require_fresh_timestamp(updated_at: dt.datetime, now: dt.datetime) -> None:
    age = (now - updated_at).total_seconds()
    if age < -MAX_STATUS_FUTURE_SKEW_SECONDS or age > MAX_STATUS_AGE_SECONDS:
        raise RestartError("Pi status heartbeat is stale or has an invalid clock")


def session_directory(project_root: Path = PROJECT_ROOT, home: Path | None = None) -> Path:
    """Return Pi's encoded session directory for this exact working tree."""
    home_path = (home or Path.home()).resolve()
    encoded_root = "--" + str(project_root.resolve()).strip("/").replace("/", "-") + "--"
    return home_path / ".pi/agent/sessions" / encoded_root


def _validate_session_file(raw_value: object, expected_dir: Path) -> Path:
    if not isinstance(raw_value, str) or not raw_value or "\x00" in raw_value:
        raise RestartError("Pi status did not contain a valid session file")
    candidate = Path(raw_value)
    expected_dir = expected_dir.resolve()
    try:
        candidate_parent = candidate.parent.resolve(strict=True)
    except OSError as error:
        raise RestartError("Pi session file directory is unavailable") from error
    if not candidate.is_absolute() or candidate_parent != expected_dir:
        raise RestartError("Pi session file is outside the fixed JARVIS session directory")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.jsonl", candidate.name):
        raise RestartError("Pi session file name is invalid")
    if candidate.is_symlink():
        raise RestartError("Pi session file may not be a symlink")
    # Pi deliberately does not materialize a new, empty session until its
    # first assistant message. A fresh session path is still a valid explicit
    # --session target and must be preserved across this restart.
    if not candidate.exists():
        return candidate
    try:
        resolved = candidate.resolve(strict=True)
        stat_result = candidate.stat()
    except OSError as error:
        raise RestartError("Pi session file is unavailable") from error
    if resolved.parent != expected_dir:
        raise RestartError("Pi session file resolved outside the fixed directory")
    if not candidate.is_file() or stat_result.st_uid != os.getuid():
        raise RestartError("Pi session file is not an owner-readable regular file")
    if not os.access(candidate, os.R_OK | os.W_OK):
        raise RestartError("Pi session file is not readable and writable by the owner")
    return candidate


def _status_paths(status_dir: Path, pane_pid: int) -> list[Path]:
    try:
        paths = [
            path
            for path in status_dir.glob(f"{pane_pid}-*.json")
            if not path.is_symlink() and path.is_file()
        ]
        direct = status_dir / f"{pane_pid}.json"
        if direct.exists() and not direct.is_symlink() and direct.is_file():
            paths.append(direct)
    except OSError as error:
        raise RestartError("Pi status directory could not be inspected") from error
    # More descriptors than the runtime contract permits is ambiguous. Do not
    # select one merely because it happens to look newest.
    if len(paths) > MAX_STATUS_FILES_PER_PID:
        raise RestartError(f"too many Pi status descriptors for PID {pane_pid}")
    return sorted(set(paths))


def _read_status_for_pid(
    status_dir: Path,
    pane_pid: int,
    expected_root: Path,
    expected_session_dir: Path,
    now: dt.datetime,
) -> tuple[Path, Mapping[str, object]]:
    candidates: list[tuple[dt.datetime, Path, Mapping[str, object]]] = []
    for path in _status_paths(status_dir, pane_pid):
        try:
            if path.stat().st_size > MAX_STATUS_BYTES:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("source") != STATUS_SOURCE or payload.get("version") != 2:
            continue
        if type(payload.get("pid")) is not int or payload.get("pid") != pane_pid:
            continue
        lifecycle = payload.get("lifecycle")
        if lifecycle not in VALID_LIFECYCLES:
            continue
        cwd = payload.get("cwd")
        try:
            if not isinstance(cwd, str) or Path(cwd).resolve() != expected_root.resolve():
                continue
        except OSError:
            continue
        try:
            updated_at = _parse_timestamp(payload.get("updatedAt"))
        except RestartError:
            continue
        candidates.append((updated_at, path, payload))

    if not candidates:
        raise RestartError(f"no valid Pi status descriptor for PID {pane_pid}")
    updated_at, status_path, payload = max(candidates, key=lambda item: item[0])
    _require_fresh_timestamp(updated_at, now)
    # Validate before any restart. This also prevents an invalid newest
    # descriptor from silently falling back to an older session selection.
    _validate_session_file(payload.get("sessionFile"), expected_session_dir)
    return status_path, payload


def parse_fixed_panes(stdout: str) -> dict[str, PaneEvidence]:
    """Parse exactly one fixed pane per allowlisted session."""
    rows: dict[str, list[PaneEvidence | None]] = {name: [] for name in SLOT_NAMES.values()}
    for raw_line in stdout.splitlines():
        fields = raw_line.split("\t")
        if not fields or fields[0] not in rows:
            continue
        if len(fields) != 8:
            rows[fields[0]].append(None)
            continue
        try:
            pane = PaneEvidence(
                name=fields[0],
                window_index=fields[1],
                pane_index=fields[2],
                pane_id=fields[3],
                pane_dead=fields[4],
                pane_pid=int(fields[5]),
                width=int(fields[6]),
                height=int(fields[7]),
            )
        except ValueError:
            rows[fields[0]].append(None)
        else:
            rows[fields[0]].append(pane)

    result: dict[str, PaneEvidence] = {}
    for name, matching_rows in rows.items():
        if len(matching_rows) != 1 or matching_rows[0] is None:
            raise RestartError(f"fixed tmux session {name} is missing or ambiguous")
        pane = matching_rows[0]
        assert pane is not None
        if pane.window_index != "0" or pane.pane_index != "0":
            raise RestartError(f"fixed tmux session {name} is not pane 0.0")
        if pane.pane_dead != "0" or pane.pane_pid <= 0:
            raise RestartError(f"fixed tmux session {name} does not have a live pane")
        if not re.fullmatch(r"%[0-9]+", pane.pane_id):
            raise RestartError(f"fixed tmux session {name} has an invalid pane identity")
        if pane.width <= 0 or pane.height <= 0:
            raise RestartError(f"fixed tmux session {name} has invalid dimensions")
        result[name] = pane
    return result


def snapshots_from_panes(
    pane_output: str,
    *,
    project_root: Path = PROJECT_ROOT,
    status_dir: Path = STATUS_DIR,
    expected_session_dir: Path | None = None,
    now: dt.datetime | None = None,
) -> list[SessionEvidence]:
    """Build and validate all six immutable preflight snapshots."""
    project_root = project_root.resolve()
    expected_session_dir = (expected_session_dir or session_directory(project_root)).resolve()
    observed_at = now or _utc_now()
    panes = parse_fixed_panes(pane_output)
    snapshots: list[SessionEvidence] = []
    errors: list[str] = []

    for slot, name in SLOT_NAMES.items():
        pane = panes[name]
        try:
            status_path, payload = _read_status_for_pid(
                status_dir,
                pane.pane_pid,
                project_root,
                expected_session_dir,
                observed_at,
            )
            session_file = _validate_session_file(payload.get("sessionFile"), expected_session_dir)
            updated_at = _parse_timestamp(payload.get("updatedAt"))
            snapshots.append(
                SessionEvidence(
                    slot=slot,
                    name=name,
                    pane_id=pane.pane_id,
                    pane_pid=pane.pane_pid,
                    session_file=session_file,
                    lifecycle=str(payload["lifecycle"]),
                    updated_at=updated_at,
                    status_path=status_path,
                    width=pane.width,
                    height=pane.height,
                )
            )
        except RestartError as error:
            errors.append(f"slot {slot} ({name}): {error}")

    if errors:
        raise RestartError("; ".join(errors))
    busy = [
        f"slot {snapshot.slot} ({snapshot.name}) is {snapshot.lifecycle}"
        for snapshot in snapshots
        if snapshot.lifecycle != "idle"
    ]
    if busy:
        raise RestartError("refusing to restart non-idle Pi process: " + "; ".join(busy))
    return snapshots


def _run_tmux(arguments: Sequence[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(TMUX_BIN), "-L", TMUX_SOCKET, *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RestartError(f"tmux command could not be executed: {error}") from error


def _list_fixed_panes() -> dict[str, PaneEvidence]:
    result = _run_tmux(
        [
            "list-panes",
            "-a",
            "-F",
            "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_dead}\t#{pane_pid}\t#{pane_width}\t#{pane_height}",
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        suffix = f": {detail[0][:200]}" if detail else ""
        raise RestartError("jarvis-mobile tmux server is unavailable" + suffix)
    return parse_fixed_panes(result.stdout or "")


def pi_shell_command(session_file: Path) -> str:
    command: list[str] = ["/usr/bin/env"]
    for variable in STALE_SSH_VARIABLES:
        command.extend(["-u", variable])
    command.extend(
        [
            "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            str(PI_BIN),
            "--tui-mode",
            "regular",
            "--session",
            str(session_file),
        ]
    )
    return shlex.join(command)


def respawn_arguments(snapshot: SessionEvidence, project_root: Path = PROJECT_ROOT) -> list[str]:
    return [
        "respawn-pane",
        "-k",
        "-c",
        str(project_root),
        "-t",
        f"={snapshot.name}:0.0",
        pi_shell_command(snapshot.session_file),
    ]


def _respawn(snapshot: SessionEvidence, project_root: Path) -> None:
    result = _run_tmux(respawn_arguments(snapshot, project_root), timeout=15.0)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        suffix = f": {detail[0][:200]}" if detail else ""
        raise RestartError(f"slot {snapshot.slot} ({snapshot.name}) could not be respawned{suffix}")


def _wait_for_ready(
    snapshot: SessionEvidence,
    *,
    project_root: Path,
    status_dir: Path,
    expected_session_dir: Path,
    timeout_seconds: float = READY_TIMEOUT_SECONDS,
) -> tuple[PaneEvidence, SessionEvidence]:
    deadline = time.monotonic() + timeout_seconds
    last_problem = "Pi has not published its new status descriptor"
    while time.monotonic() < deadline:
        try:
            panes = _list_fixed_panes()
            pane = panes[snapshot.name]
            if pane.pane_id != snapshot.pane_id:
                raise RestartError(
                    f"pane identity changed from {snapshot.pane_id} to {pane.pane_id}"
                )
            if pane.pane_pid == snapshot.pane_pid:
                raise RestartError("Pi PID has not changed yet")
            if pane.pane_dead != "0":
                raise RestartError("new Pi pane is dead")
            refreshed = snapshots_from_panes(
                "\n".join(
                    "\t".join(
                        [
                            item.name,
                            item.window_index,
                            item.pane_index,
                            item.pane_id,
                            item.pane_dead,
                            str(item.pane_pid),
                            str(item.width),
                            str(item.height),
                        ]
                    )
                    for item in panes.values()
                ),
                project_root=project_root,
                status_dir=status_dir,
                expected_session_dir=expected_session_dir,
            )
            current = next(item for item in refreshed if item.slot == snapshot.slot)
            if current.session_file != snapshot.session_file:
                raise RestartError("new Pi selected a different session file")
            if current.lifecycle != "idle":
                raise RestartError(f"new Pi is {current.lifecycle}, not idle")
            return pane, current
        except (RestartError, KeyError, StopIteration) as error:
            last_problem = str(error)
            time.sleep(POLL_SECONDS)
    raise RestartError(f"slot {snapshot.slot} ({snapshot.name}) did not become ready: {last_problem}")


def _source_profile() -> None:
    result = _run_tmux(["source-file", str(TMUX_CONFIG)])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        suffix = f": {detail[0][:200]}" if detail else ""
        raise RestartError("tmux profile could not be reloaded" + suffix)


def _set_latest_window_size(name: str) -> None:
    # This changes only tmux's future sizing policy; it does not resize the
    # current pane and leaves the active client's dimensions authoritative.
    result = _run_tmux(["set-option", "-w", "-t", f"={name}:0", "window-size", "latest"])
    if result.returncode != 0:
        raise RestartError(f"tmux sizing policy could not be reapplied for {name}")


@contextmanager
def _restart_lock(path: Path = LOCK_PATH) -> Iterator[None]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    file_handle = path.open("a+")
    try:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RestartError("another JARVIS Pi restart is already running") from error
        yield
    finally:
        try:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
        finally:
            file_handle.close()


def restart_all(*, dry_run: bool = False) -> None:
    """Preflight, restart, and verify all six fixed Pi panes."""
    if not PROJECT_ROOT.is_dir():
        raise RestartError(f"JARVIS project root is missing: {PROJECT_ROOT}")
    if not TMUX_BIN.is_file() or not PI_BIN.is_file() or not TMUX_CONFIG.is_file():
        raise RestartError("required tmux, Pi, or tmux profile executable is missing")
    if not STATUS_DIR.is_dir():
        raise RestartError(f"Pi status directory is missing: {STATUS_DIR}")
    if not SESSION_DIR.is_dir():
        raise RestartError(f"Pi session directory is missing: {SESSION_DIR}")

    with _restart_lock():
        pane_result = _run_tmux(
            [
                "list-panes",
                "-a",
                "-F",
                "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_dead}\t#{pane_pid}\t#{pane_width}\t#{pane_height}",
            ]
        )
        if pane_result.returncode != 0:
            raise RestartError("jarvis-mobile tmux server is unavailable")
        snapshots = snapshots_from_panes(pane_result.stdout or "")

        if dry_run:
            for snapshot in snapshots:
                print(
                    f"slot {snapshot.slot}: {snapshot.name} {snapshot.pane_id} "
                    f"would reload {snapshot.session_file.name}"
                )
            return

        # Do not mutate any pane until all six fixed identities, status files,
        # session paths, and idle states have passed preflight.
        _source_profile()
        for snapshot in snapshots:
            _set_latest_window_size(snapshot.name)
            _respawn(snapshot, PROJECT_ROOT)
            pane, refreshed = _wait_for_ready(
                snapshot,
                project_root=PROJECT_ROOT,
                status_dir=STATUS_DIR,
                expected_session_dir=SESSION_DIR,
            )
            print(
                f"slot {snapshot.slot}: {snapshot.name} restarted "
                f"({snapshot.pane_id}, PID {snapshot.pane_pid}->{pane.pane_pid}, "
                f"{refreshed.session_file.name})"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restart all six local JARVIS Pi processes in-place while preserving sessions."
    )
    parser.add_argument("--all", action="store_true", help="restart all six fixed Pi panes")
    parser.add_argument("--dry-run", action="store_true", help="perform preflight without restarting")
    args = parser.parse_args(argv)
    if not args.all:
        parser.error("--all is required")
    try:
        restart_all(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("Pi restart cancelled before completion.", file=sys.stderr)
        return 130
    except RestartError as error:
        print(f"JARVIS Pi restart refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
