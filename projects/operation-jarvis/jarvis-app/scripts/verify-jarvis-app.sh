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
python3 -m unittest discover -s terminald/tests -v
python3 -m unittest discover -s ../../../.pi/scheduler/tests -v
python3 -m py_compile \
  jarvisd/jarvisd.py \
  terminald/jarvis_terminald.py \
  ../jarvis.py \
  ../raspberry-pi/room_audio/room_audio_server.py \
  ../voice/voice_pipeline.py \
  ../../../pi_rpc.py \
  ../../../.pi/scheduler/runner.py \
  ../../../.pi/scheduler/apns_provider.py

printf '%s\n' '== activity-aware jarvisd collector contract =='
grep -q 'DEFAULT_ACTIVE_LEASE_SECONDS = 45.0' jarvisd/jarvisd.py
grep -q 'DEFAULT_ACTIVATION_WAIT_SECONDS = 3.0' jarvisd/jarvisd.py
grep -q 'DEFAULT_IDLE_INTERVALS = {' jarvisd/jarvisd.py
grep -q 'self._condition = threading.Condition(self._lock)' jarvisd/jarvisd.py
grep -q 'def activate_client(self, wait_timeout:' jarvisd/jarvisd.py
grep -q 'return STATE_COORDINATOR.snapshot(client_active=True)' jarvisd/jarvisd.py
grep -q 'record\["stale"\] = True' jarvisd/jarvisd.py
reject_match 'fixed 250-millisecond jarvisd scheduler polling was restored' -Fq 'self._stop.wait(0.25)' jarvisd/jarvisd.py

printf '%s\n' '== bounded foreground stale convergence =='
grep -q 'staleConvergenceInterval: Duration = .milliseconds(500)' JARVISKit/Sources/JARVISKit/RefreshPolicy.swift
grep -q 'staleConvergenceAttempts = 8' JARVISKit/Sources/JARVISKit/RefreshPolicy.swift
grep -q 'attempts < staleConvergenceAttempts' JARVIS/AppState.swift
grep -q 'snapshot.stale == true' JARVIS/AppState.swift
grep -q 'snapshot.refreshing == true' JARVIS/AppState.swift
grep -q 'if app.isAwaitingFreshState { return "Online · refreshing" }' JARVIS/Views/HomeView.swift
grep -q 'State is refreshing; wait before changing it' JARVIS/Views/HomeView.swift
grep -q 'testStateFetchDoesNotRetryCompletedStaleSnapshot' JARVISTests/AppStateTests.swift

printf '%s\n' '== bounded jarvisd logging contract =='
grep -q 'from logging.handlers import RotatingFileHandler' jarvisd/jarvisd.py
grep -q 'JARVISD_LOG_MAX_BYTES' jarvisd/jarvisd.py
grep -q 'JARVISD_LOG_BACKUP_COUNT' jarvisd/jarvisd.py
grep -q 'MAX_LOG_LINE_CHARS = 4096' jarvisd/jarvisd.py
grep -q 'class RoutineRequestLogGate' jarvisd/jarvisd.py
grep -q 'ROUTINE_REQUEST_LOG_PATHS = {"/health", "/api/v1/state"}' jarvisd/jarvisd.py
grep -q 'and status == 200' jarvisd/jarvisd.py
grep -q 'and not parsed.query' jarvisd/jarvisd.py
grep -q 'log_writer = configure_bounded_stderr()' jarvisd/jarvisd.py
grep -q '^JARVISD_LOG_MAX_BYTES=1048576$' ../../../.env.example
grep -q '^JARVISD_LOG_BACKUP_COUNT=3$' ../../../.env.example
grep -q '^JARVISD_ROUTINE_REQUEST_LOG_INTERVAL=60$' ../../../.env.example

printf '%s\n' '== semantic Watch speech selection =='
node --experimental-strip-types --input-type=module <<'NODE'
import { selectWatchTerminalSpeech } from '../../../.pi/extensions/47-watch-terminal-speech.ts';
const entries = [
  { type: 'message', id: 'user0001', message: { role: 'user', content: [{ type: 'text', text: 'status' }] } },
  { type: 'message', id: 'tools001', message: { role: 'assistant', stopReason: 'toolUse', content: [
    { type: 'thinking', thinking: 'secret reasoning' },
    { type: 'text', text: 'intermediate status' },
    { type: 'toolCall', name: 'bash' },
  ] } },
  { type: 'message', id: 'result01', message: { role: 'toolResult', content: [{ type: 'text', text: 'private output' }] } },
  { type: 'message', id: 'final001', message: { role: 'assistant', stopReason: 'stop', timestamp: 1, content: [
    { type: 'thinking', thinking: 'more secret reasoning' },
    { type: 'text', text: 'Final answer, sir.' },
  ] } },
];
const selected = selectWatchTerminalSpeech(entries, 'session');
if (!selected || selected.text !== 'Final answer, sir.' || selected.responseID.length !== 64) {
  throw new Error(`semantic speech selection failed: ${JSON.stringify(selected)}`);
}
if (selectWatchTerminalSpeech([], 'session') !== undefined) throw new Error('empty session speech must be unavailable');
NODE

printf '%s\n' '== bounded Watch speech storage contract =='
grep -q 'public final class WatchTerminalSpeechFileStore' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'public static let maximumAudioBytes = 20 \* 1024 \* 1024' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'public static let transientFilePrefix = "jarvis-watch-speech-"' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'public static let preparedFileName = "jarvis-watch-last-response.wav"' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'values.isSymbolicLink != true' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'speechFileStore.removeOrphanedDownloads()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'speechFileStore.restorePreparedSpeech()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'speechFileStore.discardPreparedSpeech()' JARVISWatch/Views/WatchTerminalView.swift

printf '%s\n' '== plist, icon, and shell syntax =='
plutil -lint \
  JARVIS/Info.plist \
  JARVIS/PrivacyInfo.xcprivacy \
  JARVISWidget/Info.plist \
  JARVISWatch/Info.plist \
  JARVISWatchWidget/Info.plist \
  jarvisd/launchd/*.plist \
  terminald/launchd/*.plist
python3 -m json.tool JARVIS/Assets.xcassets/AccentColor.colorset/Contents.json >/dev/null
python3 -m json.tool JARVIS/Assets.xcassets/JARVISMark.imageset/Contents.json >/dev/null
python3 -m json.tool JARVISWatch/Assets.xcassets/JARVISMark.imageset/Contents.json >/dev/null
python3 -m json.tool JARVISWatchWidget/Assets.xcassets/Contents.json >/dev/null
python3 -m json.tool JARVISWatchWidget/Assets.xcassets/JARVISWidgetIcon.imageset/Contents.json >/dev/null
python3 -m json.tool JARVISWatchWidget/Assets.xcassets/JARVISWidgetIconAccented.imageset/Contents.json >/dev/null
bash -n scripts/*.sh jarvisd/resurrector.sh
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes:0:CFBundleURLSchemes:0' JARVIS/Info.plist)" == "jarvis" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes:0:CFBundleURLSchemes:0' JARVISWatch/Info.plist)" == "jarvis" ]]
shasum -a 256 -c config/protected-jarvis-icon-assets.sha256

printf '%s\n' '== xhigh purple theme contract =='
grep -q 'darkAccent = JARVISBrandRGB(red: 209, green: 131, blue: 232)' JARVISKit/Sources/JARVISKit/BrandTheme.swift
grep -q 'lightAccent = JARVISBrandRGB(red: 139, green: 0, blue: 139)' JARVISKit/Sources/JARVISKit/BrandTheme.swift
grep -q 'static let accent = Color(uiColor: UIColor' JARVIS/Views/Components.swift
grep -q 'case ...12: return JarvisPalette.accent' JARVIS/Views/HomeView.swift
grep -q 'case ...12: return WatchJarvisStyle.accent' JARVISWatch/Views/WatchDashboardContent.swift
[[ "$(grep -c '\.tint(JarvisPalette\.accent)' JARVIS/Views/HomeView.swift)" -ge 3 ]]
reject_match 'retired clean-air blue remains in native purifier chrome' -RqsE 'airQualityGood|clean-air cyan' JARVIS JARVISWatch
grep -q 'background(WatchJarvisStyle.accent, in: RoundedRectangle' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'retired blue brand tokens remain in native app chrome' -RqsE 'JarvisPalette\.(cyan|electricBlue)|WatchJarvisStyle\.(cyan|electricBlue)|Color\.cyan' JARVIS JARVISWatch
reject_match 'widget pending/launcher chrome must use the shared xhigh accent' -RqsE 'Color\.blue|foregroundStyle\(\.cyan\)' JARVISWidget JARVISWatchWidget
grep -q 'JARVISWidgetTheme.accent' JARVISWidget/LauncherWidget.swift
grep -q '.widgetAccentable()' JARVISWatchWidget/LauncherWidget.swift

printf '%s\n' '== native navigation contract =='
[[ ! -e JARVIS/Views/EventsView.swift ]]
[[ "$(grep -c '\.tabItem' JARVIS/JARVISApp.swift)" == "4" ]]
grep -q 'Label("Home"' JARVIS/JARVISApp.swift
grep -q 'Label("JARVIS"' JARVIS/JARVISApp.swift
grep -q 'Label("Jobs", systemImage: "calendar.badge.clock")' JARVIS/JARVISApp.swift
reject_match 'Pi tab must be labeled JARVIS' -Fq 'Label("Pi"' JARVIS/JARVISApp.swift
grep -q 'Label("Settings"' JARVIS/JARVISApp.swift
grep -q 'JobsView(requestedResultSequence:' JARVIS/JARVISApp.swift
grep -q '/api/v1/scheduled-job-results' jarvisd/jarvisd.py
grep -q 'static let limit = 100' JARVIS/ScheduledJobResultCache.swift
grep -q 'case jobs' JARVIS/AppState.swift
grep -q 'await self.refreshJobs()' JARVIS/AppState.swift
grep -q 'scheme == "http" || scheme == "https"' JARVIS/Views/LinkedJobResultText.swift
grep -q 'JobChannelMessage' JARVIS/Views/JobsView.swift
reject_match 'Jobs must not restore the flat Inbox/Schedules picker' -Fq 'Picker("Jobs section"' JARVIS/Views/JobsView.swift
reject_match 'Jobs must remain read-only' -RqsE 'runServiceAction|runCommand|setPlug|setPurifier|retry' JARVIS/Views/JobsView.swift
grep -q 'case pi' JARVIS/AppState.swift
grep -q 'case "pi": selection = .pi' JARVIS/JARVISApp.swift
reject_match 'retired Events UI is still referenced' -RqsE 'EventsView|case events|fetchEvents|lastEvents|eventsLoading' JARVIS

printf '%s\n' '== compact iPhone dashboard contract =='
grep -q 'private var compactConnectionStrip' JARVIS/Views/HomeView.swift
grep -q 'MinimalSectionHeader(title: "System"' JARVIS/Views/HomeView.swift
grep -q 'ForEach(1...3, id: \\.self)' JARVIS/Views/HomeView.swift
grep -q 'private func piSessionStatusSection(sessionID: Int, active: Bool?)' JARVIS/Views/HomeView.swift
grep -q 'label = "Running"' JARVIS/Views/HomeView.swift
grep -q 'tone = \.running' JARVIS/Views/HomeView.swift
grep -q 'case \.running: return \.green' JARVIS/Views/HomeView.swift
grep -q 'label = "Idle"' JARVIS/Views/HomeView.swift
grep -q 'tone = \.idle' JARVIS/Views/HomeView.swift
grep -q 'case \.idle: return \.purple' JARVIS/Views/HomeView.swift
reject_match 'Pi status indicator must not render inactive state in red' -Fq 'active.map { $0 ? JarvisPalette.accent : .red }' JARVIS/Views/HomeView.swift
grep -q 'public let mobileSessions: \[PiMobileSession\]?' JARVISKit/Sources/JARVISKit/Models.swift
grep -q 'MOBILE_TMUX_SESSIONS = ((1, "jarvis-ios"), (2, "jarvis-ios-2"), (3, "jarvis-ios-3"))' jarvisd/jarvisd.py
grep -q '#{session_name}\\t#{pane_dead}\\t#{pane_pid}' jarvisd/jarvisd.py
grep -q 'pi-extension-local-session-status' jarvisd/jarvisd.py
grep -q 'if project_root_is_explicit:' jarvisd/jarvisd.py
grep -q '"mobileSessions": _mobile_pi_session_states()' jarvisd/jarvisd.py
grep -q 'SettingsGroup(title: "Configuration")' JARVIS/Views/SettingsView.swift
grep -q 'SettingsGroup(title: "Maintenance")' JARVIS/Views/SettingsView.swift
[[ "$(grep -c 'NavigationLink {' JARVIS/Views/SettingsView.swift)" == "4" ]]
grep -q 'ConnectionSettingsView()' JARVIS/Views/SettingsView.swift
grep -q 'PiTerminalSettingsView()' JARVIS/Views/SettingsView.swift
grep -q 'WatchTerminalSettingsView()' JARVIS/Views/SettingsView.swift
grep -q 'DeveloperSigningSettingsView()' JARVIS/Views/SettingsView.swift
grep -Fq 'JARVIS \(SettingsPresentation.appVersion)' JARVIS/Views/SettingsView.swift
grep -q 'DisclosureGroup("Technical Details"' JARVIS/Views/ConnectionSettingsView.swift
grep -q 'Forget Trusted SSH Host' JARVIS/Views/PiTerminalSettingsView.swift
grep -q 'navigationTitle(title)' JARVIS/Views/SettingsComponents.swift
grep -q 'Renew for 7 Days' JARVIS/Views/DeveloperSigningSettingsView.swift
grep -q 'LocalSigningStatus.current' JARVIS/Views/DeveloperSigningSettingsView.swift
grep -q 'How Renewal Works · 7 Steps' JARVIS/Views/DeveloperSigningSettingsView.swift
grep -q 'SigningRenewalStep.allCases' JARVIS/Views/DeveloperSigningSettingsView.swift
reject_match 'streamlined Settings must not restore separate Diagnostics or About destinations' -RqsE 'diagnosticsDetail|aboutDetail|About JARVIS' JARVIS/Views
reject_match 'streamlined Settings must not retain monolithic detail properties' -RqsE 'piTerminalDetail|watchTerminalDetail|developerSigningDetail' JARVIS/Views
grep -q '"/api/v1/signing/status"' JARVISKit/Sources/JARVISKit/JarvisClient.swift
grep -q '"/api/v1/signing/renew"' JARVISKit/Sources/JARVISKit/JarvisClient.swift
grep -q 'signing renewal does not accept a request body' jarvisd/jarvisd.py
grep -q '\[str(SIGNING_RENEWAL_SCRIPT)\]' jarvisd/jarvisd.py
[[ -x scripts/renew-free-signing.sh ]]
grep -q 'refs/heads/main' scripts/renew-free-signing.sh
grep -q 'PROFILE_REFRESH_COMPLETE' scripts/renew-free-signing.sh
grep -q 'case verifying' JARVISKit/Sources/JARVISKit/Models.swift
grep -q 'write_status "verifying"' scripts/renew-free-signing.sh
grep -q '"failedPhase": failed_phase or None' scripts/renew-free-signing.sh
grep -q 'SIGNING_RENEWAL_STEPS' jarvisd/jarvisd.py
grep -q 'iPhone renewal succeeded, but Watch installation failed' scripts/renew-free-signing.sh
reject_match 'signing renewal endpoint must not accept shell commands or client arguments' -E 'shell=True|SIGNING_RENEWAL_SCRIPT.*payload|renew-free-signing.sh.*\$@' jarvisd/jarvisd.py scripts/renew-free-signing.sh
reject_match 'legacy oversized iPhone status hero remains' -RqsE 'private var statusHeader|private var settingsHero|Native control plane' JARVIS/Views
reject_match 'legacy expanded Home service groups remain' -qsE 'runtimeServicesExpanded|scheduledJobsExpanded|DisclosureGroup' JARVIS/Views/HomeView.swift
reject_match 'Pi and Codex summaries must remain directly visible on Home' -qsE 'codexDetail|navigationTitle\("Codex usage"\)' JARVIS/Views/HomeView.swift

printf '%s\n' '== Pi terminal source contract =='
grep -q 'exactVersion: 1.20.0' project.yml
grep -q 'exactVersion: 0.15.0' project.yml
grep -q 'exactVersion: 2.101.3' project.yml
grep -q 'import SwiftTerm' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'import NIOSSH' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'guard let synchronousOptions = childChannel.syncOptions' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'try synchronousOptions.setOption(.allowRemoteHalfClosure, value: true)' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'SSH child option setup must stay synchronously event-loop-confined' -qE 'func handlerAdded\(context: ChannelHandlerContext\)|allowRemoteHalfClosure.*whenFailure|assumeIsolated\(\)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'SimplePasswordDelegate intentionally owns mutable one-shot' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'one-shot SSH authentication must not use unsafe sendability or loop-bound escape hatches' -qE '@preconcurrency.*SimplePasswordDelegate|nonisolated\(unsafe\).*SimplePasswordDelegate|SimplePasswordDelegate.*@unchecked Sendable|NIOLoopBound.*userAuth' JARVIS/Terminal/PiSSHTransport.swift
python3 - <<'PY'
from pathlib import Path
source = Path("JARVIS/Terminal/PiSSHTransport.swift").read_text()
connect = source.index("    func connect() {")
initializer = source.index("            .channelInitializer { channel in", connect)
completed = source.index("                channel.eventLoop.makeCompletedFuture {", initializer)
auth = source.index("                    let userAuth = SimplePasswordDelegate(", completed)
handler = source.index("                    let sshHandler = NIOSSHHandler(", auth)
assert source.find("let userAuth = SimplePasswordDelegate(", connect, initializer) == -1
assert completed < auth < handler
PY
grep -q 'TerminalView, @MainActor TerminalViewDelegate, UIGestureRecognizerDelegate' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'SwiftTerm delegate isolation must not be suppressed or made unsafe' -qE '@preconcurrency TerminalViewDelegate|nonisolated\(unsafe\).*TerminalViewDelegate' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'queueing, reordering, or weakening the byte-exact terminal path.' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'defaultFontSize: CGFloat = 18' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'zoomSchemaDefaultsKey = "jarvis.pi-terminal.zoom-schema"' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'savedZoomSchema >= currentZoomSchema' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'keyboardDismissMode = .interactive' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'handleTouchScrollPan' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'configureFixedStepTouchScrolling' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'panGestureRecognizer.isEnabled = false' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'alwaysBounceVertical = false' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'bounces = false' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'isDirectionalLockEnabled = true' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'allowMouseReporting = false' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'override func mouseModeChanged' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'sendTouchScrollStep' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'PiTerminalTouchScroll.wheelBytes' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'if abs(touchScrollRemainder) >= pointsPerWheelStep' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'Every generated byte' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'testPiTerminalUsesImmediateFixedStepPiScrollingAndProvidesSlashShortcut' JARVISTests/AppStateTests.swift
reject_match 'fixed-step iPhone scroll must never queue, pace, retry, replay, or interpolate gestures' -E 'pendingTouchScroll|touchScrollDisplayLink|CADisplayLink|deliverNextTouchScrollStep|enqueueTouchScrollStep|PiTerminalScrollPhysicsDriver|resizableSnapshotView' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'fixed-step iPhone scroll must not write native content offsets or enter tmux copy mode' -E 'setContentOffset\(|capture-pane|send-keys.*copy-mode|copy-mode -e' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'rejected native/history replay architecture must remain removed' -E 'PiTerminalHistoryMonitor|PiTerminalSessionHistoryMonitor|PiTerminalOutputFilter|PiTerminalHistoryPromotionState|resumeReplay|jarvis_mobile_session_history' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'override func showCursor(source: Terminal)' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'Pi mouse mode must not install SwiftTerm remote drag reporting on iPhone' -Fq 'super.mouseModeChanged' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'toggleTerminalKeyboard' JARVIS/Terminal/PiTerminalController.swift
grep -q 'keyboard.chevron.compact.down' JARVIS/Terminal/PiTerminalView.swift
grep -q 'slashBytes: \[UInt8\] = \[0x2f\]' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'key("/", label: "Slash", bytes: PiTerminalKeyDeck.slashBytes)' JARVIS/Terminal/PiTerminalView.swift
reject_match 'Pi key deck must not retain the dedicated Control-C button' -Fq 'Control C, abort' JARVIS/Terminal/PiTerminalView.swift
reject_match 'Pi key deck must end at the Down arrow' -E 'Left arrow|Right arrow|Shift Return|Option Return|Pi keyboard shortcuts|accessibilityLabel\("Paste"\)' JARVIS/Terminal/PiTerminalView.swift
reject_match 'Pi terminal must not force the keyboard open when its view appears' -Fq 'DispatchQueue.main.async { _ = view.becomeFirstResponder() }' JARVIS/Terminal/PiTerminalView.swift
reject_match 'Pi terminal key deck must not implicitly reopen the keyboard' -RqsE 'focusTerminal|hideTerminalKeyboard' JARVIS/Terminal

grep -q 'scripts/jarvis-mobile-terminal.sh' JARVIS/Terminal/PiTerminalSettings.swift
[[ -x scripts/jarvis-mobile-terminal.sh ]]
zsh -n scripts/jarvis-mobile-terminal.sh
grep -q 'TMUX_SOCKET="jarvis-mobile"' scripts/jarvis-mobile-terminal.sh
grep -q 'TMUX_SESSION="jarvis-ios"' scripts/jarvis-mobile-terminal.sh
grep -q 'TMUX_SESSION="jarvis-ios-2"' scripts/jarvis-mobile-terminal.sh
grep -q 'TMUX_SESSION="jarvis-ios-3"' scripts/jarvis-mobile-terminal.sh
grep -q 'case "$slot" in' scripts/jarvis-mobile-terminal.sh
grep -q -- '--slot' scripts/jarvis-mobile-terminal.sh
grep -q 'new-session -d' scripts/jarvis-mobile-terminal.sh
grep -q 'attach-session' scripts/jarvis-mobile-terminal.sh
grep -q 'export PATH="/opt/homebrew/bin:' scripts/jarvis-mobile-terminal.sh
grep -q "PI_COMMAND='/opt/homebrew/bin/pi --tui-mode regular'" scripts/jarvis-mobile-terminal.sh
reject_match 'Mobile Pi launcher must not restore fullscreen TUI mode' -Fq -- '--tui-mode fullscreen' scripts/jarvis-mobile-terminal.sh
grep -q 'source-file "$TMUX_CONFIG"' scripts/jarvis-mobile-terminal.sh
grep -q 'send-keys -X -N 1 scroll-up' config/jarvis-mobile.tmux.conf
grep -q 'send-keys -X -N 1 scroll-down' config/jarvis-mobile.tmux.conf
reject_match 'Pi terminal must not assign a special Pi session name' -Fq -- '--name' scripts/jarvis-mobile-terminal.sh
reject_match 'Pi launcher must not interpolate a client-supplied tmux session' -E 'TMUX_SESSION=.*\$slot|TMUX_SESSION=.*\$[12]' scripts/jarvis-mobile-terminal.sh
grep -q 'static func remoteCommand(for slot: JARVISTerminalSlot)' JARVIS/Terminal/PiTerminalSettings.swift
grep -q 'private var sessionGeneration = 0' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'readiness only after send() can resolve this exact child' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'self.sessionReady(generation: generation)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'Never open a replacement while the prior PTY might still' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'Pi session switching must not open a replacement after an unverified child close' -Fq 'previous.close().whenComplete { _ in openSelected() }' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'sessionSwipeRequested' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'JARVISTerminalSlot.load(from: slotDefaults)' JARVIS/Terminal/PiTerminalController.swift
grep -q 'PiAttachmentProtocol.receiverCommand(for: slot)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly' JARVIS/Terminal/PiTerminalSettings.swift
grep -q 'String(openSSHPublicKey: hostKey)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'extended-keys-format csi-u' config/jarvis-mobile.tmux.conf
grep -q 'window-size latest' config/jarvis-mobile.tmux.conf
reject_match 'Pi terminal must not accept every SSH host key' -RqsE 'AcceptAllHostKeys|acceptAnything' JARVIS/Terminal
reject_match 'Pi terminal reconnect must not queue input' -RqsE 'queuedInput|pendingInput|inputQueue' JARVIS/Terminal
grep -q 'struct PiTerminalInputTransitionState' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'beginTerminalInputTransition(generation: nextGeneration' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'completeTerminalInputTransition(generation: generation)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'guard isTerminalInputReady else { return false }' JARVIS/Terminal/PiSSHTransport.swift
[[ "$(grep -c 'guard isTerminalInputReady else { return }' JARVIS/Terminal/PiSSHTransport.swift)" -ge 5 ]]
grep -q 'status == .connected && terminalView?.isTerminalInputReady == true' JARVIS/Terminal/PiTerminalController.swift
grep -q 'testPiTerminalInputIsRearmedOnlyByTheExactFreshSession' JARVISTests/AppStateTests.swift
python3 - <<'PY'
from pathlib import Path
source = Path("JARVIS/Terminal/PiSSHTransport.swift").read_text()
on_ready = source.index("            onReady:")
complete = source.index("self.completeTerminalInputTransition(generation: generation)", on_ready)
connected = source.index("self.stateChanged?(.connected)", complete)
assert on_ready < complete < connected
switch = source.index("    func switchSession(to slot: JARVISTerminalSlot) -> Bool")
transition = source.index("    func beginTerminalInputTransition", switch)
switch_body = source[switch:transition]
assert "sendAccessoryBytes" not in switch_body
assert "[0x1b]" not in switch_body
PY
grep -q 'prepareTerminalForFreshConnection()' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'terminal.resetToInitialState()' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'windowState.update(cols: cols, rows: rows)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'initialWindowSize: self.windowState.snapshot()' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'publishWindowChange(self.windowState.snapshot(), on: childChannel)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'testPiTerminalResetsStaleAlternateScreenBeforeFreshConnection' JARVISTests/AppStateTests.swift
grep -q 'testPiTerminalRetainsLayoutResizeUntilSSHSessionIsReady' JARVISTests/AppStateTests.swift
reject_match 'Pi SSH session must not replay stale initial dimensions after authentication' -Fq 'self.resize(cols: self.initialWindowSize.cols, rows: self.initialWindowSize.rows)' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'Pi launcher must not kill its persistent session' -RqsE 'kill-session|kill-server' JARVIS/Terminal config/jarvis-mobile.tmux.conf scripts/jarvis-mobile-terminal.sh
grep -q 'set-option -w -t "=$TMUX_SESSION:0" window-size latest' scripts/jarvis-mobile-terminal.sh
reject_match 'Pi launcher must not force pane dimensions' -qsE '\$TMUX_BIN.*resize-(pane|window)' scripts/jarvis-mobile-terminal.sh

[[ "$(/usr/libexec/PlistBuddy -c 'Print :UISupportedInterfaceOrientations' JARVIS/Info.plist | grep -c UIInterfaceOrientationLandscape)" == "2" ]]

grep -q -- '--ensure-only' scripts/jarvis-mobile-terminal.sh

printf '%s\n' '== Watch JARVIS terminal contract =='
grep -q '._statusBarHidden()' JARVISWatch/Views/WatchConnectView.swift
grep -q '^[[:space:]]*\.ignoresSafeArea()' JARVISWatch/Views/WatchConnectView.swift
reject_match 'Watch root NavigationStack would reserve the removed clock strip' -Fq 'NavigationStack { WatchDashboardContent' JARVISWatch/Views/WatchConnectView.swift
grep -q 'DEFAULT_PORT = 8792' terminald/jarvis_terminald.py
grep -q 'ThreadingHTTPServer' terminald/jarvis_terminald.py
grep -q 'ssl.PROTOCOL_TLS_SERVER' terminald/jarvis_terminald.py
grep -q 'hmac.compare_digest' terminald/jarvis_terminald.py
grep -q 'MAX_INPUT_BYTES = 4096' terminald/jarvis_terminald.py
grep -q 'capture-pane' terminald/jarvis_terminald.py
grep -q 'self.frame_condition = threading.Condition(self.lock)' terminald/jarvis_terminald.py
grep -q 'def _sampler_loop(self)' terminald/jarvis_terminald.py
grep -q 'capture_arguments = self.tmux_arguments(' terminald/jarvis_terminald.py
grep -q 'self.next_sample_at = 0.0' terminald/jarvis_terminald.py
reject_match 'per-request terminal capture polling was restored' -Fq 'time.sleep(POLL_INTERVAL_SECONDS)' terminald/jarvis_terminald.py
grep -q 'MAX_HISTORY_PAGE_ROWS = 256' terminald/jarvis_terminald.py
grep -q 'def history_page(self, start: int, limit: int)' terminald/jarvis_terminald.py
grep -q '"/v1/terminal/history"' terminald/jarvis_terminald.py
grep -q 'public func historyPage(' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'Array(retained.suffix(3))' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'paste-buffer' terminald/jarvis_terminald.py
grep -q 'processed_request_ids' terminald/jarvis_terminald.py
grep -q 'refresh-client' terminald/jarvis_terminald.py
grep -q 'Record successful delivery before the best-effort client redraw' terminald/jarvis_terminald.py
grep -q 'terminalConfiguration' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly' HostAppIntents/JARVISTerminalConfigurationStore.swift
grep -q 'SecTrustCopyCertificateChain' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'final class WatchTerminalClient' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'private var sceneIsActive = false' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'let resumedAsFrontmost = !appIsForeground' JARVISWatch/Views/WatchConnectView.swift
grep -q 'terminal.sceneDidEnterAlwaysOn()' JARVISWatch/Views/WatchConnectView.swift
reject_match 'Watch parent must not swallow active-to-inactive wrist-down transitions' -Fq 'guard !appIsForeground else { return }' JARVISWatch/Views/WatchConnectView.swift
grep -q 'private func scheduleWakeRecovery()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.restartIfNeeded(preserveLiveStatus: true)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.successfulPollCount += 1' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'selectWatchTerminalSpeech' ../../../.pi/extensions/47-watch-terminal-speech.ts
grep -q 'pi.on("agent_settled"' ../../../.pi/extensions/47-watch-terminal-speech.ts
grep -q 'message.stopReason !== "stop" && message.stopReason !== "length"' ../../../.pi/extensions/47-watch-terminal-speech.ts
grep -q 'part?.type === "text"' ../../../.pi/extensions/47-watch-terminal-speech.ts
grep -q 'ROOM_SPEECH_URL = "http://127.0.0.1:8791/synthesize"' terminald/jarvis_terminald.py
grep -q '"/v1/terminal/input": (False, False)' terminald/jarvis_terminald.py
grep -q '"/v2/terminal/input": (True, False)' terminald/jarvis_terminald.py
grep -q '"/v2/terminal/speech": (True, True)' terminald/jarvis_terminald.py
grep -q 'TMUX_SESSIONS = {1: "jarvis-ios", 2: "jarvis-ios-2", 3: "jarvis-ios-3"}' terminald/jarvis_terminald.py
grep -q 'self.tmux_target = TMUX_TARGET if session_id == 1 else "=" + self.tmux_session + ":"' terminald/jarvis_terminald.py
grep -q 'service.frame_after(after)' terminald/jarvis_terminald.py
grep -q 'def _v2_payload_session(value: Any)' terminald/jarvis_terminald.py
grep -q 'if type(value) is not int or value not in TMUX_SESSIONS' terminald/jarvis_terminald.py
grep -q '"sessionID": session_id' terminald/jarvis_terminald.py
grep -q 'private static func canonicalSessionID(in data: Data) throws -> Int' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'CFGetTypeID(number) == CFNumberGetTypeID()' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q '!CFNumberIsFloatType(number)' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'acknowledgement.ok' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'path == "/synthesize"' ../raspberry-pi/room_audio/room_audio_server.py
grep -q 'is_loopback_address(self.client_address\[0\])' ../raspberry-pi/room_audio/room_audio_server.py
grep -q 'public func speechAudio(' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'import AVFoundation' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Image(systemName: controller.isSpeechPlaying ? "stop.fill" : "speaker.wave.2.fill")' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private func prepareSpeechIfNeeded()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private var speechClient: WatchTerminalClient?' JARVISWatch/Views/WatchTerminalView.swift
grep -q '_ = try await speechClient.preflight(slot: slot)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'downloadedURL = try await speechClient.speechAudio(responseID: responseID, slot: slot)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.appIsForeground' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.prepareSpeechIfNeeded()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.speechFileURL = try self.retainPreparedSpeech' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'AVAudioPlayer(contentsOf: speechFileURL)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'policy: \.longFormAudio' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'session.activate(options: \[\])' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch background speech must not use synchronous default-route activation' -Fq 'try session.setActive(true)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'preservePreparedSpeech: !isSpeechLoading && speechFileURL != nil' JARVISWatch/Views/WatchTerminalView.swift
grep -q '@Published private(set) var isConnectionConfirmed = false' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'var terminalInputIsReady: Bool' JARVISWatch/Views/WatchTerminalView.swift
grep -q '@Environment(\\.isLuminanceReduced) private var isLuminanceReduced' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Image(systemName: controller.frame == nil ? "circle.dotted" : "checkmark.circle.fill")' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Session retained; live networking resumes when active' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.isConnectionConfirmed = true' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'isConnectionConfirmed = false' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'restartIfNeeded(preserveLiveStatus: frame != nil)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'preserveLiveStatus && frame != nil && status != \.notConfigured' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'guard appIsForeground, isVisible, terminalInputIsReady' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if !self.isSpeechPlaying { self.stopSpeech() }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'var sequence = 0' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.frame(width: 44, height: 35)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Color.white.opacity(0.09)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'TextField("", text: \$keyboardDraft, prompt:' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.opacity(0.01)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'preservePreparedSpeech: isSpeechLoading || speechFileURL != nil' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if !preserveSpeechPlayback && !preservePreparedSpeech { stopSpeech() }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'failureAge < 12' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'public enum WatchTerminalSpeechRetryPolicy' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'preferredBaseURL: preferredRoute' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'public static let defaultResponseIDKey = "jarvis.watch-terminal.prepared-speech-response-id"' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'public static let preparedFileName = "jarvis-watch-last-response.wav"' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'values.isExcludedFromBackup = true' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'try? fileManager.removeItem(at: destination)' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'guard let speech = frame?.speech else { return true }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private func trace(_ event: String)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.speech_synthesis_events: Dict\[str, threading.Event\]' terminald/jarvis_terminald.py
grep -q 'completion.wait(timeout=185)' terminald/jarvis_terminald.py
grep -q 'os.replace(temporary_path, cache_path)' terminald/jarvis_terminald.py
grep -q 'for stale_path in self.speech_dir.glob("{}-\*.wav".format(self.session_id))' terminald/jarvis_terminald.py
/usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes:0' JARVISWatch/Info.plist | grep -qx 'audio'
grep -q 'def _bounded_tts_chunks' ../voice/voice_pipeline.py
grep -q 'cleaned_text = self._clean_text_for_tts(text)' ../voice/voice_pipeline.py
reject_match 'Watch terminal frame must never carry raw final response text' -RqsE 'responseText|speechText' JARVISKit/Sources/JARVISKit/WatchTerminal.swift terminald/jarvis_terminald.py
reject_match 'Watch speech must not accept arbitrary client text' -Fq '"text"' < <(sed -n '/    def do_POST(self)/,/^def parse_cidrs/p' terminald/jarvis_terminald.py)
reject_match 'Watch terminal must not fake a workout or unsupported extended-runtime category' -E 'WKExtendedRuntimeSession|HKWorkoutSession|isFrontmostTimeoutExtended' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'digitalCrownRotation' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.focused(\$crownIsFocused)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'from: -100_100' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'through: 0' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'isContinuous: false' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalCrownHistory.scrollOffset' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Crown live edge must not use rebound-prone incremental history' -Fq 'adjustScroll(towardHistory:' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalANSIParser.parse(lines: lines)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'controller.parsedANSILines(frame.ansiLines)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'controller.parsedANSILines(sourceANSI)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private static let ansiParseCacheLimit = 3' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if ansiParseCache.count >= Self.ansiParseCacheLimit' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalANSIParser.wrapped(' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalLayout.mirrorFontSize(' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'let outputColumns = max(1, frame.columns)' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal must not restore the rejected oversized font' -Fq 'wrappedOutputFontSize = 12.0' JARVISKit/Sources/JARVISKit/WatchTerminal.swift JARVISWatch/Views/WatchTerminalView.swift
grep -q 'public var liveEditorRange: Range<Int>?' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'frame.liveEditorRange' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalANSIParser.viewport(' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'let editorFontSize = outputFontSize' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal must not require horizontal swiping' -Fq 'ScrollView(.horizontal' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal must not duplicate Pi input in a prompt rail' -E 'private var promptRail|promptViewport\(displayColumns:' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Text("JARVIS · \\(controller.selectedSlot.displayName)")' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'func selectAdjacentSlot(_ direction: Int) -> Bool' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.connectionGeneration == generation' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'abs(horizontal) >= 48' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'JARVISTerminalSlot.allCases' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.frame(maxWidth: \.infinity, alignment: \.center)' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.padding(\.horizontal, 7)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Image(systemName: "terminal.fill")' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal must not restore the removed FIT/GRID selector' -E 'WatchTerminalDisplayMode|case fit|case grid|"FIT"|"GRID"' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Crown scrolling must remain local and read-only' -Fq 'controller.sendWheel' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'showingKeyPalette' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.submitLabel(.done)' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Input must not use the system chooser that can resume in dictation' -Fq 'TextFieldLink' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Vertical touch remains dashboard navigation' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private func stageInput(_ input: String)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'title: "Keys"' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'title: "Input"' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Image(systemName: "return")' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal Return must be symbol-only' -E 'title: "Enter"|Text\("Enter"\)' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal Return must not be mislabeled Send' -Fq 'title: "Send"' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'controller.sendText(message, appendReturn: false)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'controller.sendEnter()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'send(WatchTerminalKeyBytes.carriageReturn, appendReturn: false)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'controller.sendBackspace()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'data: WatchTerminalKeyBytes.backspace' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'session: selectedSlot' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'pendingBackspaceCount = pendingBackspaceIDs.count' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Backspace must not enter the normal loading state' -Fq 'isSending = true' < <(sed -n '/func sendBackspace()/,/private func restartIfNeeded/p' JARVISWatch/Views/WatchTerminalView.swift)
reject_match 'Watch input dock must not show a Backspace loading indicator' -Fq 'ProgressView' < <(sed -n '/private var inputDock/,/private func stageInput/p' JARVISWatch/Views/WatchTerminalView.swift)
grep -q 'public static let backspace = Data(\[0x7f\])' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'payload = data + (b"\\r" if append_return else b"")' terminald/jarvis_terminald.py
reject_match 'Siri Return must stay atomic with its prompt' -Fq 'send-keys", "-t", TMUX_TARGET, "Enter"' terminald/jarvis_terminald.py
reject_match 'Watch terminal must not restore the duplicate Type action' -Fq 'title: "Type"' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal must not label system text input as voice-only' -Fq 'title: "Speak"' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Input must not reopen a WatchKit input chooser' -Fq 'presentTextInputController' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Input must not require the intermediate local composer' -Fq 'inputComposer' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'mirrorFontSize(availableWidth:' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'MAX_SCROLLBACK_ROWS = 160' terminald/jarvis_terminald.py
grep -q '"-e"' terminald/jarvis_terminald.py
grep -q '"lines": lines\[screen_start:\]' terminald/jarvis_terminald.py
grep -q '"capturedLines": lines' terminald/jarvis_terminald.py
grep -q '"capturedANSILines": ansi_lines' terminald/jarvis_terminald.py
grep -q 'Text("/")' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'controller.sendKey(WatchTerminalKeyBytes.slash)' JARVISWatch/Views/WatchTerminalView.swift
[[ "$(grep -c '\.frame(width: 28, height: 35)' JARVISWatch/Views/WatchTerminalView.swift)" == "3" ]]
reject_match 'Slash must not remain duplicated in the expandable key palette' -Fq 'terminalKey("/"' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.padding(\.horizontal, 8)' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.padding(\.top, 6)' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.padding(\.bottom, 8)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalLayout.brightenedForeground(value)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'foreground.opacity(span.style.dim ? 0.82 : 1)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'public static let minimumForegroundLuminance = 188' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'private var codexQuotaPanel' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'private func codexQuotaCard' JARVIS/Views/HomeView.swift
grep -q 'public static let criticalRemainingPercent = 30.0' JARVISKit/Sources/JARVISKit/Models.swift
grep -q 'CodexQuotaPresentationPolicy.isCritical(remainingPercent: remaining)' JARVIS/Views/HomeView.swift
grep -q 'CodexQuotaPresentationPolicy.isCritical(remainingPercent: remaining)' JARVISWatch/Views/WatchDashboardContent.swift
grep -q '? JarvisPalette.critical' JARVIS/Views/HomeView.swift
grep -q '? WatchJarvisStyle.critical' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'AirQualityGauge.cleanlinessProgress(pm25: value)' JARVIS/Views/HomeView.swift
grep -q 'AirQualityGauge.cleanlinessProgress(pm25: value)' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'let pollutedFraction = (Double(value) - 1) / 74' JARVISKit/Sources/JARVISKit/AirQualityGauge.swift
grep -q 'public struct CodexQuotaSubsystem' JARVISKit/Sources/JARVISKit/Models.swift
grep -q 'CODEX_QUOTAS_SCRIPT' jarvisd/jarvisd.py
grep -q 'JARVIS_ROOT / "projects" / "operation-jarvis" / "quotas" / "quotas.py"' jarvisd/jarvisd.py
grep -q '\[sys.executable, str(CODEX_QUOTAS_SCRIPT), "codex", "--json"\]' jarvisd/jarvisd.py
grep -q '"codexQuota": 60.0' jarvisd/jarvisd.py
grep -q 'query.get("refresh") == \["codexQuota"\]' jarvisd/jarvisd.py
grep -q 'stateRefreshingCodexQuota' JARVISKit/Sources/JARVISKit/JarvisClient.swift
grep -q 'model.refreshCodexQuotaWhenVisible()' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'page == .system' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'NONCRITICAL_SUBSYSTEMS = frozenset({"codexQuota"})' jarvisd/jarvisd.py
reject_match 'Watch System page must not restore the removed Direct to Mac panel' -Fq 'Direct to Mac' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'configuration.candidateBaseURLs' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'dylans-mac-mini-2.tailcba1e5.ts.net' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'final class PiTerminalKeyboardResponder: UITextView' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'override var hasText: Bool { true }' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'private let keyboardResponder = PiTerminalKeyboardResponder()' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'override func deleteBackward()' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'SwiftTerm must not regain the marked repeat sentinel' -qsF 'setMarkedText(sentinel' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'WatchTerminalView(' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'private enum WatchDashboardPage: Hashable, CaseIterable' JARVISWatch/Views/WatchDashboardContent.swift
[[ "$(sed -n '/private enum WatchDashboardPage/,/^}/p' JARVISWatch/Views/WatchDashboardContent.swift | grep -c '^    case ')" == "3" ]]
grep -q '@State private var selectedPage: WatchDashboardPage = .terminal' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'pageDragGesture(previous: .terminal, next: .system)' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'The shorter Plugs grid must not collapse the page before the bottom edge.' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'GeometryReader { geometry in' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'let tileHeight = max(72, (geometry.size.height - rowSpacing) / CGFloat(rowCount))' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'plugButton(name, minimumHeight: tileHeight)' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'minHeight: minimumHeight' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'private func pageHeader(_ title: String, symbol: String)' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'Watch Plugs/System top-right header summaries must remain removed' -RqsE 'plugSummary|codexQuotaHeader|pageHeader\([^)]*trailing:' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'private func purifierPowerButton' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'private func purifierModeControl' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'private func purifierFanControl' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'WatchBridge.shared.requestPurifierCommand' JARVISWatch/Views/WatchConnectView.swift
grep -q 'watchBridgeDidReceivePurifierCommand' JARVIS/AppStateWatchBridge.swift
grep -q 'public struct WatchPurifierCommand' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'public let verificationPending: Bool?' JARVISKit/Sources/JARVISKit/Models.swift
grep -q 'public let pendingCommand: PurifierPendingCommand?' JARVISKit/Sources/JARVISKit/Models.swift
grep -q 'purifierConfirmationCaption' JARVIS/Views/HomeView.swift
grep -q 'purifierPendingSummary' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'data\["pendingCommand"\] = pending_command' jarvisd/jarvisd.py
reject_match 'Air-purifier controls must stay in the existing System card, not add a Watch page' -Fq 'case purifier' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'System Watch pager must not reserve the removed clock strip' -Fq 'tabViewStyle(.verticalPage)' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'Watch terminal must not require an Open button' -qs 'Open JARVIS' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'Watch terminal must not use a navigation launcher' -qs 'NavigationLink' JARVISWatch/Views/WatchDashboardContent.swift
[[ -x terminald/jarvis_terminald.py ]]
[[ -x scripts/install-jarvis-terminald.sh ]]
[[ -x scripts/jarvis-terminal-provisioning.sh ]]
reject_match 'Watch terminal must not open SSH directly' -RqsE 'import NIOSSH|import NIOPosix|import SwiftTerm' JARVISWatch
reject_match 'terminal bridge must remain separate from jarvisd' -RqsF 'terminal/frame' jarvisd

printf '%s\n' '== concurrency-safe native formatting and WidgetKit contracts =='
grep -q 'Date.ISO8601FormatStyle(includingFractionalSeconds: true)' JARVIS/Views/Components.swift
grep -q 'try? iso8601.parse(s)' JARVIS/Views/Components.swift
reject_match 'shared mutable iPhone ISO-8601 formatter remains' -Fq 'ISO8601DateFormatter' JARVIS/Views/Components.swift
grep -q 'testISO8601ParsingSupportsPlainAndFractionalTimestampsWithoutSharedMutableFormatter' JARVISTests/AppStateTests.swift
grep -q 'Date.ISO8601FormatStyle(includingFractionalSeconds: true)' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'try? Self.iso8601.parse(resetAt)' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'shared mutable Watch ISO-8601 formatter remains' -Fq 'ISO8601DateFormatter' JARVISWatch/Views/WatchDashboardContent.swift
for support in JARVISWidget/WidgetSupport.swift JARVISWatchWidget/WidgetSupport.swift; do
  [[ "$(grep -c '@escaping @Sendable' "$support")" == "2" ]]
  reject_match 'WidgetKit completion callback lost its Sendable contract' -qE 'completion: @escaping \(' "$support"
done

printf '%s\n' '== fail-closed endpoint URL contract =='
grep -q 'public enum JarvisEndpointURLPolicy' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'private static let allowedSchemes: Set<String> = \["http", "https"\]' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'components.user == nil' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'components.password == nil' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'components.query == nil' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'components.fragment == nil' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'JarvisEndpointURLPolicy.parse(trimmed)' JARVISKit/Sources/JARVISKit/EndpointStore.swift
grep -q 'guard defaults.string(forKey: urlKey) != normalizedValue else { return }' JARVISKit/Sources/JARVISKit/EndpointStore.swift
grep -q 'JarvisEndpointURLPolicy.parse(string)' JARVIS/AppState.swift
grep -q 'JarvisEndpointURLPolicy.parse(endpoint)' JARVIS/AppStateWatchBridge.swift
grep -q 'JarvisEndpointURLPolicy.parse(endpoint)' JARVISWatch/Views/WatchConnectView.swift
grep -q 'JarvisEndpointURLPolicy.normalize(endpoint.baseURL)' JARVISKit/Sources/JARVISKit/JarvisClient.swift
grep -q 'JarvisEndpointURLPolicy.normalize(candidate)' JARVISKit/Sources/JARVISKit/JarvisClient.swift
reject_match 'endpoint bridges must not restore permissive scheme-and-host-only checks' -RqsF 'url.scheme != nil, url.host != nil' JARVIS JARVISWatch

printf '%s\n' '== native refresh and Tailscale contract =='
grep -q 'activeInterval: Duration = .seconds(15)' JARVISKit/Sources/JARVISKit/RefreshPolicy.swift
grep -q 'dylans-mac-mini-2.tailcba1e5.ts.net' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q '100.87.28.34' JARVISKit/Sources/JARVISKit/Endpoints.swift
grep -q 'TAILSCALE_APP_CLI' jarvisd/jarvisd.py
for plist in JARVIS/Info.plist JARVISWatch/Info.plist JARVISWidget/Info.plist JARVISWatchWidget/Info.plist; do
  grep -q 'dylans-mac-mini-2.tailcba1e5.ts.net' "$plist"
  grep -q '100.87.28.34' "$plist"
done
reject_match 'retired Tailscale node address is still present' -RqsF '100.96.55.86' \
  JARVIS JARVISWatch JARVISWidget JARVISWatchWidget JARVISKit/Sources jarvisd
grep -q 'Task.sleep(for: self.activeRefreshInterval)' JARVIS/AppState.swift
grep -q 'Task.sleep(for: self.activeRefreshInterval)' JARVISWatch/Views/WatchConnectView.swift
grep -q 'client.resolveState(' JARVISWatch/Views/WatchConnectView.swift
grep -q 'private var cachedAuthenticationToken: String?' JARVISWatch/Views/WatchConnectView.swift
grep -q 'if let cachedAuthenticationToken { return cachedAuthenticationToken }' JARVISWatch/Views/WatchConnectView.swift
grep -q 'guard let token = store.token, !token.isEmpty else { return "" }' JARVISWatch/Views/WatchConnectView.swift
grep -q 'cachedAuthenticationToken = token' JARVISWatch/Views/WatchConnectView.swift
[[ "$(grep -c 'store.token' JARVISWatch/Views/WatchConnectView.swift)" == "1" ]]
grep -q 'let frameChanged = self.frame != next' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if frameChanged { self.frame = next }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if self.status != .live { self.status = .live }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if self.errorMessage != nil { self.errorMessage = nil }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'guard lastPersistedPreferredRoute != value else { return }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.prepareSpeechIfNeeded()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if let normalizedPreferred {' JARVISKit/Sources/JARVISKit/JarvisClient.swift
grep -q 'usedDiscovery: false' JARVISKit/Sources/JARVISKit/JarvisClient.swift
reject_match 'Watch refresh still issues a redundant post-discovery health request' -Fq '_ = try await client.health(endpoint)' JARVISWatch/Views/WatchConnectView.swift
grep -q 'sceneDidBecomeActive' JARVISWatch/Views/WatchConnectView.swift
grep -q 'TimelineView(.periodic(from: .now, by: 15))' JARVISWatch/Views/WatchConnectView.swift
grep -q 'model.sceneDidEnterAlwaysOn()' JARVISWatch/Views/WatchConnectView.swift
grep -q 'model.sceneDidEnterBackground()' JARVISWatch/Views/WatchConnectView.swift
grep -q 'terminal.sceneDidEnterAlwaysOn()' JARVISWatch/Views/WatchConnectView.swift
grep -q 'terminal.sceneDidEnterBackground()' JARVISWatch/Views/WatchConnectView.swift
grep -q '<true/>' < <(sed -n '/<key>WKSupportsAlwaysOnDisplay<\/key>/,+1p' JARVISWatch/Info.plist)
reject_match 'Always On must not be treated as background' -Fq 'case .inactive, .background:' JARVISWatch/Views/WatchConnectView.swift
reject_match 'Watch lifecycle must not disconnect merely because the scene became inactive' -Fq 'sceneWillResignActive' JARVISWatch/Views/WatchConnectView.swift JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Retry now' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'always-visible Watch refresh control is still present' -qs 'Refresh status' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'iPhone toolbar refresh control is still present' -qs 'accessibilityLabel("Refresh home status")' JARVIS/Views/HomeView.swift

printf '%s\n' '== two-turn Siri prompt source contract =='
[[ ! -e HostAppIntents/JARVISSiriPlugIntents.swift ]]
grep -q 'phrases: \["Hey \\(.applicationName)"\]' HostAppIntents/JARVISSiriShortcuts.swift
[[ "$(grep -c 'AppShortcut(' HostAppIntents/JARVISSiriShortcuts.swift)" == "1" ]]
grep -q 'struct SendPromptToJARVISIntent: AppIntent' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'requestValueDialog: IntentDialog("What would you like me to send to JARVIS?")' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'var prompt: String' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'JARVISSiriPromptRuntime.submit(prompt)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'guard outcome == \.sent else { return \.result() }' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'JARVISSpokenPrompt.normalize(rawPrompt)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'typealias SlotLoader = () -> JARVISTerminalSlot' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'let slot = slotLoader()' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'session: slot' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'data: Data(normalized.utf8)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q '#if os(watchOS)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'static var openAppWhenRun: Bool { true }' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'static var openAppWhenRun: Bool { false }' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'JARVISSiriNavigation.requestTerminalPresentation()' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'struct OpenJARVISTerminalIntent: OpenIntent' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'opensIntent: OpenJARVISTerminalIntent(target: .terminal)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q '@MainActor' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'URL(string: "jarvis://terminal")' HostAppIntents/JARVISSiriPromptIntent.swift
reject_match 'host Siri plug intent/entity/runtime remains' -RqsE 'Turn(On|Off)JARVISPlugIntent|JARVISPlugEntity|JARVISSiriPlugRuntime|JARVISSiriParameterRegistrar|updateJARVISSiriParametersIfNeeded' HostAppIntents JARVIS JARVISWatch JARVISTests
reject_match 'unsupported one-turn prompt entity remains' -RqsE 'JARVISPromptEntity|JARVISPromptEntityQuery|EntityStringQuery' HostAppIntents JARVISTests
[[ "$(grep -c 'IntentDialog(' HostAppIntents/JARVISSiriPromptIntent.swift)" == "1" ]]
reject_match 'Siri completion or failure dialogue remains' -qsE 'ProvidesDialog|return \.result\([^)]*dialog:' HostAppIntents/JARVISSiriPromptIntent.swift
reject_match 'Siri greeting playback code remains' -RqsE 'AudioPlaybackIntent|AVAudioPlayer|AVAudioSession|requestValue\(nil\)|greeting_(started|finished|recovery)' HostAppIntents
reject_match 'bundled JARVIS greeting resource remains referenced' -RqsE 'JARVIS-Siri-Ready|Siri-Ready\.wav' HostAppIntents JARVIS JARVISWatch project.yml JARVIS.xcodeproj/project.pbxproj
if find JARVIS JARVISWatch HostAppIntents -type f \( -iname '*.wav' -o -iname '*.wave' -o -iname '*.aiff' -o -iname '*.caf' -o -iname '*.m4a' -o -iname '*.mp3' \) -print -quit | grep -q .; then
  echo 'bundled host audio resource remains in source targets' >&2
  exit 1
fi
reject_match 'Siri terminal handoff must not use OpenURLIntent with a custom URL scheme' -qsF 'OpenURLIntent(' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'selection = \.pi' JARVIS/JARVISApp.swift
grep -q 'selectedPage = \.terminal' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'JARVISSiriNavigation.consumeTerminalPresentationRequest()' JARVIS/JARVISApp.swift
grep -q 'JARVISSiriNavigation.consumeTerminalPresentationRequest()' JARVISWatch/Views/WatchConnectView.swift
grep -q 'JARVISSiriNavigation.isTerminalURL(url)' JARVIS/JARVISApp.swift
grep -q 'JARVISSiriNavigation.isTerminalURL(url)' JARVISWatch/Views/WatchConnectView.swift
[[ ! -d SharedAppIntents ]]
grep -q 'WatchBridge.shared.requestPlugCommand' JARVISWatch/Views/WatchConnectView.swift
grep -q 'WatchBridge.shared.requestPurifierCommand' JARVISWatch/Views/WatchConnectView.swift
grep -q 'public static let maximumDeliveryAge: TimeInterval = 25' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'validateCommandDelivery(raw, requestID: requestID)' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'failure(.confirmationUnavailable)' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'Never retry an' JARVISWatch/Views/WatchConnectView.swift
grep -q 'public enum WatchStatePublicationPolicy' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'public func sendState(json: Data, requestID: String)' JARVISKit/Sources/JARVISKit/WatchBridge.swift
reject_match 'immediate Watch state publication must require explicit request correlation' -Fq 'sendState(json: Data, requestID: String =' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'WatchStatePublicationPolicy.shouldAccept(state, over: self.lastState)' JARVISWatch/Views/WatchConnectView.swift
reject_match 'routine iPhone state refresh must not send an immediate duplicate to Watch' -Fq 'WatchBridge.shared.sendState' JARVIS/AppState.swift
[[ "$(grep -c 'bridge.sendState(json: data, requestID: requestID)' JARVIS/AppStateWatchBridge.swift)" == "1" ]]
reject_match 'explicit Watch state reply must not republish the same application context' -Fq 'bridge.updateApplicationContext' JARVIS/AppStateWatchBridge.swift
reject_match 'interactive Watch relay writes must never use durable queued delivery' -Fq 'transferUserInfo' JARVISKit/Sources/JARVISKit/WatchBridge.swift
reject_match 'Watch relay must not expose queued command delivery switches' -Fq 'queueIfUnreachable' JARVISKit/Sources/JARVISKit/WatchBridge.swift
reject_match 'Watch relay UI must not poll a side-channel response dictionary' -E 'waitForRelayResponse|relayResponses|RelayResponse' JARVISWatch/Views/WatchConnectView.swift
grep -q 'allowsWatchRelayFallback' JARVISKit/Sources/JARVISKit/PlugCommandExecutor.swift
reject_match 'terminal input path must never toggle a plug implicitly' -RqsF 'plug-toggle' HostAppIntents JARVISKit/Sources/JARVISKit/PlugCatalog.swift JARVISKit/Sources/JARVISKit/PlugCommandExecutor.swift

printf '%s\n' '== widget source contract =='
reject_match 'failed Watch launcher experiment must remain fully removed' -RqsE 'ExternalLaunchProbe|NeuralLauncher|WatchWidgetRoute|WatchExternalLaunchRoute|WatchWidgetDestinationViews|quick-actions|now-playing|NowPlayingView' JARVISWatch JARVISWatchWidget JARVISKit/Sources JARVISKit/Tests
[[ ! -d SharedAppIntents ]]
[[ ! -e JARVISWidget/SelectedPlugWidget.swift ]]
[[ ! -e JARVISWidget/PlugGridWidget.swift ]]
[[ ! -e JARVISWatchWidget/SelectedPlugWidget.swift ]]
[[ ! -e JARVISWatchWidget/PlugGridWidget.swift ]]
[[ ! -e JARVISWidget/PurifierWidget.swift ]]
[[ ! -e JARVISWatchWidget/PurifierWidget.swift ]]
reject_match 'retired plug or purifier widget code or kinds remain' -RqsE 'SetPlugIntent|SelectJARVISPlugIntent|JARVISPlugChoice|JARVISWidgetControlStore|JARVISPendingPlugCommand|JARVISWidgetCommandDisposition|JARVIS(Watch)?SelectedPlugWidget|JARVIS(Watch)?PlugGridWidget|JARVISPurifierWidget|JARVISWatchPurifierWidget|PurifierWidget\.swift' JARVISWidget JARVISWatchWidget JARVISKit/Sources project.yml JARVIS.xcodeproj/project.pbxproj
for kind in \
  JARVISNeuralCoreWidget.v1 \
  JARVISLauncherWidget.v1; do
  grep -Rqs "let kind = \"$kind\"" JARVISWidget || { echo "missing iOS widget kind: $kind" >&2; exit 1; }
done
for kind in \
  JARVISWatchNeuralCoreWidget.v1 \
  JARVISWatchLauncherWidget.v2; do
  grep -Rqs "let kind = \"$kind\"" JARVISWatchWidget || { echo "missing watch widget kind: $kind" >&2; exit 1; }
done
[[ "$(grep -c 'Widget()' JARVISWidget/JARVISWidgetBundle.swift)" == "2" ]]
[[ "$(grep -c 'Widget()' JARVISWatchWidget/JARVISWatchWidgetBundle.swift)" == "2" ]]
reject_match 'all remaining widgets must stay non-interactive' -RqsF 'Button(intent:' JARVISWidget JARVISWatchWidget
grep -q 'JARVISNeuralCoreWidget()' JARVISWidget/JARVISWidgetBundle.swift
grep -q 'JARVISWatchNeuralCoreWidget()' JARVISWatchWidget/JARVISWatchWidgetBundle.swift
grep -q 'supportedFamilies(\[.systemMedium\])' JARVISWidget/NeuralCoreWidget.swift
grep -q 'supportedFamilies(\[.accessoryRectangular\])' JARVISWatchWidget/NeuralCoreWidget.swift
grep -q 'Color.clear' JARVISWatchWidget/NeuralCoreWidget.swift
grep -q 'URL(string: "jarvis://home")' JARVISWidget/NeuralCoreWidget.swift
grep -q 'URL(string: "jarvis://terminal")' JARVISWatchWidget/NeuralCoreWidget.swift
grep -q 'JARVISNeuralCoreTelemetry' JARVISKit/Sources/JARVISKit/NeuralCoreTelemetry.swift
reject_match 'Neural Core widgets must not draw an authored outer frame' -qsF '.strokeBorder(' WidgetShared/NeuralCoreArtwork.swift
reject_match 'Neural Core widgets must remain read-only artwork' -RqsE 'Button\(|AppIntentButton|Toggle\(' JARVISWidget/NeuralCoreWidget.swift JARVISWatchWidget/NeuralCoreWidget.swift WidgetShared
reject_match 'Neural Core must not run a process-driven animation loop' -RqsE 'TimelineView|Timer[[:space:]]*\(|repeatForever|AnimationTimelineSchedule|CADisplayLink' JARVISWidget/NeuralCoreWidget.swift JARVISWatchWidget/NeuralCoreWidget.swift WidgetShared
reject_match 'Neural Core must not use private clock-hand animation effects' -RqsE 'ClockHandRotationEffect|clockHandRotationEffect|_ClockHand' JARVISWidget JARVISWatchWidget WidgetShared
reject_match 'Neural Core must not embed animated media or Metal rendering' -RqsE 'VideoPlayer|AVPlayer|\.gif|\.apng|MTKView|import Metal' JARVISWidget JARVISWatchWidget WidgetShared
grep -q 'Text(date, style: .timer)' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'CTFontManagerRegisterFontsForURL' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'JARVISNeuralCoreContinuousMotionPolicy.decision' WidgetShared/NeuralCoreContinuousAnimation.swift
reject_match 'telemetry freshness must not disable the outer Neural Core selector' -qsF '&& !telemetry.signalLost' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'JARVISNeuralCoreArtworkMotionPolicy.isMotionEnabled' WidgetShared/NeuralCoreArtwork.swift
reject_match 'telemetry freshness must not collapse selected Watch frames to the static phase' -qsF '&& !telemetry.signalLost' WidgetShared/NeuralCoreArtwork.swift
# The sole remaining signalLost reference is the truthful accessibility label;
# decorative phase, density, energy, and luminance must not branch on freshness.
[[ "$(grep -Fc 'telemetry.signalLost' WidgetShared/NeuralCoreArtwork.swift)" == "1" ]]
grep -q 'private var decorativeEnergy: CGFloat { 1 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'private var coreStrength: Double { 1 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'case luminanceReduced' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
grep -q 'case reduceMotion' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
grep -q 'case fontUnavailable' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
grep -q 'phoneContinuousFrameCount = 48' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
grep -q 'watchContinuousFrameCount = 48' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
grep -q 'continuousSynchronizedBasePhase: Double = 0' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
[[ "$(grep -c 'basePhase: JARVISNeuralCoreMotion.continuousSynchronizedBasePhase' WidgetShared/NeuralCoreContinuousAnimation.swift)" == "2" ]]
grep -q 'JARVISWidgetTimerAnimationFont.register()' JARVISWidget/NeuralCoreWidget.swift
grep -q '.id(entry.date.timeIntervalSinceReferenceDate)' JARVISWidget/NeuralCoreWidget.swift
grep -q '.id(entry.date.timeIntervalSinceReferenceDate)' JARVISWatchWidget/NeuralCoreWidget.swift
[[ "$(grep -Rcs 'selectorGeneration: entry.date.timeIntervalSinceReferenceDate' JARVISWidget/NeuralCoreWidget.swift JARVISWatchWidget/NeuralCoreWidget.swift | awk -F: '{sum += $2} END {print sum + 0}')" == "2" ]]
grep -q 'JARVISNeuralCoreSelectorGeneration' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'telemetrySignalLost: telemetry.signalLost' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'ZStack(alignment: .topLeading)' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'ForEach(0..<layout.continuousFrameCount' WidgetShared/NeuralCoreContinuousAnimation.swift
reject_match 'live Neural Core must not retain an unmasked frame-zero fallback' -qsF 'firstMaskedFrame' WidgetShared/NeuralCoreContinuousAnimation.swift
# One mutually exclusive selector stack per platform; neither runtime path
# duplicates a frame's mask as the rejected build-71 replacement did.
[[ "$(grep -c 'JARVISWidgetTimerFrameWindow(' WidgetShared/NeuralCoreContinuousAnimation.swift)" == "2" ]]
grep -q 'if layout == .watch' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q '48 nominal-24-FPS selector scenes' WidgetShared/NeuralCoreContinuousAnimation.swift
reject_match 'phone Neural Core motion must not be disabled by a host rendering-mode classification' -qsF 'layout != .phone || renderingMode == .fullColor' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'JARVISNeuralCoreFrameArtwork' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q '.widgetAccentable(true)' WidgetShared/NeuralCoreArtwork.swift
reject_match 'live Cathedral frames must not use extra blend passes' -Eq '\.blendMode\(|\.compositingGroup\(' WidgetShared/NeuralCoreContinuousAnimation.swift
reject_match 'live Cathedral Canvas must not paint an opaque phone fill' -Eq 'fillsBackground|widgetAccentable\(false\)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'var radiusFactor: CGFloat { 0.325 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'var latitudeCount: Int { 11 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'var longitudeCount: Int { 13 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'var filamentCount: Int { 92 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'var particleCount: Int { 78 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'var rayCount: Int { 28 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'var columnCount: Int { 11 }' WidgetShared/NeuralCoreArtwork.swift
grep -q 'func lineScale(for radius: CGFloat)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'func detailScale(for radius: CGFloat)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'func curveSegments(watch _: Int, phone: Int)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'layout.curveSegments(watch: 46, phone: 44)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'layout.curveSegments(watch: 9, phone: 8)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'layout.curveSegments(watch: 5, phone: 5)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'layout.curveSegments(watch: 10, phone: 10)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'layout.curveSegments(watch: 12, phone: 12)' WidgetShared/NeuralCoreArtwork.swift
reject_match 'phone Cathedral curves must retain archive-safe physical tessellation' -Eq 'layout == \.watch \? (34 : 64|30 : 56|46 : 82|38 : 72|24 : 46|9 : 14)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'JARVISNeuralCoreWordmark(layout: layout)' WidgetShared/NeuralCoreContinuousAnimation.swift
# The Watch branch retains its full wrapper for the common static halo and every
# complete motion phase; the third occurrence is the accessible static branch.
# Phone live phases remain Canvas-only.
[[ "$(grep -c 'JARVISNeuralCoreArtwork(' WidgetShared/NeuralCoreContinuousAnimation.swift)" == "3" ]]
grep -q 'layerSet: .staticBackground' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'layerSet: .phaseArtwork' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'includesWordmark: false' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'case staticBackground' WidgetShared/NeuralCoreArtwork.swift
grep -q 'case phaseArtwork' WidgetShared/NeuralCoreArtwork.swift
reject_match 'Watch and phone must not use visually divergent Canvas layer sets' -Eq 'case watchStatic|case watchMotion|layerSet: \.watch' WidgetShared/NeuralCoreArtwork.swift WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'private static let pseudoCache: \[CGFloat\]' WidgetShared/NeuralCoreArtwork.swift
grep -q 'static func rotatedEllipsePath(' WidgetShared/NeuralCoreArtwork.swift
grep -q 'static func arcPath(' WidgetShared/NeuralCoreArtwork.swift
reject_match 'optimized Cathedral geometry must not restore temporary arc/ellipse point arrays' -Eq 'rotatedEllipsePoints|arcPoints' WidgetShared/NeuralCoreArtwork.swift
reject_match 'Watch artwork must retain the same firing and particle glows as phone artwork' -Eq 'trailIndex == 0 && layout|twinkle > 0\.80 && layout' WidgetShared/NeuralCoreArtwork.swift
python3 - <<'PY'
from pathlib import Path
source = Path("WidgetShared/NeuralCoreArtwork.swift").read_text()
static_start = source.index("case .staticBackground:")
phase_start = source.index("case .phaseArtwork:", static_start)
phase_end = source.index("\n            }\n        }\n    }", phase_start)
static_block = source[static_start:phase_start]
phase_block = source[phase_start:phase_end]
assert static_block.count("drawHalo(") == 1
assert "drawHalo(" not in phase_block
ordered = [
    "drawCathedralArchitecture(", "drawWireframe(", "drawFilaments(",
    "drawColumns(", "drawRadialCrown(", "drawParticles(",
    "drawPlugAnchors(", "drawSegmentedQuotaRing(",
    "drawReactorDischarges(", "drawCore(",
]
positions = [phase_block.index(call) for call in ordered]
assert positions == sorted(positions)
canvas_start = source.index("private struct JARVISMonochromeCathedralCanvas")
canvas_end = source.index("private struct JARVISCathedralFilament", canvas_start)
canvas = source[canvas_start:canvas_end]
assert "layout == .phone" not in canvas
assert "layout == .watch" not in canvas
wordmark_start = source.index("struct JARVISNeuralCoreWordmark")
wordmark_end = source.index("enum JARVISNeuralCoreAccessibility", wordmark_start)
wordmark = source[wordmark_start:wordmark_end]
assert "layout == .phone" not in wordmark
assert "layout == .watch" not in wordmark
PY
[[ "$(grep -c 'Text("JARVIS")' WidgetShared/NeuralCoreArtwork.swift)" == "1" ]]
grep -q 'reloadTimelines(ofKind: "JARVISNeuralCoreWidget.v1")' JARVIS/JARVISApp.swift
grep -q 'PhoneNeuralCoreWidgetReloadCoordinator.reloadIfDue()' JARVIS/JARVISApp.swift
grep -q 'JARVISNeuralCoreWidgetReloadPolicy.shouldRequestReload' JARVIS/JARVISApp.swift
grep -q 'JARVISWidgetTimerAnimationFont.register()' JARVISWatchWidget/NeuralCoreWidget.swift
[[ "$(grep -c 'reloadTimelines(ofKind: "JARVISWatchNeuralCoreWidget.v1")' JARVISWatch/JARVISWatchApp.swift)" == "1" ]]
grep -q 'WatchNeuralCoreWidgetReloadCoordinator.reloadIfDue()' JARVISWatch/JARVISWatchApp.swift
grep -q 'JARVISNeuralCoreWidgetReloadPolicy.shouldRequestReload' JARVISWatch/JARVISWatchApp.swift
grep -q 'timelineRefreshDeadline: TimeInterval = 8' JARVISKit/Sources/JARVISKit/WidgetSupport.swift
grep -q 'JARVISWidgetRefreshDeadline.run' JARVISKit/Sources/JARVISKit/WidgetSupport.swift
reject_match 'Watch Neural Core recovery must stay targeted' -qsF 'reloadAllTimelines()' JARVISWatch/JARVISWatchApp.swift
[[ "$(shasum -a 256 WidgetShared/FillRect-Regular.otf | awk '{print $1}')" == "7a41bc7e983b7e67f055fdb444fc3dd0d94fd3e288532295b7045b79b655a42a" ]]
[[ -f docs/third-party/AnimationLimitBreaker-LICENSE.txt ]]
reject_match 'approved artwork omits the Neural Core subtitle' -qsF 'Text("NEURAL CORE")' WidgetShared/NeuralCoreArtwork.swift
reject_match 'approved artwork omits the synchronized subtitle' -qsF 'Text("SYNCHRONIZED")' WidgetShared/NeuralCoreArtwork.swift
reject_match 'approved artwork omits visible signal-lost copy' -qsF 'Text("SIGNAL LOST")' WidgetShared/NeuralCoreArtwork.swift
reject_match 'approved artwork omits visible host copy' -qsF 'Text("MAC-MINI-64")' WidgetShared/NeuralCoreArtwork.swift
grep -q 'Text("JARVIS")' WidgetShared/NeuralCoreArtwork.swift
grep -q '.unredacted()' WidgetShared/NeuralCoreArtwork.swift
grep -q 'JARVISNeuralCoreMotion.transitionDuration' WidgetShared/NeuralCoreArtwork.swift
grep -q 'accessibilityReduceMotion' WidgetShared/NeuralCoreArtwork.swift
grep -q 'isLuminanceReduced' WidgetShared/NeuralCoreArtwork.swift
grep -q 'client.resolveState(' JARVISKit/Sources/JARVISKit/WidgetSupport.swift
grep -q 'preferredEndpoint: preferredEndpoint' JARVISKit/Sources/JARVISKit/WidgetSupport.swift
reject_match 'widget refresh must not rediscover before trying its saved authenticated route' -qsF 'client.discover(' JARVISKit/Sources/JARVISKit/WidgetSupport.swift
reject_match 'widget state loader must not retain retired plug interaction state' -qsE 'applyConfirmedPlugState|plugNames\(|JARVISWidgetControlStore|pending-plug-commands|completed-plug-commands' JARVISKit/Sources/JARVISKit/WidgetSupport.swift
reject_match 'iPhone widget support must not retain configurable plug providers' -qsE 'AppIntent|SelectedPlug|PlugChoice' JARVISWidget/WidgetSupport.swift
reject_match 'Watch widget support must not retain configurable plug providers' -qsE 'AppIntent|SelectedPlug|PlugChoice' JARVISWatchWidget/WidgetSupport.swift
grep -q 'Image("JARVISWidgetIcon", bundle: .main)' JARVISWatchWidget/LauncherWidget.swift
grep -q 'Image("JARVISWidgetIconAccented", bundle: .main)' JARVISWatchWidget/LauncherWidget.swift
grep -q '@Environment(\\.widgetRenderingMode)' JARVISWatchWidget/LauncherWidget.swift
grep -q 'GeometryReader' JARVISWatchWidget/LauncherWidget.swift
grep -q 'let kind = "JARVISWatchLauncherWidget.v2"' JARVISWatchWidget/LauncherWidget.swift
grep -q 'reloadTimelines(ofKind: "JARVISWatchLauncherWidget.v2")' JARVISWatch/JARVISWatchApp.swift
grep -q 'WatchLauncherWidgetReloadPolicy.reloadAfterUpgradeIfNeeded()' JARVISWatch/JARVISWatchApp.swift
grep -q 'jarvis.watch-launcher-widget.last-reload-build' JARVISWatch/JARVISWatchApp.swift
grep -q 'guard defaults.string(forKey: lastRequestedBuildKey) != build else { return }' JARVISWatch/JARVISWatchApp.swift
[[ -s JARVISWatchWidget/Assets.xcassets/JARVISWidgetIcon.imageset/JARVISWidgetIcon@2x.png ]]
[[ -s JARVISWatchWidget/Assets.xcassets/JARVISWidgetIconAccented.imageset/JARVISWidgetIconAccented@2x.png ]]
grep -Rqs 'Image("JARVISMark")' JARVIS/Views
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
  -skipPackagePluginValidation \
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
from pathlib import Path
for path in sys.argv[1:3]:
    metadata = Path(path)
    if not metadata.exists():
        continue
    with metadata.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload.get("actions", {}) == {}, path
    assert payload.get("entities", {}) == {}, path
    assert payload.get("queries", {}) == {}, path

for path in sys.argv[3:]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    actions = payload.get("actions", {})
    is_watch = "/Watch/" in path
    expected_actions = {"SendPromptToJARVISIntent"}
    if not is_watch:
        expected_actions.add("OpenJARVISTerminalIntent")
    assert set(actions) == expected_actions, (path, sorted(actions))
    prompt_action = actions["SendPromptToJARVISIntent"]
    assert prompt_action["isDiscoverable"] is True, path
    assert prompt_action["openAppWhenRun"] is is_watch, path
    assert prompt_action["systemProtocols"] == [], path
    prompt_parameter = prompt_action["parameters"][0]
    assert prompt_parameter["name"] == "prompt", path
    assert prompt_parameter["isOptional"] is False, path
    assert prompt_parameter["valueType"]["primitive"]["wrapper"]["typeIdentifier"] == 0, path
    if not is_watch:
        terminal_open = actions["OpenJARVISTerminalIntent"]
        assert terminal_open["isDiscoverable"] is False, path
        assert terminal_open["openAppWhenRun"] is True, path
        assert terminal_open["parameters"][0]["name"] == "target", path
    shortcuts = payload.get("autoShortcuts", [])
    assert [item["actionIdentifier"] for item in shortcuts] == ["SendPromptToJARVISIntent"], path
    phrases = [item["key"] for item in shortcuts[0].get("phraseTemplates", [])]
    assert phrases == ["Hey ${applicationName}"], (path, phrases)
    assert payload.get("entities", {}) == {}, path
    assert payload.get("queries", {}) == {}, path
PY
if find "$PHONE_APP" -type f \( -iname '*.wav' -o -iname '*.wave' -o -iname '*.aiff' -o -iname '*.caf' -o -iname '*.m4a' -o -iname '*.mp3' \) -print -quit | grep -q .; then
  echo 'built app bundle contains an unexpected audio resource' >&2
  exit 1
fi
PHONE_WIDGET_BINARY="$PHONE_WIDGET/JARVISWidget"
WATCH_WIDGET_BINARY="$WATCH_WIDGET/JARVISWatchWidget"
[[ -f "$PHONE_WIDGET/JARVISWidget.debug.dylib" ]] && PHONE_WIDGET_BINARY="$PHONE_WIDGET/JARVISWidget.debug.dylib"
[[ -f "$WATCH_WIDGET/JARVISWatchWidget.debug.dylib" ]] && WATCH_WIDGET_BINARY="$WATCH_WIDGET/JARVISWatchWidget.debug.dylib"
for kind in \
  JARVISNeuralCoreWidget.v1 \
  JARVISLauncherWidget.v1; do
  grep -aFq "$kind" "$PHONE_WIDGET_BINARY" || { echo "built iOS widget missing kind: $kind" >&2; exit 1; }
done
for kind in \
  JARVISWatchNeuralCoreWidget.v1 \
  JARVISWatchLauncherWidget.v2; do
  grep -aFq "$kind" "$WATCH_WIDGET_BINARY" || { echo "built watch widget missing kind: $kind" >&2; exit 1; }
done
for retired_kind in \
  JARVISPlugWidget JARVISSelectedPlugWidget.v1 JARVISPlugGridWidget.v1 \
  JARVISWatchSelectedPlugWidget.v1 JARVISWatchPlugGridWidget.v1 \
  JARVISPurifierWidget.v1 JARVISWatchPurifierWidget.v1; do
  if grep -aFq "$retired_kind" "$PHONE_WIDGET_BINARY" || grep -aFq "$retired_kind" "$WATCH_WIDGET_BINARY"; then
    echo "built widget still contains retired kind: $retired_kind" >&2
    exit 1
  fi
done

if [[ "${JARVIS_RUN_IOS_TESTS:-0}" == "1" ]]; then
  printf '%s\n' '== iOS unit tests =='
  xcodebuild \
    -skipPackagePluginValidation \
    -project JARVIS.xcodeproj \
    -scheme JARVIS \
    -configuration Debug \
    -destination 'platform=iOS Simulator,name=JARVIS iPhone 11,OS=26.5' \
    -derivedDataPath "$DERIVED_DATA_PATH" \
    CODE_SIGNING_ALLOWED=NO \
    test
fi

printf '%s\n' '== watchOS simulator build =='
xcodebuild \
  -skipPackagePluginValidation \
  -project JARVIS.xcodeproj \
  -scheme JARVISWatch \
  -configuration Debug \
  -destination 'generic/platform=watchOS Simulator' \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  CODE_SIGNING_ALLOWED=NO \
  build
[[ -d "$DERIVED_DATA_PATH/Build/Products/Debug-watchsimulator/JARVISWatch.app/PlugIns/JARVISWatchWidget.appex" ]] \
  || { echo "watch widget was not embedded" >&2; exit 1; }
WATCH_HOST_BINARY="$DERIVED_DATA_PATH/Build/Products/Debug-watchsimulator/JARVISWatch.app/JARVISWatch"
[[ -f "$DERIVED_DATA_PATH/Build/Products/Debug-watchsimulator/JARVISWatch.app/JARVISWatch.debug.dylib" ]] \
  && WATCH_HOST_BINARY="$DERIVED_DATA_PATH/Build/Products/Debug-watchsimulator/JARVISWatch.app/JARVISWatch.debug.dylib"
reject_match 'SSH terminal code leaked into the Watch host' -aFq 'PiTerminalConfiguration' "$WATCH_HOST_BINARY"

printf '%s\n' '== complete =='
