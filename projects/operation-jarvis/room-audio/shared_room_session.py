"""Voice adapter for the real, interactive mobile Pi Session 10.

Both audio servers use this single owner. No RPC subprocess, idle reset, queue,
reconnect, prompt replay or fallback to separate conversations.
"""
import json
import os
from pathlib import Path
import socket
import stat
import threading
import time
import uuid


class SharedRoomSession:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._active = None
        self._lock = threading.Lock()

    def _descriptor(self):
        directory = self.root / '.pi/runtime/room-audio-session'
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('Private room session unavailable')
        path = directory / 'owner.json'
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096:
                raise RuntimeError('Private room descriptor unavailable')
            data = json.loads(os.read(fd, 4097))
        finally:
            os.close(fd)
        if data.get('version') != 1 or data.get('sessionID') != 10 or type(data.get('pid')) is not int:
            raise RuntimeError('Wrong room session')
        os.kill(data['pid'], 0)
        target = Path(data['socketPath'])
        if target.parent != directory or target.name != f"room-{data['pid']}.sock":
            raise RuntimeError('Wrong room socket')
        info = target.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeError('Private room socket unavailable')
        return data

    def exchange(self, action, *, timeout=3, **values):
        deadline = time.monotonic() + timeout
        descriptor = self._descriptor()
        payload = {'version': 1, 'generation': descriptor['generation'], 'action': action, **values}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(max(.01, deadline - time.monotonic()))
            connection.connect(descriptor['socketPath'])
            connection.sendall(json.dumps(payload, ensure_ascii=False).encode() + b'\n')
            raw = bytearray()
            while not raw.endswith(b'\n'):
                left = deadline - time.monotonic()
                if left <= 0 or len(raw) > 1_048_576:
                    raise RuntimeError('Room response unavailable; never replay')
                connection.settimeout(left)
                chunk = connection.recv(8192)
                if not chunk: raise RuntimeError('Room response lost; never replay')
                raw.extend(chunk)
            reply = json.loads(raw)
            if type(reply) is not dict or type(reply.get('ok')) is not bool:
                raise RuntimeError('Invalid room response; never replay')
            return reply

    def run_prompt(self, prompt, *, on_event=None, timeout_seconds=1800, **kwargs):
        request_id = uuid.uuid4().hex
        with self._lock:
            if self._active is not None: raise RuntimeError('Room conversation busy')
            self._active = request_id
        try:
            reply = self.exchange('prompt', id=request_id, text=prompt, timeout=timeout_seconds)
            if reply.get('ok') is not True or reply.get('requestID') != request_id:
                raise RuntimeError('Room conversation busy, cancelled or unknown; never replay automatically')
            if on_event:
                on_event({'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': reply.get('text', '')}})
        finally:
            with self._lock: self._active = None

    def abort_active(self):
        with self._lock: request_id = self._active
        if request_id is None: return False
        return self.exchange('abort', id=request_id).get('ok') is True

    def stop(self):
        # Closing a speaker server never terminates the shared interactive Pi.
        try: self.abort_active()
        except Exception: pass

    def seconds_since_last_activity(self): return None
    def start_new_session_if_idle(self, *args, **kwargs): return False
