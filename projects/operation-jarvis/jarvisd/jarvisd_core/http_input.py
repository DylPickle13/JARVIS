"""Bounded JSON request decoding; independent of routes and device execution."""
from __future__ import annotations

import json
from typing import BinaryIO


class RequestInputError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def read_json(stream: BinaryIO, raw_length: str | None, *, max_bytes: int) -> dict:
    if raw_length is None:
        raise RequestInputError(411, "Content-Length is required")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise RequestInputError(400, "invalid Content-Length") from exc
    if length <= 0:
        raise RequestInputError(400, "JSON body is required")
    if length > max_bytes:
        raise RequestInputError(413, "JSON body is too large")
    try:
        raw = stream.read(length)
        if len(raw) != length:
            raise RequestInputError(400, "incomplete request body")
        payload = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RequestInputError(400, "request body must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise RequestInputError(400, "malformed JSON") from exc
    if not isinstance(payload, dict):
        raise RequestInputError(400, "JSON body must be an object")
    return payload
