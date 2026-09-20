#!/usr/bin/env python3
"""Private local wake worker: isolated stream state, shared ONNX weights, room lease.

Existing capture/playback clients remain separate to preserve device routing.
No audio is written to disk. Socket failure is fail-closed (never local fallback).
"""
from __future__ import annotations

import base64
from collections import deque
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import socketserver
import threading
import time

MAX_MESSAGE = 65536


@contextmanager
def shared_onnx_sessions():
    """Only used during serial model construction in this dedicated worker.

    ONNX sessions contain weights, not openWakeWord's stream history. Models and
    AudioFeatures retain independent Python buffers. Restore the factory on exit.
    """
    import onnxruntime as ort
    original = ort.InferenceSession
    cache = {}

    def create(path, sess_options=None, providers=None, **kwargs):
        key = (str(path), repr(providers), repr(kwargs))
        if key not in cache:
            options = sess_options or ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.add_session_config_entry('session.intra_op.allow_spinning', '0')
            options.add_session_config_entry('session.inter_op.allow_spinning', '0')
            cache[key] = original(path, sess_options=options, providers=providers, **kwargs)
        return cache[key]

    ort.InferenceSession = create
    try:
        yield cache
    finally:
        ort.InferenceSession = original


class QuietGate:
    def __init__(self, detector, threshold=120, preroll_seconds=0.4, hangover=1.0):
        self.detector = detector
        self.threshold = threshold
        self.preroll_seconds = preroll_seconds
        self.hangover = hangover
        self.pending = deque()
        self.pending_seconds = 0.0
        self.active_until = 0.0
        self.active = False

    def reset(self):
        self.pending.clear()
        self.pending_seconds = 0.0
        self.active_until = 0.0
        self.active = False
        self.detector.reset_stream()

    def process(self, frame, rate, now):
        from pi_room_audio_client import pcm_rms_s16le_mono
        if pcm_rms_s16le_mono(frame) >= self.threshold:
            self.active_until = now + self.hangover
        if now >= self.active_until:
            if self.active:
                self.reset()
            self.pending.append(frame)
            self.pending_seconds += len(frame) / (2 * rate)
            while self.pending and self.pending_seconds > self.preroll_seconds:
                self.pending_seconds -= len(self.pending.popleft()) / (2 * rate)
            return None
        self.active = True
        # Replay buffered context once; preserve normal inference cadence within it.
        hit = None
        while self.pending:
            hit = self.detector.process_frame(self.pending.popleft(), source_rate=rate, now=now) or hit
        self.pending_seconds = 0.0
        return self.detector.process_frame(frame, source_rate=rate, now=now) or hit


class Coordinator:
    def __init__(self, detectors, *, threshold=120, lease_seconds=8.0, clock=time.monotonic):
        self.rooms = {room: QuietGate(detector, threshold) for room, detector in detectors.items()}
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.owner = None
        self.deadline = 0.0
        self.lock = threading.Lock()

    def handle(self, request):
        with self.lock:  # A single inference lane, including resets and lease changes.
            room = request['room']
            if room not in self.rooms:
                raise ValueError('unknown room')
            now = self.clock()
            if self.owner is not None and now >= self.deadline:
                self.owner = None
                for gate in self.rooms.values():
                    gate.reset()
            gate = self.rooms[room]
            op = request['op']
            allowed = self.owner in (None, room)
            hit = None
            if op == 'reset':
                gate.reset()
            elif op == 'activity':
                if allowed and request.get('active'):
                    # Recover an existing conversation after a worker restart or
                    # stalled heartbeat, before allowing another room to wake.
                    if self.owner is None:
                        for other, other_gate in self.rooms.items():
                            if other != room:
                                other_gate.reset()
                    self.owner = room
                    self.deadline = now + self.lease_seconds
            elif op == 'frame':
                rate = request['rate']
                if rate not in (8000, 16000, 24000, 32000, 44100, 48000):
                    raise ValueError('unsupported sample rate')
                frame = base64.b64decode(request['pcm'], validate=True)
                if len(frame) % 2 or len(frame) > rate * 2:
                    raise ValueError('invalid PCM frame')
                if allowed:
                    hit = gate.process(frame, rate, now)
                    if hit:
                        self.owner = room
                        self.deadline = now + self.lease_seconds
                        for other, other_gate in self.rooms.items():
                            if other != room:
                                other_gate.reset()
            else:
                raise ValueError('unknown operation')
            detector = gate.detector
            return {'allowed': allowed, 'hit': hit, 'owner': self.owner,
                    'last_score': detector.last_score, 'last_model': detector.last_model}


class RemoteWakeDetector:
    """Adapter matching the existing detector API; persistent bounded local RPC."""
    def __init__(self, path, room):
        self.path, self.room = path, room
        self.socket = None
        self.file = None
        self.allowed = False
        self.last_score = self.max_score = 0.0
        self.last_model = self.max_model = ''
        self._activity_at = 0.0
        self._active = None

    def close(self):
        if self.file is not None:
            self.file.close()
        if self.socket is not None:
            self.socket.close()
        self.file = self.socket = None
        self.allowed = False

    def rpc(self, op, **values):
        try:
            if self.socket is None:
                self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.socket.settimeout(2.0)
                self.socket.connect(self.path)
                self.file = self.socket.makefile('rwb')
            self.file.write(json.dumps(dict(room=self.room, op=op, **values)).encode() + b'\n')
            self.file.flush()
            line = self.file.readline(MAX_MESSAGE + 1)
            if not line or len(line) > MAX_MESSAGE:
                raise RuntimeError('shared wake worker disconnected')
            result = json.loads(line)
            if 'error' in result:
                raise RuntimeError(result['error'])
            self.allowed = bool(result['allowed'])
            self.last_score = result['last_score']
            self.last_model = result['last_model']
            if self.last_score > self.max_score:
                self.max_score, self.max_model = self.last_score, self.last_model
            return result
        except Exception:
            self.close()
            raise

    def update_activity(self, active, now):
        if active != self._active or now - self._activity_at >= 0.5:
            self.rpc('activity', active=bool(active))
            self._activity_at, self._active = now, active

    def reset_stream(self):
        self.rpc('reset')
        self.last_score = self.max_score = 0.0
        self.last_model = self.max_model = ''

    def process_frame(self, frame, *, source_rate, now):
        return self.rpc('frame', rate=source_rate, pcm=base64.b64encode(frame).decode())['hit']


class WakeServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        try:
            while True:
                line = self.rfile.readline(MAX_MESSAGE + 1)
                if not line or len(line) > MAX_MESSAGE:
                    return
                try:
                    result = self.server.coordinator.handle(json.loads(line))
                except (ValueError, KeyError, TypeError):
                    result = {'error': 'invalid wake request'}
                self.wfile.write(json.dumps(result).encode() + b'\n')
                self.wfile.flush()
        except (OSError, TimeoutError):
            return


def main():
    import argparse
    import fcntl
    from pi_room_audio_client import build_parser, LocalWakeWordDetector
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--rooms', nargs='+', default=['powerconf', 'camera'])
    parser.add_argument('--silence-threshold', type=int, default=120)
    options = parser.parse_args()
    path = Path(options.socket).expanduser()
    os.umask(0o077)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077:
        raise RuntimeError('wake socket directory must be owner-only')
    # Hold an exclusive lock before unlinking a stale socket.
    with open(str(path) + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        args = build_parser().parse_args(['--local-wake-word', '--openwakeword-inference', 'onnx',
            '--openwakeword-ncpu', '1', '--no-openwakeword-auto-download',
            '--local-wake-word-threshold', '0.75'])
        with shared_onnx_sessions() as sessions:
            detectors = {room: LocalWakeWordDetector(args) for room in options.rooms}
        path.unlink(missing_ok=True)
        with WakeServer(str(path), Handler) as server:
            server.coordinator = Coordinator(detectors, threshold=options.silence_threshold)
            print(f'Shared wake ready: rooms={options.rooms} ONNX_sessions={len(sessions)} '
                  f'silence_threshold={options.silence_threshold}', flush=True)
            try:
                server.serve_forever()
            finally:
                path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
