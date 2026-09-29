"""Silent, bounded, per-turn Piper pre-rendering; no playback or phrase cache.

Candidate audio is never returned to a consumer. commit() accepts only the
completed agent answer and transfers WAVs matching its canonical speech text.
"""
from __future__ import annotations

from pathlib import Path
import re
import threading
import time
from typing import Callable

from voice_pipeline import _bounded_tts_chunks, _tts_segment_dedupe_key

_BOUNDARY = re.compile(r'(?<=[.!?])\s+')
_ABBREVIATION = re.compile(r'(?:\b(?:mr|mrs|ms|dr|prof|st|vs|etc)\.|(?:\b[A-Za-z]\.)+)$', re.I)


class RoomTTSPrerenderCancelled(RuntimeError):
    pass


def speech_segments(pipeline, text: str, *, final: bool) -> list[str]:
    """Use the same canonical cleaning for speculation and final verification."""
    cleaned = pipeline._clean_text_for_tts(pipeline._clean_reply_text(text))
    sentences = []
    start = 0
    for boundary in _BOUNDARY.finditer(cleaned):
        part = cleaned[start:boundary.start()].strip()
        if _ABBREVIATION.search(part):
            continue
        sentences.append(part)
        start = boundary.end()
    tail = cleaned[start:].strip()
    if tail and (final or (tail.endswith(('.', '!', '?')) and
                          not _ABBREVIATION.search(tail) and not re.search(r'\d\.$', tail))):
        sentences.append(tail)
    segments = []
    seen = set()
    for sentence in sentences:
        for segment in _bounded_tts_chunks(sentence, pipeline.config.max_tts_chars_per_segment):
            key = _tts_segment_dedupe_key(segment)
            if segment and (not key or key not in seen):
                segments.append(segment)
                if key:
                    seen.add(key)
    limit = pipeline.config.max_tts_segments
    return segments if limit <= 0 else segments[:limit]


def _delete(paths) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


class RoomTTSPrerender:
    def __init__(self, pipeline, *, cancel_event: threading.Event | None = None,
                 check_cancelled: Callable[[], None] = lambda: None,
                 max_chars: int = 8192, max_segments: int = 16, max_bytes: int = 8 * 1024 * 1024):
        self.pipeline = pipeline
        self._settings = pipeline.config  # VoicePipelineConfig is immutable.
        self.cancel_event = cancel_event or threading.Event()
        self.check_cancelled = check_cancelled
        self.max_chars = max_chars
        self.max_segments = max_segments
        self.max_bytes = max_bytes
        self._condition = threading.Condition()
        self._candidate = 0
        self._candidate_open = False
        self._epoch = 0
        self._raw = ''
        self._wanted: list[str] = []
        self._prepared: dict[str, Path] = {}
        self._attempted = set()
        self._inflight = None
        self._bytes = 0
        self._attempts = 0
        self._closed = False
        self._committing = False
        self._final_keys = set()
        self._thread: threading.Thread | None = None
        self._stats = {'renderedSegments': 0, 'reusedSegments': 0, 'discardedSegments': 0,
                       'renderSeconds': 0.0}

    def on_candidate(self, event: dict) -> None:
        """Nonblocking with respect to inference; never publishes audio."""
        candidate = event.get('candidate')
        kind = event.get('type')
        if type(candidate) is not int or candidate <= 0:
            return
        garbage = []
        with self._condition:
            if self._closed or self._committing or self.cancel_event.is_set():
                return
            if kind == 'candidate_start':
                if candidate <= self._candidate:
                    return
                self._candidate = candidate
                self._candidate_open = True
                self._epoch += 1
                self._raw = ''
                self._wanted = []
                garbage = list(self._prepared.values())
                self._stats['discardedSegments'] += len(garbage)
                self._prepared.clear()
                self._bytes = 0
            elif candidate != self._candidate:
                return
            elif kind == 'candidate_invalidate':
                self._candidate_open = False
                self._epoch += 1
                self._raw = ''
                self._wanted = []
                garbage = list(self._prepared.values())
                self._stats['discardedSegments'] += len(garbage)
                self._prepared.clear()
                self._bytes = 0
            elif kind in {'candidate_delta', 'candidate_end'}:
                if not self._candidate_open:
                    return
                if kind == 'candidate_end':
                    self._candidate_open = False
                value = event.get('delta' if kind == 'candidate_delta' else 'text')
                if not isinstance(value, str):
                    return
                text = self._raw + value if kind == 'candidate_delta' else value
                self._raw = text[:self.max_chars]
                self._wanted = speech_segments(self.pipeline, self._raw,
                    final=kind == 'candidate_end' and len(text) <= self.max_chars)[:self.max_segments]
            else:
                return
            if self._thread is None:
                self._thread = threading.Thread(target=self._render, name='jarvis-room-tts-prerender', daemon=True)
                self._thread.start()
            self._condition.notify_all()
        _delete(garbage)

    def _next(self):
        if self._attempts >= self.max_segments or self._bytes >= self.max_bytes:
            return None
        return next((text for text in self._wanted if (self._epoch, text) not in self._attempted), None)

    def _render(self) -> None:
        while True:
            with self._condition:
                while not self._closed and not self._committing and not self.cancel_event.is_set() and self._next() is None:
                    self._condition.wait(.05)
                if self.cancel_event.is_set():
                    self.close()
                    return
                if self._closed or self._committing:
                    return
                text = self._next()
                epoch = self._epoch
                self._attempted.add((epoch, text))
                self._attempts += 1
                self._inflight = (epoch, text)
            path = None
            started = time.monotonic()
            try:
                path = self.pipeline._synthesize_segment(text)
                size = path.stat().st_size
            except Exception:
                # A speculative failure is not a failed answer. The ordinary
                # final renderer will retry this exact segment if necessary.
                size = 0
            with self._condition:
                self._stats['renderSeconds'] += time.monotonic() - started
                valid = (path is not None and size > 44 and not self._closed and
                         not self.cancel_event.is_set() and epoch == self._epoch and
                         text in (self._final_keys if self._committing else self._wanted) and
                         self._bytes + size <= self.max_bytes)
                if valid:
                    self._prepared[text] = path
                    self._bytes += size
                    self._stats['renderedSegments'] += 1
                    path = None
                elif path is not None:
                    self._stats['discardedSegments'] += 1
                self._inflight = None
                self._condition.notify_all()
            if path is not None:
                _delete([path])

    def _check_cancelled(self) -> None:
        self.check_cancelled()
        if self.cancel_event.is_set():
            raise RoomTTSPrerenderCancelled('Room TTS pre-render was cancelled.')

    def commit(self, final_text: str) -> list[Path]:
        """Called only AFTER the successful agent turn returns its final text."""
        segments = speech_segments(self.pipeline, final_text, final=True)
        output = []
        try:
            self._check_cancelled()
            garbage = []
            with self._condition:
                if self._closed:
                    raise RoomTTSPrerenderCancelled('Room TTS pre-render is closed.')
                if self.pipeline.config != self._settings:
                    # Settings changed mid-turn: never reuse the old voice/prosody.
                    self._epoch += 1
                    garbage = list(self._prepared.values())
                    self._stats['discardedSegments'] += len(garbage)
                    self._prepared.clear()
                    self._bytes = 0
                self._committing = True
                self._final_keys = set(segments)
                self._condition.notify_all()
                deadline = time.monotonic() + self.pipeline.config.tts_timeout_seconds
                # Wait only for useful current-candidate work already in flight.
                while (self._inflight is not None and self._inflight[0] == self._epoch and
                       self._inflight[1] in self._final_keys and not self._closed):
                    self._check_cancelled()
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Room TTS pre-render did not finish in time')
                    self._condition.wait(.05)
            _delete(garbage)
            for segment in segments:
                self._check_cancelled()
                with self._condition:
                    path = self._prepared.pop(segment, None)
                    if path is not None:
                        self._bytes -= path.stat().st_size
                        self._stats['reusedSegments'] += 1
                if path is None:
                    path = self.pipeline._synthesize_segment(segment)
                output.append(path)
                self._check_cancelled()
            return output
        except BaseException:
            _delete(output)
            raise
        finally:
            self.close()

    def stats(self) -> dict:
        with self._condition:
            return {**self._stats, 'renderSeconds': round(self._stats['renderSeconds'], 4)}

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._wanted = []
            garbage = list(self._prepared.values())
            self._stats['discardedSegments'] += len(garbage)
            self._prepared.clear()
            self._bytes = 0
            self._condition.notify_all()
        _delete(garbage)
        # Never wait for an uncancellable inference on a cancelled/disconnected
        # turn. Its worker checks _closed and deletes its eventual output.
