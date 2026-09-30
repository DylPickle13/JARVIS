#!/usr/bin/env python3
"""Isolated-server tests; never attach to or write into the real Pi sessions."""
import importlib.util
import os
from pathlib import Path
import pty
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
import fcntl
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "jarvis-mobile-copy-refresh.py"
SPEC = importlib.util.spec_from_file_location("copy_refresh", SCRIPT)
REFRESH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFRESH)

PRODUCER = r'''
import sys, termios
settings = termios.tcgetattr(0)
settings[3] &= ~(termios.ECHO | termios.ECHONL)
termios.tcsetattr(0, termios.TCSANOW, settings)
print("\n".join("history-%03d" % i for i in range(60)), flush=True)
def token(label):
    sys.stdout.write("\x1b[12;1H\x1b[2Kstream-token-" + label + "\x1b[24;1H")
    sys.stdout.flush()
token("A")
for line in open(sys.argv[1]):
    label = line.strip()
    if label == "sync-start":
        sys.stdout.write("\x1b[?2026h")
        token("SYNC")
    elif label == "sync-end":
        sys.stdout.write("\x1b[?2026l")
        sys.stdout.flush()
    elif label == "append":
        print("new-bottom-line", flush=True)
    else:
        token(label)
'''


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Condition not reached before timeout")


@unittest.skipUnless(Path(REFRESH.TMUX).exists(), "tmux integration requires Homebrew tmux")
class CopyRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jarvis-copy-test-")
        self.socket = str(Path(self.tmp.name) / "socket")
        self.workers = []
        self.clients = []
        fifo = str(Path(self.tmp.name) / "producer-input")
        os.mkfifo(fifo)
        self.producer_input = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        self.tm("-f", "/dev/null", "new-session", "-d", "-s", "jarvis-ios", "-x", "80", "-y", "24",
                f"{shlex.quote(sys.executable)} -u -c {shlex.quote(PRODUCER)} {shlex.quote(fifo)}")
        self.tm("set-option", "-g", "status", "off")
        self.tm("set-option", "-g", "@jarvis-copy-refresh-enabled", "on")
        self.pane = self.tm("display-message", "-p", "#{pane_id}").strip()
        self.server_pid = int(self.tm("display-message", "-p", "#{pid}"))
        wait_for(lambda: "stream-token-A" in self.capture())

    def tearDown(self):
        self.tm("kill-server", check=False)
        for worker in self.workers + self.clients:
            try:
                worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=3)
        os.close(self.producer_input)
        self.tmp.cleanup()

    def tm(self, *args, check=True):
        result = subprocess.run([REFRESH.TMUX, "-S", self.socket, *args],
                                text=True, capture_output=True, timeout=3)
        if check and result.returncode:
            self.fail(result.stderr)
        return result.stdout

    def capture(self, mode=False):
        if not mode:
            return self.tm("capture-pane", "-p", "-t", self.pane)
        # -M exposes copy mode's backing grid, not its scrolled display screen.
        position, height = map(int, self.tm(
            "display-message", "-p", "-t", self.pane,
            "#{scroll_position}|#{pane_height}",
        ).strip().split("|"))
        return self.tm("capture-pane", "-p", "-M", "-t", self.pane,
                       "-S", str(-position), "-E", str(height - position - 1))

    def send(self, text):
        os.write(self.producer_input, (text + "\n").encode())

    def enter_copy(self):
        self.tm("copy-mode", "-t", self.pane)
        self.tm("send-keys", "-t", self.pane, "-X", "scroll-up")

    def worker(self, server_pid=None):
        process = subprocess.Popen([
            sys.executable, str(SCRIPT), "--socket", self.socket,
            "--server-pid", str(server_pid or self.server_pid),
            "--lock-dir", str(Path(self.tmp.name) / "locks"),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.workers.append(process)
        return process

    def test_live_text_updates_without_exiting_or_moving_history(self):
        self.enter_copy()
        anchor = self.capture(mode=True).splitlines()[0]
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture())
        self.assertIn("stream-token-A", self.capture(mode=True))  # Reproduce freeze.
        self.worker()
        wait_for(lambda: "stream-token-B" in self.capture(mode=True))
        self.assertEqual(anchor, self.capture(mode=True).splitlines()[0])
        self.assertEqual("copy-mode|1", self.tm("display-message", "-p", "#{pane_mode}|#{scroll_position}").strip())
        self.send("C")
        wait_for(lambda: "stream-token-C" in self.capture(mode=True))
        self.send("append")
        wait_for(lambda: "new-bottom-line" in self.capture())
        wait_for(lambda: self.tm("display-message", "-p", "#{scroll_position}").strip() == "2")
        self.assertEqual(anchor, self.capture(mode=True).splitlines()[0])

    def test_selection_pauses_refresh_and_resumes_after_clear(self):
        self.enter_copy()
        self.tm("send-keys", "-t", self.pane, "-X", "begin-selection")
        before = self.capture(mode=True)
        self.worker()
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture())
        time.sleep(0.25)
        self.assertEqual(before, self.capture(mode=True))
        self.assertEqual("1", self.tm("display-message", "-p", "#{selection_active}").strip())
        self.tm("send-keys", "-t", self.pane, "-X", "clear-selection")
        wait_for(lambda: "stream-token-B" in self.capture(mode=True))

    def test_synchronized_frame_is_not_refreshed_until_complete(self):
        self.enter_copy()
        self.worker()
        self.send("sync-start")
        wait_for(lambda: self.tm("display-message", "-p", "#{synchronized_output_flag}").strip() == "1")
        time.sleep(0.15)
        self.assertIn("stream-token-A", self.capture(mode=True))
        self.assertEqual("1", self.tm("display-message", "-p", "#{synchronized_output_flag}").strip())
        self.send("sync-end")
        wait_for(lambda: "stream-token-SYNC" in self.capture(mode=True))

    def test_only_one_worker_and_exit_when_copy_mode_ends(self):
        self.enter_copy()
        first = self.worker()
        time.sleep(0.15)
        second = self.worker()
        self.assertEqual(0, second.wait(timeout=2))
        self.assertIsNone(first.poll())
        self.tm("send-keys", "-t", self.pane, "-X", "cancel")
        self.assertEqual(0, first.wait(timeout=2))

    def test_wrong_server_and_other_sessions_are_ignored(self):
        self.enter_copy()
        wrong = self.worker(server_pid=self.server_pid + 1)
        self.assertEqual(0, wrong.wait(timeout=2))
        self.tm("rename-session", "-t", "jarvis-ios", "unrelated")
        other = self.worker()
        self.assertEqual(0, other.wait(timeout=2))
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture())
        self.assertIn("stream-token-A", self.capture(mode=True))

    def test_idle_grid_is_not_recloned_after_first_refresh(self):
        self.enter_copy()
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture())
        snapshots = {}
        actual = REFRESH.command
        with patch.object(REFRESH, "command", wraps=actual) as calls:
            for _ in range(3):
                panes = REFRESH.read_state(self.socket, self.server_pid)
                REFRESH.refresh_once(self.socket, self.server_pid, panes, snapshots)
            refreshes = [c for c in calls.call_args_list if c.args[1] == "if-shell"]
        self.assertEqual(1, len(refreshes))

    def source_profile(self):
        profile = SCRIPT.parents[1] / "config/jarvis-mobile.tmux.conf"
        content = profile.read_text().replace(
            "--server-pid #{pid}",
            "--server-pid #{pid} --lock-dir " + str(Path(self.tmp.name) / "locks"),
        )
        path = Path(self.tmp.name) / "profile.conf"
        path.write_text(content)
        self.tm("source-file", str(path))

    def test_profile_hook_starts_refresh_automatically(self):
        self.source_profile()
        self.enter_copy()
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture(mode=True))
        self.assertEqual("copy-mode", self.tm("display-message", "-p", "#{pane_mode}").strip())
        self.assertIn("after-copy-mode[90]", self.tm("show-hooks", "-g", "after-copy-mode"))
        self.assertEqual("off", self.tm("show-options", "-gv", "status").strip())

    def test_profile_reload_covers_existing_copy_view(self):
        self.enter_copy()
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture())
        self.assertIn("stream-token-A", self.capture(mode=True))
        self.source_profile()
        wait_for(lambda: "stream-token-B" in self.capture(mode=True))

    def test_disable_switch_stops_worker_without_exiting_copy_mode(self):
        self.enter_copy()
        worker = self.worker()
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture(mode=True))
        self.tm("set-option", "-g", "@jarvis-copy-refresh-enabled", "off")
        self.assertEqual(0, worker.wait(timeout=2))
        self.send("C")
        wait_for(lambda: "stream-token-C" in self.capture())
        time.sleep(0.15)
        self.assertIn("stream-token-B", self.capture(mode=True))

    def test_execution_guard_protects_selection_started_after_metadata_sample(self):
        self.enter_copy()
        self.send("B")
        wait_for(lambda: "stream-token-B" in self.capture())
        panes = REFRESH.read_state(self.socket, self.server_pid)
        self.tm("send-keys", "-t", self.pane, "-X", "begin-selection")
        snapshots = {}
        REFRESH.refresh_once(self.socket, self.server_pid, panes, snapshots)
        self.assertIn("stream-token-A", self.capture(mode=True))
        self.assertEqual({}, snapshots)

    def test_allowlist_contains_exactly_ten_sessions(self):
        self.assertEqual({"jarvis-ios"} | {f"jarvis-ios-{i}" for i in range(2, 11)}, REFRESH.SESSIONS)

    def test_attached_client_receives_updated_screen(self):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        client = subprocess.Popen([REFRESH.TMUX, "-S", self.socket, "attach-session", "-t", "jarvis-ios"],
                                  stdin=slave, stdout=slave, stderr=slave,
                                  env={**os.environ, "TERM": "xterm-256color", "TMUX": ""})
        self.clients.append(client)
        os.close(slave)
        def drain(duration):
            data = b""
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.02)[0]:
                    data += os.read(master, 65536)
            return data
        try:
            drain(0.2)
            self.enter_copy()
            drain(0.1)
            self.worker()
            self.send("B")
            output = drain(0.4)
            self.assertIn(b"stream-token-B", output)
        finally:
            os.close(master)


if __name__ == "__main__":
    unittest.main(verbosity=2)
