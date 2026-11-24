"""Viewer cell widths must match VS Code's xterm.js; isolated socket, no agents."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parent
INSTALLED = Path.home() / '.local/share/pi-desk/bin/tmux'
# Expected widths are xterm.js Unicode 11 per-codepoint counts (VS Code's terminal).
SAMPLES = {'বাংলা': 5, 'मराठी': 5, 'हिंदी': 4, 'ਪੰਜਾਬੀ': 5, 'తెలుగు': 5,
           'ไทย': 3, 'සිංහල': 4, '⚠️': 1, '日本語': 6, 'abc': 3}


def binary():
    if INSTALLED.is_file() and os.access(INSTALLED, os.X_OK):
        return str(INSTALLED)
    return shutil.which('tmux')


@unittest.skipUnless(binary(), 'tmux unavailable')
class CellWidthTests(unittest.TestCase):
    def setUp(self):
        version = subprocess.run([binary(), '-V'], capture_output=True, text=True).stdout
        number = version.split()[-1].rstrip('abcdefghijklmnopqrstuvwxyz') if version else '0'
        if tuple(map(int, number.split('.')[:2])) < (3, 5):
            self.skipTest('codepoint-widths needs tmux 3.5+')
        self.socket = 'pi-desk-width-test-' + uuid.uuid4().hex
        self.tmux = [binary(), '-L', self.socket]
        subprocess.run(self.tmux + ['-f', str(ROOT / 'config/tmux.conf'), 'new-session', '-d',
                                    '-x', '100', '-y', '10', 'sleep 60'], check=True,
                       env={**os.environ, 'LANG': 'en_US.UTF-8'})
        self.addCleanup(subprocess.run, self.tmux + ['kill-server'], capture_output=True)

    def width(self, text):
        subprocess.run(self.tmux + ['respawn-pane', '-k', '-t', '0',
                                    f"printf '%s' '{text}'; sleep 30"], check=True)
        deadline = time.monotonic() + 3
        previous = None
        while time.monotonic() < deadline:
            time.sleep(.1)
            current = subprocess.run(self.tmux + ['display-message', '-p', '-t', '0', '#{cursor_x}'],
                                     capture_output=True, text=True, check=True).stdout.strip()
            if current == previous and current != '0':
                return int(current)
            previous = current
        return int(previous)

    def test_widths_match_vscode_terminal(self):
        for text, expected in SAMPLES.items():
            with self.subTest(text=text):
                self.assertEqual(self.width(text), expected)


if __name__ == '__main__':
    unittest.main()
