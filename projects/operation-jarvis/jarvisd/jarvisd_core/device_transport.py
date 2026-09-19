"""Route legacy-shaped internal argv to a frozen, device-only worker.

All command actions, including local system status, use the private worker.
A failed/missing worker is never retried through the CLI. Timeout/environment ownership remains
with the existing process-group runner; no shell or background queue is added.
"""
from __future__ import annotations

from pathlib import Path
from .commands import CommandError
from .device_worker import HANDLERS


class DeviceAdapterRunner:
    def __init__(self, *, cli: Path, worker: Path, python: str,
                 operation_root: Path, project_root: Path, run):
        self.cli, self.worker, self.python = cli, worker, python
        self.operation_root, self.project_root, self.run = operation_root, project_root, run

    def worker_prefix(self) -> list[str]:
        return [self.python, "-B", str(self.worker),
                "--operation-root", str(self.operation_root),
                "--project-root", str(self.project_root), "--json"]

    def __call__(self, argv: list[str], timeout: float = 20.0, env=None) -> dict:
        if len(argv) < 3 or argv[:2] != [str(self.cli), "--json"]:
            raise CommandError("Invalid internal adapter request")
        if argv[2] in HANDLERS and (argv[2] != "status" or argv[2:] == ["status", "--no-cast"]):
            command = [*self.worker_prefix(), *argv[2:]]
        else:
            raise CommandError("Unsupported internal adapter action")
        return self.run(command, timeout=timeout, env=env)
