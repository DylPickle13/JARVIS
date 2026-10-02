"""Non-modal restart progress shared by all local Pi Desk viewers."""
import fcntl
import os
import re
import json
import socket
from pathlib import Path
import subprocess
import time

from backend import clean_environment, load
from core import tmux

STATE = Path.home() / '.local/state/pi-desk'


def publish(text):
    temporary = STATE / f'restart-status.{os.getpid()}.tmp'
    temporary.write_text(f'{time.time()}\n{text}')
    temporary.replace(STATE / 'restart-status')


class Progress:
    """Keep every slot's state, not just the most recent helper message."""
    def __init__(self):
        self.slots = {}

    def update(self, line):
        match = re.match(r'^slot (10|[1-9]): (.*)$', line)
        if not match:
            return
        slot, detail = int(match[1]), match[2]
        if detail.startswith('queued;'):
            state = 'waiting'
        elif detail.startswith('restarting '):
            state = 'starting'
        elif detail.startswith('ready ('):
            state = 'ready'
        else:
            state = 'failed'
        self.slots[slot] = state

    def summary(self):
        if not self.slots:
            return ''
        parts = [f'{sum(state == "ready" for state in self.slots.values())}/10 ready']
        for state, label in (('waiting', 'Waiting for idle'),
                             ('starting', 'Restarting'), ('failed', 'Restart failed')):
            numbers = [f'#{slot}' for slot in sorted(self.slots) if self.slots[slot] == state]
            if numbers:
                noun = 'session' if len(numbers) == 1 else 'sessions'
                parts.append(f'{label}: {noun} {", ".join(numbers)}')
        if len(self.slots) < 10:
            parts.append('Checking remaining sessions')
        return ' · '.join(parts)


def status_line():
    try:
        stamp, text = (STATE / 'restart-status').read_text().split('\n', 1)
        if time.time() - float(stamp) > 60:
            return ''
    except (OSError, ValueError):
        return ''
    # Also interpret an already-running, older worker's raw event. This lets
    # reopened viewers show aggregate progress without relaunching the restart.
    if text.startswith('slot '):
        try:
            progress = Progress()
            for line in (STATE / 'restart.log').read_text().splitlines():
                progress.update(line)
            text = progress.summary() or text
        except OSError:
            pass
    text = ' '.join(text.split()).replace('#', '##')
    return '#[align=left,norange,bg=#1e1e1e,fg=colour179,nobold] Restart: ' + text


def notify(text, client=None):
    """Use only the invoking client's status message, never pane output/modes."""
    command = ['display-message', '-d', '5000']
    if client is not None:
        command += ['-c', client]
    try:
        tmux(*command, text, check=False)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        pass  # A detached viewer must not disturb an existing restart.


def run(client=None):
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'restart.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            tracker = Progress()
            try:
                for line in (STATE / 'restart.log').read_text().splitlines():
                    tracker.update(line)
                slots = [slot for slot, state in tracker.slots.items() if state == 'ready']
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as request:
                    request.settimeout(1)
                    request.sendto(json.dumps(slots).encode(), str(STATE / 'restart-control.sock'))
                notify('Ready sessions requested again; waiting/restarting sessions unchanged.', client)
            except OSError:
                notify('Existing restart cannot accept requests; retry after it finishes.', client)
            return 0
        # A reader thread lets the main thread refresh progress while a busy
        # agent is silent, without blocking terminal input or the status monitor.
        import queue
        import threading
        messages = queue.Queue()
        progress = Progress()
        latest = 'Checking all ten sessions; busy sessions will wait for idle…'
        publish(latest)
        control = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        control_path = STATE / 'restart-control.sock'
        try:
            control_path.unlink(missing_ok=True)
            control.bind(str(control_path))
            control_path.chmod(0o600)
            control.setblocking(False)
            with (STATE / 'restart.log').open('w') as log:
                process = subprocess.Popen(load().restart(interactive=True), env=clean_environment(),
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, errors='replace')
                def read_output():
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        if line.strip():
                            messages.put(line.strip())
                    messages.put(None)
                reader = threading.Thread(target=read_output, daemon=True)
                reader.start()
                refreshed = 0.0
                while True:
                    try:
                        request = control.recv(4096)
                    except BlockingIOError:
                        pass
                    else:
                        try:
                            process.stdin.write(request.decode() + '\n')
                            process.stdin.flush()
                        except (BrokenPipeError, OSError):
                            notify('Restart just finished; press F10 again for another cycle.', client)
                    try:
                        message = messages.get(timeout=0.1)
                    except queue.Empty:
                        if time.monotonic() - refreshed < 5:
                            continue
                        message = latest
                    if message is None:
                        break
                    progress.update(message)
                    latest = progress.summary() or message
                    publish(latest)
                    refreshed = time.monotonic()
                process.stdin.close()
                result = process.wait()
                reader.join()
                process.stdout.close()
            publish('Complete — all sessions ready.' if result == 0 else
                    f'Failed (exit {result}); {latest} — see ~/.local/state/pi-desk/restart.log')
            return result
        except (OSError, ValueError) as exc:
            publish(f'Failed: {exc}')
            return 1
        finally:
            control.close()
            control_path.unlink(missing_ok=True)
