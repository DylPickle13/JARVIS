#!/usr/bin/env bash
# Build, install, and optionally launch JARVIS on a connected physical iPhone
# using free Apple ID provisioning. The app bundle is always taken from this
# invocation's private DerivedData directory; stale builds cannot be selected.
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
SCHEME="JARVIS"
CONFIG="Debug"
BUNDLE_ID="com.operation-jarvis.jarvis"
LAUNCH=1
DEVICE_UDID="${DEVICE_UDID:-}"
TEAM_ID="${TEAM_ID:-}"

usage() {
  cat <<'EOF'
Usage: scripts/redeploy-jarvis-app.sh [options]

Options:
  --device UUID   install on this physical iPhone
  --no-launch     build and install without launching
  --clean         retained for compatibility; this script always uses clean temporary output
  -h, --help      show this help

Environment:
  TEAM_ID=...     force the signing team
  DEVICE_UDID=... same as --device
EOF
}

while (($#)); do
  case "$1" in
    --device)
      [[ $# -ge 2 ]] || { echo "--device requires a UUID" >&2; exit 2; }
      DEVICE_UDID="$2"; shift 2 ;;
    --no-launch) LAUNCH=0; shift ;;
    --clean) shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

c_green=$'\033[32m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_rst=$'\033[0m'
ok()   { echo "${c_green}✓${c_rst} $*"; }
warn() { echo "${c_yel}!${c_rst} $*"; }
die()  { echo "${c_red}✗${c_rst} $*" >&2; exit 1; }

DERIVED_DATA_PATH="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-derived.XXXXXX")"
BUILD_LOG="$(mktemp "${TMPDIR:-/tmp}/jarvis-build.XXXXXX")"
cleanup() {
  rm -rf "$DERIVED_DATA_PATH" "$BUILD_LOG"
}
trap cleanup EXIT

ID_COUNT=$(security find-identity -v -p codesigning 2>/dev/null | grep -cE '^[[:space:]]*[0-9]+\)' || true)
if [[ "${ID_COUNT:-0}" -lt 1 ]]; then
  die "No codesigning identity found. Sign into Xcode with the free Apple ID first."
fi
ok "Found $ID_COUNT signing identity(ies)."

if [[ -z "$TEAM_ID" ]]; then
  TEAM_ID=$(defaults read com.apple.dt.Xcode IDEProvisioningTeamByIdentifier 2>/dev/null \
    | grep -oE 'teamID = [A-Z0-9]{10}' | head -1 | awk '{print $3}' || true)
fi
if [[ -z "$TEAM_ID" ]]; then
  TEAM_ID=$(security find-identity -v -p codesigning 2>/dev/null \
    | grep -oE '\([A-Z0-9]{10}\)' | head -1 | tr -d '()' || true)
fi
if [[ -n "$TEAM_ID" ]]; then ok "Using signing team: $TEAM_ID"; fi

if [[ -z "$DEVICE_UDID" ]]; then
  DEVICE_LINE=$(xcrun devicectl list devices 2>/dev/null \
    | awk 'NR>2 && /iPhone/ && !/Simulator/ && !/unavailable/ && !/Unavailable/ && /Dylan/ {print; exit}')
  if [[ -z "$DEVICE_LINE" ]]; then
    DEVICE_LINE=$(xcrun devicectl list devices 2>/dev/null \
      | awk 'NR>2 && /iPhone/ && !/Simulator/ && !/unavailable/ && !/Unavailable/ {print; exit}')
  fi
  [[ -n "$DEVICE_LINE" ]] || die "No available physical iPhone found. Connect it and tap Trust This Computer."
  DEVICE_UDID=$(printf '%s\n' "$DEVICE_LINE" | grep -oE '[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}' | head -1 || true)
  [[ -n "$DEVICE_UDID" ]] || die "Could not parse a device UUID from: $DEVICE_LINE"
  ok "Target device: ${DEVICE_LINE#*  }"
else
  [[ "$DEVICE_UDID" =~ ^[0-9A-Fa-f-]{36}$ ]] || die "Invalid device UUID: $DEVICE_UDID"
  ok "Target device UUID: $DEVICE_UDID"
fi

DEVICE_DETAILS=$(xcrun devicectl device info details --device "$DEVICE_UDID" 2>/dev/null || true)
if ! grep -qE 'name: Dylan.*iPhone' <<<"$DEVICE_DETAILS"; then
  die "Refusing to deploy: target is not Dylan’s iPhone ($DEVICE_UDID)."
fi
ok "Verified target identity: Dylan’s iPhone"

printf 'Building %s (%s) for device…\n' "$SCHEME" "$CONFIG"
xcodebuild \
  -skipPackagePluginValidation \
  -project JARVIS.xcodeproj \
  -scheme "$SCHEME" \
  -configuration "$CONFIG" \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  -allowProvisioningUpdates \
  ${TEAM_ID:+DEVELOPMENT_TEAM="$TEAM_ID"} \
  CODE_SIGN_STYLE=Automatic \
  build >"$BUILD_LOG" 2>&1 || {
    echo "Build failed. Last 60 lines:" >&2
    tail -60 "$BUILD_LOG" >&2
    exit 1
  }
ok "Build succeeded."

APP_PATH="$DERIVED_DATA_PATH/Build/Products/Debug-iphoneos/JARVIS.app"
[[ -d "$APP_PATH" ]] || die "Current build did not produce $APP_PATH"
if [[ ! -d "$APP_PATH/Watch/JARVISWatch.app" ]]; then
  die "Current iPhone bundle does not contain Watch/JARVISWatch.app"
fi
if [[ -e "$APP_PATH/PlugIns/JARVISWatch.app" ]]; then
  die "Watch app was also embedded under PlugIns/; expected only Watch/."
fi
if [[ ! -d "$APP_PATH/Watch/JARVISWatch.app/PlugIns/JARVISWatchWidget.appex" ]]; then
  die "Current Watch bundle does not contain its widget extension"
fi
ok "Current app bundle: $APP_PATH"
ok "Embedded Watch/ companion and nested widget verified."

printf 'Installing on device…\n'
xcrun devicectl device install app --device "$DEVICE_UDID" "$APP_PATH"
ok "Installed."

if [[ "$LAUNCH" -eq 1 ]]; then
  if xcrun devicectl device process launch --device "$DEVICE_UDID" "$BUNDLE_ID"; then
    ok "Launched $BUNDLE_ID"
  else
    warn "Installed, but launch failed — open JARVIS on the iPhone."
  fi
fi

ok "Done. Free provisioning profiles are refreshed by -allowProvisioningUpdates."
