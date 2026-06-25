from __future__ import annotations

import logging
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DOTENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_SCHEDULER_PATH = (
    "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:"
    "/usr/bin:/bin:/usr/sbin:/sbin"
)
_DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOGGING_CONFIGURED = False


def parse_dotenv_value(raw_value: str) -> str:
    """Parse the subset of .env syntax used by this project."""
    value = raw_value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return (
            value[1:-1]
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return re.sub(r"\s+#.*$", "", value).strip()


def parse_dotenv_file(path: str | Path = DOTENV_PATH) -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not match:
            continue
        values[match.group(1)] = parse_dotenv_value(match.group(2))
    return values


def load_project_env(path: str | Path = DOTENV_PATH, *, override: bool = False) -> dict[str, str]:
    """Load project .env values into os.environ and return parsed key/value pairs."""
    values = parse_dotenv_file(path)
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return values


def get_str_env(name: str, default: str = "", *, strip: bool = True) -> str:
    value = os.environ.get(name, default)
    return value.strip() if strip else value


def get_bool_env(name: str, default: bool = False) -> bool:
    raw_default = "1" if default else "0"
    return get_str_env(name, raw_default).lower() in {"1", "true", "yes", "on"}


def get_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = get_str_env(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def get_float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = get_str_env(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def configure_logging(*, default_level: str = "INFO") -> None:
    """Configure process-wide logging once, using JARVIS_LOG_LEVEL when set."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    level_name = get_str_env("JARVIS_LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=level, format=_DEFAULT_LOG_FORMAT)
    else:
        root_logger.setLevel(level)
    _LOGGING_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
