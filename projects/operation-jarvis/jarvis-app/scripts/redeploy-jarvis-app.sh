#!/usr/bin/env bash
#
# redeploy-jarvis-app.sh — one-command build + install of the JARVIS iOS app
# onto a connected iPhone using a FREE Apple ID (7-day auto-provisioning).
#
# Prerequisites (one-time):
#   1. Sign into Xcode with your (free) Apple ID:  Xcode -> Settings -> Accounts
#      (this creates your Personal Team + a signing identity)
#   2. Connect the iPhone via USB and "Trust This Computer"
#
# Usage:
#   ./scripts/redeploy-jarvis-app.sh                 # build + install + launch
#   ./scripts/redeploy-jarvis-app.sh --no-launch     # build + install only
#   TEAM_ID=ABC123XYZX ./scripts/redeploy-jarvis-app.sh   # force a signing team
#
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"

SCHEME="JARVIS"
CONFIG="Debug"
BUNDLE_ID="com.operation-jarvis.jarvis"
LAUNCH=1
[[ "${1:-}" == "--no-launch" ]] && LAUNCH=0

# --- helpers ---------------------------------------------------------------
c_green=$'\033[32m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_rst=$'\033[0m'
ok()   { echo "${c_green}✓${c_rst} $*"; }
warn() { echo "${c_yel}!${c_rst} $*"; }
die()  { echo "${c_red}✗${c_rst} $*" >&2; exit 1; }

# --- 1. signing identity ---------------------------------------------------
ID_COUNT=$(security find-identity -v -p codesigning 2>/dev/null | grep -cE '^[[:space:]]*[0-9]+\)' || true)
if [[ "${ID_COUNT:-0}" -lt 1 ]]; then
  die "No codesigning identity found.
  Sign into Xcode first:  Xcode -> Settings -> Accounts -> (your free Apple ID)
  Then re-run this script."
fi
ok "Found $ID_COUNT signing identity(ies)."

# Resolve team id: env override, else Xcode's free personal team (from its
# provisioning defaults), else the first Apple Development identity.
TEAM_ID="${TEAM_ID:-}"
if [[ -z "$TEAM_ID" ]]; then
  TEAM_ID=$(defaults read com.apple.dt.Xcode IDEProvisioningTeamByIdentifier 2>/dev/null \
    | grep -oE 'teamID = [A-Z0-9]{10}' | head -1 | awk '{print $3}')
fi
if [[ -z "$TEAM_ID" ]]; then
  TEAM_ID=$(security find-identity -v -p codesigning 2>/dev/null \
    | grep -oE '\([A-Z0-9]{10}\)' | head -1 | tr -d '()')
fi
if [[ -n "$TEAM_ID" ]]; then
  ok "Using signing team: $TEAM_ID"
else
  warn "Could not auto-detect team id; relying on Xcode's default account."
fi

# --- 2. connected device ---------------------------------------------------
# devicectl (Xcode 15+) lists physical + sim devices; filter to physical iPhone.
# Prefer the user's iPhone (name contains "Dylan"); fall back to the first one.
DEVICE_LINE=$(xcrun devicectl list devices 2>/dev/null | awk 'NR>2 && /iPhone/ && !/Simulator/' | awk '/Dylan/ {print; exit}')
if [[ -z "$DEVICE_LINE" ]]; then
  DEVICE_LINE=$(xcrun devicectl list devices 2>/dev/null | awk 'NR>2 && /iPhone/ && !/Simulator/' | head -1)
fi
if [[ -z "$DEVICE_LINE" ]]; then
  die "No physical iPhone found. Connect the iPhone via USB and tap 'Trust This Computer', then re-run.
  (Devices seen: $(xcrun devicectl list devices 2>/dev/null | awk 'NR>2' | wc -l | tr -d ' '))"
fi
# The devicectl identifier is a UUID; extract it regardless of column position
# (device names can contain spaces, e.g. "Dylan's iPhone").
DEVICE_UDID=$(echo "$DEVICE_LINE" | grep -oE '[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}' | head -1)
[[ -n "$DEVICE_UDID" ]] || die "Could not parse device identifier from: $DEVICE_LINE"
ok "Target device: $DEVICE_UDID"

# --- 3. build for device ---------------------------------------------------
echo "Building $SCHEME ($CONFIG) for device…"
BUILD_LOG=$(mktemp)
xcodebuild \
  -project JARVIS.xcodeproj \
  -scheme "$SCHEME" \
  -configuration "$CONFIG" \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  ${TEAM_ID:+DEVELOPMENT_TEAM="$TEAM_ID"} \
  CODE_SIGN_STYLE=Automatic \
  build >"$BUILD_LOG" 2>&1 || {
    echo "Build failed. Last 40 lines:"; tail -40 "$BUILD_LOG"; rm -f "$BUILD_LOG"; exit 1; }
rm -f "$BUILD_LOG"
ok "Build succeeded."

# Locate the built .app (device build, not simulator).
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData -name "JARVIS.app" \
  -path "*Debug-iphoneos*" 2>/dev/null | head -1)
[[ -n "$APP_PATH" ]] || die "Could not find built JARVIS.app (Debug-iphoneos)."
ok "App bundle: $APP_PATH"

# --- 4. install (+ launch) -------------------------------------------------
echo "Installing on device…"
xcrun devicectl device install app --device "$DEVICE_UDID" "$APP_PATH"
ok "Installed."

if [[ "$LAUNCH" -eq 1 ]]; then
  xcrun devicectl device process launch --device "$DEVICE_UDID" "$BUNDLE_ID" 2>/dev/null \
    && ok "Launched $BUNDLE_ID" \
    || warn "Installed, but launch failed — open the JARVIS app on the iPhone."
fi

echo
ok "Done. If the 7-day profile expired, this script refreshes it automatically via -allowProvisioningUpdates."
