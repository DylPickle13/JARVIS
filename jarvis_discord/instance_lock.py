from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import config

LOGGER = config.get_logger("jarvis.discord_bot")
_DISCORD_BOT_INSTANCE_LOCK: object | None = None


def _parse_pid(raw_pid: str) -> int | None:
    try:
        pid = int(raw_pid.strip())
    except ValueError:
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    return pid


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _pid_command(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return " ".join(completed.stdout.split())


def _pid_looks_like_discord_bot(pid: int) -> bool:
    command = _pid_command(pid)
    if not command:
        return False
    return "discord_bot.py" in command


def _terminate_existing_discord_bot(pid: int) -> bool:
    if not _pid_looks_like_discord_bot(pid):
        LOGGER.error(
            "Discord bot lock is held by pid %s, but its command does not look like this JARVIS discord_bot.py; "
            "refusing to terminate it automatically. Command: %s",
            pid,
            _pid_command(pid) or "unknown",
        )
        return False

    LOGGER.warning("Replacing existing JARVIS Discord bot process pid %s before starting this instance.", pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        LOGGER.error("Cannot terminate existing Discord bot pid %s: permission denied.", pid)
        return False
    except OSError as exc:
        LOGGER.error("Cannot terminate existing Discord bot pid %s: %s", pid, exc)
        return False

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not _pid_is_alive(pid):
            return True
        time.sleep(0.2)

    LOGGER.warning("Existing Discord bot pid %s did not exit after SIGTERM; sending SIGKILL.", pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        LOGGER.error("Cannot SIGKILL existing Discord bot pid %s: permission denied.", pid)
        return False
    except OSError as exc:
        LOGGER.error("Cannot SIGKILL existing Discord bot pid %s: %s", pid, exc)
        return False

    # If the process briefly remains visible as a zombie, its advisory lock should
    # still be released. Let the caller decide success by reacquiring the lock.
    time.sleep(0.5)
    return True


def _write_instance_lock_pid(lock_file: object) -> None:
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()


def acquire_single_instance_lock(*, project_root: Path | None = None) -> bool:
    """Run only one local bot process, replacing an older local instance by default.

    Discord voice state is especially sensitive to duplicate clients: a second
    local process can invalidate the first process's voice websocket/session and
    produce 4006 reconnect loops. The lock is advisory and automatically
    released by the OS if the process exits.
    """
    if config.get_bool_env("DISCORD_BOT_DISABLE_INSTANCE_LOCK", False):
        return True
    if os.name != "posix":
        return True
    try:
        import fcntl
    except Exception:
        LOGGER.warning("fcntl is unavailable; Discord bot single-instance lock is disabled.")
        return True

    root = project_root or config.PROJECT_ROOT
    lock_path = root / ".pi" / "discord_bot.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.seek(0)
        existing_pid_text = lock_file.read().strip()
        existing_pid = _parse_pid(existing_pid_text)
        detail = f" by pid {existing_pid_text}" if existing_pid_text else ""
        if not config.get_bool_env("DISCORD_BOT_REPLACE_EXISTING", True):
            LOGGER.error(
                "Another local JARVIS Discord bot instance is already running%s; refusing to start a duplicate. "
                "Remove DISCORD_BOT_REPLACE_EXISTING=0 to restore automatic replacement.",
                detail,
            )
            lock_file.close()
            return False
        if existing_pid is None:
            LOGGER.error(
                "Another local JARVIS Discord bot instance is already running%s, but the lock file does not contain "
                "a usable pid; refusing to guess which process to terminate.",
                detail,
            )
            lock_file.close()
            return False
        if not _terminate_existing_discord_bot(existing_pid):
            lock_file.close()
            return False

        deadline = time.monotonic() + 8.0
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    LOGGER.error("Timed out waiting for Discord bot lock held%s to be released.", detail)
                    lock_file.close()
                    return False
                time.sleep(0.2)

    _write_instance_lock_pid(lock_file)
    global _DISCORD_BOT_INSTANCE_LOCK
    _DISCORD_BOT_INSTANCE_LOCK = lock_file
    return True
