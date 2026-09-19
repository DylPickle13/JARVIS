"""Existing device command dispatch with explicit dependencies and write admission.

This coordinates daemon callers only. Direct CLI/tools and vendor SDK retry
behavior remain outside this process-local boundary until client convergence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import commands
from .admission import AdmissionError, WriteAdmission
from .devices import _purifier_command_data, _purifier_expectation, _purifier_id, _purifier_matches, _purifier_state
from .state import StateCoordinator


UNCERTAIN = "Command outcome could not be confirmed; refresh before another change."


@dataclass(frozen=True)
class WriteTarget:
    subsystem: str
    device_id: str
    resource: tuple[str, str] = field(repr=False)
    params: dict = field(repr=False)


class DeviceCommandDispatcher:
    def __init__(self, *, state: StateCoordinator, admission: WriteAdmission,
                 cli: Path, run: Callable, selected_purifier: Callable[[str], str],
                 purifier_wait_seconds: float):
        self.state = state
        self.admission = admission
        self.cli = cli
        self.run = run
        self.selected_purifier = selected_purifier
        self.purifier_wait_seconds = purifier_wait_seconds

    def _target(self, action: str, params: dict) -> WriteTarget:
        snapshot = self.state.snapshot()["subsystems"]
        if commands.COMMANDS[action].integration == "plugs":
            name = commands._plug_name(params).lower()
            item = snapshot.get("plugs", {}).get("plugs", {}).get(name, {})
            host = item.get("host")
            if not isinstance(host, str) or not host.strip():
                raise AdmissionError("Refresh the configured plug list before a change; nothing was sent.")
            return WriteTarget("plugs", name, ("plugs", host.strip().lower()), {**params, "plug": name})
        if action == "purifier-set":
            collection = snapshot.get("purifier", {})
            device_id = (commands._require_str(params, "deviceID") if "deviceID" in params
                         else collection.get("defaultDeviceID"))
            if not isinstance(device_id, str) or device_id not in collection.get("devices", {}):
                raise AdmissionError("Refresh the configured purifier list before a change; nothing was sent.")
            # Pin the default alias to the same opaque identity and explicit
            # selector as selected-device calls; never let the CLI re-resolve it.
            return WriteTarget("purifier", device_id, ("purifier", device_id), {**params, "deviceID": device_id})
        raise commands.CommandError("unsupported write integration")

    def _run(self, action: str, argv: list[str]) -> dict:
        env = None
        if action in {"purifier-set", "purifier-status"}:
            env = {"JARVIS_AIR_PURIFIER_WRITE_WAIT_SECONDS": f"{self.purifier_wait_seconds:g}"}
        try:
            result = self.run(argv, timeout=commands.COMMANDS[action].timeout_seconds, env=env)
        except Exception:
            return {"ok": False, "error": UNCERTAIN}
        return result if isinstance(result, dict) else {"ok": False, "error": UNCERTAIN}

    def _apply_write(self, target: WriteTarget, action: str, observation: dict, result: dict) -> bool:
        if result.get("ok") is not True:
            return False
        if target.subsystem == "plugs":
            plug = result.get("plug")
            expected = not observation["isOn"] if action == "plug-toggle" else action == "plug-on"
            if (not isinstance(plug, dict) or plug.get("name") != target.device_id
                    or plug.get("is_on") is not expected
                    or not isinstance(plug.get("host"), str)
                    or plug["host"].strip().lower() != target.resource[1]):
                return False
            return self.state.apply_plug_result(plug)
        data = _purifier_command_data(result)
        if (not isinstance(data, dict) or not isinstance(data.get("cid"), str)
                or _purifier_id(data["cid"]) != target.device_id or not isinstance(data.get("is_on"), bool)):
            return False
        expected = _purifier_expectation(target.params)
        if data.get("verification_pending") is True and not expected:
            # No reconciliable desired-state contract exists for this setting.
            # Do not turn adapter acceptance into a fresh/confirmed cache value.
            return False
        if expected and data.get("verification_pending") is not True and not _purifier_matches(_purifier_state(data), expected):
            return False
        return self.state.apply_purifier_result(data, expected)

    def execute(self, action, params) -> dict:
        # Validate syntax without reading state or resolving a real selector.
        # Authorization is the handler's responsibility and runs before this.
        commands.build_command(action, params, cli=self.cli, selected_purifier=lambda device_id: device_id)
        params = {} if params is None else dict(params)
        spec = commands.COMMANDS[action]
        if spec.effect == "read":
            argv = commands.build_command(action, params, cli=self.cli, selected_purifier=self.selected_purifier)
            revision = self.state.capture_revision("purifier") if action == "purifier-status" else None
            result = self._run(action, argv)
            if result.get("ok") is True and action == "purifier-status":
                # A slow HTTP read must not replace a newer command result.
                self.state.apply_purifier_result(_purifier_command_data(result), read_revision=revision)
            return result

        target = self._target(action, params)
        return self._execute_write(action, target)

    def execute_bound(self, action, params, *, resource: tuple[str, str],
                      control_epoch: tuple[str, int], authorize: Callable[[], bool]) -> dict:
        """Dormant guarded entry: immutable host target, no alias/default re-resolution.

        Existing execute() behavior is unchanged. Only an explicit trusted host
        supplies this entry's epoch and final authorization probe. No callback may
        acquire an outer ownership lock while holding a state lock.
        """
        commands.build_command(action, params, cli=self.cli, selected_purifier=lambda value: value)
        spec = commands.COMMANDS[action]
        if (spec.effect != "write" or type(resource) is not tuple or len(resource) != 2
                or resource[0] != spec.integration or type(resource[1]) is not str or not resource[1]
                or type(control_epoch) is not tuple or len(control_epoch) != 2):
            raise AdmissionError("Invalid bound write")
        params = dict(params)
        device_id = (commands._plug_name(params).lower() if spec.integration == "plugs"
                     else commands._require_str(params, "deviceID"))
        if spec.integration == "plugs":
            params["plug"] = device_id
        elif resource[1] != device_id:
            raise AdmissionError("Invalid purifier binding")
        target = WriteTarget(spec.integration, device_id, resource, params)
        return self._execute_write(action, target, control_epoch=control_epoch, authorize=authorize)

    def _execute_write(self, action: str, target: WriteTarget, *, control_epoch=None, authorize=None) -> dict:
        with self.admission.hold(target.resource):
            if control_epoch is None:
                current = self._target(action, target.params)
                matches = current.resource == target.resource
            else:
                view = self.state.inspect_device(target.subsystem, target.device_id, control_epoch=control_epoch)
                matches = view["identity"] == target.resource[1] and view["epochObserved"]
            if not matches:
                raise AdmissionError("Device identity changed; refresh before a change. Nothing was sent.")
            argv = commands.build_command(action, target.params, cli=self.cli,
                                          selected_purifier=self.selected_purifier)
            if target.subsystem == "plugs":
                argv += ["--expected-host", target.resource[1]]
            else:
                selector = argv[argv.index("--purifier") + 1]
                if _purifier_id(selector) != target.device_id:
                    raise AdmissionError("Purifier identity changed; refresh before a change. Nothing was sent.")
                argv += ["--expected-cid", selector]
            if authorize is not None and authorize() is not True:
                raise AdmissionError("Device authorization is no longer valid")
            admission_args = {"identity": target.resource[1]}
            if control_epoch is not None:
                admission_args["control_epoch"] = control_epoch
            admitted = self.state.begin_device_write(target.subsystem, target.device_id, **admission_args)
            if admitted is None:
                raise AdmissionError("Fresh device readings are required before a change; nothing was sent.")
            observation, affected = admitted
            applied = False
            try:
                result = self._run(action, argv)  # Exactly one adapter invocation, never replayed.
                applied = self._apply_write(target, action, observation, result)
                if result.get("ok") is True and not applied:
                    result = {"ok": False, "error": UNCERTAIN}
            except Exception:
                result = {"ok": False, "error": UNCERTAIN}
            finally:
                self.state.finish_device_write(target.subsystem, affected,
                                               applied_to=target.device_id if applied else None)
            if applied and target.subsystem == "plugs":
                self.state.request_refresh("plugs")
            return result
