#!/usr/bin/env python3
"""Bounded SSH JSON interface for iPhone session maintenance; no arbitrary commands.

The detached worker owns the existing restart lock. Repeating an operation ID
never launches another worker. Results survive SSH disconnects and app relaunches.
"""
from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
OPERATIONS = ROOT / ".pi/runtime/mobile-maintenance"
SCRIPT = Path(__file__).with_name("jarvis-mobile-vscode-restart.py")


def operation_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Invalid maintenance operation ID")
    return value


def save(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def read_result(path):
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["state"] in ("queued", "running") and time.time() - result["updatedAt"] > 600:
        result.update(state="unknown", message="Restart status is stale. Check the Mac before trying again.")
    return result


def request(payload):
    if not isinstance(payload, dict) or set(payload) != {"action", "operationID"}:
        raise ValueError("Invalid maintenance request")
    identifier = operation_id(payload["operationID"])
    action = payload["action"]
    if action not in ("start", "status"):
        raise ValueError("Unsupported maintenance action")
    OPERATIONS.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = OPERATIONS / (identifier + ".json")
    with (OPERATIONS / "submit.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            return read_result(path)
        if action == "status":
            return dict(operationID=identifier, state="notFound", completed=0,
                        message="This operation was not received by the Mac.")
        for existing in OPERATIONS.glob("*.json"):
            if read_result(existing)["state"] in ("queued", "running", "unknown"):
                raise ValueError("Another restart is active or unresolved. Check its status first.")
        result = dict(operationID=identifier, state="queued", completed=0,
                      message="Restart queued", updatedAt=time.time())
        save(path, result)
        try:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--worker", identifier],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
            )
        except OSError:
            result.update(state="failed", message="Could not start the restart worker.")
            save(path, result)
        return result


def worker(identifier):
    path = OPERATIONS / (operation_id(identifier) + ".json")
    result = json.loads(path.read_text(encoding="utf-8"))
    # The submission lock + exclusive creation above permits one worker per ID.
    def publish(completed=None):
        if completed is not None:
            result["completed"] = completed
        result["updatedAt"] = time.time()
        save(path, result)
    try:
        result.update(state="running", message="Restarting Pi sessions")
        publish()
        spec = importlib.util.spec_from_file_location("mobile_restart", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
            module.restart_all(progress=publish)
        result.update(state="succeeded", message="All 10 Pi sessions restarted.")
    except Exception as error:
        result.update(state="failed", message=str(error)[:1000])
    publish()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
        return
    try:
        raw = sys.stdin.buffer.readline(2049)
        if len(raw) > 2048:
            raise ValueError("Maintenance request too large")
        result = request(json.loads(raw))
    except Exception as error:
        result = dict(operationID="", state="rejected", completed=0, message=str(error)[:1000])
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
