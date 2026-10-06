#!/usr/bin/env python3
"""Install hash-pinned optional TCP source privately; dry-run makes no I/O changes.

No pip/setup.py execution, USB, ADB server, keys, photos, or frame traffic. The
CryptographySigner uses cryptography already present in the approved runtime;
RSA/pyasn1 are not used by this signer, and USB/async extras are not installed.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request

from frame_control import Controller, DEFAULT_CONFIG, FrameError, save_json
from frame_tcp import ARCHIVE_SHA256, ARCHIVE_URL


def install(config=DEFAULT_CONFIG, apply=False, fetch=None):
    if not apply:
        return {"status": "dry_run", "operation": "install_tcp_dependencies",
                "device_contacted": False, "runtime_created": False,
                "shared_virtualenv_changed": False}
    if importlib.util.find_spec("cryptography") is None:
        raise FrameError("Use the already LAN-approved Python runtime with cryptography; shared environments are not modified.")
    controller = Controller(None, config)
    target = controller.runtime / "tcp-deps"
    with controller.lock():
        if target.exists() or target.is_symlink():
            raise FrameError("TCP dependency directory already exists; no overwrite, upgrade, or automatic reinstall.")
        if fetch is None:
            def fetch():
                with urllib.request.urlopen(ARCHIVE_URL, timeout=20) as response:
                    return response.read(1024 * 1024 + 1)
        try:
            data = fetch()
        except (OSError, urllib.error.URLError):
            raise FrameError("Pinned dependency download failed; no automatic retry.") from None
        if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
            raise FrameError("TCP dependency archive digest/size did not match; no source installed.")
        staging = Path(tempfile.mkdtemp(prefix=".tcp-install-", dir=controller.runtime))
        try:
            files = {}
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                members = archive.getmembers()
                if sum(member.size for member in members) > 4 * 1024 * 1024:
                    raise FrameError("Unexpected dependency archive size.")
                for member in members:
                    parts = Path(member.name).parts
                    if (not parts or parts[0] != "adb_shell-0.4.4" or
                            any(part in (".", "..") for part in parts) or
                            not (member.isdir() or member.isfile())):
                        raise FrameError("Unexpected dependency archive path/type; no installation.")
                    # Install package source + licence only, never setup/build scripts.
                    selected = (len(parts) >= 3 and parts[1] == "adb_shell" and
                                member.isfile() and parts[-1].endswith(".py"))
                    selected = selected or (len(parts) == 2 and parts[1] == "LICENSE" and member.isfile())
                    if not selected:
                        continue
                    relative = Path(*parts[1:])
                    name = str(relative)
                    if name in files:
                        raise FrameError("Duplicate dependency archive path.")
                    output = staging / relative
                    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    for parent in output.parents:
                        if parent == staging:
                            break
                        os.chmod(parent, 0o700)
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise FrameError("Dependency member cannot be read.")
                    content = stream.read()
                    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as writer:
                        writer.write(content)
                        writer.flush()
                        os.fsync(writer.fileno())
                    files[name] = hashlib.sha256(content).hexdigest()
            required = {"adb_shell/__init__.py", "adb_shell/adb_device.py",
                        "adb_shell/auth/sign_cryptography.py", "LICENSE"}
            if not required.issubset(files):
                raise FrameError("Pinned dependency archive lacks required source/licence.")
            save_json(staging / "installed.json", {"archive_sha256": ARCHIVE_SHA256,
                                                  "version": "0.4.4", "files": files})
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return {"status": "tcp_dependency_installed", "version": "0.4.4",
                "archive_digest_verified": True, "device_contacted": False,
                "shared_virtualenv_changed": False, "build_scripts_executed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = install(args.config, apply=args.apply)
    except (FrameError, OSError, tarfile.TarError) as error:
        message = str(error) if isinstance(error, FrameError) else "Private dependency installation failed; inspect before retrying."
        print(json.dumps({"status": "error", "message": message}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
