"""Private vendor-subprocess adapters, configured explicitly by the worker.

No public jarvis-cli calls, discovery, plugin loading, or SDK imports. Existing
vendor environments and SDK retry behavior are retained. Paired vendor wrappers
check admitted identities and avoid wrapper-level post-send replay; this is not
a claim of end-to-end no-retry semantics. The daemon owns the outer process-group deadline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Optional
from .device_translation import (JarvisError, _purifier_device_args,
    _purifier_set_cli_args, _canon_purifier_setting, purifier_summary,
    smart_plug_status_summary, smart_plug_many_summary)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class DeviceVendorAdapter:
    def __init__(self, *, operation_root: Path, project_root: Path, env: dict[str, str], run):
        self.operation_root, self.project_root = operation_root, project_root
        self.smart_plug_dir = operation_root / "smart-plug"
        self.smart_plug_config = self.smart_plug_dir / "plugs.json"
        self.air_purifier_dir = operation_root / "air-purifier"
        self.air_purifier_cli = self.air_purifier_dir / "purifier-cli"
        self.env = env
        self.run = run

    def choose_smart_plug_python(self) -> str:
        """Use the smart-plug Python 3.11+ venv, separate from the main Python 3.9 venv."""
        candidates = [
            self.smart_plug_dir / ".venv" / "bin" / "python",
            Path("/opt/homebrew/bin/python3.13"),
            Path("/opt/homebrew/bin/python3.12"),
            Path("/opt/homebrew/bin/python3.11"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return "python3"

    def run_air_purifier_command(self, args: list[str], *, timeout: float) -> dict[str, Any]:
        if not self.air_purifier_cli.exists():
            raise JarvisError(f"Air-purifier CLI not found: {self.air_purifier_cli}")

        command = [str(self.air_purifier_cli), "--json", *args]
        result = self.run(
            command,
            cwd=str(self.air_purifier_dir),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=self.env,
        )
        stdout = strip_ansi(result.stdout).strip()
        stderr = strip_ansi(result.stderr).strip()
        data: Any
        try:
            data = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            data = {"stdout": stdout}
        if result.returncode != 0:
            message = ""
            if isinstance(data, dict):
                message = str(data.get("error") or "")
            raise JarvisError(message or stderr or stdout or f"purifier-cli exited with code {result.returncode}")
        return {
            "ok": True,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "data": data if isinstance(data, dict) else {"value": data},
        }

    def run_smart_plug_command(self, args: list[str], *, timeout: float, config_path: Optional[Path] = None, discovery_target: Optional[str] = None) -> dict[str, Any]:
        if not self.smart_plug_dir.exists():
            raise JarvisError(f"Smart-plug subsystem not found: {self.smart_plug_dir}")
        command = [
            self.choose_smart_plug_python(),
            "-m",
            "smart_plug.cli",
            "--json",
            "--config",
            str(config_path or self.smart_plug_config),
            *args,
        ]
        env = self.env.copy()
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        env.setdefault("KASA_TIMEOUT", str(max(1, int(timeout))))
        if discovery_target:
            env["KASA_DISCOVERY_TARGET"] = discovery_target

        result = self.run(
            command,
            cwd=str(self.smart_plug_dir),
            text=True,
            capture_output=True,
            timeout=timeout + 10.0,
            env=env,
        )
        stdout = strip_ansi(result.stdout).strip()
        stderr = strip_ansi(result.stderr).strip()
        payload: Any = None
        if stdout:
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = stdout
        if result.returncode != 0:
            message = stderr or stdout or f"smart-plug command exited with code {result.returncode}: {' '.join(command)}"
            if "Device response did not match our challenge" in message:
                message += " Credentials may be correct; newer Kasa/Tapo firmware can reject local third-party KLAP auth unless Third-Party Compatibility is enabled in the Kasa/Tapo app."
            raise JarvisError(message)
        return {
            "ok": True,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "data": payload,
        }

    def handle_purifier_collection(self, args: argparse.Namespace) -> dict[str, Any]:
        command = "list" if args.command == "purifier-list" else "status-all"
        cli_args = (["--retry-cooldown"] if getattr(args, "retry_cooldown", False) else []) + [command]
        result = self.run_air_purifier_command(cli_args, timeout=args.purifier_timeout)
        devices = result["data"]
        return {"ok": True, "action": args.command, "purifiers": devices,
                "discoveryOnly": command == "list",
                "summary": f"{len(devices)} purifiers: " + "; ".join(
                    f"{entry.get('status', entry).get('name', cid)}: " +
                    ("discovered (readings not refreshed)" if command == "list" else
                     purifier_summary(entry["status"]) if entry.get("ok") else "refresh failed")
                    for cid, entry in devices.items())}

    def handle_purifier_status(self, args: argparse.Namespace) -> dict[str, Any]:
        result = self.run_air_purifier_command(
            (["--retry-cooldown"] if getattr(args, "retry_cooldown", False) else []) + ["status", *_purifier_device_args(args)],
            timeout=args.purifier_timeout,
        )
        status = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": True,
            "action": "purifier-status",
            "airPurifierRoot": str(self.air_purifier_dir),
            "purifier": status,
            "summary": purifier_summary(status),
            "airPurifier": result,
        }

    def handle_purifier_set(self, args: argparse.Namespace) -> dict[str, Any]:
        cli_args = ["--expected-cid", args.expected_cid, *_purifier_set_cli_args(args)]
        result = self.run_air_purifier_command(cli_args, timeout=args.purifier_timeout)
        status = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": True,
            "action": "purifier-set",
            "setting": _canon_purifier_setting(args.setting),
            "airPurifierRoot": str(self.air_purifier_dir),
            "purifier": status,
            "summary": purifier_summary(status),
            "airPurifier": result,
        }

    def handle_plug_collection(self, args: argparse.Namespace) -> dict[str, Any]:
        result = self.run_smart_plug_command(['status-all'], timeout=8.0,
            config_path=self.smart_plug_config, discovery_target=args.discovery_target)
        plugs = result.get('data')
        if not isinstance(plugs, dict) or len(plugs) > 64:
            raise JarvisError('Invalid plug collection')
        return {'ok': True, 'action': 'plug-status-all', 'plugs': plugs}

    def handle_plug_list(self, args: argparse.Namespace) -> dict[str, Any]:
        result = self.run_smart_plug_command(
            ["list"],
            timeout=args.plug_timeout,
            config_path=self.smart_plug_config,
            discovery_target=args.discovery_target,
        )
        plugs = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": True,
            "action": "plug-list",
            "smartPlugRoot": str(self.smart_plug_dir),
            "plugs": plugs,
            "summary": smart_plug_many_summary(plugs, verb="configured"),
            "smartPlug": result,
        }

    def _handle_plug_power_action(self, args: argparse.Namespace, command: str, action: str) -> dict[str, Any]:
        cli_args = [command, args.plug]
        if action in {"plug-on", "plug-off", "plug-toggle"}:
            cli_args += ["--expected-host", args.expected_host]
        result = self.run_smart_plug_command(
            cli_args,
            timeout=args.plug_timeout,
            config_path=self.smart_plug_config,
            discovery_target=args.discovery_target,
        )
        status = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "ok": True,
            "action": action,
            "smartPlugRoot": str(self.smart_plug_dir),
            "plugName": status.get("name") or args.plug,
            "plug": status,
            "summary": smart_plug_status_summary(status),
            "smartPlug": result,
        }

    def handle_plug_status(self, args: argparse.Namespace) -> dict[str, Any]:
        return self._handle_plug_power_action(args, "status", "plug-status")

    def handle_plug_on(self, args: argparse.Namespace) -> dict[str, Any]:
        return self._handle_plug_power_action(args, "on", "plug-on")

    def handle_plug_off(self, args: argparse.Namespace) -> dict[str, Any]:
        return self._handle_plug_power_action(args, "off", "plug-off")

    def handle_plug_toggle(self, args: argparse.Namespace) -> dict[str, Any]:
        return self._handle_plug_power_action(args, "toggle", "plug-toggle")

    def handle_local_status(self, args: argparse.Namespace) -> dict[str, Any]:
        """Preserve status --no-cast using local file checks only, never a CLI."""
        if args.no_cast is not True:
            raise JarvisError("Only local status without Cast is supported")
        python = next((str(p) for p in (self.operation_root / ".venv/bin/python",
                                       self.project_root / ".venv/bin/python") if p.exists()),
                      sys.executable or "python3")
        tv_script = self.operation_root / "scripts/tv.py"
        return {
            "ok": True, "action": "status", "operationRoot": str(self.operation_root),
            "castScript": str(tv_script), "python": python,
            "checks": {
                "operationRootExists": self.operation_root.exists(),
                "castScriptExists": tv_script.exists(),
                "smartPlugSubsystemExists": self.smart_plug_dir.exists(),
                "smartPlugConfigExists": self.smart_plug_config.exists(),
                "airPurifierSubsystemExists": self.air_purifier_dir.exists(),
                "airPurifierCliExists": self.air_purifier_cli.exists(),
            },
            "smartPlug": {"root": str(self.smart_plug_dir), "config": str(self.smart_plug_config),
                          "python": self.choose_smart_plug_python(), "configured": self.smart_plug_config.exists()},
            "airPurifier": {"root": str(self.air_purifier_dir), "cli": str(self.air_purifier_cli),
                            "configured": self.air_purifier_cli.exists()},
            "summary": "Operation JARVIS local files are installed. Cast status was skipped; "
                       f"smart plugs configured={self.smart_plug_config.exists()}.",
        }
