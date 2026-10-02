"""Non-modal restart progress shared by all local Pi Desk viewers."""
import fcntl
import os
import re
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
                             ('starting', 'Restarting'), ('failed', 'Failed')):
            numbers = [str(slot) for slot in sorted(self.slots) if self.slots[slot] == state]
            if numbers:
                parts.append(f'{label}: {", ".join(numbers)}')
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
            # A duplicate is a successful no-op, not a failed restart. Keep the
            # original worker's progress/log intact and do not take over a pane.
            notify('Restart already in progress; see the top status area.', client)
            return 0
        # A reader thread lets the main thread refresh progress while a busy
        # agent is silent, without blocking terminal input or the status monitor.
        import queue
        import threading
        messages = queue.Queue()
        progress = Progress()
        latest = 'Checking all ten sessions; busy sessions will wait for idle…'
        publish(latest)
        try:
            with (STATE / 'restart.log').open('w') as log:
                process = subprocess.Popen(load().restart(), env=clean_environment(),
                                           stdin=subprocess.DEVNULL,
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
                while True:
                    try:
                        message = messages.get(timeout=5)
                    except queue.Empty:
                        message = latest
                    if message is None:
                        break
                    progress.update(message)
                    latest = progress.summary() or message
                    publish(latest)
                result = process.wait()
                reader.join()
                process.stdout.close()
            publish('Complete — all sessions ready.' if result == 0 else
                    f'Failed (exit {result}); {latest} — see ~/.local/state/pi-desk/restart.log')
            return result
        except (OSError, ValueError) as exc:
            publish(f'Failed: {exc}')
            return 1
