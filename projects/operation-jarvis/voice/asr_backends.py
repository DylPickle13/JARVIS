"""Automatic-speech-recognition backends for the Operation JARVIS voice pipeline."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


class ASRBackendError(RuntimeError):
    """Raised when an ASR backend cannot produce a trustworthy result."""


class ASRBackend(Protocol):
    name: str

    def transcribe(self, audio_path: Path) -> str:
        ...

    def warm_up(self) -> dict[str, Any]:
        ...

    def status(self) -> dict[str, Any]:
        ...


_BACKEND_ALIASES = {
    "omlx": "omlx",
    "whisper": "omlx",
    "omlx-whisper": "omlx",
    "apple": "apple-speech",
    "speech": "apple-speech",
    "apple-speech": "apple-speech",
    "speech-transcriber": "apple-speech",
    "dictation": "apple-dictation",
    "apple-dictation": "apple-dictation",
    "dictation-transcriber": "apple-dictation",
}


def normalize_asr_backend(value: str, *, allow_empty: bool = False) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw and allow_empty:
        return ""
    normalized = _BACKEND_ALIASES.get(raw)
    if normalized is None:
        choices = ", ".join(sorted(set(_BACKEND_ALIASES.values())))
        raise ValueError(f"Unsupported ASR backend {value!r}; expected one of: {choices}")
    return normalized


class CallbackASRBackend:
    """Adapter for an in-process transcription callback, currently oMLX Whisper."""

    def __init__(self, name: str, callback: Callable[[Path], str]) -> None:
        self.name = normalize_asr_backend(name)
        self._callback = callback

    def transcribe(self, audio_path: Path) -> str:
        return self._callback(audio_path)

    def warm_up(self) -> dict[str, Any]:
        return {"ok": True, "backend": self.name, "available": True}

    def status(self) -> dict[str, Any]:
        return {"ok": True, "backend": self.name, "available": True}


@dataclass(frozen=True)
class AppleSpeechASRSettings:
    helper_path: Path
    locale: str = "en-CA"
    engine: str = "speech"
    timeout_seconds: float = 15.0
    contextual_strings: tuple[str, ...] = ()


class AppleSpeechASRBackend:
    """Invoke the compiled macOS SpeechAnalyzer helper for one bounded WAV."""

    def __init__(self, settings: AppleSpeechASRSettings) -> None:
        engine = str(settings.engine or "speech").strip().lower()
        if engine not in {"speech", "dictation"}:
            raise ValueError(f"Unsupported Apple ASR engine: {settings.engine!r}")
        self.settings = AppleSpeechASRSettings(
            helper_path=Path(settings.helper_path).expanduser(),
            locale=str(settings.locale or "en-CA").strip() or "en-CA",
            engine=engine,
            timeout_seconds=max(1.0, float(settings.timeout_seconds)),
            contextual_strings=tuple(
                dict.fromkeys(
                    value.strip()
                    for value in settings.contextual_strings
                    if isinstance(value, str) and value.strip()
                )
            )[:100],
        )
        self.name = f"apple-{engine}"

    def _base_command(self, action: str) -> list[str]:
        return [
            str(self.settings.helper_path),
            action,
            "--engine",
            self.settings.engine,
            "--locale",
            self.settings.locale,
        ]

    def _validate_helper(self) -> None:
        path = self.settings.helper_path
        if not path.is_file():
            raise ASRBackendError("Apple ASR helper is missing")
        if not os.access(path, os.X_OK):
            raise ASRBackendError("Apple ASR helper is not executable")

    @staticmethod
    def _parse_payload(raw: str, *, source: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise ASRBackendError(f"Apple ASR returned malformed {source} JSON") from exc
        if not isinstance(payload, dict):
            raise ASRBackendError(f"Apple ASR returned non-object {source} JSON")
        return payload

    def _run(self, command: list[str], *, timeout: float | None = None) -> dict[str, Any]:
        self._validate_helper()
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout or self.settings.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ASRBackendError(
                f"Apple ASR timed out after {float(timeout or self.settings.timeout_seconds):.1f}s"
            ) from exc
        except OSError as exc:
            raise ASRBackendError(f"Failed to launch Apple ASR helper: {exc}") from exc

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            if detail:
                try:
                    payload = self._parse_payload(detail, source="error")
                    detail = str(payload.get("error") or detail)
                except ASRBackendError:
                    detail = detail[:500]
            else:
                detail = f"exit status {result.returncode}"
            raise ASRBackendError(f"Apple ASR failed: {detail}")

        payload = self._parse_payload(result.stdout, source="result")
        if payload.get("ok") is not True:
            raise ASRBackendError(f"Apple ASR failed: {payload.get('error') or 'unknown helper error'}")
        return payload

    def transcribe(self, audio_path: Path) -> str:
        path = Path(audio_path)
        if not path.is_file():
            raise ASRBackendError(f"ASR input WAV is missing: {path}")
        command = self._base_command("transcribe") + ["--file", str(path)]
        for phrase in self.settings.contextual_strings:
            command.extend(("--context", phrase))
        payload = self._run(command)
        transcript = payload.get("transcript", "")
        if not isinstance(transcript, str):
            raise ASRBackendError("Apple ASR transcript was not text")
        return " ".join(transcript.split()).strip()

    def status(self) -> dict[str, Any]:
        payload = self._run(self._base_command("health"), timeout=min(self.settings.timeout_seconds, 15.0))
        available = payload.get("available") is True and payload.get("assetStatus") == "installed"
        return {
            "ok": True,
            "backend": self.name,
            "available": available,
            "locale": str(payload.get("locale") or self.settings.locale),
            "assetStatus": str(payload.get("assetStatus") or "unknown"),
        }

    def warm_up(self) -> dict[str, Any]:
        status = self.status()
        if not status.get("available"):
            raise ASRBackendError(
                f"Apple ASR is unavailable for {status.get('locale')}: assetStatus={status.get('assetStatus')}"
            )
        return status

    def install_assets(self) -> dict[str, Any]:
        return self._run(self._base_command("install-assets"), timeout=max(self.settings.timeout_seconds, 600.0))
