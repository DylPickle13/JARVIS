"""Real mouse/copy gestures in a private PTY; never touch live agent sockets."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config/tmux.conf'


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.socket = 'pi-desk-selection-test-' + uuid.uuid4().hex
        self.addCleanup(lambda: self.tmux('kill-server', check=False))
        program = self.root / 'app.py'
        program.write_text('''import os, select, sys, time, tty
from pathlib import Path
tty.setraw(0)
root = Path(sys.argv[1])
os.write(1, b'\\x1b[?1000h\\x1b[?1006h\\x1b[Halpha beta gamma\\r\\nsecond line')
n = 0
while True:
    n += 1
    (root / 'ticks').write_text(str(n))
    os.write(1, ('\\x1b[5;1Htick ' + str(n)).encode())
    if select.select([0], [], [], .03)[0]:
        data = os.read(0, 4096)
        with (root / 'input').open('ab') as stream:
            stream.write(data)
''')
        command = shlex.join([sys.executable, str(program), str(self.root)])
        env = dict(os.environ, TERM='xterm-256color')
        env.pop('TMUX', None)
        env.pop('TMUX_PANE', None)
        self.env = env
        self.tmux('-f', '/dev/null', 'new-session', '-d', '-s', 'selection',
                  '-x', '80', '-y', '20', command)
        # Replace only the status-click action so tests never call deployed helpers.
        config = CONFIG.read_text().replace(
            'run-shell -b \'python3 "$HOME/.local/share/pi-desk/desktop.py" click "#{mouse_status_range}" "#{client_pid}"\'',
            'set-option -g @test-status-click yes')
        private = self.root / 'config.tmux'
        private.write_text(config)
        self.tmux('source-file', str(private), ';', 'set-option', '-g', 'pane-border-status', 'off',
                  ';', 'set-option', '-g', 'status-format[0]',
                  '#[range=user|test]Selection test status#[norange]')
        clipboard = self.root / 'clipboard.py'
        clipboard.write_text('import sys\nfrom pathlib import Path\n'
                             'Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())\n')
        self.clipboard = self.root / 'clipboard'
        self.tmux('set-option', '-s', 'copy-command',
                  shlex.join([sys.executable, str(clipboard), str(self.clipboard)]))
        self.master, self.slave = os.openpty()
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', 20, 80, 0, 0))
        self.client = subprocess.Popen(['tmux', '-L', self.socket, 'attach-session', '-t', '=selection'],
                                       stdin=self.slave, stdout=self.slave, stderr=self.slave, env=env)
        self.addCleanup(self.close_client)
        self.output = bytearray()
        def drain():
            try:
                while True:
                    data = os.read(self.master, 65536)
                    if not data:
                        break
                    self.output.extend(data)
            except OSError:
                pass
        threading.Thread(target=drain, daemon=True).start()
        self.wait(lambda: str(self.client.pid) in self.tmux('list-clients', '-F', '#{client_pid}').stdout)
        self.wait(lambda: self.format('#{mouse_any_flag}') == '1')
        self.wait(lambda: self.root.joinpath('ticks').exists())

    def close_client(self):
        self.client.terminate()
        try:
            self.client.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.client.kill()
            self.client.wait(timeout=2)
        os.close(self.slave)
        os.close(self.master)

    def tmux(self, *args, check=True):
        return subprocess.run(['tmux', '-L', self.socket, *args], capture_output=True,
                              text=True, timeout=3, check=check,
                              env=getattr(self, 'env', None))

    def format(self, value, target='selection:0.0'):
        return self.tmux('display-message', '-p', '-t', target, value).stdout.strip()

    def wait(self, condition):
        for _ in range(150):
            if condition():
                return
            time.sleep(.02)
        self.fail('Timed out; selection state=' + self.format(
            '#{pane_mode}|#{selection_present}|#{selection_active}') +
            '; terminal output=' + repr(bytes(self.output[-250:])))

    def mouse(self, button, x, y, release=False):
        os.write(self.master, f'\x1b[<{button};{x};{y}{"m" if release else "M"}'.encode())
        time.sleep(.04)

    def drag(self, y=2):
        self.mouse(0, 1, y)
        self.mouse(32, 6, y)
        self.mouse(32, 11, y)
        self.mouse(0, 11, y, release=True)
        self.wait(lambda: self.format('#{selection_present}|#{selection_active}') == '1|0')

    def test_drag_is_sticky_and_freezes_only_view_while_app_runs(self):
        self.drag()
        self.assertEqual(self.format('#{pane_mode}'), 'copy-mode')
        self.assertFalse(self.clipboard.exists(), 'Release must not copy')
        frozen = self.tmux('capture-pane', '-p', '-M', '-t', 'selection:0.0').stdout
        ticks = int((self.root / 'ticks').read_text())
        self.wait(lambda: int((self.root / 'ticks').read_text() or '0') > ticks + 4)
        self.assertEqual(frozen, self.tmux('capture-pane', '-p', '-M', '-t', 'selection:0.0').stdout)
        self.assertNotEqual(frozen, self.tmux('capture-pane', '-p', '-t', 'selection:0.0').stdout)
        os.write(self.master, b'\x1b[9001~')
        self.wait(lambda: self.clipboard.exists())
        self.assertEqual(self.clipboard.read_text(), 'alpha beta')
        self.assertEqual(self.format('#{pane_mode}|#{selection_present}'), 'copy-mode|1')
        # Another copy still uses the same selection and does not dismiss it.
        self.clipboard.unlink()
        os.write(self.master, b'\x1b[9001~')
        self.wait(lambda: self.clipboard.exists())
        self.assertEqual(self.clipboard.read_text(), 'alpha beta')
        self.mouse(0, 25, 3)
        self.wait(lambda: self.format('#{pane_mode}') == '')
        self.assertNotIn(b'\x1b[9001~', self.root.joinpath('input').read_bytes())

    def test_typing_after_mouse_selection_resumes_input_without_losing_first_key(self):
        # These include keys that stock copy mode treats as navigation/search,
        # Unicode, and editing keys. None should disappear into the selection.
        for mode in ('emacs', 'vi'):
            self.tmux('set-option', '-g', 'mode-keys', mode)
            for key in (b'fhello', b'qhello', b'nhello', b' hello',
                        'éhello'.encode(), b'\x7f', b'\x1b[3~', b'\t'):
                with self.subTest(mode=mode, key=key):
                    self.drag()
                    before = self.root.joinpath('input').read_bytes()
                    os.write(self.master, key)
                    self.wait(lambda: self.format('#{pane_mode}') == '')
                    self.wait(lambda: self.root.joinpath('input').read_bytes() == before + key)
                    self.assertFalse(self.clipboard.exists())

    def test_clicking_transcript_then_typing_reaches_input(self):
        # A single click above the prompt remains ordinary input focus.
        self.mouse(0, 7, 2)
        self.mouse(0, 7, 2, release=True)
        before = self.root.joinpath('input').read_bytes()
        os.write(self.master, b'first')
        self.wait(lambda: self.root.joinpath('input').read_bytes() == before + b'first')
        # Rapid clicks may become a word selection; typing must recover too.
        time.sleep(.5)
        for _ in range(2):
            self.mouse(0, 7, 2)
            self.mouse(0, 7, 2, release=True)
        self.wait(lambda: self.format('#{selection_present}') == '1')
        before = self.root.joinpath('input').read_bytes()
        os.write(self.master, b'second')
        self.wait(lambda: self.format('#{pane_mode}') == '')
        self.wait(lambda: self.root.joinpath('input').read_bytes() == before + b'second')

    def test_selection_fallback_replays_root_shortcuts_without_agent_input(self):
        self.tmux('bind-key', '-T', 'root', 'C-Left', 'set-option', '-g',
                  '@test-navigation', 'yes')
        self.drag()
        before = self.root.joinpath('input').read_bytes()
        os.write(self.master, b'\x1b[1;5D')
        self.wait(lambda: self.format('#{@test-navigation}') == 'yes')
        self.assertEqual(self.format('#{pane_mode}'), '')
        self.assertEqual(self.root.joinpath('input').read_bytes(), before)

    def test_nested_tmux_selection_then_typing_reaches_hosted_input(self):
        # Match the deployment: outer app requests mouse input because it is
        # tmux, but the inner agent itself does not enable mouse reporting.
        inner = self.socket + '-inner'
        def inner_tmux(*args, check=True):
            return subprocess.run(['tmux', '-L', inner, *args], capture_output=True,
                                  text=True, timeout=3, check=check, env=self.env)
        self.addCleanup(lambda: inner_tmux('kill-server', check=False))
        root = self.root / 'inner'
        root.mkdir()
        program = root / 'app.py'
        program.write_text(self.root.joinpath('app.py').read_text().replace(
            r'\x1b[?1000h\x1b[?1006h', ''))
        inner_tmux('-f', '/dev/null', 'new-session', '-d', '-s', 'hosted',
                   '-x', '80', '-y', '19',
                   shlex.join([sys.executable, str(program), str(root)]))
        inner_tmux('set-option', '-g', 'mouse', 'on')
        errors = root / 'attach-errors'
        command = shlex.join([
            'env', '-u', 'TMUX', '-u', 'TMUX_PANE', 'TERM=xterm-256color',
            'tmux', '-L', inner, 'attach-session', '-t', '=hosted'])
        self.tmux('respawn-pane', '-k', '-t', 'selection:0.0',
                  '/bin/sh', '-c', command + ' 2>' + shlex.quote(str(errors)))
        self.wait(lambda: errors.exists() and (
            self.format('#{mouse_any_flag}') == '1'
            or self.format('#{pane_dead}') == '1'))
        self.assertEqual(self.format('#{mouse_any_flag}'), '1', errors.read_text())
        self.wait(lambda: root.joinpath('ticks').exists())
        self.assertEqual(inner_tmux('display-message', '-p', '-t', 'hosted:0.0',
                                   '#{mouse_any_flag}').stdout.strip(), '0')
        self.drag()
        os.write(self.master, 'fhello é'.encode())
        self.wait(lambda: root.joinpath('input').exists()
                  and root.joinpath('input').read_bytes() == 'fhello é'.encode())
        self.assertEqual(self.format('#{pane_mode}'), '')
        self.assertEqual(inner_tmux('display-message', '-p', '-t', 'hosted:0.0',
                                   '#{pane_mode}').stdout.strip(), '')

    def test_header_click_dismisses_selection_and_focuses_clicked_prompt(self):
        root = self.root / 'second'
        root.mkdir()
        self.tmux('split-window', '-h', '-t', 'selection:0', shlex.join([
            sys.executable, str(self.root / 'app.py'), str(root)]), ';',
            'select-pane', '-t', 'selection:0.0', ';',
            'set-option', '-g', 'pane-border-status', 'top')
        self.wait(lambda: root.joinpath('ticks').exists())
        self.drag(y=3)
        self.mouse(0, 65, 2)
        self.mouse(0, 65, 2, release=True)
        self.wait(lambda: self.format('#{pane_mode}') == '')
        self.assertEqual(self.format('#{pane_index}', 'selection:0'), '1')
        os.write(self.master, b'hello')
        self.wait(lambda: root.joinpath('input').exists()
                  and b'hello' in root.joinpath('input').read_bytes())
        self.assertFalse(self.clipboard.exists())

    def test_keyboard_copy_mode_keeps_its_original_navigation(self):
        self.tmux('copy-mode', '-t', 'selection:0.0')
        os.write(self.master, b'q')
        self.wait(lambda: self.format('#{pane_mode}') == '')
        self.assertFalse(self.root.joinpath('input').exists())

    def test_vi_mode_has_same_mouse_and_copy_behaviour(self):
        self.tmux('set-option', '-g', 'mode-keys', 'vi')
        self.drag()
        os.write(self.master, b'\x1b[9001~')
        self.wait(lambda: self.clipboard.exists())
        self.assertTrue(self.clipboard.read_text().startswith('alpha beta'))
        self.assertEqual(self.format('#{pane_mode}|#{selection_present}'), 'copy-mode|1')
        self.mouse(0, 25, 3)
        self.wait(lambda: self.format('#{pane_mode}') == '')

    def test_copy_without_selection_is_noop_and_never_reaches_app(self):
        before = self.root.joinpath('input').read_bytes() if self.root.joinpath('input').exists() else b''
        os.write(self.master, b'\x1b[9001~')
        time.sleep(.15)
        self.assertFalse(self.clipboard.exists())
        after = self.root.joinpath('input').read_bytes() if self.root.joinpath('input').exists() else b''
        self.assertEqual(before, after)
        self.assertEqual(self.format('#{pane_mode}'), '')
        self.tmux('copy-mode', '-t', 'selection:0.0')
        os.write(self.master, b'\x1b[9001~')
        time.sleep(.15)
        self.assertFalse(self.clipboard.exists())
        self.assertEqual(self.format('#{selection_present}'), '0')

    def test_escape_and_enter_dismiss_without_copying(self):
        for key in (b'\x1b', b'\r'):
            self.drag()
            os.write(self.master, key)
            self.wait(lambda: self.format('#{pane_mode}') == '')
            self.assertFalse(self.clipboard.exists())

    def test_status_click_dismisses_before_status_action(self):
        self.drag()
        self.mouse(0, 8, 1)
        self.wait(lambda: self.format('#{pane_mode}') == '')
        self.assertEqual(self.format('#{@test-status-click}'), 'yes')
        self.assertFalse(self.clipboard.exists())

    def test_clicking_another_pane_dismisses_and_focuses(self):
        self.tmux('split-window', '-h', '-t', 'selection:0', 'sleep 120', ';',
                  'select-pane', '-t', 'selection:0.0')
        self.drag()
        self.mouse(0, 65, 3)
        self.wait(lambda: self.format('#{pane_mode}') == '')
        self.assertEqual(self.format('#{pane_index}', 'selection:0'), '1')
        self.assertFalse(self.clipboard.exists())

    def test_double_and_triple_click_keep_word_and_line_highlight(self):
        for count, expected in ((2, 'beta'), (3, 'alpha beta gamma')):
            self.mouse(0, 7, 2)
            self.mouse(0, 7, 2, release=True)
            for _ in range(count - 1):
                self.mouse(0, 7, 2)
                self.mouse(0, 7, 2, release=True)
            self.wait(lambda: self.format('#{selection_present}') == '1')
            time.sleep(.4)  # Catch tmux's old delayed copy-and-cancel behaviour.
            self.assertEqual(self.format('#{pane_mode}'), 'copy-mode')
            self.assertFalse(self.clipboard.exists())
            os.write(self.master, b'\x1b[9001~')
            self.wait(lambda: self.clipboard.exists())
            self.assertEqual(self.clipboard.read_text().rstrip('\n'), expected)
            self.clipboard.unlink()
            os.write(self.master, b'\x1b')
            self.wait(lambda: self.format('#{pane_mode}') == '')
            time.sleep(.5)  # Reset the click repeat counter before the next gesture.


class BridgePackageTests(unittest.TestCase):
    def test_offline_package_and_native_copy_scope(self):
        root = ROOT / 'vscode-selection'
        spec = importlib.util.spec_from_file_location('build_vsix', root / 'build_vsix.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path = module.build(Path(directory) / 'selection.vsix')
            with zipfile.ZipFile(path) as archive:
                package = json.loads(archive.read('extension/package.json'))
                self.assertEqual(package['extensionKind'], ['ui'])
                binding = package['contributes']['keybindings'][0]
                self.assertEqual(binding['mac'], 'cmd+c')
                self.assertIn('piDesk.selectionTerminal', binding['when'])
                self.assertIn('!terminalTextSelected', binding['when'])
                self.assertNotIn('node_modules', '\n'.join(archive.namelist()))
                self.assertIn('extension.vsixmanifest', archive.namelist())


if __name__ == '__main__':
    unittest.main()
