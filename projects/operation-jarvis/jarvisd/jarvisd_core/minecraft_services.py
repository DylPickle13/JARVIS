"""Read-only, fixed-purpose Minecraft process observations on the local Mac.

No screen/console commands, shell, log/world reads, startup, or import-time I/O.
Process identity requires the owner's private runtime, exact entry point and
project working directory. Health requests stay on fixed loopback endpoints.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import socket
import subprocess
import threading
import time

ADAPTERS = frozenset({"minecraft-paper", "minecraft-bot"})
TIMEOUT = 4.0
MAX_OUTPUT = 2 * 1024 * 1024
MAX_HEALTH = 8192


def _command(argv, deadline):
    """Bound both output and total elapsed time; never return stderr/private argv."""
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, start_new_session=True) as process:
        try:
            data = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError()
                    chunk = os.read(process.stdout.fileno(), min(65536, MAX_OUTPUT + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_OUTPUT:
                        raise ValueError("output limit")
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            return code, data.decode("utf-8", errors="strict")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def _health(port, method, deadline):
    # Fixed host/path/method, no proxy, redirects, credentials or retries.
    connection = http.client.HTTPConnection("127.0.0.1", port,
        timeout=max(0.001, min(0.75, deadline - time.monotonic())))
    def expire():
        # Socket timeouts alone are per-recv, not a total header deadline.
        # Interrupt this read's own socket if headers are drip-fed indefinitely.
        sock = connection.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        connection.close()
        raise TimeoutError()
    watchdog = threading.Timer(remaining, expire)
    watchdog.daemon = True
    watchdog.start()
    try:
        connection.request(method, "/health", body=b"{}" if method == "POST" else None,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("health unavailable")
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            # read1 avoids unbounded reads from a peer drip-feeding the body.
            if connection.sock is not None:
                connection.sock.settimeout(min(0.75, remaining))
            chunk = response.read1(min(4096, MAX_HEALTH + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_HEALTH:
                raise ValueError("health output limit")
        value = json.loads(data)
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise ValueError("invalid health")
        return value
    finally:
        watchdog.cancel()
        connection.close()


def _processes(text, root, uid):
    matches = {"paper": [], "bot": [], "agent": []}
    java = root / "java/current/bin/java"
    node = root / "node/current/bin/node"
    java_commands = {str(java), str(java.resolve()), "java"}
    node_commands = {str(node), str(node.resolve()), "node"}
    valid_rows = 0
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(\d+)\s+(\d+)\s+(.+)", line)
        if match is None:
            # Unrelated argv can contain newlines. ps succeeded with a bounded
            # complete body; only structured process rows can become candidates.
            continue
        valid_rows += 1
        pid, owner = int(match[1]), int(match[2])
        if owner != uid or pid <= 0:
            continue
        program = match[3].split(None, 1)[0]
        if program not in java_commands | node_commands:
            continue
        # Unrelated command lines need not be shell-parseable. A malformed
        # runtime candidate must not become false proof of absence.
        argv = shlex.split(match[3])
        # Java on macOS rewrites argv[0] to 'java'. Candidate names are not
        # identity evidence: mapped executable + cwd are verified below.
        if program in java_commands:
            if "-jar" not in argv:
                continue
            index = argv.index("-jar") + 1
            if index < len(argv) and argv[index] in ("paper.jar", str(root / "server/paper.jar")):
                matches["paper"].append(pid)
        elif len(argv) == 2:
            for kind, entry in (("bot", "bot.js"), ("agent", "pi-rpc-client.js")):
                if argv[1] in (entry, str(root / "jarvis-bot" / entry)):
                    matches[kind].append(pid)
    if not valid_rows:
        raise ValueError("invalid process inventory")
    if sum(map(len, matches.values())) > 16:
        raise ValueError("ambiguous inventory")
    return matches


def _lsof_records(text):
    records = {}
    pid = None
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:]); records.setdefault(pid, [])
        elif re.fullmatch(r"f(?:cwd|txt|\d+[rwu]?)", line):
            continue  # lsof emits mandatory file-record boundaries with -F.
        elif line.startswith("n") and pid is not None:
            records[pid].append(line[1:])
        elif line:
            raise ValueError("invalid lsof inventory")
    return records


def _listens(records, pid, port):
    return any(re.fullmatch(r".+:" + str(port), name) for name in records.get(pid, []))


def collect_minecraft_services(adapters, root, *, command=_command, health=_health,
                               uid=None, clock=time.monotonic):
    """One bounded process/cwd/listener inventory shared by both service rows."""
    root = Path(root).resolve()
    adapters = set(adapters) & ADAPTERS
    results = {}
    for adapter in adapters:
        files = ("java/current/bin/java", "server/paper.jar") if adapter == "minecraft-paper" else (
            "node/current/bin/node", "jarvis-bot/bot.js", "jarvis-bot/pi-rpc-client.js")
        results[adapter] = {"ok": True, "configured": all((root / file).is_file() for file in files),
                            "running": None, "pid": None, "ready": None, "readinessReason": None}
    if not adapters:
        return results
    deadline = clock() + TIMEOUT
    try:
        code, text = command(["/bin/ps", "-ww", "-axo", "pid=,uid=,command="], deadline)
        if code != 0 or not text.strip():
            raise ValueError("process inventory unavailable")
        matches = _processes(text, root, os.getuid() if uid is None else uid)
        pids = sorted({pid for values in matches.values() for pid in values})
        cwd = {}
        if pids:
            code, text = command(["/usr/sbin/lsof", "-a", "-p", ",".join(map(str, pids)),
                                  "-d", "cwd", "-Fn"], deadline)
            if code not in (0, 1):
                raise ValueError("working directory unavailable")
            cwd = _lsof_records(text)
        verified = {}
        unverified = set()
        for kind, values in matches.items():
            expected = str(root / ("server" if kind == "paper" else "jarvis-bot"))
            if any(not cwd.get(pid) for pid in values):
                unverified.add(kind)
            verified[kind] = [pid for pid in values if cwd.get(pid) == [expected]]
        identity_pids = sorted({pid for values in verified.values() for pid in values})
        if identity_pids:
            code, text = command(["/usr/sbin/lsof", "-a", "-p", ",".join(map(str, identity_pids)),
                                  "-d", "txt", "-Fn"], deadline)
            if code not in (0, 1):
                raise ValueError("executable identity unavailable")
            images = _lsof_records(text)
            for kind, values in verified.items():
                expected = str((root / ("java/current/bin/java" if kind == "paper" else "node/current/bin/node")).resolve())
                if any(not images.get(pid) for pid in values):
                    unverified.add(kind)
                verified[kind] = [pid for pid in values if expected in images.get(pid, [])]
        for adapter in adapters:
            kind = "paper" if adapter == "minecraft-paper" else "bot"
            values = verified[kind]
            if kind in unverified:
                results[adapter].update(ok=False, error="Minecraft process identity is unverified.")
            elif len(values) > 1:
                results[adapter].update(ok=False, error="Minecraft process identity is ambiguous.")
            else:
                results[adapter].update(running=bool(values), pid=values[0] if values else None)
        running = [adapter for adapter in adapters if results[adapter]["running"] is True]
        if not running:
            return results
        code, text = command(["/usr/sbin/lsof", "-nP", "-a", "-p", ",".join(map(str, pids)),
                              "-iTCP", "-sTCP:LISTEN", "-Fpn"], deadline)
        if code not in (0, 1) or (code == 1 and text.strip()):
            raise ValueError("listener inventory unavailable")
        listeners = _lsof_records(text)
        for adapter in running:
            value = results[adapter]
            try:
                if adapter == "minecraft-paper":
                    value["ready"] = _listens(listeners, value["pid"], 25565)
                    value["readinessReason"] = "java_listening" if value["ready"] else "java_not_listening"
                    continue
                if not _listens(listeners, value["pid"], 3100):
                    value.update(ready=False, readinessReason="bot_rpc_unavailable")
                    continue
                body = health(3100, "POST", deadline)  # Existing non-mutating RPC.
                if body.get("username") != "jarvis" or type(body.get("spawned")) is not bool:
                    raise ValueError("invalid bot health")
                if body["spawned"] is False:
                    value.update(ready=False, readinessReason="bot_disconnected")
                    continue
                operation = body.get("rpcOperation")
                if isinstance(operation, dict) and operation.get("quarantined") is True:
                    value.update(ready=False, readinessReason="bot_quarantined")
                    continue
                agents = verified["agent"]
                if "agent" in unverified or len(agents) > 1:
                    raise ValueError("agent identity unverified")
                if len(agents) != 1 or not _listens(listeners, agents[0], 3101):
                    value.update(ready=False, readinessReason="agent_unavailable")
                    continue
                agent = health(3101, "GET", deadline)
                if type(agent.get("piRunning")) is not bool:
                    raise ValueError("invalid agent health")
                value.update(ready=agent["piRunning"], readinessReason=(
                    "bot_ready" if agent["piRunning"] else "agent_unavailable"))
            except Exception:
                value.update(ready=None, readinessReason="health_unavailable")
        return results
    except Exception:
        for value in results.values():
            if value["running"] is True:
                value.update(ready=None, readinessReason="health_unavailable")
            elif value["ok"]:
                value.update(ok=False, running=None, error="Minecraft process observation unavailable.")
        return results
