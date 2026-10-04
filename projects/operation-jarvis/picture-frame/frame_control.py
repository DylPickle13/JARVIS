"""Local-only Frameo commissioning/controller. Python 3.9+, standard library only.

No server, root, database edits, device auto-selection, arbitrary shell, or retries.
ADB identity properties are a safety fence, not cryptographic device attestation.
"""
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import struct
import subprocess
import tempfile
import uuid

DEFAULT_CONFIG = Path.home() / "Library/Application Support/JARVIS/picture-frame/config.json"
MAX_PHOTO_BYTES = 50 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PACKAGE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
SERIAL_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
PROPERTIES = {
    "hardware_serial": "ro.serialno",
    "manufacturer": "ro.product.manufacturer",
    "model": "ro.product.model",
    "build_fingerprint": "ro.build.fingerprint",
}
PIN_FIELDS = tuple(PROPERTIES)


class FrameError(Exception):
    pass


class AdbError(FrameError):
    pass


def validate_serial(serial):
    if not isinstance(serial, str) or not SERIAL_RE.fullmatch(serial) or serial.startswith("-"):
        raise FrameError("Supply an exact ADB serial from devices; no automatic selection.")
    if ":" in serial:
        # Network transport is deliberately restricted to literal RFC1918 IPv4.
        try:
            host, port = serial.rsplit(":", 1)
            ip = ipaddress.IPv4Address(host)
            allowed = any(ip in ipaddress.ip_network(net) for net in (
                "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
            if not allowed or not port.isdecimal() or not 1 <= int(port) <= 65535:
                raise ValueError
        except ValueError:
            raise FrameError("Network serial must be a private-LAN IPv4:port, not a public host.") from None
    return serial


def validate_package(package):
    if not isinstance(package, str) or not PACKAGE_RE.fullmatch(package):
        raise FrameError("Invalid Android package name; use the exact Frameo package from probe.")
    if "frameo" not in package.lower().split("."):
        raise FrameError("Only a package with a Frameo namespace component may be paired.")
    return package


class Adb:
    def __init__(self, executable="adb", runner=None):
        self.executable = executable
        self.runner = runner or subprocess.run

    def call(self, args, serial=None, binary=False, timeout=20, allowed=(0,)):
        command = [self.executable]
        if serial is not None:
            command += ["-s", validate_serial(serial)]
        command += list(args)
        try:
            result = self.runner(command, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise AdbError("ADB deadline exceeded. Do not replay a dispatched write; inspect pending state.") from None
        except OSError:
            raise AdbError("ADB unavailable. Install Android platform-tools or pass --adb PATH.") from None
        if result.returncode not in allowed:
            # Raw ADB output can include filenames, endpoints, and unrelated device data.
            raise AdbError("ADB command failed. A dispatched write may have an unknown outcome; do not retry.")
        output = result.stdout
        if binary:
            return output
        return output.decode("utf-8", errors="replace").strip()

    def shell(self, serial, *args):
        # Android's shell also needs quoting: local argv alone is insufficient.
        return self.call(["shell", shlex.join(str(arg) for arg in args)], serial=serial)

    def devices(self):
        output = self.call(["devices", "-l"])
        devices = []
        for line in output.splitlines():
            if not line.strip() or line.startswith(("List of devices", "*")):
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append({"serial": parts[0], "state": parts[1]})
        return devices

    def probe(self, serial, package=None):
        validate_serial(serial)
        if package is not None:
            validate_package(package)
        if self.call(["get-state"], serial=serial) != "device":
            raise FrameError("Selected target is not authorized/online. Check its USB authorization prompt.")
        identity = {name: self.shell(serial, "getprop", prop) for name, prop in PROPERTIES.items()}
        if not identity["hardware_serial"]:
            identity["hardware_serial"] = self.shell(serial, "getprop", "ro.boot.serialno")
        packages = self.shell(serial, "pm", "list", "packages")
        candidates = sorted({line[8:] for line in packages.splitlines()
                             if line.startswith("package:") and
                             "frameo" in line[8:].lower().split(".")})
        if package is not None and package not in candidates:
            raise FrameError("Configured Frameo package is not installed on the selected target.")
        return {"serial": serial, "identity": identity, "frameo_packages": candidates}


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise FrameError("Private runtime directory must be a real directory.")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise FrameError("Use a dedicated owner-only runtime directory (0700), not a shared source directory.")


def save_json(path, value):
    private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".frame-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Persist pending markers/config replacements before any hardware write.
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    try:
        with path.open() as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError):
        raise FrameError("Private JSON state is missing or invalid; do not overwrite it blindly.") from None


def validate_identity(identity):
    if not isinstance(identity, dict):
        raise FrameError("Missing pinned identity.")
    for field in PIN_FIELDS:
        value = identity.get(field)
        if not isinstance(value, str) or not value.strip() or value.lower() in ("unknown", "null"):
            raise FrameError("Identity property is missing/unknown: " + field + ". Review the device manually.")


def png_dimensions(data):
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise FrameError("Device did not return a PNG screenshot.")
    width, height = struct.unpack(">II", data[16:24])
    if not (1 <= width <= 8192 and 1 <= height <= 8192):
        raise FrameError("Unexpected screenshot dimensions.")
    return width, height


def display_state(power):
    # Prefer explicit display state; awake CPUs alone do not prove the screen is on.
    match = re.search(r"(?:Display Power: state=|mScreenState=)(ON|OFF|DOZE)\b", power)
    if match:
        return {"ON": True, "OFF": False, "DOZE": None}[match.group(1)]
    match = re.search(r"mWakefulness=(Awake|Asleep|Dozing|Dreaming)\b", power)
    if match:
        return {"Awake": True, "Asleep": False, "Dozing": None, "Dreaming": None}[match.group(1)]
    return None


class Controller:
    def __init__(self, adb, config=DEFAULT_CONFIG):
        self.adb = adb
        self.config_path = Path(config).expanduser().absolute()
        self.runtime = self.config_path.parent
        self.pending_path = self.runtime / "pending.json"
        self.uploads_path = self.runtime / "uploads.json"

    @contextlib.contextmanager
    def lock(self):
        private_directory(self.runtime)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.runtime / "controller.lock", flags, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise FrameError("Another picture-frame command is running; no action was dispatched.") from None
            yield
        finally:
            os.close(fd)

    def config(self):
        config = read_json(self.config_path)
        if config.get("schema_version") != 1:
            raise FrameError("Unsupported configuration version.")
        validate_serial(config.get("serial"))
        validate_package(config.get("package"))
        validate_identity(config.get("identity"))
        return config

    def checked(self, config):
        actual = self.adb.probe(config["serial"], config["package"])
        if any(actual["identity"].get(field) != config["identity"][field] for field in PIN_FIELDS):
            raise FrameError("Pinned device/build identity changed. No write; review firmware/transport manually.")
        return actual

    def pair(self, serial, package, apply=False):
        validate_serial(serial)
        validate_package(package)
        if not apply:
            return {"status": "dry_run", "operation": "pair", "device_contacted": False}
        with self.lock():
            if self.config_path.exists() or self.config_path.is_symlink() or self.pending_path.exists():
                raise FrameError("Existing pairing/pending state will not be replaced. Review it manually.")
            probe = self.adb.probe(serial, package)
            validate_identity(probe["identity"])
            config = {"schema_version": 1, "serial": serial,
                      "package": package, "identity": probe["identity"]}
            save_json(self.config_path, config)
            return {"status": "paired", "hardware_changed": False, "config": str(self.config_path)}

    def status(self):
        with self.lock():
            config = self.config()
            self.checked(config)
            serial = config["serial"]
            brightness = self.adb.shell(serial, "settings", "get", "system", "screen_brightness")
            mode = self.adb.shell(serial, "settings", "get", "system", "screen_brightness_mode")
            power = self.adb.shell(serial, "dumpsys", "power")
            return {"status": "read", "identity_matches": True,
                    "screen_on": display_state(power),
                    "android_brightness_setting": int(brightness) if brightness.isdecimal() else None,
                    "brightness_mode": {"0": "manual", "1": "automatic"}.get(mode, "unknown"),
                    "pending": read_json(self.pending_path) if self.pending_path.exists() else None,
                    "physical_acceptance": "not_verified"}

    def _begin(self, operation):
        if self.pending_path.exists():
            raise FrameError("An earlier write is pending/unknown. Inspect the frame and resolve-pending; do not retry.")
        save_json(self.pending_path, {"operation": operation, "outcome": "pending_or_unknown"})

    def _finish(self):
        self.pending_path.unlink()
        directory_fd = os.open(self.runtime, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def resolve_pending(self, apply=False):
        if not apply:
            return {"status": "dry_run", "operation": "resolve-pending", "device_contacted": False}
        with self.lock():
            if not self.pending_path.exists():
                return {"status": "no_pending_write", "device_contacted": False}
            previous = read_json(self.pending_path)
            save_json(self.runtime / "last-resolved.json", previous)
            self._finish()
            return {"status": "pending_acknowledged", "device_contacted": False,
                    "note": "Acknowledgement is not verification; no action was replayed."}

    def use_transport(self, serial, apply=False):
        validate_serial(serial)
        if not apply:
            return {"status": "dry_run", "operation": "use-transport", "device_contacted": False}
        with self.lock():
            if self.pending_path.exists():
                raise FrameError("Resolve the pending write before changing transport.")
            config = self.config()
            candidate = {**config, "serial": serial}
            self.checked(candidate)
            save_json(self.config_path, candidate)
            return {"status": "transport_updated", "hardware_changed": False}

    def screenshot(self, apply=False):
        if not apply:
            return {"status": "dry_run", "operation": "screenshot", "device_contacted": False}
        with self.lock():
            config = self.config()
            self.checked(config)
            data = self.adb.call(["exec-out", "screencap", "-p"], serial=config["serial"], binary=True)
            width, height = png_dimensions(data)
            directory = self.runtime / "screenshots"
            private_directory(directory)
            output = directory / (uuid.uuid4().hex + ".png")
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            return {"status": "captured", "output": str(output), "width": width, "height": height,
                    "note": "Private screenshot may contain family photos; do not publish."}

    def control(self, action, value=None, apply=False, slideshow_ready=False):
        if action not in ("wake", "sleep", "brightness", "next", "previous", "wifi-enable"):
            raise FrameError("Unsupported control.")
        if action == "brightness" and (type(value) is not int or not 0 <= value <= 255):
            raise FrameError("Brightness must be an integer from 0 through 255.")
        if action == "wifi-enable" and (type(value) is not int or not 1024 <= value <= 65535):
            raise FrameError("Wireless ADB port must be 1024 through 65535.")
        if not apply:
            return {"status": "dry_run", "operation": action, "value": value, "device_contacted": False}
        if action in ("next", "previous") and not slideshow_ready:
            raise FrameError("Navigation is experimental: confirm the visible slideshow with --slideshow-ready.")
        with self.lock():
            if self.pending_path.exists():
                raise FrameError("An earlier write is pending/unknown. Inspect and resolve-pending first.")
            config = self.config()
            self.checked(config)
            serial = config["serial"]
            commands = []
            if action == "wifi-enable":
                if ":" in serial:
                    raise FrameError("Enable wireless ADB only while using the verified USB transport.")
            elif action in ("wake", "sleep"):
                commands = [("input", "keyevent", "224" if action == "wake" else "223")]
            elif action == "brightness":
                commands = [("settings", "put", "system", "screen_brightness_mode", "0"),
                            ("settings", "put", "system", "screen_brightness", str(value))]
            else:
                window = self.adb.shell(serial, "dumpsys", "window", "windows")
                focus = re.search(r"mCurrentFocus=.*?\s([A-Za-z0-9_.]+)/", window)
                if not focus or focus.group(1) != config["package"]:
                    raise FrameError("Frameo is not the focused app; no swipe was dispatched.")
                # Measure the actual rotated display. Keep image bytes in memory only.
                data = self.adb.call(["exec-out", "screencap", "-p"], serial=serial, binary=True)
                width, height = png_dimensions(data)
                left, right, y = int(width * .2), int(width * .8), height // 2
                start, end = (right, left) if action == "next" else (left, right)
                commands = [("input", "swipe", start, y, end, y, "300")]
            self._begin(action)
            # A failure from here onward leaves the durable pending marker intact.
            if action == "wifi-enable":
                output = self.adb.call(["tcpip", str(value)], serial=serial)
                if "restarting in TCP mode" not in output:
                    raise FrameError("Wireless ADB response was unexpected; outcome unknown, do not retry.")
            else:
                for command in commands:
                    self.adb.shell(serial, *command)
            result = {"status": "dispatched_unverified", "operation": action,
                      "physical_acceptance": "not_verified"}
            if action in ("wake", "sleep"):
                actual = display_state(self.adb.shell(serial, "dumpsys", "power"))
                if actual is not (action == "wake"):
                    raise FrameError("Display readback is unknown/different; inspect pending state, do not retry.")
                result.update(status="android_state_verified", screen_on=actual)
            elif action == "brightness":
                actual = self.adb.shell(serial, "settings", "get", "system", "screen_brightness")
                mode = self.adb.shell(serial, "settings", "get", "system", "screen_brightness_mode")
                if actual != str(value) or mode != "0":
                    raise FrameError("Brightness readback did not match; inspect pending state, do not retry.")
                result.update(status="android_setting_verified", android_brightness_setting=value)
            self._finish()
            return result

    def upload(self, source, apply=False, import_ready=False):
        source = Path(source).expanduser()
        suffix = source.suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png"):
            raise FrameError("Initial uploader accepts JPEG/PNG only; convert HEIC before use.")
        if not apply:
            return {"status": "dry_run", "operation": "upload", "device_contacted": False,
                    "note": "No file read/transferred. --import-ready is required to apply."}
        if not import_ready:
            raise FrameError("First enable Transfer from computer on the frame; confirm with --import-ready.")
        if not source.is_file():
            raise FrameError("Photo source must be a regular file.")
        with self.lock():
            if self.pending_path.exists():
                raise FrameError("An earlier write is pending/unknown. Inspect and resolve-pending first.")
            config = self.config()
            self.checked(config)
            serial = config["serial"]
            with tempfile.TemporaryDirectory(prefix="photo-", dir=self.runtime) as temporary:
                staged = Path(temporary) / ("photo.png" if suffix == ".png" else "photo.jpg")
                digest = hashlib.sha256()
                size = 0
                with source.open("rb") as reader, staged.open("xb") as writer:
                    os.chmod(staged, 0o600)
                    while True:
                        chunk = reader.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_PHOTO_BYTES:
                            raise FrameError("Photo exceeds the 50 MiB commissioning limit.")
                        digest.update(chunk)
                        writer.write(chunk)
                with staged.open("rb") as stream:
                    header = stream.read(32)
                if suffix == ".png":
                    if not header.startswith(PNG_SIGNATURE):
                        raise FrameError("File extension/content mismatch; expected PNG.")
                elif not header.startswith(b"\xff\xd8\xff"):
                    raise FrameError("File extension/content mismatch; expected JPEG.")
                content_hash = digest.hexdigest()
                uploads = read_json(self.uploads_path) if self.uploads_path.exists() else {}
                if content_hash in uploads:
                    raise FrameError("This photo was already transferred; no duplicate dispatched.")
                # Do not create guessed Frameo directories or modify its private database.
                self.adb.shell(serial, "test", "-d", "/sdcard/DCIM")
                extension = "png" if suffix == ".png" else "jpg"
                remote = "/sdcard/DCIM/jarvis-" + content_hash + "." + extension
                # Do not expose a half-transferred JPEG/PNG to Frameo's importer.
                partial = remote + ".part"
                exists = self.adb.shell(serial, "sh", "-c", "if [ -e " + shlex.quote(remote) +
                                        " ] || [ -e " + shlex.quote(partial) +
                                        " ]; then printf exists; else printf absent; fi")
                if exists != "absent":
                    raise FrameError("Remote final/staging file exists or cannot be checked; no overwrite dispatched.")
                self._begin("upload")
                self.adb.call(["push", str(staged), partial], serial=serial, timeout=120)
                count = self.adb.shell(serial, "wc", "-c", partial).split()
                if not count or count[0] != str(size):
                    raise FrameError("Staged byte-count readback did not match; inspect pending state, do not retry.")
                # -n forbids clobbering, even if another process created the final name.
                self.adb.shell(serial, "mv", "-n", partial, remote)
                remaining = self.adb.shell(serial, "sh", "-c", "if [ -e " + shlex.quote(partial) +
                                           " ]; then printf exists; else printf absent; fi")
                if remaining != "absent":
                    raise FrameError("Staging file remains after rename; inspect pending state, do not retry.")
                uploads[content_hash] = {"status": "transferred_import_unverified"}
                save_json(self.uploads_path, uploads)
                self._finish()
                return {"status": "transferred_import_unverified", "bytes": size,
                        "note": "ADB transfer succeeded; inspect the Frameo slideshow/import count. Not proof of import."}
