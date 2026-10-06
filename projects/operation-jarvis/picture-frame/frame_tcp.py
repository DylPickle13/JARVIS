"""Optional in-process ADB transport; no host ADB server, discovery, or reconnects.

Run the entire CLI in a normally LAN-authorized Python runtime. This does not
borrow another application's permission, alter TCC, or authorize a denied adb
executable. The optional adb-shell dependency lives in private runtime storage.
"""
import contextlib
import hashlib
import importlib
import json
import logging
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import sys
import threading
import uuid

from frame_control import (Adb, AdbError, FrameError, LEGACY_LAN_WARNING, MAX_PHOTO_BYTES,
                           PIN_FIELDS, PROPERTIES, validate_legacy_approval, validate_serial)

ARCHIVE_SHA256 = "04c305f30a2ca25d5c54b3cd6ce9bb64c36e5f07967b23b3fb6aaecc851b90b6"
ARCHIVE_URL = ("https://files.pythonhosted.org/packages/8f/73/"
               "d246034db6f3e374dad9a35ee3f61345a6b239d4febd2a41ab69df9936fe/"
               "adb_shell-0.4.4.tar.gz")


def owned_path(path, directory=False, private=True):
    """No symlinks, special files, foreign ownership, or shared private files."""
    try:
        info = path.lstat()
    except OSError:
        raise FrameError("Required private TCP dependency/key is missing; do not generate a replacement key.") from None
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.getuid():
        raise FrameError("TCP dependency/key must be a real owner-controlled file/directory.")
    if private and stat.S_IMODE(info.st_mode) & 0o077:
        raise FrameError("Private TCP dependency/key permissions must exclude group and other access.")
    if not private and stat.S_IMODE(info.st_mode) & 0o022:
        raise FrameError("Public key must not be writable by group/others.")


def load_dependencies(directory):
    """Verify the pinned private source installation before importing code."""
    owned_path(directory.parent, directory=True)
    owned_path(directory, directory=True)
    manifest_path = directory / "installed.json"
    owned_path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text())
        files = manifest["files"]
        if manifest["archive_sha256"] != ARCHIVE_SHA256 or not isinstance(files, dict) or not files:
            raise ValueError
        found = {str(path.relative_to(directory)) for path in directory.rglob("*")
                 if path.is_file() and path != manifest_path}
        if found != set(files):
            raise ValueError
        for name, digest in files.items():
            parts = Path(name).parts
            if not parts or Path(name).is_absolute() or any(part in (".", "..") for part in parts):
                raise ValueError
            path = directory / name
            for parent in path.parents:
                if parent == directory:
                    break
                owned_path(parent, directory=True)
            owned_path(path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError
        for path in directory.rglob("*"):
            if path.is_dir():
                owned_path(path, directory=True)
        # Do not accept an already-imported unrelated installation.
        existing = sys.modules.get("adb_shell")
        if existing is not None and Path(existing.__file__).parent != directory / "adb_shell":
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError):
        raise FrameError("TCP dependency installation is invalid/changed; inspect it, do not reinstall automatically.") from None
    sys.path.insert(0, str(directory))
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        device_module = importlib.import_module("adb_shell.adb_device")
        auth_module = importlib.import_module("adb_shell.auth.sign_cryptography")
        # Third-party packet DEBUG logs can expose command/photo/key material.
        logging.getLogger("adb_shell").disabled = True
        device_module._LOGGER.disabled = True
        return device_module.AdbDeviceTcp, auth_module.CryptographySigner
    except (ImportError, AttributeError):
        raise FrameError("Optional TCP backend requires the reviewed adb-shell source and cryptography in this runtime.") from None
    finally:
        sys.dont_write_bytecode = previous_bytecode
        sys.path.remove(str(directory))


@contextlib.contextmanager
def deadline(seconds):
    """Hard total operation deadline, including FileSync/EOF waits; CLI only."""
    if threading.current_thread() is not threading.main_thread():
        raise FrameError("Direct TCP transport requires a main-thread CLI process for bounded deadlines.")
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL)
    if timer[0] or timer[1]:
        raise FrameError("Another process timer is active; no TCP operation started.")

    def expired(signum, frame):
        raise TimeoutError("Direct TCP deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class DirectTcpAdb(Adb):
    """Adb-compatible, exact-target transport. Construction performs no I/O."""
    backend = "direct_tcp"

    def __init__(self, dependencies, key=None, factory=None, signer_factory=None):
        self.dependencies = Path(dependencies).expanduser().absolute()
        self.key = Path(key or Path.home() / ".android/adbkey").expanduser().absolute()
        self.factory = factory
        self.signer_factory = signer_factory
        self.device = None
        self.serial = None
        self.failed = False

    def devices(self):
        raise FrameError("Direct TCP never discovers devices. Inspect USB devices with the platform-tools backend.")

    @staticmethod
    def reject_new_authorization(unused):
        raise FrameError("Existing Mac ADB key was not accepted. Inspect frame authorization; no new key request was sent.")

    def _connect(self, serial):
        validate_serial(serial)
        if ":" not in serial:
            raise FrameError("Direct TCP requires ONE literal private-LAN IPv4:port; USB is not a fallback.")
        if self.failed:
            raise FrameError("This TCP session failed; no automatic reconnect/replay.")
        if self.device is not None:
            if serial != self.serial:
                raise FrameError("A TCP session cannot change its exact target.")
            return
        if self.factory is None:
            self.factory, self.signer_factory = load_dependencies(self.dependencies)
        owned_path(self.key.parent, directory=True, private=False)
        owned_path(self.key)
        owned_path(Path(str(self.key) + ".pub"), private=False)
        raw_signer = self.signer_factory(str(self.key))

        class ExistingKeySigner:
            signed = False

            def Sign(self, challenge):
                signature = raw_signer.Sign(challenge)
                self.signed = True
                return signature

            def GetPublicKey(self):
                raise FrameError("Existing Mac ADB key was not accepted; no new key request was sent.")

        signer = ExistingKeySigner()
        host, port = serial.rsplit(":", 1)
        self.serial = serial
        self.device = self.factory(host, int(port), default_transport_timeout_s=5,
                                   banner=b"jarvis-picture-frame")
        if not self.device.connect(rsa_keys=[signer], transport_timeout_s=5,
                                   auth_timeout_s=10, read_timeout_s=10,
                                   auth_callback=self.reject_new_authorization):
            raise FrameError("Direct TCP ADB authentication was not confirmed.")
        if not signer.signed:
            raise FrameError("TCP peer did not request existing-key RSA authentication; connection rejected.")

    def close(self):
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
        # Closing is terminal for this instance, not permission to reconnect.
        self.failed = True

    def call(self, args, serial=None, binary=False, timeout=20, allowed=(0,)):
        args = list(args)
        # Validate supported operations before loading a key or opening a socket.
        state = args == ["get-state"]
        shell = len(args) == 2 and args[0] == "shell"
        capture = args == ["exec-out", "screencap", "-p"] and binary
        push = len(args) == 3 and args[0] == "push" and not binary
        if not (state or shell or capture or push):
            raise FrameError("Unsupported direct TCP operation; no generic ADB server/API or device fallback.")
        if shell and binary:
            raise FrameError("Binary TCP output is limited to the private screenshot operation.")
        if push:
            source = Path(args[1])
            owned_path(source)
            if not 0 < source.stat().st_size <= MAX_PHOTO_BYTES:
                raise FrameError("TCP push requires a bounded staged regular photo.")
            if not re.fullmatch(r"/sdcard/DCIM/jarvis-[0-9a-f]{64}\.(?:png|jpg)\.part", args[2]):
                raise FrameError("TCP push is limited to this controller's exact staged DCIM path.")
        try:
            with deadline(timeout):
                self._connect(serial)
                if state:
                    return "device"
                if capture:
                    return self.device.exec_out("screencap -p", decode=False,
                                                transport_timeout_s=5, read_timeout_s=timeout,
                                                timeout_s=timeout)
                if push:
                    self.device.push(args[1], args[2], st_mode=0o100644,
                                     transport_timeout_s=5, read_timeout_s=timeout)
                    return "staged FileSync transfer completed"
                # Shell v1 has no reliable native exit status. Capture it explicitly;
                # missing/corrupt markers fail closed, including test -d and mv -n.
                marker = "JARVIS_EXIT_" + uuid.uuid4().hex
                # This Android build's printf %d emits an invalid large integer;
                # echo the shell's actual decimal status without numeric formatting.
                command = ("sh -c " + shlex.quote(args[1]) + "; _jarvis_status=$?; echo; echo \"" +
                           marker + ':$_jarvis_status"')
                output = self.device.shell(command, decode=False, transport_timeout_s=5,
                                           read_timeout_s=timeout, timeout_s=timeout)
                match = re.search(b"\n" + marker.encode() + rb":([0-9]{1,3})\r?\n$", output)
                if not match or int(match.group(1)) not in allowed:
                    raise AdbError("TCP shell status missing/nonzero. Inspect pending state; no automatic retry.")
                return output[:match.start()].decode("utf-8", errors="replace").strip()
        except FrameError:
            self.close()
            raise
        except Exception:
            self.close()
            # Never leak endpoints, key material, filenames, packets, or raw exceptions.
            raise AdbError("Direct TCP ADB failed/deadline exceeded. Inspect authorization/pending state; no replay.") from None


class LegacyLanAdb(DirectTcpAdb):
    """Separate owner-authorized legacy policy, not a relaxation of RSA TCP mode.

    Approval must bind this exact private endpoint, package and every build pin.
    No host key is read/sent. If firmware requests authentication, fail closed and
    require the authenticated transport; there is no downgrade/fallback.
    """
    backend = "legacy_lan"
    security_warning = LEGACY_LAN_WARNING

    def __init__(self, dependencies, approval, factory=None):
        super().__init__(dependencies, factory=factory)
        # Keep caller mutations from changing an established session's scope.
        self.approval = json.loads(json.dumps(approval)) if isinstance(approval, dict) else approval
        self.identity_verified = False

    def _validate_scope(self, serial):
        approval = self.approval if isinstance(self.approval, dict) else {}
        validate_legacy_approval(approval, serial, approval.get("package"), approval.get("identity"))

    def _connect(self, serial):
        self._validate_scope(serial)
        if self.failed:
            raise FrameError("This legacy LAN session failed; no automatic reconnect/replay.")
        if self.device is not None:
            if self.serial != serial:
                raise FrameError("Legacy LAN cannot change its explicitly approved endpoint.")
            return
        if self.factory is None:
            self.factory, unused_signer = load_dependencies(self.dependencies)
        host, port = serial.rsplit(":", 1)
        self.serial = serial
        self.device = self.factory(host, int(port), default_transport_timeout_s=5,
                                   banner=b"jarvis-picture-frame-legacy-lan")
        if not self.device.connect(rsa_keys=[], transport_timeout_s=5, auth_timeout_s=10,
                                   read_timeout_s=10, auth_callback=self.reject_new_authorization):
            raise FrameError("Legacy LAN connection was not confirmed; no automatic retry.")

    def call(self, args, serial=None, **kwargs):
        self._validate_scope(serial)
        args = list(args)
        if not self.identity_verified:
            properties = set(PROPERTIES.values()) | {"ro.boot.serialno"}
            safe_shell = {shlex.join(("getprop", prop)) for prop in properties} | {"pm list packages"}
            if args != ["get-state"] and not (len(args) == 2 and args[0] == "shell" and args[1] in safe_shell):
                raise FrameError("Legacy LAN identity/package must match approval before control/content access.")
        return super().call(args, serial=serial, **kwargs)

    def probe(self, serial, package=None):
        self._validate_scope(serial)
        self.identity_verified = False
        expected_package = self.approval["package"]
        if package is not None and package != expected_package:
            raise FrameError("Legacy LAN package differs from owner approval.")
        try:
            actual = super().probe(serial, expected_package)
            if any(actual["identity"].get(field) != self.approval["identity"][field] for field in PIN_FIELDS):
                raise FrameError("Legacy LAN device/build differs from owner approval; no control dispatched.")
            self.identity_verified = True
            return actual
        except FrameError:
            self.close()
            raise

    def close(self):
        self.identity_verified = False
        super().close()
