"""OSC 8 forwarding through disposable tmux servers, never the live socket."""
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest


TMUX = shutil.which("tmux")
PROFILE = Path(__file__).resolve().parents[2] / "config" / "jarvis-mobile.tmux.conf"
URL = "https://example.com/docs"
LABEL = "JARVIS-LINK-LABEL"


@unittest.skipUnless(TMUX, "tmux is required for isolated OSC 8 integration tests")
class TerminalHyperlinkTests(unittest.TestCase):
    def capture_link(self, advertise_hyperlinks):
        with tempfile.TemporaryDirectory(prefix="jarvis-links-", dir="/tmp") as directory:
            root = Path(directory)
            socket = str(root / "socket")
            # Use the actual capability declarations, but never run the live
            # profile's maintenance hooks or absolute-path copy-refresh worker.
            declarations = [line for line in PROFILE.read_text().splitlines()
                            if line.startswith(('set -g default-terminal ', 'set -as terminal-features '))]
            if not advertise_hyperlinks:
                declarations = [line.replace(":hyperlinks", "") for line in declarations]
            config = root / "tmux.conf"
            config.write_text("\n".join(declarations + ["set -g status off"]) + "\n")
            ready = root / "emit"
            fixture = root / "fixture.py"
            fixture.write_text(
                "import pathlib,sys,time\n"
                f"ready=pathlib.Path({str(ready)!r})\n"
                "deadline=time.monotonic()+10\n"
                "while not ready.exists() and time.monotonic()<deadline: time.sleep(0.02)\n"
                f"sys.stdout.write({chr(27) + ']8;;' + URL + chr(27) + chr(92) + LABEL + chr(27) + ']8;;' + chr(27) + chr(92)!r})\n"
                "sys.stdout.flush()\ntime.sleep(10)\n"
            )
            base = [TMUX, "-S", socket]
            pid = None
            master = None
            try:
                subprocess.run(base + ["-f", str(config), "new-session", "-d", "-s", "fixture",
                                      "python3 -u " + shlex.quote(str(fixture))], check=True, timeout=5,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                pid, master = pty.fork()
                if pid == 0:
                    try:
                        os.execve(TMUX, base + ["attach-session", "-t", "fixture"],
                                  dict(os.environ, TERM="xterm-256color"))
                    finally:
                        os._exit(127)
                deadline = time.monotonic() + 5
                features = ""
                while time.monotonic() < deadline:
                    result = subprocess.run(base + ["list-clients", "-F", "#{client_termfeatures}"],
                                            capture_output=True, text=True, timeout=2)
                    features = result.stdout.strip()
                    if features:
                        break
                    time.sleep(0.02)
                self.assertTrue(features, "Synthetic xterm-256color client did not attach")
                ready.touch()
                output = bytearray()
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.05)[0]:
                        output.extend(os.read(master, 65536))
                        if LABEL.encode() in output:
                            break
                self.assertIn(LABEL.encode(), output)
                return features.split(","), bytes(output)
            finally:
                subprocess.run(base + ["kill-server"], capture_output=True, timeout=5)
                if pid:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    os.waitpid(pid, 0)
                if master is not None:
                    os.close(master)

    def test_mobile_profile_preserves_hidden_destination_for_iphone_pty(self):
        features, output = self.capture_link(advertise_hyperlinks=True)
        self.assertIn("hyperlinks", features)
        self.assertIn(b"\x1b]8;", output)
        self.assertIn(URL.encode(), output)

    def test_missing_capability_reproduces_visible_label_without_destination(self):
        features, output = self.capture_link(advertise_hyperlinks=False)
        self.assertNotIn("hyperlinks", features)
        self.assertNotIn(b"\x1b]8;", output)
        self.assertNotIn(URL.encode(), output)


if __name__ == "__main__":
    unittest.main()
