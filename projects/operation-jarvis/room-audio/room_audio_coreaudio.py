#!/usr/bin/env python3
"""Explicit-device Core Audio subprocess adapter; never changes system defaults.

Capture emits mono s16le PCM on stdout, like arecord. Playback accepts PCM WAV,
resamples to the device rate and duplicates mono for stereo USB speakers. Each
operation initializes PortAudio afresh, so hotplug cannot reuse stale indices.
No audio is retained except an explicitly requested diagnostic recording.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from pathlib import Path


def resolve_device(sd, name: str, direction: str) -> tuple[int, dict]:
    """Require one exact Core Audio endpoint; missing/ambiguous means fail closed."""
    if not name.strip():
        raise ValueError("An explicit audio device name is required")
    key = f"max_{direction}_channels"
    hosts = sd.query_hostapis()
    matches = [(i, d) for i, d in enumerate(sd.query_devices())
               if d['name'] == name and d[key] > 0
               and hosts[d['hostapi']]['name'] == 'Core Audio']
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one Core Audio {direction} device named {name!r}; found {len(matches)}")
    return matches[0]


def capture(sd, device: str, rate: int, *, path: Path | None = None, seconds: float = 0) -> None:
    index, _ = resolve_device(sd, device, 'input')
    sd.check_input_settings(device=index, channels=1, dtype='int16', samplerate=rate)
    block = max(1, rate // 50)  # 20 ms; same framing as the VAD reader.
    output = wave.open(str(path), 'wb') if path else None
    if output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
    remaining = max(1, round(seconds * rate)) if path else None
    try:
        # 100 ms headroom tolerates Python/ONNX scheduling jitter without
        # dropping PCM. Framing stays 20 ms; the watchdog still bounds stalls.
        with sd.RawInputStream(device=index, samplerate=rate, channels=1,
                               dtype='int16', blocksize=block, latency=0.1) as stream:
            while remaining is None or remaining > 0:
                count = block if remaining is None else min(block, remaining)
                pcm, overflowed = stream.read(count)
                if overflowed:
                    raise RuntimeError('Core Audio capture overflow; restart with a clean wake stream')
                if output:
                    output.writeframesraw(bytes(pcm))
                else:
                    sys.stdout.buffer.write(pcm)
                    sys.stdout.buffer.flush()
                if remaining is not None:
                    remaining -= count
    finally:
        if output:
            output.close()


def convert_pcm(pcm: bytes, channels: int, rate: int, target_channels: int, target_rate: int):
    import numpy as np
    from scipy.signal import resample_poly

    samples = np.frombuffer(pcm, dtype='<i2').reshape(-1, channels).astype(np.float32)
    if channels != target_channels:
        if channels == 1:
            samples = np.repeat(samples, target_channels, axis=1)
        elif target_channels == 1:
            samples = samples.mean(axis=1, keepdims=True)
        else:
            raise ValueError('Unsupported WAV channel conversion')
    if rate != target_rate and len(samples):
        divisor = math.gcd(rate, target_rate)
        samples = resample_poly(samples, target_rate // divisor, rate // divisor, axis=0)
    return np.ascontiguousarray(np.clip(np.rint(samples), -32768, 32767), dtype='<i2')


def playback(sd, device: str, path: Path) -> None:
    index, info = resolve_device(sd, device, 'output')
    target_rate = int(info['default_samplerate'])
    target_channels = min(2, int(info['max_output_channels']))
    with wave.open(str(path), 'rb') as source:
        if source.getsampwidth() != 2 or source.getnchannels() not in (1, 2):
            raise ValueError('Playback requires mono/stereo 16-bit PCM WAV')
        samples = convert_pcm(source.readframes(source.getnframes()), source.getnchannels(),
                              source.getframerate(), target_channels, target_rate)
    sd.check_output_settings(device=index, channels=target_channels,
                             dtype='int16', samplerate=target_rate)
    # Bounded buffering gives the parent PlaybackController responsive SIGTERM stop.
    block = max(1, target_rate // 50)
    with sd.RawOutputStream(device=index, samplerate=target_rate, channels=target_channels,
                            dtype='int16', blocksize=block, latency=0.04) as stream:
        for offset in range(0, len(samples), block):
            stream.write(samples[offset:offset + block].tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['list', 'capture', 'record', 'playback'])
    parser.add_argument('--device', default='PowerConf')
    parser.add_argument('--rate', type=int, default=48000)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--path', type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This adapter requires macOS')
    if args.rate <= 0 or args.seconds <= 0:
        parser.error('rate and seconds must be positive')
    if args.operation in ('record', 'playback') and args.path is None:
        parser.error('--path is required')
    import sounddevice as sd
    if args.operation == 'list':
        print(json.dumps(list(sd.query_devices()), indent=2))
    elif args.operation == 'playback':
        playback(sd, args.device, args.path)
    else:
        capture(sd, args.device, args.rate,
                path=args.path if args.operation == 'record' else None, seconds=args.seconds)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        raise SystemExit(0)
    except Exception as exc:
        print(f'Core Audio: {exc}', file=sys.stderr, flush=True)
        raise SystemExit(1)
