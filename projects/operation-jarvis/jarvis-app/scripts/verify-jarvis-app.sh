#!/usr/bin/env bash
# Repeatable local verification for the daemon, shared package, and host apps.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DERIVED_DATA_PATH="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-verify-derived.XXXXXX")"
trap 'rm -rf "$DERIVED_DATA_PATH"' EXIT

reject_match() {
  local message="$1"
  shift
  if grep "$@"; then
    echo "$message" >&2
    exit 1
  fi
}

printf '%s\n' '== XcodeGen =='
xcodegen generate

printf '%s\n' '== Python unit tests =='
python3 -m unittest discover -s jarvisd/tests -v
python3 -m py_compile jarvisd/jarvisd.py ../jarvis.py ../../../.pi/discord-cron/runner.py

printf '%s\n' '== plist, icon, and shell syntax =='
plutil -lint \
  JARVIS/Info.plist \
  JARVIS/PrivacyInfo.xcprivacy \
  JARVISWidget/Info.plist \
  JARVISWatch/Info.plist \
  JARVISWatchWidget/Info.plist \
  jarvisd/launchd/*.plist
python3 -m json.tool JARVIS/Assets.xcassets/JARVISMark.imageset/Contents.json >/dev/null
python3 -m json.tool JARVISWatch/Assets.xcassets/JARVISMark.imageset/Contents.json >/dev/null
python3 -m json.tool JARVISWatchWidget/Assets.xcassets/Contents.json >/dev/null
python3 -m json.tool JARVISWatchWidget/Assets.xcassets/JARVISWidgetIcon.imageset/Contents.json >/dev/null
python3 -m json.tool JARVISWatchWidget/Assets.xcassets/JARVISWidgetIconAccented.imageset/Contents.json >/dev/null
bash -n scripts/*.sh jarvisd/resurrector.sh ../scripts/install-discord-bot-launch-agent.sh
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes:0:CFBundleURLSchemes:0' JARVIS/Info.plist)" == "jarvis" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes:0:CFBundleURLSchemes:0' JARVISWatch/Info.plist)" == "jarvis" ]]

printf '%s\n' '== native navigation contract =='
[[ ! -e JARVIS/Views/EventsView.swift ]]
[[ "$(grep -c '\.tabItem' JARVIS/JARVISApp.swift)" == "2" ]]
grep -q 'Label("Home"' JARVIS/JARVISApp.swift
grep -q 'Label("Settings"' JARVIS/JARVISApp.swift
reject_match 'retired Events UI is still referenced' -RqsE 'EventsView|case events|fetchEvents|lastEvents|eventsLoading' JARVIS

printf '%s\n' '== native refresh contract =='
grep -q 'activeInterval: Duration = .seconds(15)' JARVISKit/Sources/JARVISKit/RefreshPolicy.swift
grep -q 'Task.sleep(for: self.activeRefreshInterval)' JARVIS/AppState.swift
grep -q 'Task.sleep(for: self.activeRefreshInterval)' JARVISWatch/Views/WatchConnectView.swift
grep -q 'sceneDidBecomeActive' JARVISWatch/Views/WatchConnectView.swift
grep -q 'sceneWillResignActive' JARVISWatch/Views/WatchConnectView.swift
grep -q 'Retry now' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'always-visible Watch refresh control is still present' -qs 'Refresh status' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'iPhone toolbar refresh control is still present' -qs 'accessibilityLabel("Refresh home status")' JARVIS/Views/HomeView.swift

printf '%s\n' '== Siri plug source contract =='
grep -q 'struct TurnOnJARVISPlugIntent: AppIntent' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'struct TurnOffJARVISPlugIntent: AppIntent' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'struct JARVISPlugEntity: AppEntity' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'struct JARVISPlugEntityQuery: EntityStringQuery' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Tell \\(\.applicationName) to turn on \\(\\.\$plug)' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Tell \\(\.applicationName) to turn off \\(\\.\$plug)' HostAppIntents/JARVISSiriPlugIntents.swift
[[ "$(grep -c 'AppShortcut(' HostAppIntents/JARVISSiriPlugIntents.swift)" == "2" ]]
grep -q 'static var isDiscoverable: Bool { false }' SharedAppIntents/JARVISWidgetIntents.swift
grep -q 'queueIfUnreachable: false' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'allowsWatchRelayFallback' JARVISKit/Sources/JARVISKit/PlugCommandExecutor.swift
grep -q 'private actor JARVISSiriCatalogueCoordinator' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'private let retention: TimeInterval = 15' HostAppIntents/JARVISSiriPlugIntents.swift
reject_match 'Siri source contains a compiled production plug identifier' -qsE 'family-room-light|pedalboard|"lamp"|"tv"' HostAppIntents/JARVISSiriPlugIntents.swift
reject_match 'non-plug Siri surface is present' -qsiE 'purifier|scheduled.?job|serviceAction|discord|room.?audio' HostAppIntents/JARVISSiriPlugIntents.swift
reject_match 'Siri plug path must never toggle' -RqsF 'plug-toggle' HostAppIntents JARVISKit/Sources/JARVISKit/PlugCatalog.swift JARVISKit/Sources/JARVISKit/PlugCommandExecutor.swift

printf '%s\n' '== widget source contract =='
reject_match 'legacy iPhone widget kind is still present' -RqsF 'let kind = "JARVISPlugWidget"' JARVISWidget
reject_match 'legacy Watch widget kind is still present' -RqsF 'let kind = "JARVISWatchWidget"' JARVISWatchWidget
for kind in \
  JARVISLauncherWidget.v1 \
  JARVISSelectedPlugWidget.v1 \
  JARVISPlugGridWidget.v1 \
  JARVISPurifierWidget.v1; do
  grep -Rqs "let kind = \"$kind\"" JARVISWidget || { echo "missing iOS widget kind: $kind" >&2; exit 1; }
done
for kind in \
  JARVISWatchLauncherWidget.v2 \
  JARVISWatchSelectedPlugWidget.v1 \
  JARVISWatchPlugGridWidget.v1 \
  JARVISWatchPurifierWidget.v1; do
  grep -Rqs "let kind = \"$kind\"" JARVISWatchWidget || { echo "missing watch widget kind: $kind" >&2; exit 1; }
done
reject_match 'iPhone purifier widget must remain read-only' -qsF 'Button(intent:' JARVISWidget/PurifierWidget.swift
reject_match 'Watch purifier widget must remain read-only' -qsF 'Button(intent:' JARVISWatchWidget/PurifierWidget.swift
grep -q 'applyConfirmedPlugState' SharedAppIntents/JARVISWidgetIntents.swift
grep -q 'JARVISWidgetControlStore.shared' SharedAppIntents/JARVISWidgetIntents.swift
grep -q 'reloadTimelines(ofKind:' SharedAppIntents/JARVISWidgetIntents.swift
grep -q 'pendingCommand(for:' JARVISWidget/SelectedPlugWidget.swift
grep -q 'pendingCommand(for:' JARVISWatchWidget/SelectedPlugWidget.swift
[[ "$(grep -c 'AppIntentRecommendation(intent:' JARVISWatchWidget/WidgetSupport.swift)" == "1" ]]
grep -q 'JARVISPlugChoice.allCases.compactMap' JARVISWatchWidget/PlugGridWidget.swift
reject_match 'Watch plug grid must not truncate its inventory' -qsF 'prefix(2)' JARVISWatchWidget/PlugGridWidget.swift
grep -q 'Image("JARVISWidgetIcon", bundle: .main)' JARVISWatchWidget/LauncherWidget.swift
grep -q 'Image("JARVISWidgetIconAccented", bundle: .main)' JARVISWatchWidget/LauncherWidget.swift
grep -q '@Environment(\\.widgetRenderingMode)' JARVISWatchWidget/LauncherWidget.swift
grep -q 'GeometryReader' JARVISWatchWidget/LauncherWidget.swift
grep -q 'let kind = "JARVISWatchLauncherWidget.v2"' JARVISWatchWidget/LauncherWidget.swift
grep -q 'reloadTimelines(ofKind: "JARVISWatchLauncherWidget.v2")' JARVISWatch/JARVISWatchApp.swift
[[ -s JARVISWatchWidget/Assets.xcassets/JARVISWidgetIcon.imageset/JARVISWidgetIcon@2x.png ]]
[[ -s JARVISWatchWidget/Assets.xcassets/JARVISWidgetIconAccented.imageset/JARVISWidgetIconAccented@2x.png ]]
grep -Rqs 'Image("JARVISMark")' JARVIS/Views
grep -Rqs 'Image("JARVISMark")' JARVISWatch/Views
[[ -s JARVIS/Assets.xcassets/JARVISMark.imageset/JARVISMark.png ]]
[[ -s JARVISWatch/Assets.xcassets/JARVISMark.imageset/JARVISMark.png ]]
reject_match 'completed widget refresh attempts must not be retained' -qsF 'lastAttempt' JARVISKit/Sources/JARVISKit/WidgetSupport.swift

icon_is_opaque_square() {
  local path="$1"
  local expected="$2"
  local width height alpha
  width="$(sips -g pixelWidth "$path" 2>/dev/null | awk '/pixelWidth/{print $2}')"
  height="$(sips -g pixelHeight "$path" 2>/dev/null | awk '/pixelHeight/{print $2}')"
  alpha="$(sips -g hasAlpha "$path" 2>/dev/null | awk '/hasAlpha/{print $2}')"
  [[ "$width" == "$expected" && "$height" == "$expected" && "$alpha" == "no" ]] || {
    echo "invalid app icon: $path (${width}x${height}, alpha=${alpha})" >&2
    exit 1
  }
}

icon_is_opaque_square JARVIS/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png 1024
while IFS=: read -r filename size; do
  icon_is_opaque_square "JARVISWatch/Assets.xcassets/WatchAppIcon.appiconset/$filename" "$size"
done <<'ICONS'
watch-notification-48.png:48
watch-notification-55.png:55
watch-settings-58.png:58
watch-settings-87.png:87
watch-launcher-80.png:80
watch-launcher-88.png:88
watch-launcher-100.png:100
watch-quicklook-172.png:172
watch-quicklook-196.png:196
watch-quicklook-216.png:216
watch-marketing-1024.png:1024
ICONS

printf '%s\n' '== JARVISKit tests (live tests opt-in) =='
if [[ "${JARVIS_LIVE_TESTS:-0}" == "1" ]]; then
  JARVIS_LIVE_TESTS=1 swift test --package-path JARVISKit
else
  swift test --package-path JARVISKit
fi

printf '%s\n' '== iOS simulator build =='
xcodebuild \
  -project JARVIS.xcodeproj \
  -scheme JARVIS \
  -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  CODE_SIGNING_ALLOWED=NO \
  build
[[ -d "$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/JARVIS.app/PlugIns/JARVISWidget.appex" ]] \
  || { echo "iOS widget was not embedded" >&2; exit 1; }
[[ -d "$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/JARVIS.app/Watch/JARVISWatch.app" ]] \
  || { echo "watch companion was not embedded under Watch/" >&2; exit 1; }
[[ ! -e "$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/JARVIS.app/PlugIns/JARVISWatch.app" ]] \
  || { echo "watch companion was also embedded under PlugIns/" >&2; exit 1; }
[[ -d "$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/JARVIS.app/Watch/JARVISWatch.app/PlugIns/JARVISWatchWidget.appex" ]] \
  || { echo "watch widget was not nested in the embedded watch app" >&2; exit 1; }

PHONE_APP="$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/JARVIS.app"
EMBEDDED_WATCH="$PHONE_APP/Watch/JARVISWatch.app"
PHONE_WIDGET="$PHONE_APP/PlugIns/JARVISWidget.appex"
WATCH_WIDGET="$EMBEDDED_WATCH/PlugIns/JARVISWatchWidget.appex"
[[ -f "$PHONE_APP/Assets.car" ]] || { echo "iPhone host asset catalog missing" >&2; exit 1; }
[[ -f "$EMBEDDED_WATCH/Assets.car" ]] || { echo "Watch host asset catalog missing" >&2; exit 1; }
[[ -f "$WATCH_WIDGET/Assets.car" ]] || { echo "watch widget asset catalog missing" >&2; exit 1; }
PHONE_ASSET_INFO="$(xcrun assetutil --info "$PHONE_APP/Assets.car")"
EMBEDDED_WATCH_ASSET_INFO="$(xcrun assetutil --info "$EMBEDDED_WATCH/Assets.car")"
WATCH_ASSET_INFO="$(xcrun assetutil --info "$WATCH_WIDGET/Assets.car")"
grep -q 'JARVISMark' <<<"$PHONE_ASSET_INFO" \
  || { echo "compiled iPhone JARVIS mark missing" >&2; exit 1; }
grep -q 'JARVISMark' <<<"$EMBEDDED_WATCH_ASSET_INFO" \
  || { echo "compiled Watch JARVIS mark missing" >&2; exit 1; }
grep -q 'JARVISWidgetIcon' <<<"$WATCH_ASSET_INFO" \
  || { echo "compiled Watch launcher icon missing" >&2; exit 1; }
grep -q 'JARVISWidgetIconAccented' <<<"$WATCH_ASSET_INFO" \
  || { echo "compiled accented Watch launcher icon missing" >&2; exit 1; }
python3 -c 'import json,sys; data=json.load(sys.stdin); item=next(x for x in data if x.get("Name") == "JARVISWidgetIcon"); assert item.get("Template Mode") != "automatic"' <<<"$WATCH_ASSET_INFO" \
  || { echo "compiled full-color Watch launcher icon still permits automatic template rendering" >&2; exit 1; }
python3 - \
  "$PHONE_WIDGET/Metadata.appintents/extract.actionsdata" \
  "$WATCH_WIDGET/Metadata.appintents/extract.actionsdata" \
  "$PHONE_APP/Metadata.appintents/extract.actionsdata" \
  "$EMBEDDED_WATCH/Metadata.appintents/extract.actionsdata" <<'PY'
import json
import sys
for path in sys.argv[1:3]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    actions = payload.get("actions", {})
    assert "SelectJARVISPlugIntent" in actions, path
    assert "SetPlugIntent" in actions, path

for path in sys.argv[3:]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    actions = payload.get("actions", {})
    assert actions["SetPlugIntent"]["isDiscoverable"] is False, path
    assert actions["TurnOnJARVISPlugIntent"]["isDiscoverable"] is True, path
    assert actions["TurnOffJARVISPlugIntent"]["isDiscoverable"] is True, path
    shortcuts = payload.get("autoShortcuts", [])
    assert [item["actionIdentifier"] for item in shortcuts] == [
        "TurnOnJARVISPlugIntent",
        "TurnOffJARVISPlugIntent",
    ], path
    assert "JARVISPlugEntity" in payload.get("entities", {}), path
    assert "JARVISPlugEntityQuery" in payload.get("queries", {}), path
PY
PHONE_WIDGET_BINARY="$PHONE_WIDGET/JARVISWidget"
WATCH_WIDGET_BINARY="$WATCH_WIDGET/JARVISWatchWidget"
[[ -f "$PHONE_WIDGET/JARVISWidget.debug.dylib" ]] && PHONE_WIDGET_BINARY="$PHONE_WIDGET/JARVISWidget.debug.dylib"
[[ -f "$WATCH_WIDGET/JARVISWatchWidget.debug.dylib" ]] && WATCH_WIDGET_BINARY="$WATCH_WIDGET/JARVISWatchWidget.debug.dylib"
for kind in \
  JARVISLauncherWidget.v1 \
  JARVISSelectedPlugWidget.v1 \
  JARVISPlugGridWidget.v1 \
  JARVISPurifierWidget.v1; do
  grep -aFq "$kind" "$PHONE_WIDGET_BINARY" || { echo "built iOS widget missing kind: $kind" >&2; exit 1; }
done
for kind in \
  JARVISWatchLauncherWidget.v2 \
  JARVISWatchSelectedPlugWidget.v1 \
  JARVISWatchPlugGridWidget.v1 \
  JARVISWatchPurifierWidget.v1; do
  grep -aFq "$kind" "$WATCH_WIDGET_BINARY" || { echo "built watch widget missing kind: $kind" >&2; exit 1; }
done

if [[ "${JARVIS_RUN_IOS_TESTS:-0}" == "1" ]]; then
  printf '%s\n' '== iOS unit tests =='
  xcodebuild \
    -project JARVIS.xcodeproj \
    -scheme JARVIS \
    -configuration Debug \
    -destination 'platform=iOS Simulator,name=iPhone 11,OS=26.5' \
    -derivedDataPath "$DERIVED_DATA_PATH" \
    CODE_SIGNING_ALLOWED=NO \
    test
fi

printf '%s\n' '== watchOS simulator build =='
xcodebuild \
  -project JARVIS.xcodeproj \
  -scheme JARVISWatch \
  -configuration Debug \
  -destination 'generic/platform=watchOS Simulator' \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  CODE_SIGNING_ALLOWED=NO \
  build
[[ -d "$DERIVED_DATA_PATH/Build/Products/Debug-watchsimulator/JARVISWatch.app/PlugIns/JARVISWatchWidget.appex" ]] \
  || { echo "watch widget was not embedded" >&2; exit 1; }

printf '%s\n' '== complete =='
