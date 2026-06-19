#!/usr/bin/env python3
"""Raspberry Pi room-audio client for Operation JARVIS.

Supports both fixed-window diagnostics and the production Discord-style VAD
listener. The Pi captures room audio from the Anker PowerConf, reconnects the
trusted Bluetooth speakerphone when needed, sends accepted utterances to the
Mac-side room_audio_server.py, plays the immediate processing acknowledgement,
then polls and plays the final JARVIS WAV response. The VAD listener can also
play a contextual JARVIS greeting after startup or Bluetooth/capture recovery.
"""

from __future__ import annotations

import argparse
import array
try:
    import audioop
except Exception:  # Python 3.13 removes audioop; only local wake-word resampling needs it.
    audioop = None  # type: ignore[assignment]
import base64
import json
import math
import os
import select
import subprocess
import sys
import tempfile
import time
from collections import deque
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

DEFAULT_SERVER_URL = os.environ.get("JARVIS_ROOM_AUDIO_SERVER_URL", "http://127.0.0.1:8791").rstrip("/")
DEFAULT_AUDIO_DEVICE = os.environ.get("JARVIS_ROOM_AUDIO_DEVICE", "plughw:CARD=PowerConf,DEV=0")
DEFAULT_PLAYBACK_DEVICE = os.environ.get("JARVIS_ROOM_AUDIO_PLAYBACK_DEVICE")
DEFAULT_RECORD_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_RECORD_SECONDS", "5"))
DEFAULT_RATE = int(os.environ.get("JARVIS_ROOM_AUDIO_RATE", "48000"))
DEFAULT_ASYNC_ACK = os.environ.get("JARVIS_ROOM_AUDIO_ASYNC_ACK", "0").lower() not in {"0", "false", "no", "off", ""}
# Keep these segmentation defaults aligned with ../../voice/discord_voice.py.
DEFAULT_VAD_RMS_THRESHOLD = int(os.environ.get("JARVIS_ROOM_AUDIO_VAD_RMS_THRESHOLD", "300"))
DEFAULT_VAD_SILENCE_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_VAD_SILENCE_SECONDS", "1.0"))
DEFAULT_VAD_MIN_UTTERANCE_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_VAD_MIN_UTTERANCE_SECONDS", "0.5"))
DEFAULT_VAD_MAX_UTTERANCE_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_VAD_MAX_UTTERANCE_SECONDS", "30"))
DEFAULT_VAD_PREROLL_MS = int(os.environ.get("JARVIS_ROOM_AUDIO_VAD_PREROLL_MS", "500"))
DEFAULT_VAD_MIN_VOICED_MS = int(os.environ.get("JARVIS_ROOM_AUDIO_VAD_MIN_VOICED_MS", "200"))
DEFAULT_VAD_FRAME_MS = int(os.environ.get("JARVIS_ROOM_AUDIO_VAD_FRAME_MS", "20"))
DEFAULT_CAPTURE_READ_TIMEOUT_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_CAPTURE_READ_TIMEOUT_SECONDS", "5"))
DEFAULT_VAD_RELEASE_CAPTURE_DURING_TURN = os.environ.get(
    "JARVIS_ROOM_AUDIO_VAD_RELEASE_CAPTURE_DURING_TURN",
    "0",
).lower() not in {"0", "false", "no", "off", ""}
DEFAULT_VAD_RESTORE_CAPTURE_WHILE_WAITING = os.environ.get(
    "JARVIS_ROOM_AUDIO_VAD_RESTORE_CAPTURE_WHILE_WAITING",
    "0",
).lower() not in {"0", "false", "no", "off", ""}
DEFAULT_LOCAL_WAKE_WORD_ENABLED = os.environ.get("JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ENABLED", "0").lower() not in {"0", "false", "no", "off", ""}
DEFAULT_LOCAL_WAKE_WORD_ENGINE = os.environ.get("JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ENGINE", "openwakeword").strip()
DEFAULT_LOCAL_WAKE_WORD_THRESHOLD = float(os.environ.get("JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_THRESHOLD", "0.5"))
DEFAULT_LOCAL_WAKE_WORD_COOLDOWN_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_COOLDOWN_SECONDS", "2.0"))
DEFAULT_LOCAL_WAKE_WORD_ARM_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_ARM_SECONDS", "8.0"))
DEFAULT_LOCAL_WAKE_WORD_CHUNK_MS = int(os.environ.get("JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_CHUNK_MS", "80"))
DEFAULT_LOCAL_WAKE_WORD_MODEL = os.environ.get("JARVIS_ROOM_AUDIO_OPENWAKEWORD_MODEL", "hey_jarvis").strip()
DEFAULT_LOCAL_WAKE_WORD_INFERENCE = os.environ.get("JARVIS_ROOM_AUDIO_OPENWAKEWORD_INFERENCE", "tflite").strip()
DEFAULT_LOCAL_WAKE_WORD_NCPU = max(1, int(os.environ.get("JARVIS_ROOM_AUDIO_OPENWAKEWORD_NCPU", "2")))
DEFAULT_LOCAL_WAKE_WORD_MODEL_DIR = os.environ.get("JARVIS_ROOM_AUDIO_OPENWAKEWORD_MODEL_DIR", "").strip()
DEFAULT_LOCAL_WAKE_WORD_AUTO_DOWNLOAD = os.environ.get("JARVIS_ROOM_AUDIO_OPENWAKEWORD_AUTO_DOWNLOAD", "1").lower() not in {"0", "false", "no", "off", ""}
DEFAULT_LOCAL_WAKE_WORD_LOG_SCORES = os.environ.get("JARVIS_ROOM_AUDIO_LOCAL_WAKE_WORD_LOG_SCORES", "0").lower() not in {"0", "false", "no", "off", ""}
DEFAULT_TRUST_LOCAL_WAKE_WORD = os.environ.get("JARVIS_ROOM_AUDIO_TRUST_LOCAL_WAKE_WORD", "1").lower() not in {"0", "false", "no", "off", ""}
DEFAULT_BT_PROFILE_SETTLE_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_BT_PROFILE_SETTLE_SECONDS", "0.2"))
DEFAULT_BT_PLAYBACK_DRAIN_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_BT_PLAYBACK_DRAIN_SECONDS", "1.2"))
DEFAULT_BLUETOOTH_MAC = os.environ.get("JARVIS_ROOM_AUDIO_BLUETOOTH_MAC", "").strip()
DEFAULT_STARTUP_GREETING = os.environ.get("JARVIS_ROOM_AUDIO_STARTUP_GREETING", "0").lower() not in {"0", "false", "no", "off", ""}
DEFAULT_GREETING_ON_RECONNECT = os.environ.get("JARVIS_ROOM_AUDIO_GREETING_ON_RECONNECT", "0").lower() not in {"0", "false", "no", "off", ""}
DEFAULT_GREETING_TIMEOUT_SECONDS = float(os.environ.get("JARVIS_ROOM_AUDIO_GREETING_TIMEOUT_SECONDS", "30"))
DEFAULT_SCO_MIXER_VOLUME = int(os.environ.get("JARVIS_ROOM_AUDIO_SCO_MIXER_VOLUME", "100"))


def run(cmd: list[str], *, timeout: float | None = None) -> None:
    subprocess.run(cmd, check=True, timeout=timeout)


def write_beep(path: Path, *, rate: int = 48000) -> None:
    frames: list[bytes] = []
    pattern = [(880.0, 0.16), (0.0, 0.08), (1174.66, 0.16)]
    for frequency, seconds in pattern:
        count = int(rate * seconds)
        for i in range(count):
            value = 0 if frequency <= 0 else int(0.22 * math.sin(2 * math.pi * frequency * (i / rate)) * 32767)
            frames.append(value.to_bytes(2, "little", signed=True) * 2)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(frames))


def wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            return handle.getnframes() / rate if rate > 0 else 0.0
    except Exception:
        return 0.0


def play_wav(path: Path, *, device: str) -> None:
    run(["aplay", "-q", "-D", device, str(path)], timeout=max(120, wav_duration_seconds(path) + 30))


def record_wav(path: Path, *, device: str, seconds: float, rate: int) -> None:
    run(
        [
            "arecord",
            "-q",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            str(rate),
            "-c",
            "1",
            "-d",
            str(max(1, int(round(seconds)))),
            str(path),
        ],
        timeout=seconds + 10,
    )


def write_wav_from_pcm(path: Path, pcm: bytes, *, rate: int, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)


def pcm_rms_s16le_mono(pcm: bytes) -> int:
    sample_count = len(pcm) // 2
    if sample_count <= 0:
        return 0
    samples = array.array("h")
    samples.frombytes(pcm[: sample_count * 2])
    if samples.itemsize != 2:
        return 0
    if sys.byteorder != "little":
        samples.byteswap()
    return int(math.sqrt(sum(sample * sample for sample in samples) / sample_count))


def start_raw_arecord(*, device: str, rate: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "arecord",
            "-q",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            str(rate),
            "-c",
            "1",
            "-t",
            "raw",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )


def stop_process(proc: subprocess.Popen, *, timeout: float = 2.0) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass


def read_exact_fd(fd: int, size: int, *, timeout: float | None = None) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    deadline = time.monotonic() + timeout if timeout is not None and timeout > 0 else None
    while remaining > 0:
        wait_seconds = None
        if deadline is not None:
            wait_seconds = deadline - time.monotonic()
            if wait_seconds <= 0:
                raise TimeoutError(f"timed out waiting for {remaining} capture bytes")
        ready, _, _ = select.select([fd], [], [], wait_seconds)
        if not ready:
            raise TimeoutError(f"timed out waiting for {remaining} capture bytes")
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def drain_fd(fd: int) -> int:
    drained = 0
    while True:
        ready, _, _ = select.select([fd], [], [], 0)
        if not ready:
            return drained
        chunk = os.read(fd, 65536)
        if not chunk:
            return drained
        drained += len(chunk)


class LocalWakeWordDetector:
    """Small streaming openWakeWord adapter for Pi-side wake gating.

    openWakeWord expects 16 kHz, mono, int16 PCM in roughly 80 ms chunks. The
    room-audio capture path may be 8 kHz Bluetooth SCO or a higher-rate USB mic,
    so this adapter resamples frames before inference and buffers them into the
    detector's preferred chunk size.
    """

    target_rate = 16000

    def __init__(self, args: argparse.Namespace) -> None:
        if args.local_wake_word_engine != "openwakeword":
            raise RuntimeError(f"unsupported local wake-word engine: {args.local_wake_word_engine}")
        try:
            import numpy as np  # type: ignore[import-not-found]
            import openwakeword  # type: ignore[import-not-found]
            import openwakeword.utils as openwakeword_utils  # type: ignore[import-not-found]
            from openwakeword.model import Model  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError(
                "local wake word requires openWakeWord; refresh the Pi service with "
                "`projects/operation-jarvis/raspberry-pi/scripts/install-room-audio-service.sh`"
            ) from exc

        self._np = np
        self._buffer = bytearray()
        self._ratecv_state: object | None = None
        self._cooldown_until = 0.0
        self._last_score_log_at = 0.0
        self.last_model = ""
        self.last_score = 0.0
        self.max_model = ""
        self.max_score = 0.0
        self.threshold = max(0.0, min(1.0, float(args.local_wake_word_threshold)))
        self.cooldown_seconds = max(0.0, float(args.local_wake_word_cooldown_seconds))
        self.chunk_samples = max(160, int(round(self.target_rate * (max(10, args.local_wake_word_chunk_ms) / 1000.0))))
        self.chunk_bytes = self.chunk_samples * 2
        self.log_scores = bool(args.local_wake_word_log_scores)
        self.inference_framework = str(args.openwakeword_inference).strip().lower() or "tflite"
        self.ncpu = max(1, int(getattr(args, "openwakeword_ncpu", DEFAULT_LOCAL_WAKE_WORD_NCPU)))
        model_specs = self._resolve_model_specs(args, openwakeword, openwakeword_utils)
        self._model = Model(wakeword_models=model_specs, inference_framework=self.inference_framework, ncpu=self.ncpu)
        self.model_names = tuple(model_specs)
        print(
            "local wake word online: "
            f"engine=openwakeword models={','.join(model_specs)} threshold={self.threshold:.2f} "
            f"chunk={self.chunk_samples / self.target_rate * 1000:.0f}ms cooldown={self.cooldown_seconds:.1f}s "
            f"ncpu={self.ncpu}",
            flush=True,
        )

    def _resolve_model_specs(self, args: argparse.Namespace, openwakeword: object, openwakeword_utils: object) -> list[str]:
        raw_specs = str(args.openwakeword_model or "").strip()
        specs = [item.strip() for item in raw_specs.split(",") if item.strip()] or ["hey_jarvis"]
        model_dir = Path(str(args.openwakeword_model_dir)).expanduser() if args.openwakeword_model_dir else None
        resolved: list[str] = []
        official_models = getattr(openwakeword, "MODELS", None) or getattr(openwakeword, "models", {})

        for spec in specs:
            spec_path = Path(spec).expanduser()
            if spec_path.is_file():
                resolved.append(str(spec_path))
                continue

            key = spec.lower().replace(" ", "_").replace("-", "_")
            model_info = official_models.get(key) if isinstance(official_models, dict) else None
            if not isinstance(model_info, dict):
                # Let openWakeWord attempt to resolve future built-in aliases.
                resolved.append(spec)
                continue

            download_models = getattr(openwakeword_utils, "download_models", None)
            if args.openwakeword_auto_download and callable(download_models):
                download_models(model_names=[key], target_directory=str(model_dir) if model_dir else None) if model_dir else download_models(model_names=[key])

            if model_dir:
                filename = str(model_info.get("download_url") or model_info.get("model_path") or "").rstrip("/").split("/")[-1]
                if self.inference_framework == "onnx":
                    filename = filename.replace(".tflite", ".onnx")
                resolved.append(str(model_dir / filename))
            else:
                path = str(model_info.get("model_path", spec))
                if self.inference_framework == "onnx":
                    path = path.replace(".tflite", ".onnx")
                resolved.append(path)

        return resolved

    def reset_stream(self) -> None:
        self._buffer.clear()
        self._ratecv_state = None
        self.last_model = ""
        self.last_score = 0.0
        self.max_model = ""
        self.max_score = 0.0
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()

    def process_frame(self, frame: bytes, *, source_rate: int, now: float) -> dict | None:
        if not frame:
            return None
        if source_rate != self.target_rate:
            if audioop is None:
                raise RuntimeError("local wake-word resampling requires Python audioop; capture at 16000 Hz or use Python <=3.12")
            frame, self._ratecv_state = audioop.ratecv(frame, 2, 1, source_rate, self.target_rate, self._ratecv_state)
        self._buffer.extend(frame)

        hit: dict | None = None
        while len(self._buffer) >= self.chunk_bytes:
            chunk = bytes(self._buffer[: self.chunk_bytes])
            del self._buffer[: self.chunk_bytes]
            samples = self._np.frombuffer(chunk, dtype=self._np.int16)
            prediction = self._model.predict(samples)
            scores: dict[str, float] = {}
            if isinstance(prediction, dict):
                for name, value in prediction.items():
                    try:
                        scores[str(name)] = float(value)
                    except Exception:
                        continue
            if not scores:
                continue

            model_name, score = max(scores.items(), key=lambda item: item[1])
            self.last_model = model_name
            self.last_score = score
            if score > self.max_score:
                self.max_model = model_name
                self.max_score = score
            if self.log_scores and now - self._last_score_log_at >= 1.0:
                self._last_score_log_at = now
                print(f"local wake score: model={model_name} score={score:.3f}", flush=True)
            if score >= self.threshold and now >= self._cooldown_until:
                self._cooldown_until = now + self.cooldown_seconds
                reset = getattr(self._model, "reset", None)
                if callable(reset):
                    reset()
                hit = {"model": model_name, "score": score, "scores": scores}
        return hit


def create_local_wake_word_detector(args: argparse.Namespace) -> LocalWakeWordDetector | None:
    if not args.local_wake_word:
        return None
    return LocalWakeWordDetector(args)


def post_turn(server_url: str, wav_path: Path, *, require_wake_word: bool, async_ack: bool, token: str = "") -> dict:
    payload = {
        "client": "raspberry-pi-powerconf",
        "requireWakeWord": require_wake_word,
        "asyncAck": async_ack,
        "audioWavBase64": base64.b64encode(wav_path.read_bytes()).decode("ascii"),
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["x-jarvis-room-token"] = token
    request = urllib.request.Request(f"{server_url.rstrip('/')}/turn", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Room audio server returned HTTP {exc.code}: {detail}") from exc


def get_turn_result(server_url: str, turn_id: str, *, token: str = "") -> dict:
    encoded_id = urllib.parse.quote(turn_id, safe="")
    headers = {"accept": "application/json"}
    if token:
        headers["x-jarvis-room-token"] = token
    request = urllib.request.Request(f"{server_url.rstrip('/')}/turn-result?id={encoded_id}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Room audio server returned HTTP {exc.code}: {detail}") from exc


def response_without_audio(response: dict) -> dict:
    return {k: v for k, v in response.items() if k != "audioWavBase64"}


def play_response_audio(response: dict, *, device: str, drain_seconds: float = 0.0) -> None:
    audio_b64 = response.get("audioWavBase64")
    if not isinstance(audio_b64, str) or not audio_b64:
        return
    with tempfile.TemporaryDirectory(prefix="jarvis-room-audio-play-") as tmp_dir:
        output_path = Path(tmp_dir) / "jarvis-response.wav"
        output_path.write_bytes(base64.b64decode(audio_b64))
        duration = wav_duration_seconds(output_path)
        started = time.monotonic()
        print(
            f"playing response audio: duration={duration:.2f}s bytes={output_path.stat().st_size} drain={drain_seconds:.2f}s",
            flush=True,
        )
        play_wav(output_path, device=device)
        elapsed = time.monotonic() - started
        print(f"response audio aplay finished: elapsed={elapsed:.2f}s", flush=True)
    if drain_seconds > 0:
        # BlueALSA/aplay can return as soon as the WAV is queued, while the
        # Bluetooth speaker is still physically draining its A2DP buffer. If we
        # reopen SCO capture immediately, the PowerConf switches back to headset
        # mode and clips the tail of the acknowledgement/final answer.
        time.sleep(drain_seconds)


def bluetooth_device_connected(mac: str) -> bool:
    if not mac:
        return True
    try:
        result = subprocess.run(
            ["bluetoothctl", "info", mac],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    return result.returncode == 0 and "Connected: yes" in result.stdout


def set_sco_mixer_volume(args: argparse.Namespace) -> None:
    mac = str(args.bluetooth_mac or "").strip()
    if not mac or args.sco_mixer_volume < 0:
        return
    try:
        subprocess.run(
            ["amixer", "-D", f"bluealsa:{mac}", "sset", "SCO", f"{args.sco_mixer_volume}%", "unmute", "cap"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        print(f"bluetooth mixer volume warning: {exc}", flush=True)


def ensure_bluetooth_connected(args: argparse.Namespace) -> bool:
    mac = str(args.bluetooth_mac or "").strip()
    if not mac:
        return True
    if bluetooth_device_connected(mac):
        return True

    print(f"bluetooth reconnect: connecting {mac}", flush=True)
    commands = (
        ["bluetoothctl", "power", "on"],
        ["bluetoothctl", "trust", mac],
        ["bluetoothctl", "connect", mac],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
            )
            if result.returncode != 0:
                print(f"bluetooth reconnect command failed ({' '.join(command)}): {result.stdout.strip()}", flush=True)
        except Exception as exc:
            print(f"bluetooth reconnect command error ({' '.join(command)}): {exc}", flush=True)

    connected = bluetooth_device_connected(mac)
    if connected:
        print(f"bluetooth reconnect: {mac} connected", flush=True)
        set_sco_mixer_volume(args)
    else:
        print(f"bluetooth reconnect: {mac} is still disconnected", flush=True)
    return connected


def get_greeting(server_url: str, *, token: str = "", timeout: float = 30.0) -> dict:
    headers = {"accept": "application/json"}
    if token:
        headers["x-jarvis-room-token"] = token
    request = urllib.request.Request(f"{server_url.rstrip('/')}/greeting", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, timeout)) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Room audio server returned HTTP {exc.code}: {detail}") from exc


def play_room_greeting(args: argparse.Namespace) -> None:
    response = get_greeting(args.server_url, token=args.token, timeout=args.greeting_timeout)
    print(json.dumps(response_without_audio(response), indent=2, sort_keys=True), flush=True)
    play_response_audio(response, device=args.playback_device, drain_seconds=args.bt_playback_drain_seconds)


def wait_for_final_response(args: argparse.Namespace, turn_id: str) -> dict:
    deadline = time.monotonic() + max(1.0, args.result_timeout)
    poll_interval = max(0.05, args.poll_interval)
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for room audio turn {turn_id}")
        time.sleep(poll_interval)
        response = get_turn_result(args.server_url, turn_id, token=args.token)
        if response.get("pending"):
            poll_interval = max(0.05, float(response.get("pollAfterSeconds") or args.poll_interval))
            continue
        print(json.dumps(response_without_audio(response), indent=2, sort_keys=True), flush=True)
        play_response_audio(response, device=args.playback_device, drain_seconds=args.bt_playback_drain_seconds)
        return response


def wait_for_final_response_with_idle_capture(args: argparse.Namespace, turn_id: str) -> dict:
    """Poll for the final answer while keeping the SCO mic transport open.

    The captured bytes are intentionally drained and discarded. This keeps the
    PowerConf mic indicator/live HFP route back on during long final generation,
    then releases it just before A2DP playback.
    """
    deadline = time.monotonic() + max(1.0, args.result_timeout)
    poll_interval = max(0.05, args.poll_interval)
    proc: subprocess.Popen | None = None
    fd: int | None = None

    def start_idle_capture() -> None:
        nonlocal proc, fd
        if proc is not None and proc.poll() is None:
            return
        proc = start_raw_arecord(device=args.device, rate=args.rate)
        if proc.stdout is None:
            raise RuntimeError("idle capture stdout pipe was not created")
        fd = proc.stdout.fileno()
        print("vad mic restored while waiting for final response", flush=True)

    def stop_idle_capture() -> None:
        nonlocal proc, fd
        if proc is not None:
            stop_process(proc)
        proc = None
        fd = None

    start_idle_capture()
    try:
        while True:
            if fd is not None:
                try:
                    drain_fd(fd)
                except OSError:
                    stop_idle_capture()
            if proc is not None and proc.poll() is not None:
                stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr is not None else ""
                print(f"vad idle capture stopped; restarting: {stderr.strip()}", flush=True)
                stop_idle_capture()
                time.sleep(max(0.1, args.interval))
                start_idle_capture()

            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for room audio turn {turn_id}")

            response = get_turn_result(args.server_url, turn_id, token=args.token)
            if response.get("pending"):
                poll_interval = max(0.05, float(response.get("pollAfterSeconds") or args.poll_interval))
                time.sleep(poll_interval)
                continue

            print(json.dumps(response_without_audio(response), indent=2, sort_keys=True), flush=True)
            stop_idle_capture()
            if args.bt_profile_settle_seconds > 0:
                time.sleep(args.bt_profile_settle_seconds)
            play_response_audio(response, device=args.playback_device, drain_seconds=args.bt_playback_drain_seconds)
            return response
    finally:
        stop_idle_capture()


def submit_wav_turn(args: argparse.Namespace, input_path: Path, *, require_wake_word: bool | None = None) -> dict:
    print(f"sending {input_path.stat().st_size} bytes to {args.server_url}...", flush=True)
    if require_wake_word is None:
        require_wake_word = not args.no_wake_word
    response = post_turn(
        args.server_url,
        input_path,
        require_wake_word=require_wake_word,
        async_ack=args.async_ack,
        token=args.token,
    )
    print(json.dumps(response_without_audio(response), indent=2, sort_keys=True), flush=True)

    # With async acknowledgement enabled, this first audio is the short
    # "Generating your response, sir." notice. The final answer is fetched below.
    play_response_audio(response, device=args.playback_device, drain_seconds=args.bt_playback_drain_seconds)
    if response.get("pending") and isinstance(response.get("turnId"), str):
        return wait_for_final_response(args, str(response["turnId"]))
    return response


def submit_wav_turn_capture_released(args: argparse.Namespace, input_path: Path, *, require_wake_word: bool | None = None) -> dict:
    """Submit a turn when the caller has already stopped SCO capture for A2DP.

    Capture is already off before posting. By default it stays off through the
    acknowledgement, the async wait, and final playback; this avoids a fresh
    SCO->A2DP profile switch immediately before the final answer. The older
    idle-capture behaviour remains available for diagnostics.
    """
    print(f"sending {input_path.stat().st_size} bytes to {args.server_url}...", flush=True)
    if require_wake_word is None:
        require_wake_word = not args.no_wake_word
    response = post_turn(
        args.server_url,
        input_path,
        require_wake_word=require_wake_word,
        async_ack=args.async_ack,
        token=args.token,
    )
    print(json.dumps(response_without_audio(response), indent=2, sort_keys=True), flush=True)

    if args.bt_profile_settle_seconds > 0:
        time.sleep(args.bt_profile_settle_seconds)
    play_response_audio(response, device=args.playback_device, drain_seconds=args.bt_playback_drain_seconds)
    if response.get("pending") and isinstance(response.get("turnId"), str):
        if args.vad_restore_capture_while_waiting:
            return wait_for_final_response_with_idle_capture(args, str(response["turnId"]))
        return wait_for_final_response(args, str(response["turnId"]))
    return response


def process_vad_utterance(
    args: argparse.Namespace,
    pcm: bytes,
    *,
    duration_seconds: float,
    voiced_ms: float,
    max_rms: int,
    capture_released: bool = False,
    require_wake_word: bool | None = None,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="jarvis-room-audio-vad-") as tmp_dir:
        input_path = Path(tmp_dir) / "input.wav"
        write_wav_from_pcm(input_path, pcm, rate=args.rate, channels=1)
        print(
            f"vad utterance: duration={duration_seconds:.2f}s voiced={voiced_ms:.0f}ms max_rms={max_rms}; "
            f"wav={input_path.stat().st_size} bytes",
            flush=True,
        )
        if capture_released:
            return submit_wav_turn_capture_released(args, input_path, require_wake_word=require_wake_word)
        return submit_wav_turn(args, input_path, require_wake_word=require_wake_word)


def run_vad_loop(args: argparse.Namespace) -> None:
    sample_width = 2
    channels = 1
    bytes_per_second = args.rate * sample_width * channels
    frame_bytes = max(sample_width * channels, int(bytes_per_second * (args.vad_frame_ms / 1000.0)))
    frame_bytes -= frame_bytes % (sample_width * channels)
    if frame_bytes <= 0:
        frame_bytes = sample_width * channels
    frame_seconds = frame_bytes / bytes_per_second
    preroll_frames = max(0, int(round(args.vad_preroll_ms / max(args.vad_frame_ms, 1))))

    local_wake = create_local_wake_word_detector(args)
    local_wake_gate_active = local_wake is not None
    require_server_wake_word_after_local_gate = (not args.no_wake_word) and not (
        local_wake_gate_active and args.trust_local_wake_word
    )

    print(
        "starting Discord-style VAD listener: "
        f"device={args.device} rate={args.rate}Hz frame={frame_seconds * 1000:.0f}ms "
        f"threshold={args.vad_rms_threshold} silence={args.vad_silence_seconds:.2f}s "
        f"min={args.vad_min_utterance_seconds:.2f}s max={args.vad_max_utterance_seconds:.1f}s "
        f"preroll={args.vad_preroll_ms}ms min_voiced={args.vad_min_voiced_ms}ms "
        f"release_capture_during_turn={args.vad_release_capture_during_turn} "
        f"restore_capture_while_waiting={args.vad_restore_capture_while_waiting} "
        f"bt_settle={args.bt_profile_settle_seconds:.2f}s bt_drain={args.bt_playback_drain_seconds:.2f}s "
        f"local_wake_gate={local_wake_gate_active} trust_local_wake={args.trust_local_wake_word} "
        f"server_wake_check={require_server_wake_word_after_local_gate}",
        flush=True,
    )

    greeting_pending = bool(args.startup_greeting)

    while True:
        if args.bluetooth_mac and not ensure_bluetooth_connected(args):
            if args.greeting_on_reconnect:
                greeting_pending = True
            time.sleep(max(0.1, args.interval))
            continue

        proc = start_raw_arecord(device=args.device, rate=args.rate)
        if proc.stdout is None:
            raise RuntimeError("arecord stdout pipe was not created")
        fd = proc.stdout.fileno()
        if local_wake is not None:
            local_wake.reset_stream()
        wake_armed_until = 0.0
        pre_roll: deque[tuple[bytes, bool, int]] = deque(maxlen=preroll_frames)
        utterance: list[bytes] | None = None
        utterance_bytes = 0
        utterance_wake_accepted = not local_wake_gate_active
        utterance_wake_max_score = 0.0
        utterance_wake_max_model = ""
        voiced_ms = 0.0
        max_rms = 0
        last_voice_at = 0.0
        speech_started_at = 0.0

        try:
            while True:
                frame = read_exact_fd(fd, frame_bytes, timeout=args.capture_read_timeout_seconds)
                now = time.monotonic()
                if len(frame) < frame_bytes:
                    stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr is not None else ""
                    raise RuntimeError(f"arecord stopped while reading VAD audio: {stderr.strip()}")

                if greeting_pending:
                    greeting_pending = False
                    print("vad capture online; playing room-audio greeting", flush=True)
                    stop_process(proc)
                    if args.bt_profile_settle_seconds > 0:
                        time.sleep(args.bt_profile_settle_seconds)
                    try:
                        play_room_greeting(args)
                    except Exception as exc:
                        print(f"room-audio greeting error: {exc}", flush=True)
                    break

                if local_wake is not None:
                    wake_hit = local_wake.process_frame(frame, source_rate=args.rate, now=now)
                    if utterance is not None and local_wake.last_score > utterance_wake_max_score:
                        utterance_wake_max_score = local_wake.last_score
                        utterance_wake_max_model = local_wake.last_model
                    if wake_hit:
                        wake_armed_until = now + max(0.0, args.local_wake_word_arm_seconds)
                        if utterance is not None:
                            utterance_wake_accepted = True
                        print(
                            "local wake detected: "
                            f"model={wake_hit.get('model')} score={float(wake_hit.get('score', 0.0)):.3f} "
                            f"armed_for={max(0.0, wake_armed_until - now):.1f}s",
                            flush=True,
                        )

                rms = pcm_rms_s16le_mono(frame)
                is_voiced = rms >= args.vad_rms_threshold

                if utterance is None:
                    if not is_voiced:
                        pre_roll.append((frame, False, rms))
                        continue
                    utterance = []
                    utterance_bytes = 0
                    utterance_wake_accepted = (not local_wake_gate_active) or now <= wake_armed_until
                    utterance_wake_max_score = local_wake.last_score if local_wake is not None else 0.0
                    utterance_wake_max_model = local_wake.last_model if local_wake is not None else ""
                    voiced_ms = 0.0
                    max_rms = rms
                    speech_started_at = now - (len(pre_roll) * frame_seconds)
                    for preroll_frame, preroll_voiced, preroll_rms in pre_roll:
                        utterance.append(preroll_frame)
                        utterance_bytes += len(preroll_frame)
                        max_rms = max(max_rms, preroll_rms)
                        if preroll_voiced:
                            voiced_ms += frame_seconds * 1000.0
                    pre_roll.clear()
                    utterance.append(frame)
                    utterance_bytes += len(frame)
                    voiced_ms += frame_seconds * 1000.0
                    last_voice_at = now
                    print(f"vad speech start: rms={rms}", flush=True)
                    continue

                utterance.append(frame)
                utterance_bytes += len(frame)
                max_rms = max(max_rms, rms)
                if is_voiced:
                    voiced_ms += frame_seconds * 1000.0
                    last_voice_at = now

                duration = utterance_bytes / bytes_per_second
                silence_seconds = now - last_voice_at
                if duration < args.vad_max_utterance_seconds and silence_seconds < args.vad_silence_seconds:
                    continue

                pcm = b"".join(utterance)
                enough_duration = duration >= args.vad_min_utterance_seconds
                enough_voice = voiced_ms >= args.vad_min_voiced_ms and max_rms >= args.vad_rms_threshold
                utterance = None
                utterance_bytes = 0
                pre_roll.clear()

                if not enough_duration or not enough_voice:
                    print(
                        f"vad dropped: duration={duration:.2f}s voiced={voiced_ms:.0f}ms max_rms={max_rms}",
                        flush=True,
                    )
                    continue

                reason = "max-duration" if duration >= args.vad_max_utterance_seconds else "silence"
                if local_wake_gate_active and not utterance_wake_accepted:
                    print(
                        f"local wake dropped utterance: duration={duration:.2f}s voiced={voiced_ms:.0f}ms "
                        f"max_rms={max_rms} wake_max={utterance_wake_max_score:.3f} "
                        f"wake_model={utterance_wake_max_model or '-'} threshold={args.local_wake_word_threshold:.2f} "
                        f"reason=no wake word",
                        flush=True,
                    )
                    continue

                print(
                    f"vad speech end: reason={reason} elapsed={now - speech_started_at:.2f}s "
                    f"local_wake_accepted={utterance_wake_accepted}",
                    flush=True,
                )
                if args.vad_release_capture_during_turn:
                    print("vad releasing capture for A2DP playback", flush=True)
                    stop_process(proc)
                    process_vad_utterance(
                        args,
                        pcm,
                        duration_seconds=duration,
                        voiced_ms=voiced_ms,
                        max_rms=max_rms,
                        capture_released=True,
                        require_wake_word=require_server_wake_word_after_local_gate,
                    )
                    break
                try:
                    process_vad_utterance(
                        args,
                        pcm,
                        duration_seconds=duration,
                        voiced_ms=voiced_ms,
                        max_rms=max_rms,
                        require_wake_word=require_server_wake_word_after_local_gate,
                    )
                finally:
                    drained = drain_fd(fd)
                    if drained:
                        print(f"vad drained {drained} bytes captured while processing/playback", flush=True)
        except KeyboardInterrupt:
            stop_process(proc)
            raise
        except Exception as exc:
            print(f"vad error: {exc}; restarting capture in {args.interval:.1f}s", flush=True)
            if args.greeting_on_reconnect:
                greeting_pending = True
            stop_process(proc)
            time.sleep(max(0.1, args.interval))


def run_turn(args: argparse.Namespace) -> dict:
    with tempfile.TemporaryDirectory(prefix="jarvis-room-audio-") as tmp_dir:
        tmp = Path(tmp_dir)
        if args.beep:
            beep_path = tmp / "ready.wav"
            write_beep(beep_path, rate=args.rate)
            play_wav(beep_path, device=args.playback_device)
            time.sleep(args.post_beep_delay)

        input_path = tmp / "input.wav"
        print(f"recording {args.duration:.1f}s from {args.device}...", flush=True)
        record_wav(input_path, device=args.device, seconds=args.duration, rate=args.rate)

        return submit_wav_turn(args, input_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument("--device", default=DEFAULT_AUDIO_DEVICE, help="ALSA capture device; also used for playback unless --playback-device is set")
    parser.add_argument("--playback-device", default=DEFAULT_PLAYBACK_DEVICE, help="ALSA playback device, useful when Bluetooth capture uses SCO and playback uses A2DP")
    parser.add_argument("--duration", type=float, default=DEFAULT_RECORD_SECONDS)
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE)
    parser.add_argument("--vad-loop", action="store_true", help="Use Discord-style continuous voice activity detection instead of fixed-length recording windows")
    parser.add_argument("--vad-rms-threshold", type=int, default=DEFAULT_VAD_RMS_THRESHOLD)
    parser.add_argument("--vad-silence-seconds", type=float, default=DEFAULT_VAD_SILENCE_SECONDS)
    parser.add_argument("--vad-min-utterance-seconds", type=float, default=DEFAULT_VAD_MIN_UTTERANCE_SECONDS)
    parser.add_argument("--vad-max-utterance-seconds", type=float, default=DEFAULT_VAD_MAX_UTTERANCE_SECONDS)
    parser.add_argument("--vad-preroll-ms", type=int, default=DEFAULT_VAD_PREROLL_MS)
    parser.add_argument("--vad-min-voiced-ms", type=int, default=DEFAULT_VAD_MIN_VOICED_MS)
    parser.add_argument("--vad-frame-ms", type=int, default=DEFAULT_VAD_FRAME_MS)
    parser.add_argument("--capture-read-timeout-seconds", type=float, default=DEFAULT_CAPTURE_READ_TIMEOUT_SECONDS, help="Restart Bluetooth capture if no PCM bytes arrive for this many seconds; 0 disables the watchdog")
    parser.add_argument(
        "--vad-release-capture-during-turn",
        dest="vad_release_capture_during_turn",
        action="store_true",
        default=DEFAULT_VAD_RELEASE_CAPTURE_DURING_TURN,
        help="Release SCO capture around A2DP playback and restore the mic while waiting for the final response",
    )
    parser.add_argument("--no-vad-release-capture-during-turn", dest="vad_release_capture_during_turn", action="store_false")
    parser.add_argument(
        "--vad-restore-capture-while-waiting",
        dest="vad_restore_capture_while_waiting",
        action="store_true",
        default=DEFAULT_VAD_RESTORE_CAPTURE_WHILE_WAITING,
        help="Reopen and drain SCO capture while waiting for the async final response; off by default for more reliable A2DP playback",
    )
    parser.add_argument("--no-vad-restore-capture-while-waiting", dest="vad_restore_capture_while_waiting", action="store_false")
    parser.add_argument("--local-wake-word", dest="local_wake_word", action="store_true", default=DEFAULT_LOCAL_WAKE_WORD_ENABLED, help="Enable Pi-side wake-word detection before sending VAD utterances to the Mac")
    parser.add_argument("--no-local-wake-word", dest="local_wake_word", action="store_false")
    parser.add_argument("--local-wake-word-engine", default=DEFAULT_LOCAL_WAKE_WORD_ENGINE, choices=["openwakeword"])
    parser.add_argument("--local-wake-word-threshold", type=float, default=DEFAULT_LOCAL_WAKE_WORD_THRESHOLD, help="openWakeWord activation threshold, usually 0.4-0.7")
    parser.add_argument("--local-wake-word-cooldown-seconds", type=float, default=DEFAULT_LOCAL_WAKE_WORD_COOLDOWN_SECONDS, help="Minimum seconds between local wake-word activations")
    parser.add_argument("--local-wake-word-arm-seconds", type=float, default=DEFAULT_LOCAL_WAKE_WORD_ARM_SECONDS, help="Seconds after a local wake hit during which the current/next VAD utterance is allowed through")
    parser.add_argument("--local-wake-word-chunk-ms", type=int, default=DEFAULT_LOCAL_WAKE_WORD_CHUNK_MS, help="Inference chunk size for local wake-word detection; openWakeWord recommends 80ms")
    parser.add_argument("--local-wake-word-log-scores", action="store_true", default=DEFAULT_LOCAL_WAKE_WORD_LOG_SCORES, help="Log the best local wake-word score about once per second for tuning")
    parser.add_argument("--openwakeword-model", default=DEFAULT_LOCAL_WAKE_WORD_MODEL, help="Comma-separated openWakeWord model names or model file paths; default hey_jarvis")
    parser.add_argument("--openwakeword-inference", default=DEFAULT_LOCAL_WAKE_WORD_INFERENCE, choices=["tflite", "onnx"], help="openWakeWord inference framework")
    parser.add_argument("--openwakeword-ncpu", type=int, default=DEFAULT_LOCAL_WAKE_WORD_NCPU, help="CPU threads for openWakeWord preprocessing; Pi 3 default is 2 for better real-time headroom")
    parser.add_argument("--openwakeword-model-dir", default=DEFAULT_LOCAL_WAKE_WORD_MODEL_DIR, help="Optional directory for downloaded/openWakeWord model files")
    parser.add_argument("--openwakeword-auto-download", dest="openwakeword_auto_download", action="store_true", default=DEFAULT_LOCAL_WAKE_WORD_AUTO_DOWNLOAD, help="Download missing official openWakeWord models at startup")
    parser.add_argument("--no-openwakeword-auto-download", dest="openwakeword_auto_download", action="store_false")
    parser.add_argument("--trust-local-wake-word", dest="trust_local_wake_word", action="store_true", default=DEFAULT_TRUST_LOCAL_WAKE_WORD, help="Tell older Mac-side servers to trust Pi-side openWakeWord and skip transcript wake-word re-checking")
    parser.add_argument("--no-trust-local-wake-word", dest="trust_local_wake_word", action="store_false")
    parser.add_argument("--bt-profile-settle-seconds", type=float, default=DEFAULT_BT_PROFILE_SETTLE_SECONDS, help="Small delay after switching from SCO capture to A2DP playback")
    parser.add_argument("--bt-playback-drain-seconds", type=float, default=DEFAULT_BT_PLAYBACK_DRAIN_SECONDS, help="Delay after A2DP playback before reopening SCO capture, to avoid clipping buffered Bluetooth audio")
    parser.add_argument("--bluetooth-mac", default=DEFAULT_BLUETOOTH_MAC, help="Paired/trusted Bluetooth device MAC to reconnect before opening BlueALSA capture")
    parser.add_argument("--sco-mixer-volume", type=int, default=DEFAULT_SCO_MIXER_VOLUME, help="BlueALSA SCO mixer percent to restore after Bluetooth reconnect; use -1 to skip")
    parser.add_argument("--startup-greeting", dest="startup_greeting", action="store_true", default=DEFAULT_STARTUP_GREETING, help="Play a JARVIS greeting once the room mic/speaker path is online")
    parser.add_argument("--no-startup-greeting", dest="startup_greeting", action="store_false")
    parser.add_argument("--greeting-on-reconnect", dest="greeting_on_reconnect", action="store_true", default=DEFAULT_GREETING_ON_RECONNECT, help="Play the greeting again after capture/Bluetooth recovers from a disconnect")
    parser.add_argument("--no-greeting-on-reconnect", dest="greeting_on_reconnect", action="store_false")
    parser.add_argument("--greeting-timeout", type=float, default=DEFAULT_GREETING_TIMEOUT_SECONDS, help="Seconds to wait for optional startup/reconnect greeting audio before listening anyway")
    parser.add_argument("--token", default=os.environ.get("JARVIS_ROOM_AUDIO_TOKEN", ""))
    parser.add_argument("--no-wake-word", action="store_true", help="Do not require the transcript to contain Jarvis")
    parser.add_argument("--beep", action="store_true", help="Play a short tone before recording")
    parser.add_argument("--post-beep-delay", type=float, default=0.35)
    parser.add_argument("--async-ack", dest="async_ack", action="store_true", default=DEFAULT_ASYNC_ACK, help="Play the processing acknowledgement immediately after ASR accepts the wake word, then poll for the final answer")
    parser.add_argument("--no-async-ack", dest="async_ack", action="store_false")
    parser.add_argument("--poll-interval", type=float, default=float(os.environ.get("JARVIS_ROOM_AUDIO_POLL_INTERVAL", "0.25")))
    parser.add_argument("--result-timeout", type=float, default=float(os.environ.get("JARVIS_ROOM_AUDIO_RESULT_TIMEOUT", "300")))
    parser.add_argument("--loop", action="store_true", help="Keep recording fixed-length turns")
    parser.add_argument("--interval", type=float, default=0.5)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.playback_device:
        args.playback_device = args.device
    if args.vad_loop:
        run_vad_loop(args)
        return 0
    if args.loop:
        while True:
            try:
                run_turn(args)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"error: {exc}", flush=True)
            time.sleep(max(0.0, args.interval))
    else:
        run_turn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
