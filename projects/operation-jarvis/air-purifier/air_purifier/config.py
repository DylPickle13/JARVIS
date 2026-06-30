from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

AIR_PURIFIER_ROOT = Path(__file__).resolve().parents[1]
OPERATION_ROOT = AIR_PURIFIER_ROOT.parent


def find_repo_root(start: Path = AIR_PURIFIER_ROOT) -> Path:
    for path in (start, *start.parents):
        if (path / ".pi").exists() and (path / "projects").exists():
            return path
    return OPERATION_ROOT.parents[1]


REPO_ROOT = find_repo_root()
DEFAULT_ENV_PATH = AIR_PURIFIER_ROOT / ".env"
OPERATION_ENV_PATH = OPERATION_ROOT / ".env"
REPO_ENV_PATH = REPO_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    username: str | None
    password: str | None
    country_code: str
    time_zone: str
    default_device: str | None
    write_wait_seconds: float

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)


def load_dotenv(path: Path = DEFAULT_ENV_PATH) -> None:
    """Load simple KEY=VALUE pairs without overriding existing environment."""
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    normalized = re.sub(r"[\s_]+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9.-]+", "", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    return normalized.strip("-")


def load_settings() -> Settings:
    # More-local files win because load_dotenv uses setdefault.
    load_dotenv(DEFAULT_ENV_PATH)
    load_dotenv(OPERATION_ENV_PATH)
    load_dotenv(REPO_ENV_PATH)

    username = (
        os.environ.get("VESYNC_EMAIL")
        or os.environ.get("VESYNC_USERNAME")
        or os.environ.get("JARVIS_VESYNC_EMAIL")
        or os.environ.get("JARVIS_VESYNC_USERNAME")
        or None
    )
    password = (
        os.environ.get("VESYNC_PASSWORD")
        or os.environ.get("JARVIS_VESYNC_PASSWORD")
        or None
    )
    default_device = (
        os.environ.get("JARVIS_AIR_PURIFIER_NAME")
        or os.environ.get("JARVIS_AIR_PURIFIER_DEVICE")
        or os.environ.get("VESYNC_AIR_PURIFIER_NAME")
        or None
    )

    return Settings(
        username=username,
        password=password,
        country_code=(os.environ.get("VESYNC_COUNTRY_CODE") or "CA").upper(),
        time_zone=os.environ.get("VESYNC_TIME_ZONE") or "America/Toronto",
        default_device=default_device,
        write_wait_seconds=float(os.environ.get("JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS", "150") or "150"),
    )
