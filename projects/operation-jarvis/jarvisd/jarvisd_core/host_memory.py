"""Read-only whole-Mac memory counters; no dependency on oMLX or client code.

Memory used = non-purgeable anonymous + wired + physical compressor pages.
File-backed cache and free pages are excluded; compressed logical pages and
swap are not added again. This follows Activity Monitor's memory categories,
though separate samples need not exactly match its live display.
"""
from __future__ import annotations

import os
import re
import selectors
import signal
import subprocess
import time

MAX_OUTPUT = 16 * 1024
TIMEOUT = 4.0
COMMAND = "/usr/sbin/sysctl -n hw.memsize && /usr/bin/vm_stat"


def parse_memory(text: str) -> dict:
    lines = text.strip().splitlines()
    if not lines or not re.fullmatch(r"[0-9]+", lines[0]):
        raise ValueError("missing physical memory")
    total = int(lines[0])
    page = re.search(r"page size of ([0-9]+) bytes", text)
    if page is None or int(page[1]) not in (4096, 16384):
        raise ValueError("unsupported page size")
    values = {}
    for name in ("Anonymous pages", "Pages purgeable", "Pages wired down", "Pages occupied by compressor"):
        matches = re.findall(r"^" + re.escape(name) + r":\s*([0-9]+)\.\s*$", text, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("missing or duplicate memory counter")
        values[name] = int(matches[0])
    page_size = int(page[1])
    if not 0 < total <= 2**53 or any(n * page_size > total for n in values.values()):
        raise ValueError("invalid memory counter")
    app = values["Anonymous pages"] - values["Pages purgeable"]
    used = (app + values["Pages wired down"] + values["Pages occupied by compressor"]) * page_size
    if app < 0 or not 0 <= used <= total:
        raise ValueError("inconsistent memory counters")
    return {"ok": True, "usedBytes": used, "totalBytes": total,
            "definition": "macos-nonpurgeable-anonymous-wired-compressed"}


def _read(argv: list[str]) -> str:
    """Hard deadline and output bound, including SSH startup/banner failures."""
    deadline = time.monotonic() + TIMEOUT
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, start_new_session=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                data = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError()
                    chunk = os.read(process.stdout.fileno(), min(4096, MAX_OUTPUT + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_OUTPUT:
                        raise ValueError("oversized memory output")
                if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                    raise ValueError("memory command failed")
                return data.decode("ascii")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def collect_host_memory(server_id: str) -> dict:
    try:
        if server_id == "mac-mini-64":
            argv = ["/bin/sh", "-c", COMMAND]
        elif server_id == "mac-mini-16":
            # Existing operator-managed SSH alias and host key. Never provision
            # credentials, accept a new host key, prompt, forward, or retry.
            argv = ["/usr/bin/ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                    "-o", "ConnectTimeout=3", "-o", "ConnectionAttempts=1",
                    "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no",
                    "-o", "ForwardX11=no", "-o", "PermitLocalCommand=no",
                    "mac-mini-16", COMMAND]
        else:
            raise ValueError("unknown host")
        return parse_memory(_read(argv))
    except Exception:
        return {"ok": False, "error": "Mac memory unavailable."}
