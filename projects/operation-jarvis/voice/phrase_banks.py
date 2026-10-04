"""Offline announcement assets and durable, cross-process shuffled bags.

No synthesis, networking, playback, or service startup. Activation requires an
explicit reviewed manifest hash. Defaults remain in voice_lines.py.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import stat
import tempfile
import time
import wave

ROOT = Path.home() / 'Library/Application Support/JARVIS/phrase-banks'
CATALOGUE = Path(__file__).with_name('phrase_catalogue.json')
COUNTS = {'wake': 24, 'processing': 24, 'arrival': 12, 'departure': 24}
SETTINGS = ('tts_backend', 'tts_speed', 'tts_piper_repo_id', 'tts_piper_quality',
            'tts_piper_length_scale', 'tts_piper_volume', 'tts_piper_noise_scale',
            'tts_piper_noise_w_scale')


class BankError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def voice_settings(config):
    return {key: getattr(config, key) for key in SETTINGS}


def catalogue():
    value = json.loads(CATALOGUE.read_bytes())
    rows = value['phrases']
    if value['version'] != 1 or len({row['id'] for row in rows}) != 84:
        raise BankError('invalid_catalogue')
    for event, count in COUNTS.items():
        bank = [row for row in rows if row['event'] == event]
        if (len(bank) != count or len({row['text'] for row in bank}) != count
                or any(sum(row['style'] == style for row in bank) != count // 2
                       for style in ('straight', 'dry'))):
            raise BankError('invalid_bank_balance')
    return rows


def private_dir(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise BankError('private_directory_required')
    return path


def read_private(path, limit=2 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > limit):
            raise BankError('invalid_private_asset')
        data = source.read(limit + 1)
    if len(data) > limit:
        raise BankError('asset_too_large')
    return data


def wav_info(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as wav:
            channels, width, rate, frames, compression, _ = wav.getparams()
            pcm = wav.readframes(frames)
        if (channels != 1 or width != 2 or rate not in (16000, 22050, 24000, 44100, 48000)
                or compression != 'NONE' or not 0 < frames / rate <= 15
                or len(pcm) != frames * channels * width):
            raise BankError('invalid_wav')
        return {'seconds': frames / rate, 'rate': rate, 'channels': channels, 'width': width}
    except (EOFError, wave.Error, ZeroDivisionError) as exc:
        raise BankError('invalid_wav') from exc


def padded(data, milliseconds):
    if milliseconds == 0:
        return data
    with wave.open(io.BytesIO(data), 'rb') as source:
        params = source.getparams()
        pcm = source.readframes(source.getnframes())
    target = io.BytesIO()
    with wave.open(target, 'wb') as out:
        out.setparams(params)
        out.writeframes(b'\0' * (int(params.framerate * milliseconds / 1000)
                                * params.nchannels * params.sampwidth) + pcm)
    return target.getvalue()


@dataclass(frozen=True)
class Clip:
    id: str
    event: str
    text: str
    audio: bytes
    sha256: str

    def temporary(self):
        """Caller owns this disposable copy, never the validated master."""
        fd, name = tempfile.mkstemp(prefix='jarvis-phrase-', suffix='.wav')
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(self.audio)
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
        return Path(name)


class Bundle:
    def __init__(self, directory, manifest_sha256, *, expected_settings=None,
                 events=tuple(COUNTS)):
        self.root = private_dir(directory)
        raw = read_private(self.root / 'manifest.json')
        if not manifest_sha256 or digest(raw) != manifest_sha256:
            raise BankError('manifest_hash_mismatch')
        manifest = json.loads(raw)
        rows = catalogue()
        if (manifest.get('version') != 1 or manifest.get('reviewed') is not True
                or manifest.get('catalogue_sha256') != digest(encoded(rows))
                or manifest.get('settings_sha256') != digest(encoded(manifest.get('settings')))
                or (expected_settings is not None and manifest.get('settings') != expected_settings)):
            raise BankError('unreviewed_or_incompatible_bundle')
        entries = manifest['recordings']
        if set(entries) != {row['id'] for row in rows}:
            raise BankError('incomplete_bundle')
        self.clips = {}
        self.ids = {}
        for row in rows:
            if row['event'] not in events:
                continue
            entry = entries[row['id']]
            if entry.get('text') != row['text'] or entry.get('file') != row['id'] + '.wav':
                raise BankError('recording_catalogue_mismatch')
            data = read_private(self.root / entry['file'], 1024 * 1024)
            info = wav_info(data)
            limit = manifest['limits_seconds'][row['event']]
            if (type(limit) not in (float, int) or not math.isfinite(limit) or not 0 < limit <= 15
                    or info != entry.get('audio') or digest(data) != entry.get('sha256')
                    or entry.get('quality', {}).get('clipped_samples') != 0
                    or info['seconds'] > limit
                    or (row['event'] == 'departure' and info['seconds'] > 4.5)):
                raise BankError('recording_validation_failed')
            self.clips[row['id']] = Clip(row['id'], row['event'], row['text'], data, digest(data))
            self.ids.setdefault(row['event'], []).append(row['id'])
        self.catalogue_hash = manifest['catalogue_sha256']
        self.manifest_hash = manifest_sha256

    def default(self, event):
        return self.clips[f'{event}-straight-01']


class Selector:
    """Reserve once, before dispatch. Duplicate keys suppress, never replay.

    A 25 ms SQLite busy bound avoids unbounded lock waits (not a total I/O
    latency guarantee). Failed reservations suppress announcements; no retry
    is performed here. The original defaults remain available for rollback.
    """
    def __init__(self, path=ROOT / 'selection.sqlite3'):
        self.path = Path(path)
        private_dir(self.path.parent)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        read_private(self.path, 64 * 1024 * 1024)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS bags (
                    event TEXT PRIMARY KEY, catalogue TEXT NOT NULL,
                    remaining TEXT NOT NULL, last TEXT);
                CREATE TABLE IF NOT EXISTS claims (
                    event TEXT NOT NULL, key TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(event, key));
            ''')

    @contextmanager
    def _connect(self):
        # The DB and sidecars live in a verified owner-only directory.
        db = sqlite3.connect(self.path, timeout=0.025)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, bundle, event, key):
        if event not in bundle.ids or not isinstance(key, str) or not 0 < len(key) <= 256:
            raise BankError('invalid_reservation')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM claims WHERE event=? AND key=?', (event, key)).fetchone():
                return None
            row = db.execute('SELECT catalogue, remaining, last FROM bags WHERE event=?', (event,)).fetchone()
            remaining, last = [], None
            if row:
                if row[0] != bundle.catalogue_hash:
                    raise BankError('catalogue_changed_requires_review')
                remaining, last = json.loads(row[1]), row[2]
                if (not isinstance(remaining, list) or len(set(remaining)) != len(remaining)
                        or any(item not in bundle.ids[event] for item in remaining)
                        or last not in bundle.ids[event]):
                    raise BankError('invalid_selection_state')
            if not remaining:
                remaining = list(bundle.ids[event])
                random.SystemRandom().shuffle(remaining)
                if len(remaining) > 1 and remaining[0] == last:
                    remaining[0], remaining[1] = remaining[1], remaining[0]
            chosen = remaining.pop(0)
            db.execute('INSERT OR REPLACE INTO bags VALUES (?, ?, ?, ?)',
                       (event, bundle.catalogue_hash, json.dumps(remaining), chosen))
            db.execute('INSERT INTO claims VALUES (?, ?, ?)', (event, key, time.time()))
            # Request keys are single-use random IDs, never reused intentionally.
            db.execute('DELETE FROM claims WHERE created < ?', (time.time() - 7 * 86400,))
        return bundle.clips[chosen]


class RoomBanks:
    def __init__(self, bundle, selector, *, wake_padding=450, padding=450):
        import base64
        self.bundle, self.selector = bundle, selector
        self.audio = {key: base64.b64encode(padded(clip.audio,
            wake_padding if clip.event == 'wake' else padding)).decode('ascii')
            for key, clip in bundle.clips.items()}
        self.failures = 0

    def choose(self, event, key):
        try:
            return self.selector.reserve(self.bundle, event, key)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            self.failures += 1
            # Storage uncertainty cannot establish whether this key was used.
            # Silence is safer than replaying a default or synthesizing live.
            return None

    def status(self):
        return {'enabled': True, 'manifestSha256': self.bundle.manifest_hash,
                'counts': {event: len(ids) for event, ids in self.bundle.ids.items()},
                'selectionFailures': self.failures}


def room_banks_from_env(config, *, wake_padding=450, padding=450):
    directory = os.environ.get('JARVIS_ROOM_PHRASE_BANK_DIR', '').strip()
    if not directory:
        return None
    bundle = Bundle(directory, os.environ.get('JARVIS_ROOM_PHRASE_BANK_SHA256', ''),
                    expected_settings=voice_settings(config), events=('wake', 'processing', 'arrival'))
    return RoomBanks(bundle, Selector(), wake_padding=wake_padding, padding=padding)
