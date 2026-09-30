#!/usr/bin/env python3
"""Keep regular-mode Pi's tmux copy view live without changing its layout.

Runs only while an allowlisted pane is in copy mode. Refreshes the actual copy
buffer, not Pi input; selections and DEC synchronized-output frames are protected.
One bounded worker per server, started by after-copy-mode (and profile reload).
"""

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import time

TMUX = "/opt/homebrew/bin/tmux"
SESSIONS = frozenset(["jarvis-ios"] + [f"jarvis-ios-{i}" for i in range(2, 11)])
INTERVAL = 0.1
FORMAT = "|".join([
    "#{session_name}", "#{pane_id}", "#{pane_mode}",
    "#{||:#{selection_present},#{selection_active}}",
    "#{synchronized_output_flag}", "#{pane_unseen_changes}", "#{history_size}",
    "#{pane_width}", "#{pane_height}", "#{pane_pid}",
])
DEFAULT_LOCK_DIR = Path(__file__).resolve().parents[4] / ".pi/runtime/copy-refresh"


def command(socket, *args):
    return subprocess.run(
        [TMUX, "-S", socket, *args], capture_output=True, timeout=2, check=False,
    )


def read_state(socket, server_pid):
    result = command(socket, "display-message", "-p",
                     "#{pid}|#{@jarvis-copy-refresh-enabled}", ";",
                     "list-panes", "-a", "-F", FORMAT)
    if result.returncode:
        return None
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    if not lines or lines[0] != f"{server_pid}|on":
        return None  # Never follow a replacement server on the same socket.
    panes = []
    for line in lines[1:]:
        fields = line.split("|")
        if len(fields) != 10:
            continue
        session, pane, mode, selection, sync, unseen, history, width, height, pid = fields
        if session in SESSIONS and re.fullmatch(r"%\d+", pane) and mode == "copy-mode":
            panes.append({"session": session, "pane": pane, "selection": selection,
                          "sync": sync, "unseen": unseen,
                          "identity": (pid, history, width, height)})
    return panes


def refresh_guard(session, server_pid):
    # Recheck at execution time, not just when the worker sampled metadata.
    conditions = [
        "#{==:#{pid}," + str(server_pid) + "}",
        "#{==:#{@jarvis-copy-refresh-enabled},on}",
        "#{==:#{session_name}," + session + "}",
        "#{==:#{pane_mode},copy-mode}",
        "#{!:#{||:#{selection_present},#{selection_active}}}",
        "#{!:#{synchronized_output_flag}}",
        "#{pane_unseen_changes}",
    ]
    guard = conditions.pop()
    for condition in reversed(conditions):
        guard = "#{&&:" + condition + "," + guard + "}"
    return guard


def refresh_once(socket, server_pid, panes, snapshots):
    active = {p["pane"] for p in panes}
    for pane in list(snapshots):
        if pane not in active:
            del snapshots[pane]
    for p in panes:
        if p["selection"] == "1" or p["sync"] == "1" or p["unseen"] != "1":
            continue
        pane = p["pane"]
        # pane_unseen_changes is sticky on tmux 3.7c. Compare the live grid so
        # idle panes don't repeatedly clone their potentially 100k-line history.
        capture = command(socket, "capture-pane", "-p", "-e", "-t", pane)
        if capture.returncode:
            continue
        snapshot = (p["identity"], capture.stdout)
        if snapshots.get(pane) == snapshot:
            continue
        clients = command(socket, "list-clients", "-t", "=" + p["session"],
                          "-F", "#{client_name}")
        if clients.returncode:
            continue
        # 3.7c updates the mode's grid but does not reliably repaint its body.
        # Redraw only clients viewing this session, never unrelated terminals.
        actions = [f"send-keys -t {pane} -X refresh-from-pane"]
        for client in clients.stdout.decode("utf-8", errors="strict").splitlines():
            actions.append("refresh-client -t " + shlex.quote(client))
        actions.append("display-message -p refreshed")
        result = command(
            socket, "if-shell", "-F", "-t", pane,
            refresh_guard(p["session"], server_pid), " ; ".join(actions), "",
        )
        if result.returncode == 0 and result.stdout.strip() == b"refreshed":
            snapshots[pane] = snapshot


def run(socket, server_pid, lock_dir):
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = lock_dir.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Copy-refresh lock directory must be owner-only")
    key = hashlib.sha256(f"{socket}:{server_pid}".encode()).hexdigest()[:24]
    fd = os.open(lock_dir / (key + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Unsafe copy-refresh lock file")
        # A brief bounded wait avoids a lost start if the previous worker is
        # exiting just as copy mode is entered again. Never queue lasting workers.
        deadline = time.monotonic() + 1
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(INTERVAL)
        snapshots = {}
        while True:
            started = time.monotonic()
            panes = read_state(socket, server_pid)
            if not panes:
                return
            refresh_once(socket, server_pid, panes, snapshots)
            # Bound aggregate cloning load if several clients scroll at once.
            interval = max(INTERVAL, len(panes) * 0.05)
            time.sleep(max(0, interval - (time.monotonic() - started)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--server-pid", type=int, required=True)
    parser.add_argument("--lock-dir", type=Path, default=DEFAULT_LOCK_DIR)
    args = parser.parse_args()
    try:
        run(args.socket, args.server_pid, args.lock_dir)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Fail closed: no retries across server loss, no terminal input fallback.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
