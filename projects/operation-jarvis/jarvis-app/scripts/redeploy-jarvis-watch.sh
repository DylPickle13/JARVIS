#!/usr/bin/env bash
# Build and install the physical watch companion with free Apple ID provisioning.
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
SCHEME="JARVISWatch"
CONFIG="Debug"
BUNDLE_ID="com.operation-jarvis.jarvis.watchkitapp"
WATCH_UDID="${WATCH_UDID:-}"
TEAM_ID="${TEAM_ID:-}"
LAUNCH=1

usage() {
  cat <<'EOF'
Usage: scripts/redeploy-jarvis-watch.sh [options]

Options:
  --device UUID   install on this physical Apple Watch
  --no-launch     build and install without launching
  -h, --help      show this help

Environment:
  TEAM_ID=...     force the signing team
  WATCH_UDID=...  same as --device
EOF
}

while (($#)); do
  case "$1" in
    --device)
      [[ $# -ge 2 ]] || { echo "--device requires a UUID" >&2; exit 2; }
      WATCH_UDID="$2"; shift 2 ;;
    --no-launch) LAUNCH=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

c_green=$'\033[32m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_rst=$'\033[0m'
ok()   { echo "${c_green}✓${c_rst} $*"; }
warn() { echo "${c_yel}!${c_rst} $*"; }
die()  { echo "${c_red}✗${c_rst} $*" >&2; exit 1; }

DERIVED_DATA_PATH="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-watch-derived.XXXXXX")"
BUILD_LOG="$(mktemp "${TMPDIR:-/tmp}/jarvis-watch-build.XXXXXX")"
cleanup() {
  rm -rf "$DERIVED_DATA_PATH" "$BUILD_LOG"
}
trap cleanup EXIT

ID_COUNT=$(security find-identity -v -p codesigning 2>/dev/null | grep -cE '^[[:space:]]*[0-9]+\)' || true)
[[ "${ID_COUNT:-0}" -ge 1 ]] || die "No codesigning identity found. Sign into Xcode with the free Apple ID first."
ok "Found $ID_COUNT signing identity(ies)."

if [[ -z "$TEAM_ID" ]]; then
  TEAM_ID=$(defaults read com.apple.dt.Xcode IDEProvisioningTeamByIdentifier 2>/dev/null \
    | grep -oE 'teamID = [A-Z0-9]{10}' | head -1 | awk '{print $3}' || true)
fi
if [[ -z "$TEAM_ID" ]]; then
  TEAM_ID=$(security find-identity -v -p codesigning 2>/dev/null \
    | grep -oE '\([A-Z0-9]{10}\)' | head -1 | tr -d '()' || true)
fi
[[ -n "$TEAM_ID" ]] && ok "Using signing team: $TEAM_ID"

if [[ -z "$WATCH_UDID" ]]; then
  WATCH_LINE=$(xcrun devicectl list devices 2>/dev/null \
    | awk 'NR>2 && /Watch/ && !/unavailable/ && !/Unavailable/ {print; exit}')
  if [[ -z "$WATCH_LINE" ]]; then
    die "No available physical Apple Watch found. Keep the paired Watch unlocked, nearby, and connected to the Mac; verify Developer Mode and trust in Xcode Devices."
  fi
  WATCH_UDID=$(printf '%s\n' "$WATCH_LINE" \
    | grep -oE '[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}' \
    | head -1 || true)
  [[ -n "$WATCH_UDID" ]] || die "Could not parse a Watch UUID from: $WATCH_LINE"
  ok "Target Watch: ${WATCH_LINE#*  }"
else
  [[ "$WATCH_UDID" =~ ^[0-9A-Fa-f-]{36}$ ]] || die "Invalid Watch UUID: $WATCH_UDID"
  ok "Target Watch UUID: $WATCH_UDID"
fi

if ! xcrun devicectl device info lockState --device "$WATCH_UDID" --timeout 60 >/dev/null 2>&1; then
  die "Could not establish the Apple Watch developer tunnel. Unlock it, keep it nearby, and reconnect it in Xcode Devices."
fi
WATCH_DETAILS=$(xcrun devicectl device info details --device "$WATCH_UDID" --timeout 60 2>/dev/null || true)
if ! grep -qE 'name: Dylan.*Apple.*Watch' <<<"$WATCH_DETAILS"; then
  die "Refusing to deploy: target is not Dylan’s Apple Watch ($WATCH_UDID)."
fi
if ! grep -q 'tunnelState: connected' <<<"$WATCH_DETAILS"; then
  die "The requested Apple Watch is not available to CoreDevice. Unlock it, keep it nearby, and reconnect it in Xcode Devices."
fi
if ! grep -q 'developerModeStatus: enabled' <<<"$WATCH_DETAILS"; then
  die "Developer Mode is disabled on the Apple Watch. Enable it under Settings → Privacy & Security → Developer Mode."
fi
if ! grep -q 'ddiServicesAvailable: true' <<<"$WATCH_DETAILS"; then
  die "Apple Watch developer services are unavailable. Keep the Watch unlocked while Xcode finishes preparing it."
fi
WATCH_DEVICE_UDID=$(awk '/^[[:space:]]*• udid: / {print $3; exit}' <<<"$WATCH_DETAILS")
[[ -n "$WATCH_DEVICE_UDID" ]] || die "Could not read the physical Watch UDID from CoreDevice."
ok "Verified target identity: Dylan’s Apple Watch"
ok "Physical Watch UDID: $WATCH_DEVICE_UDID"

printf 'Building %s (%s) for watchOS device…\n' "$SCHEME" "$CONFIG"
BUILD_ARGS=(
  -project JARVIS.xcodeproj
  -scheme "$SCHEME"
  -configuration "$CONFIG"
  -destination "platform=watchOS,id=$WATCH_DEVICE_UDID"
  -derivedDataPath "$DERIVED_DATA_PATH"
  -allowProvisioningUpdates
  -allowProvisioningDeviceRegistration
  CODE_SIGN_STYLE=Automatic
)
[[ -n "$TEAM_ID" ]] && BUILD_ARGS+=("DEVELOPMENT_TEAM=$TEAM_ID")
xcodebuild "${BUILD_ARGS[@]}" build >"$BUILD_LOG" 2>&1 || {
  echo "Build failed. Last 80 lines:" >&2
  tail -80 "$BUILD_LOG" >&2
  exit 1
}
ok "Build succeeded."

WATCH_APP_PATH="$DERIVED_DATA_PATH/Build/Products/Debug-watchos/JARVISWatch.app"
[[ -d "$WATCH_APP_PATH" ]] || die "Current build did not produce $WATCH_APP_PATH"
ok "Current Watch bundle: $WATCH_APP_PATH"

printf 'Installing on Apple Watch…\n'
xcrun devicectl device install app --device "$WATCH_UDID" "$WATCH_APP_PATH"
ok "Installed."

if [[ "$LAUNCH" -eq 1 ]]; then
  if xcrun devicectl device process launch --device "$WATCH_UDID" "$BUNDLE_ID"; then
    ok "Launched $BUNDLE_ID"
  else
    warn "Installed, but launch failed — open JARVIS on the Apple Watch."
  fi
fi

ok "Done."
