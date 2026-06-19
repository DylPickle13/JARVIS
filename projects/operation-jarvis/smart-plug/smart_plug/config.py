from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SMART_PLUG_ROOT = Path(__file__).resolve().parents[1]
OPERATION_ROOT = SMART_PLUG_ROOT.parent


def find_repo_root(start: Path = SMART_PLUG_ROOT) -> Path:
    for path in (start, *start.parents):
        if (path / ".pi").exists() and (path / "projects").exists():
            return path
    return OPERATION_ROOT.parents[1]


REPO_ROOT = find_repo_root()
DEFAULT_CONFIG_PATH = SMART_PLUG_ROOT / "plugs.json"
DEFAULT_ENV_PATH = SMART_PLUG_ROOT / ".env"
OPERATION_ENV_PATH = OPERATION_ROOT / ".env"
REPO_ENV_PATH = REPO_ROOT / ".env"


@dataclass(frozen=True)
class PlugConfig:
    name: str
    host: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class KasaCredential:
    label: str
    username: str
    password: str


@dataclass(frozen=True)
class Settings:
    username: str | None
    password: str | None
    credentials: list[KasaCredential]
    discovery_target: str
    timeout: int
    config_path: Path
    plugs: dict[str, PlugConfig]


def load_dotenv(path: Path = DEFAULT_ENV_PATH) -> None:
    """Small .env loader so the project has no dependency beyond python-kasa."""
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _parse_env_plugs(value: str | None) -> dict[str, PlugConfig]:
    plugs: dict[str, PlugConfig] = {}
    if not value:
        return plugs
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Invalid SMART_PLUGS item {item!r}; expected name=ip")
        name, host = item.split("=", 1)
        name = normalize_name(name)
        host = host.strip()
        if name and host:
            plugs[name] = PlugConfig(name=name, host=host)
    return plugs


def _parse_json_plugs(path: Path) -> dict[str, PlugConfig]:
    if not path.exists():
        return {}
    data: Any = json.loads(path.read_text())
    raw_plugs = data.get("plugs", data) if isinstance(data, dict) else data
    plugs: dict[str, PlugConfig] = {}

    if isinstance(raw_plugs, dict):
        for name, value in raw_plugs.items():
            if isinstance(value, str):
                host = value
                raw_aliases = []
            elif isinstance(value, dict):
                host = value.get("host") or value.get("ip")
                raw_aliases = value.get("aliases") or []
            else:
                host = None
                raw_aliases = []
            if host:
                clean_name = normalize_name(str(name))
                aliases = tuple(
                    normalize_name(str(alias))
                    for alias in raw_aliases
                    if str(alias).strip()
                )
                plugs[clean_name] = PlugConfig(name=clean_name, host=str(host), aliases=aliases)
    elif isinstance(raw_plugs, list):
        for item in raw_plugs:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("alias")
            host = item.get("host") or item.get("ip")
            raw_aliases = item.get("aliases") or []
            if name and host:
                clean_name = normalize_name(str(name))
                aliases = tuple(
                    normalize_name(str(alias))
                    for alias in raw_aliases
                    if str(alias).strip()
                )
                plugs[clean_name] = PlugConfig(name=clean_name, host=str(host), aliases=aliases)
    return plugs


def normalize_name(value: str) -> str:
    return value.strip().lower().replace(" ", "-").replace("_", "-")


def _load_credentials(username: str | None, password: str | None) -> list[KasaCredential]:
    credentials: list[KasaCredential] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, maybe_username: str | None, maybe_password: str | None) -> None:
        if not maybe_username or not maybe_password:
            return
        key = (maybe_username, maybe_password)
        if key in seen:
            return
        seen.add(key)
        credentials.append(KasaCredential(label=label, username=maybe_username, password=maybe_password))

    add("default", username, password)

    # Optional support for multiple TP-Link/Kasa passwords. This is useful when
    # plugs were onboarded before and after a TP-Link account password change;
    # the device-local KLAP credentials may not update on older plugs.
    for index in range(2, 11):
        add(
            f"extra-{index}",
            os.environ.get(f"KASA_USERNAME_{index}") or username,
            os.environ.get(f"KASA_PASSWORD_{index}") or None,
        )

    # Optional compact form for extra passwords using the same username.
    # Separator is || to avoid clashing with most password characters.
    extra_passwords = os.environ.get("KASA_EXTRA_PASSWORDS") or ""
    for offset, extra_password in enumerate(extra_passwords.split("||"), start=1):
        add(f"extra-list-{offset}", username, extra_password.strip() or None)

    return credentials


def load_settings(config_path: Path | None = None) -> Settings:
    # Load smart-plug secrets first, then Operation JARVIS and repo-root .env as fallbacks.
    # load_dotenv uses setdefault, so more local values win if several files exist.
    load_dotenv(DEFAULT_ENV_PATH)
    load_dotenv(OPERATION_ENV_PATH)
    load_dotenv(REPO_ENV_PATH)
    path = config_path or Path(os.environ.get("SMART_PLUG_CONFIG", DEFAULT_CONFIG_PATH))
    plugs = _parse_json_plugs(path)
    plugs.update(_parse_env_plugs(os.environ.get("SMART_PLUGS")))

    username = os.environ.get("KASA_USERNAME") or None
    password = os.environ.get("KASA_PASSWORD") or None
    credentials = _load_credentials(username, password)

    return Settings(
        username=username,
        password=password,
        credentials=credentials,
        discovery_target=os.environ.get("KASA_DISCOVERY_TARGET", "255.255.255.255") or "255.255.255.255",
        timeout=int(os.environ.get("KASA_TIMEOUT", "10") or "10"),
        config_path=path,
        plugs=plugs,
    )


def write_plug_config(plugs: dict[str, PlugConfig], path: Path = DEFAULT_CONFIG_PATH) -> None:
    payload = {
        "plugs": {
            name: {"host": plug.host}
            for name, plug in sorted(plugs.items())
        }
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
