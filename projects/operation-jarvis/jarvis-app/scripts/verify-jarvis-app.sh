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
python3 -m py_compile \
  jarvisd/jarvisd.py \
  terminald/jarvis_terminald.py \
  ../jarvis.py \
  ../raspberry-pi/room_audio/room_audio_server.py \
  ../voice/discord_voice.py \
  ../../../.pi/discord-cron/runner.py

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

printf '%s\n' '== plist, icon, and shell syntax =='
plutil -lint \
  JARVIS/Info.plist \
  JARVIS/PrivacyInfo.xcprivacy \
  JARVISWidget/Info.plist \
  JARVISWatch/Info.plist \
  JARVISWatchWidget/Info.plist \
  jarvisd/launchd/*.plist \
  terminald/launchd/*.plist
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
[[ "$(grep -c '\.tabItem' JARVIS/JARVISApp.swift)" == "3" ]]
grep -q 'Label("Home"' JARVIS/JARVISApp.swift
grep -q 'Label("JARVIS"' JARVIS/JARVISApp.swift
reject_match 'Pi tab must be labeled JARVIS' -Fq 'Label("Pi"' JARVIS/JARVISApp.swift
grep -q 'Label("Settings"' JARVIS/JARVISApp.swift
grep -q 'case pi' JARVIS/AppState.swift
grep -q 'case "pi": selection = .pi' JARVIS/JARVISApp.swift
reject_match 'retired Events UI is still referenced' -RqsE 'EventsView|case events|fetchEvents|lastEvents|eventsLoading' JARVIS

printf '%s\n' '== compact iPhone dashboard contract =='
grep -q 'private var compactConnectionStrip' JARVIS/Views/HomeView.swift
grep -q 'MinimalSectionHeader(title: "System"' JARVIS/Views/HomeView.swift
grep -q 'private func settingsGroup<Content: View>' JARVIS/Views/SettingsView.swift
grep -q 'private var diagnosticsDetail' JARVIS/Views/SettingsView.swift
grep -q 'private var piTerminalDetail' JARVIS/Views/SettingsView.swift
grep -q 'private var watchTerminalDetail' JARVIS/Views/SettingsView.swift
reject_match 'legacy oversized iPhone status hero remains' -RqsE 'private var statusHeader|private var settingsHero|Native control plane' JARVIS/Views
reject_match 'legacy expanded Home service groups remain' -qsE 'runtimeServicesExpanded|scheduledJobsExpanded|DisclosureGroup' JARVIS/Views/HomeView.swift
reject_match 'Pi and Codex summaries must remain directly visible on Home' -qsE 'codexDetail|navigationTitle\("Codex usage"\)' JARVIS/Views/HomeView.swift

printf '%s\n' '== Pi terminal source contract =='
grep -q 'exactVersion: 1.20.0' project.yml
grep -q 'exactVersion: 0.15.0' project.yml
grep -q 'exactVersion: 2.101.3' project.yml
grep -q 'import SwiftTerm' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'import NIOSSH' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'defaultFontSize: CGFloat = 18' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'zoomSchemaDefaultsKey = "jarvis.pi-terminal.zoom-schema"' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'savedZoomSchema >= currentZoomSchema' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'keyboardDismissMode = .interactive' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'handleKeyboardDismissPan' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'allowMouseReporting = false' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'override func mouseModeChanged' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'prioritizeTouchScrolling' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'handleTouchScrollPan' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'let button = scrollingUp ? 64 : 65' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'max(36, fontSize \* 2.5)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'static let deliveryFramesPerSecond = 60' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'CADisplayLink(target: self, selector: #selector(deliverNextTouchScrollStep(_:)))' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'stopTouchScrollDelivery(clearPending: true)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'override func showCursor(source: Terminal)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'PiTerminalTouchScroll.cursorLocation' JARVIS/Terminal/PiSSHTransport.swift
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
grep -q 'new-session -d' scripts/jarvis-mobile-terminal.sh
grep -q 'attach-session' scripts/jarvis-mobile-terminal.sh
grep -q 'export PATH="/opt/homebrew/bin:' scripts/jarvis-mobile-terminal.sh
grep -q "PI_COMMAND='/opt/homebrew/bin/pi --tui-mode regular'" scripts/jarvis-mobile-terminal.sh
reject_match 'Mobile Pi launcher must not restore fullscreen TUI mode' -Fq -- '--tui-mode fullscreen' scripts/jarvis-mobile-terminal.sh
grep -q 'source-file "$TMUX_CONFIG"' scripts/jarvis-mobile-terminal.sh
grep -q 'send-keys -X -N 1 scroll-up' config/jarvis-mobile.tmux.conf
grep -q 'send-keys -X -N 1 scroll-down' config/jarvis-mobile.tmux.conf
reject_match 'Pi terminal must not assign a special Pi session name' -Fq -- '--name' scripts/jarvis-mobile-terminal.sh
grep -q 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly' JARVIS/Terminal/PiTerminalSettings.swift
grep -q 'String(openSSHPublicKey: hostKey)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'extended-keys-format csi-u' config/jarvis-mobile.tmux.conf
grep -q 'window-size latest' config/jarvis-mobile.tmux.conf
reject_match 'Pi terminal must not accept every SSH host key' -RqsE 'AcceptAllHostKeys|acceptAnything' JARVIS/Terminal
reject_match 'Pi terminal reconnect must not queue input' -RqsE 'queuedInput|pendingInput|inputQueue' JARVIS/Terminal
grep -q 'prepareTerminalForFreshConnection()' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'terminal.resetToInitialState()' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'windowState.update(cols: cols, rows: rows)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'initialWindowSize: self.windowState.snapshot()' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'publishWindowChange(self.windowState.snapshot(), on: childChannel)' JARVIS/Terminal/PiSSHTransport.swift
grep -q 'testPiTerminalResetsStaleAlternateScreenBeforeFreshConnection' JARVISTests/AppStateTests.swift
grep -q 'testPiTerminalRetainsLayoutResizeUntilSSHSessionIsReady' JARVISTests/AppStateTests.swift
reject_match 'Pi SSH session must not replay stale initial dimensions after authentication' -Fq 'self.resize(cols: self.initialWindowSize.cols, rows: self.initialWindowSize.rows)' JARVIS/Terminal/PiSSHTransport.swift
reject_match 'Pi launcher must not kill its persistent session' -RqsE 'kill-session|kill-server' JARVIS/Terminal config/jarvis-mobile.tmux.conf scripts/jarvis-mobile-terminal.sh
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
grep -q 'parsed.path not in {"/v1/terminal/input", "/v1/terminal/speech"}' terminald/jarvis_terminald.py
grep -q 'path == "/synthesize"' ../raspberry-pi/room_audio/room_audio_server.py
grep -q 'is_loopback_address(self.client_address\[0\])' ../raspberry-pi/room_audio/room_audio_server.py
grep -q 'public func speechAudio(responseID: String)' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'import AVFoundation' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Image(systemName: controller.isSpeechPlaying ? "stop.fill" : "speaker.wave.2.fill")' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private func prepareSpeechIfNeeded()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private var speechClient: WatchTerminalClient?' JARVISWatch/Views/WatchTerminalView.swift
grep -q '_ = try await speechClient.preflight()' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'downloadedURL = try await speechClient.speechAudio(responseID: responseID)' JARVISWatch/Views/WatchTerminalView.swift
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
grep -q 'requiresLiveTerminal: false' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'preservePreparedSpeech: isSpeechLoading || speechFileURL != nil' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'if !preserveSpeechPlayback && !preservePreparedSpeech { stopSpeech() }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'failureAge < 12' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'public enum WatchTerminalSpeechRetryPolicy' JARVISKit/Sources/JARVISKit/WatchTerminal.swift
grep -q 'preferredBaseURL: preferredRoute' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private static let preparedSpeechResponseIDKey' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'appendingPathComponent("jarvis-watch-last-response", isDirectory: false)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'values.isExcludedFromBackup = true' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'try? fileManager.removeItem(at: destination)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'guard let speech = frame?.speech else { return true }' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'private func trace(_ event: String)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'self.speech_synthesis_events: Dict\[str, threading.Event\]' terminald/jarvis_terminald.py
grep -q 'completion.wait(timeout=185)' terminald/jarvis_terminald.py
grep -q 'os.replace(temporary_path, cache_path)' terminald/jarvis_terminald.py
grep -q 'for stale_path in self.speech_dir.glob("\*.wav")' terminald/jarvis_terminald.py
/usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes:0' JARVISWatch/Info.plist | grep -qx 'audio'
grep -q 'def _bounded_tts_chunks' ../voice/discord_voice.py
grep -q 'cleaned_text = self._clean_text_for_tts(text)' ../voice/discord_voice.py
reject_match 'Watch terminal frame must never carry raw final response text' -RqsE 'responseText|speechText' JARVISKit/Sources/JARVISKit/WatchTerminal.swift terminald/jarvis_terminald.py
reject_match 'Watch speech must not accept arbitrary client text' -Fq '"text"' < <(sed -n '/    def do_POST(self)/,/^def parse_cidrs/p' terminald/jarvis_terminald.py)
reject_match 'Watch terminal must not fake a workout or unsupported extended-runtime category' -E 'WKExtendedRuntimeSession|HKWorkoutSession|isFrontmostTimeoutExtended' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'digitalCrownRotation' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.focused(\$crownIsFocused)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'through: 0' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'isContinuous: false' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalCrownHistory.scrollOffset' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Crown live edge must not use rebound-prone incremental history' -Fq 'adjustScroll(towardHistory:' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'WatchTerminalANSIParser.parse(lines: frame.ansiLines)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'frame.viewportRange(maximumLines:' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch terminal must not duplicate Pi input in a prompt rail' -E 'private var promptRail|promptViewport\(displayColumns:' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Text("JARVIS")' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.frame(maxWidth: \.infinity, alignment: \.center)' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.padding(\.horizontal, 7)' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Image(systemName: "terminal.fill")' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'case fit' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'case grid' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Crown scrolling must remain local and read-only' -Fq 'controller.sendWheel' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'showingKeyPalette' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'TextField("", text: \$keyboardDraft, prompt:' JARVISWatch/Views/WatchTerminalView.swift
grep -q '\.submitLabel(.done)' JARVISWatch/Views/WatchTerminalView.swift
reject_match 'Watch Input must not use the system chooser that can resume in dictation' -Fq 'TextFieldLink' JARVISWatch/Views/WatchTerminalView.swift
grep -q 'Touch remains page navigation only' JARVISWatch/Views/WatchTerminalView.swift
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
grep -q 'WatchTerminalInput(data: WatchTerminalKeyBytes.backspace, appendReturn: false)' JARVISWatch/Views/WatchTerminalView.swift
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
reject_match 'System Watch pager must not reserve the removed clock strip' -Fq 'tabViewStyle(.verticalPage)' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'Watch terminal must not require an Open button' -qs 'Open JARVIS' JARVISWatch/Views/WatchDashboardContent.swift
reject_match 'Watch terminal must not use a navigation launcher' -qs 'NavigationLink' JARVISWatch/Views/WatchDashboardContent.swift
[[ -x terminald/jarvis_terminald.py ]]
[[ -x scripts/install-jarvis-terminald.sh ]]
[[ -x scripts/jarvis-terminal-provisioning.sh ]]
reject_match 'Watch terminal must not open SSH directly' -RqsE 'import NIOSSH|import NIOPosix|import SwiftTerm' JARVISWatch
reject_match 'terminal bridge must remain separate from jarvisd' -RqsF 'terminal/frame' jarvisd

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

printf '%s\n' '== Siri plug source contract =='
grep -q 'struct TurnOnJARVISPlugIntent: AppIntent' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'struct TurnOffJARVISPlugIntent: AppIntent' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'struct JARVISPlugEntity: AppEntity' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'struct JARVISPlugEntityQuery: EntityStringQuery' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Hey \\(\.applicationName), turn on a plug' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Hey \\(\.applicationName), turn off a plug' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Hey \\(\.applicationName), turn on \\(\\.\$plug)' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Hey \\(\.applicationName), turn on the \\(\\.\$plug)' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Hey \\(\.applicationName), turn off \\(\\.\$plug)' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'Hey \\(\.applicationName), turn off the \\(\\.\$plug)' HostAppIntents/JARVISSiriPlugIntents.swift
reject_match 'legacy Siri phrase is still advertised' -qsE 'Tell \\(\.applicationName)| with \\(\.applicationName)|Use \\(\.applicationName)' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'struct SendPromptToJARVISIntent: AppIntent' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'requestValueDialog: IntentDialog("What would you like me to send to JARVIS?")' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'JARVISSpokenPrompt.normalize(rawPrompt)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'WatchTerminalInput(data: Data(normalized.utf8), appendReturn: true)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q '#if os(watchOS)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'static var openAppWhenRun: Bool { true }' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'static var openAppWhenRun: Bool { false }' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'case \.sent:' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'JARVISSiriNavigation.requestTerminalPresentation()' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'struct OpenJARVISTerminalIntent: OpenIntent' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'opensIntent: OpenJARVISTerminalIntent(target: .terminal)' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q '@MainActor' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'URL(string: "jarvis://terminal")' HostAppIntents/JARVISSiriPromptIntent.swift
reject_match 'Siri terminal handoff must not use OpenURLIntent with a custom URL scheme' -qsF 'OpenURLIntent(' HostAppIntents/JARVISSiriPromptIntent.swift
grep -q 'selection = \.pi' JARVIS/JARVISApp.swift
grep -q 'selectedPage = \.terminal' JARVISWatch/Views/WatchDashboardContent.swift
grep -q 'JARVISSiriNavigation.consumeTerminalPresentationRequest()' JARVIS/JARVISApp.swift
grep -q 'JARVISSiriNavigation.consumeTerminalPresentationRequest()' JARVISWatch/Views/WatchConnectView.swift
grep -q 'JARVISSiriNavigation.isTerminalURL(url)' JARVIS/JARVISApp.swift
grep -q 'JARVISSiriNavigation.isTerminalURL(url)' JARVISWatch/Views/WatchConnectView.swift
grep -q 'phrases: \["Hey \\(.applicationName)"\]' HostAppIntents/JARVISSiriPlugIntents.swift
[[ "$(grep -c 'AppShortcut(' HostAppIntents/JARVISSiriPlugIntents.swift)" == "3" ]]
grep -q 'static var isDiscoverable: Bool { false }' SharedAppIntents/JARVISWidgetIntents.swift
grep -q 'queueIfUnreachable: false' JARVISKit/Sources/JARVISKit/WatchBridge.swift
grep -q 'allowsWatchRelayFallback' JARVISKit/Sources/JARVISKit/PlugCommandExecutor.swift
grep -q 'private actor JARVISSiriCatalogueCoordinator' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'private let retention: TimeInterval = 15' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'final class JARVISSiriParameterRegistrar' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'schemaVersion: Int = 5' HostAppIntents/JARVISSiriPlugIntents.swift
grep -q 'jarvis.siri.parameter-signature.v1' HostAppIntents/JARVISSiriPlugIntents.swift
reject_match 'Siri source contains a compiled production plug identifier' -qsE 'family-room-light|pedalboard|"lamp"|"tv"' HostAppIntents/JARVISSiriPlugIntents.swift
reject_match 'non-plug Siri surface is present' -qsiE 'purifier|scheduled.?job|serviceAction|discord|room.?audio' HostAppIntents/JARVISSiriPlugIntents.swift
reject_match 'Siri plug path must never toggle' -RqsF 'plug-toggle' HostAppIntents JARVISKit/Sources/JARVISKit/PlugCatalog.swift JARVISKit/Sources/JARVISKit/PlugCommandExecutor.swift

printf '%s\n' '== widget source contract =='
reject_match 'legacy iPhone widget kind is still present' -RqsF 'let kind = "JARVISPlugWidget"' JARVISWidget
reject_match 'legacy Watch widget kind is still present' -RqsF 'let kind = "JARVISWatchWidget"' JARVISWatchWidget
for kind in \
  JARVISNeuralCoreWidget.v1 \
  JARVISLauncherWidget.v1 \
  JARVISSelectedPlugWidget.v1 \
  JARVISPlugGridWidget.v1 \
  JARVISPurifierWidget.v1; do
  grep -Rqs "let kind = \"$kind\"" JARVISWidget || { echo "missing iOS widget kind: $kind" >&2; exit 1; }
done
for kind in \
  JARVISWatchNeuralCoreWidget.v1 \
  JARVISWatchLauncherWidget.v2 \
  JARVISWatchSelectedPlugWidget.v1 \
  JARVISWatchPlugGridWidget.v1 \
  JARVISWatchPurifierWidget.v1; do
  grep -Rqs "let kind = \"$kind\"" JARVISWatchWidget || { echo "missing watch widget kind: $kind" >&2; exit 1; }
done
reject_match 'iPhone purifier widget must remain read-only' -qsF 'Button(intent:' JARVISWidget/PurifierWidget.swift
reject_match 'Watch purifier widget must remain read-only' -qsF 'Button(intent:' JARVISWatchWidget/PurifierWidget.swift
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
grep -q 'phoneContinuousFrameCount = 60' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
grep -q 'watchContinuousFrameCount = 32' JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift
grep -q 'JARVISWidgetTimerAnimationFont.register()' JARVISWidget/NeuralCoreWidget.swift
grep -q '.id(entry.date.timeIntervalSinceReferenceDate)' JARVISWidget/NeuralCoreWidget.swift
grep -q 'ZStack(alignment: .topLeading)' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'ForEach(0..<layout.continuousFrameCount' WidgetShared/NeuralCoreContinuousAnimation.swift
reject_match 'live Neural Core must not retain an unmasked frame-zero fallback' -qsF 'firstMaskedFrame' WidgetShared/NeuralCoreContinuousAnimation.swift
# One mutually exclusive selector stack per platform; neither runtime path
# duplicates a frame's mask as the rejected build-71 replacement did.
[[ "$(grep -c 'JARVISWidgetTimerFrameWindow(' WidgetShared/NeuralCoreContinuousAnimation.swift)" == "2" ]]
grep -q 'if layout == .watch' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q '32 complete Cathedral views' WidgetShared/NeuralCoreContinuousAnimation.swift
reject_match 'phone Neural Core motion must not be disabled by a host rendering-mode classification' -qsF 'layout != .phone || renderingMode == .fullColor' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q 'JARVISNeuralCoreFrameArtwork' WidgetShared/NeuralCoreContinuousAnimation.swift
grep -q '.widgetAccentable(true)' WidgetShared/NeuralCoreArtwork.swift
reject_match 'live Cathedral frames must not use extra blend passes' -Eq '\.blendMode\(|\.compositingGroup\(' WidgetShared/NeuralCoreContinuousAnimation.swift
reject_match 'live Cathedral Canvas must not paint an opaque phone fill' -Eq 'fillsBackground|widgetAccentable\(false\)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'func curveSegments(watch: Int, phone: Int)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'layout.curveSegments(watch: 46, phone: 44)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'layout.curveSegments(watch: 9, phone: 8)' WidgetShared/NeuralCoreArtwork.swift
reject_match 'phone Cathedral curves must retain archive-safe physical tessellation' -Eq 'layout == \.watch \? (34 : 64|30 : 56|46 : 82|38 : 72|24 : 46|9 : 14)' WidgetShared/NeuralCoreArtwork.swift
grep -q 'JARVISNeuralCoreWordmark(layout: layout)' WidgetShared/NeuralCoreContinuousAnimation.swift
# The Watch branch restores full per-phase artwork; the other occurrence is the
# common accessible static branch. Phone live phases remain Canvas-only.
[[ "$(grep -c 'JARVISNeuralCoreArtwork(' WidgetShared/NeuralCoreContinuousAnimation.swift)" == "2" ]]
[[ "$(grep -c 'Text("JARVIS")' WidgetShared/NeuralCoreArtwork.swift)" == "1" ]]
grep -q 'reloadTimelines(ofKind: "JARVISNeuralCoreWidget.v1")' JARVIS/JARVISApp.swift
grep -q 'JARVISWidgetTimerAnimationFont.register()' JARVISWatchWidget/NeuralCoreWidget.swift
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
for path in sys.argv[1:3]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    actions = payload.get("actions", {})
    assert "SelectJARVISPlugIntent" in actions, path
    assert "SetPlugIntent" in actions, path
    assert "SendPromptToJARVISIntent" not in actions, path

for path in sys.argv[3:]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    actions = payload.get("actions", {})
    assert actions["SetPlugIntent"]["isDiscoverable"] is False, path
    assert actions["TurnOnJARVISPlugIntent"]["isDiscoverable"] is True, path
    assert actions["TurnOffJARVISPlugIntent"]["isDiscoverable"] is True, path
    assert actions["SendPromptToJARVISIntent"]["isDiscoverable"] is True, path
    expected_open_app = "/Watch/" in path
    assert actions["SendPromptToJARVISIntent"]["openAppWhenRun"] is expected_open_app, path
    if expected_open_app:
        assert "OpenJARVISTerminalIntent" not in actions, path
    else:
        terminal_open = actions["OpenJARVISTerminalIntent"]
        assert terminal_open["isDiscoverable"] is False, path
        assert terminal_open["openAppWhenRun"] is True, path
        assert terminal_open["parameters"][0]["name"] == "target", path
    prompt_parameter = actions["SendPromptToJARVISIntent"]["parameters"][0]
    assert prompt_parameter["name"] == "prompt", path
    assert prompt_parameter["isOptional"] is False, path
    assert prompt_parameter["valueType"]["primitive"]["wrapper"]["typeIdentifier"] == 0, path
    shortcuts = payload.get("autoShortcuts", [])
    assert [item["actionIdentifier"] for item in shortcuts] == [
        "TurnOnJARVISPlugIntent",
        "TurnOffJARVISPlugIntent",
        "SendPromptToJARVISIntent",
    ], path
    expected_phrases = {
        "TurnOnJARVISPlugIntent": [
            "Hey ${applicationName}, turn on a plug",
            "Hey ${applicationName}, turn on ${plug}",
            "Hey ${applicationName}, turn on the ${plug}",
        ],
        "TurnOffJARVISPlugIntent": [
            "Hey ${applicationName}, turn off a plug",
            "Hey ${applicationName}, turn off ${plug}",
            "Hey ${applicationName}, turn off the ${plug}",
        ],
        "SendPromptToJARVISIntent": ["Hey ${applicationName}"],
    }
    for shortcut in shortcuts:
        phrases = [item["key"] for item in shortcut.get("phraseTemplates", [])]
        assert phrases == expected_phrases[shortcut["actionIdentifier"]], (path, phrases)
        assert any("${plug}" not in phrase for phrase in phrases), path
        if shortcut["actionIdentifier"] == "SendPromptToJARVISIntent":
            assert phrases == ["Hey ${applicationName}"], path
        else:
            assert all(phrase.startswith("Hey ${applicationName}, ") for phrase in phrases), path
        assert all(" with ${applicationName}" not in phrase for phrase in phrases), path
    assert "JARVISPlugEntity" in payload.get("entities", {}), path
    assert "JARVISPlugEntityQuery" in payload.get("queries", {}), path
PY
PHONE_WIDGET_BINARY="$PHONE_WIDGET/JARVISWidget"
WATCH_WIDGET_BINARY="$WATCH_WIDGET/JARVISWatchWidget"
[[ -f "$PHONE_WIDGET/JARVISWidget.debug.dylib" ]] && PHONE_WIDGET_BINARY="$PHONE_WIDGET/JARVISWidget.debug.dylib"
[[ -f "$WATCH_WIDGET/JARVISWatchWidget.debug.dylib" ]] && WATCH_WIDGET_BINARY="$WATCH_WIDGET/JARVISWatchWidget.debug.dylib"
for kind in \
  JARVISNeuralCoreWidget.v1 \
  JARVISLauncherWidget.v1 \
  JARVISSelectedPlugWidget.v1 \
  JARVISPlugGridWidget.v1 \
  JARVISPurifierWidget.v1; do
  grep -aFq "$kind" "$PHONE_WIDGET_BINARY" || { echo "built iOS widget missing kind: $kind" >&2; exit 1; }
done
for kind in \
  JARVISWatchNeuralCoreWidget.v1 \
  JARVISWatchLauncherWidget.v2 \
  JARVISWatchSelectedPlugWidget.v1 \
  JARVISWatchPlugGridWidget.v1 \
  JARVISWatchPurifierWidget.v1; do
  grep -aFq "$kind" "$WATCH_WIDGET_BINARY" || { echo "built watch widget missing kind: $kind" >&2; exit 1; }
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
