#!/usr/bin/env python3
"""One read-only availability check for the already-approved, pinned LAN frame.

No control/status/photo operations, discovery, USB/key fallback or retries.
Default invocation is a no-I/O dry-run; only --check performs the explicit read.
Run in the same normally LAN-approved Python runtime as the frame controller.
"""
import argparse
import json


def check_frame(config_path=None):
    # Deferred imports preserve the no-contact/no-state/no-dependency dry-run.
    from frame_control import Controller, DEFAULT_CONFIG, AdbError, FrameError
    from frame_tcp import LegacyLanAdb, owned_path
    from pathlib import Path

    config_path = Path(config_path if config_path is not None else DEFAULT_CONFIG)
    try:
        # Monitoring must never pair or create missing commissioning state.
        owned_path(config_path.parent, directory=True)
        owned_path(config_path)
        owned_path(config_path.parent / "controller.lock")
        local = Controller(None, config_path)
        with local.lock():
            config = local.config()
            if config.get("adb_backend") != "legacy_lan":
                return {"ok": None, "reason": "transport_unavailable"}
            transport = LegacyLanAdb(local.runtime / "tcp-deps", config["legacy_lan_approval"])
            try:
                # Only the existing identity/package probe; do not call status(),
                # which additionally reads display/brightness/pending-write data.
                Controller(transport, config_path).checked(config)
                return {"ok": True, "reason": None}
            except AdbError:
                return {"ok": False, "reason": "read_failed"}
            except FrameError:
                # Wrong identity, dependency/consent failures do not prove outage.
                return {"ok": None, "reason": "identity_unverified"}
            finally:
                transport.close()
    except FrameError as exc:
        busy = str(exc) == "Another picture-frame command is running; no action was dispatched."
        return {"ok": None, "reason": "device_busy" if busy else "configuration_unavailable"}
    except Exception:
        return {"ok": None, "reason": "check_failed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.check:
        return {"status": "dry_run", "operation": "frame-availability",
                "device_contacted": False, "runtime_read": False}
    return check_frame()


if __name__ == "__main__":
    # Never expose raw exceptions, endpoints, fingerprints or private paths.
    try:
        result = main()
    except Exception:
        result = {"ok": None, "reason": "check_failed"}
    print(json.dumps(result, sort_keys=True))
