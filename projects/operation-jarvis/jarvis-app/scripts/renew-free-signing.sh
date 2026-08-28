#!/usr/bin/env bash
# Refresh JARVIS Personal Team profiles, archive one exact product, audit it,
# and install that same product on the private allowlisted iPhone and Watch.
# This script accepts no deployment arguments. Device selectors live in the
# private mode-600 config outside Git.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
STATE_DIR="${JARVIS_SIGNING_STATE_DIR:-$HOME/Library/Application Support/JARVIS/signing-renewal}"
CONFIG_FILE="${JARVIS_SIGNING_CONFIG:-$STATE_DIR/config.env}"
STATUS_FILE="$STATE_DIR/status.json"
LOCK_DIR="$STATE_DIR/run.lock"
PROFILE_DIR="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
BUNDLE_IDS=(
  "com.operation-jarvis.jarvis"
  "com.operation-jarvis.jarvis.widget"
  "com.operation-jarvis.jarvis.watchkitapp"
  "com.operation-jarvis.jarvis.watchkitapp.widget"
)

if [[ "${1:-}" == "status" && $# -eq 1 ]]; then
  if [[ -f "$STATUS_FILE" ]]; then
    cat "$STATUS_FILE"
  else
    printf '%s\n' '{"ok":true,"available":true,"phase":"idle","running":false,"message":"No renewal has run yet."}'
  fi
  exit 0
fi
if (( $# != 0 )); then
  echo "Usage: $0 [status]" >&2
  exit 2
fi

mkdir -p "$STATE_DIR" "$STATE_DIR/artifacts" "$STATE_DIR/logs" "$PROFILE_DIR"
chmod 700 "$STATE_DIR" "$STATE_DIR/artifacts" "$STATE_DIR/logs"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  if [[ -f "$LOCK_DIR/pid" ]]; then
    existing_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
      echo "A signing renewal is already running." >&2
      exit 75
    fi
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
printf '%s\n' "$$" >"$LOCK_DIR/pid"
chmod 700 "$LOCK_DIR"

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
IPHONE_INSTALLED=false
WATCH_INSTALLED=false
EXPIRES_AT=""
FAILED_STATUS_WRITTEN=0
PROFILE_REFRESH_COMPLETE=0
WORKTREE=""
RUN_DIR=""
QUARANTINE=""

write_status() {
  local phase="$1" running="$2" ok="$3" message="$4"
  python3 - "$STATUS_FILE" "$phase" "$running" "$ok" "$message" "$STARTED_AT" "$EXPIRES_AT" "$IPHONE_INSTALLED" "$WATCH_INSTALLED" "$$" <<'PY'
import datetime as dt
import json
import os
import sys
from pathlib import Path

(path_raw, phase, running_raw, ok_raw, message, started_at, expires_at,
 iphone_raw, watch_raw, pid_raw) = sys.argv[1:]
path = Path(path_raw)
now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
running = running_raw == "true"
payload = {
    "ok": ok_raw == "true",
    "available": True,
    "phase": phase,
    "running": running,
    "message": message[:300],
    "startedAt": started_at,
    "updatedAt": now,
    "expiresAt": expires_at or None,
    "iPhoneInstalled": iphone_raw == "true",
    "watchInstalled": watch_raw == "true",
    # Used only by jarvisd to suppress a duplicate process after a daemon restart.
    # jarvisd never includes this private implementation field in its response.
    "pid": int(pid_raw),
}
if not running:
    payload["completedAt"] = now
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY
}

restore_profiles() {
  [[ -n "$QUARANTINE" && -d "$QUARANTINE" ]] || return 0
  if [[ "$PROFILE_REFRESH_COMPLETE" -eq 0 ]]; then
    shopt -s nullglob
    for profile in "$QUARANTINE"/*.mobileprovision; do
      destination="$PROFILE_DIR/$(basename "$profile")"
      if [[ ! -e "$destination" ]]; then
        mv "$profile" "$destination"
      fi
    done
    shopt -u nullglob
  fi
  rm -rf "$QUARANTINE"
}

cleanup() {
  local rc=$?
  trap - ERR
  restore_profiles || true
  if [[ -n "$WORKTREE" && -d "$WORKTREE" ]]; then
    git -C "$REPO_ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || rm -rf "$WORKTREE"
  fi
  rm -rf "$LOCK_DIR"
  if [[ "$rc" -ne 0 && "$FAILED_STATUS_WRITTEN" -eq 0 ]]; then
    write_status "failed" false false "Renewal failed. Open JARVIS and try again after checking Xcode and device connectivity." || true
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit $?' ERR

fail_public() {
  FAILED_STATUS_WRITTEN=1
  write_status "failed" false false "$1"
  echo "$1" >&2
  exit 1
}

write_status "preparing" true true "Checking the Mac and allowlisted devices…"

[[ -f "$CONFIG_FILE" ]] || fail_public "Renewal is not configured on this Mac."
[[ "$(stat -f '%Lp' "$CONFIG_FILE")" == "600" ]] || fail_public "The private renewal config must have mode 600."
# shellcheck disable=SC1090
source "$CONFIG_FILE"
: "${TEAM_ID:?TEAM_ID is required}"
: "${IPHONE_COREDEVICE_ID:?IPHONE_COREDEVICE_ID is required}"
: "${IPHONE_UDID:?IPHONE_UDID is required}"
: "${WATCH_COREDEVICE_ID:?WATCH_COREDEVICE_ID is required}"
: "${WATCH_UDID:?WATCH_UDID is required}"
[[ "$TEAM_ID" =~ ^[A-Z0-9]{10}$ ]] || fail_public "The configured signing team is invalid."
[[ "$IPHONE_COREDEVICE_ID" =~ ^[0-9A-Fa-f-]{36}$ ]] || fail_public "The configured iPhone selector is invalid."
[[ "$WATCH_COREDEVICE_ID" =~ ^[0-9A-Fa-f-]{36}$ ]] || fail_public "The configured Watch selector is invalid."
[[ "$IPHONE_UDID" =~ ^[0-9A-Fa-f-]{25}$ ]] || fail_public "The configured iPhone identity is invalid."
[[ "$WATCH_UDID" =~ ^[0-9A-Fa-f-]{25}$ ]] || fail_public "The configured Watch identity is invalid."

identity_count="$(security find-identity -v -p codesigning 2>/dev/null | grep -cE '^[[:space:]]*[0-9]+\)' || true)"
[[ "$identity_count" -ge 1 ]] || fail_public "No Apple Development signing identity is available in the Mac keychain."
command -v xcodebuild >/dev/null || fail_public "Xcode command-line tools are unavailable."
command -v ideviceinstaller >/dev/null || fail_public "ideviceinstaller is unavailable on the Mac."

iphone_details="$(xcrun devicectl device info details --device "$IPHONE_COREDEVICE_ID" --timeout 60 2>/dev/null)" \
  || fail_public "The allowlisted iPhone is unavailable. Keep it unlocked and connected to the Mac."
watch_details="$(xcrun devicectl device info details --device "$WATCH_COREDEVICE_ID" --timeout 60 2>/dev/null)" \
  || fail_public "The allowlisted Apple Watch is unavailable. Keep it unlocked and near the iPhone."
grep -Fq "udid: $IPHONE_UDID" <<<"$iphone_details" || fail_public "The connected iPhone does not match the private allowlist."
grep -Fq "deviceType: iPhone" <<<"$iphone_details" || fail_public "The allowlisted iPhone selector did not resolve to an iPhone."
grep -Fq "pairingState: paired" <<<"$iphone_details" || fail_public "The allowlisted iPhone is not paired with this Mac."
grep -Fq "tunnelState: connected" <<<"$iphone_details" || fail_public "The allowlisted iPhone developer tunnel is unavailable."
grep -Fq "udid: $WATCH_UDID" <<<"$watch_details" || fail_public "The connected Watch does not match the private allowlist."
grep -Fq "deviceType: appleWatch" <<<"$watch_details" || fail_public "The allowlisted Watch selector did not resolve to an Apple Watch."
grep -Fq "pairingState: paired" <<<"$watch_details" || fail_public "The allowlisted Apple Watch is not paired with this Mac."
grep -Fq "tunnelState: connected" <<<"$watch_details" || fail_public "The allowlisted Apple Watch developer tunnel is unavailable."

run_id="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$STATE_DIR/artifacts/$run_id"
mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
BUILD_LOG="$RUN_DIR/archive.log"
AUDIT_JSON="$RUN_DIR/audit.json"
ARCHIVE_PATH="$RUN_DIR/JARVIS.xcarchive"
IPA_PATH="$RUN_DIR/JARVIS.ipa"
OLD_UUIDS="$RUN_DIR/old-profile-uuids.txt"
: >"$OLD_UUIDS"

write_status "provisioning" true true "Requesting fresh Personal Team profiles from Apple…"
QUARANTINE="$(mktemp -d "$STATE_DIR/profile-quarantine.XXXXXX")"
chmod 700 "$QUARANTINE"
shopt -s nullglob
for profile in "$PROFILE_DIR"/*.mobileprovision; do
  decoded="$(mktemp "$STATE_DIR/profile.XXXXXX.plist")"
  if security cms -D -i "$profile" >"$decoded" 2>/dev/null; then
    application_id="$(plutil -extract Entitlements.application-identifier raw -o - "$decoded" 2>/dev/null || true)"
    for bundle_id in "${BUNDLE_IDS[@]}"; do
      if [[ "$application_id" == "$TEAM_ID.$bundle_id" ]]; then
        plutil -extract UUID raw -o - "$decoded" >>"$OLD_UUIDS" 2>/dev/null || true
        mv "$profile" "$QUARANTINE/"
        break
      fi
    done
  fi
  rm -f "$decoded"
done
shopt -u nullglob

worktree_parent="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-signing-worktree.XXXXXX")"
rmdir "$worktree_parent"
WORKTREE="$worktree_parent"
git -C "$REPO_ROOT" worktree add --detach "$WORKTREE" refs/heads/main >/dev/null
APP_DIR="$WORKTREE/projects/operation-jarvis/jarvis-app"
[[ -d "$APP_DIR" ]] || fail_public "The approved JARVIS source is unavailable."
commit="$(git -C "$WORKTREE" rev-parse HEAD)"
printf '%s\n' "$commit" >"$RUN_DIR/source-commit.txt"

write_status "building" true true "Building the approved JARVIS source…"
DERIVED_DATA="$RUN_DIR/DerivedData"
if ! xcodebuild \
  -skipPackagePluginValidation \
  -project "$APP_DIR/JARVIS.xcodeproj" \
  -scheme JARVIS \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE_PATH" \
  -derivedDataPath "$DERIVED_DATA" \
  -allowProvisioningUpdates \
  -allowProvisioningDeviceRegistration \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  archive >"$BUILD_LOG" 2>&1; then
  tail -80 "$BUILD_LOG" >&2 || true
  fail_public "Xcode could not create a freshly signed JARVIS archive."
fi
rm -rf "$DERIVED_DATA"

APP_PATH="$ARCHIVE_PATH/Products/Applications/JARVIS.app"
[[ -d "$APP_PATH" ]] || fail_public "The signed archive did not contain JARVIS.app."

write_status "auditing" true true "Auditing all four profiles and signatures…"
if ! python3 - "$APP_PATH" "$AUDIT_JSON" "$TEAM_ID" "$IPHONE_UDID" "$WATCH_UDID" "$OLD_UUIDS" <<'PY'
import datetime as dt
import hashlib
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

app = Path(sys.argv[1])
audit_path = Path(sys.argv[2])
team = sys.argv[3]
required_devices = {sys.argv[4], sys.argv[5]}
old_uuids = set(Path(sys.argv[6]).read_text(encoding="utf-8").split())
products = [
    ("iPhone app", app, "com.operation-jarvis.jarvis"),
    ("iPhone widget", app / "PlugIns/JARVISWidget.appex", "com.operation-jarvis.jarvis.widget"),
    ("Watch app", app / "Watch/JARVISWatch.app", "com.operation-jarvis.jarvis.watchkitapp"),
    ("Watch widget", app / "Watch/JARVISWatch.app/PlugIns/JARVISWatchWidget.appex", "com.operation-jarvis.jarvis.watchkitapp.widget"),
]
now = dt.datetime.now(dt.timezone.utc)
minimum_expiration = now + dt.timedelta(days=6) - dt.timedelta(minutes=30)
records = []
versions = set()
for label, product, bundle_id in products:
    if not product.is_dir():
        raise SystemExit(f"missing {label}")
    info = plistlib.loads((product / "Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != bundle_id:
        raise SystemExit(f"unexpected bundle identifier for {label}")
    versions.add((str(info.get("CFBundleShortVersionString")), str(info.get("CFBundleVersion"))))
    profile_path = product / "embedded.mobileprovision"
    decoded = subprocess.run(
        ["security", "cms", "-D", "-i", str(profile_path)],
        check=True,
        capture_output=True,
    ).stdout
    profile = plistlib.loads(decoded)
    uuid = profile.get("UUID")
    creation = profile.get("CreationDate")
    expiration = profile.get("ExpirationDate")
    entitlements = profile.get("Entitlements") or {}
    teams = profile.get("TeamIdentifier") or []
    devices = set(profile.get("ProvisionedDevices") or [])
    if uuid in old_uuids:
        raise SystemExit(f"Apple reused the previous profile for {label}")
    if team not in teams or entitlements.get("application-identifier") != f"{team}.{bundle_id}":
        raise SystemExit(f"wrong signing team or application identifier for {label}")
    if not required_devices.issubset(devices):
        raise SystemExit(f"allowlisted devices are missing from {label} profile")
    if not isinstance(creation, dt.datetime) or not isinstance(expiration, dt.datetime):
        raise SystemExit(f"missing profile dates for {label}")
    creation = creation.replace(tzinfo=creation.tzinfo or dt.timezone.utc)
    expiration = expiration.replace(tzinfo=expiration.tzinfo or dt.timezone.utc)
    if creation < now - dt.timedelta(hours=6):
        raise SystemExit(f"profile for {label} was not freshly created")
    if expiration < minimum_expiration:
        raise SystemExit(f"profile for {label} has less than six days remaining")
    if "com.apple.security.application-groups" in entitlements:
        raise SystemExit(f"App Groups unexpectedly enabled for {label}")
    executable = product / str(info.get("CFBundleExecutable"))
    records.append({
        "label": label,
        "bundleIdentifier": bundle_id,
        "profileUUID": uuid,
        "creationDate": creation.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "expirationDate": expiration.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "executableSHA256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    })
if len(versions) != 1:
    raise SystemExit("product versions do not match")
subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], check=True)
audio_suffixes = {".aac", ".caf", ".m4a", ".mp3", ".wav"}
if any(path.suffix.lower() in audio_suffixes for path in app.rglob("*")):
    raise SystemExit("bundled audio is not allowed")
expires = min(record["expirationDate"] for record in records)
result = {
    "ok": True,
    "teamIdentifier": team,
    "version": next(iter(versions))[0],
    "build": next(iter(versions))[1],
    "sourceCommit": Path(audit_path.parent / "source-commit.txt").read_text(encoding="utf-8").strip(),
    "earliestExpiration": expires,
    "products": records,
}
temporary = audit_path.with_suffix(".tmp")
temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, audit_path)
print(expires)
PY
then
  fail_public "The new archive did not pass JARVIS signing and profile checks. Try again closer to expiration."
fi
EXPIRES_AT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["earliestExpiration"])' "$AUDIT_JSON")"
PROFILE_REFRESH_COMPLETE=1
restore_profiles
QUARANTINE=""

PAYLOAD_ROOT="$RUN_DIR/package"
mkdir -p "$PAYLOAD_ROOT/Payload"
/usr/bin/ditto "$APP_PATH" "$PAYLOAD_ROOT/Payload/JARVIS.app"
(
  cd "$PAYLOAD_ROOT"
  /usr/bin/ditto -c -k --sequesterRsrc --keepParent Payload "$IPA_PATH"
)
rm -rf "$PAYLOAD_ROOT"

write_status "installingIPhone" true true "Installing the renewed build on iPhone…"
if ! ideviceinstaller -u "$IPHONE_UDID" -n -w upgrade "$IPA_PATH"; then
  fail_public "The renewed archive is valid, but iPhone installation failed. Keep the iPhone unlocked and try again."
fi
IPHONE_INSTALLED=true
write_status "installingWatch" true true "Installing the same renewed build on Apple Watch…"
WATCH_APP_PATH="$APP_PATH/Watch/JARVISWatch.app"
if ! xcrun devicectl device install app --device "$WATCH_COREDEVICE_ID" "$WATCH_APP_PATH" --timeout 120; then
  fail_public "iPhone renewal succeeded, but Watch installation failed. Keep the Watch unlocked and try again."
fi
WATCH_INSTALLED=true

iphone_inventory="$RUN_DIR/iphone-inventory.json"
watch_inventory="$RUN_DIR/watch-inventory.json"
xcrun devicectl device info apps --device "$IPHONE_COREDEVICE_ID" --bundle-id com.operation-jarvis.jarvis --json-output "$iphone_inventory" --timeout 60 >/dev/null
xcrun devicectl device info apps --device "$WATCH_COREDEVICE_ID" --bundle-id com.operation-jarvis.jarvis.watchkitapp --json-output "$watch_inventory" --timeout 60 >/dev/null
python3 - "$iphone_inventory" "$watch_inventory" "$AUDIT_JSON" <<'PY'
import json
import sys

def app_record(path):
    payload = json.load(open(path, encoding="utf-8"))
    records = payload.get("result", {}).get("apps", [])
    if len(records) != 1:
        raise SystemExit("installed app inventory did not contain exactly one match")
    return records[0]

audit = json.load(open(sys.argv[3], encoding="utf-8"))
expected = str(audit["build"])
for path in sys.argv[1:3]:
    record = app_record(path)
    actual = str(record.get("bundleVersion") or record.get("version") or "")
    if actual != expected:
        raise SystemExit(f"installed build mismatch: expected {expected}, got {actual}")
PY

# Installation is authoritative; launch is best effort because either device may
# lock while the exact signed product is being transferred.
xcrun devicectl device process launch --device "$IPHONE_COREDEVICE_ID" com.operation-jarvis.jarvis --timeout 60 >/dev/null 2>&1 || true
xcrun devicectl device process launch --device "$WATCH_COREDEVICE_ID" com.operation-jarvis.jarvis.watchkitapp --timeout 60 >/dev/null 2>&1 || true

write_status "succeeded" false true "JARVIS was renewed on iPhone and Apple Watch."
printf 'JARVIS signing renewed through %s\n' "$EXPIRES_AT"
