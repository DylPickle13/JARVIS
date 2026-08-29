import AVFoundation
import Foundation
import JARVISKit
import OSLog
import SwiftUI

@MainActor
private final class WatchTerminalSettings {
    #if DEBUG && targetEnvironment(simulator)
    private var simulatorConfiguration: WatchTerminalConfiguration?
    #endif

    var configuration: WatchTerminalConfiguration? {
        #if DEBUG && targetEnvironment(simulator)
        if let simulatorConfiguration { return simulatorConfiguration }
        #endif
        guard case .configured(let configuration) = JARVISTerminalConfigurationStore.load() else {
            return nil
        }
        return configuration
    }

    @discardableResult
    func save(_ configuration: WatchTerminalConfiguration) -> Bool {
        guard configuration.isValid else { return false }
        #if DEBUG && targetEnvironment(simulator)
        simulatorConfiguration = configuration
        return true
        #else
        return JARVISTerminalConfigurationStore.save(configuration)
        #endif
    }
}

@MainActor
final class WatchTerminalController: NSObject, ObservableObject, AVAudioPlayerDelegate {
    enum Status: Equatable {
        case notConfigured
        case connecting
        case live
        case offline

        var label: String {
            switch self {
            case .notConfigured: return "SET UP ON IPHONE"
            case .connecting: return "CONNECTING"
            case .live: return "LIVE"
            case .offline: return "OFFLINE"
            }
        }

        var color: Color {
            switch self {
            case .notConfigured: return .orange
            case .connecting: return .orange
            case .live: return .green
            case .offline: return .red
            }
        }
    }

    @Published private(set) var frame: WatchTerminalFrame?
    @Published private(set) var status: Status
    @Published private(set) var errorMessage: String?
    @Published private(set) var isSending = false
    @Published private(set) var pendingBackspaceCount = 0
    @Published private(set) var isConnectionConfirmed = false
    @Published private(set) var isSpeechLoading = false
    @Published private(set) var isSpeechPlaying = false
    @Published private(set) var historyPages: [WatchTerminalHistoryPage] = []
    @Published private(set) var isHistoryLoading = false
    @Published var speechErrorMessage: String?
    @Published var controlLatched = false

    private let settings = WatchTerminalSettings()
    private let speechFileStore = WatchTerminalSpeechFileStore()
    private var client: WatchTerminalClient?
    private var pollTask: Task<Void, Never>?
    private var wakeRecoveryTask: Task<Void, Never>?
    private var historyTask: Task<Void, Never>?
    private var historyRequest: (paneID: String, start: Int)?
    private var appIsForeground = false
    private var sceneIsActive = false
    private var isVisible = false
    private var connectionGeneration = 0
    private var successfulPollCount = 0
    private var pendingBackspaceIDs = Set<UUID>()
    private var speechTask: Task<Void, Never>?
    private var speechRetryTask: Task<Void, Never>?
    private var speechClient: WatchTerminalClient?
    private var speechPreparationID: UUID?
    private var speechActivationID: UUID?
    private var speechPlayer: AVAudioPlayer?
    private var speechFileURL: URL?
    private var speechResponseID: String?
    private var failedSpeechResponseID: String?
    private var exhaustedSpeechResponseID: String?
    private var speechRetryAttempt = 0
    private var speechInterruptionResumeTime: TimeInterval?
    private var pollFailureStartedAt: Date?
    private var lastPersistedPreferredRoute: String?
    private struct ANSIParseCacheEntry {
        let lines: [String]
        let spans: [[WatchTerminalANSISpan]]
    }
    private var ansiParseCache: [ANSIParseCacheEntry] = []
    private let logger = Logger(subsystem: "com.operation-jarvis.jarvis.watchkitapp", category: "terminal")

    private static let preferredRouteKey = "jarvis.watch-terminal.preferred-route"
    private static let ansiParseCacheLimit = 3

    override init() {
        #if DEBUG && targetEnvironment(simulator)
        let arguments = CommandLine.arguments
        if let index = arguments.firstIndex(of: "-jarvisSeedWatchTerminal"), index + 1 < arguments.count,
           let configuration = WatchTerminalConfiguration.fromProvisioningCode(arguments[index + 1]) {
            settings.save(configuration)
        }
        #endif
        status = settings.configuration == nil ? .notConfigured : .offline
        lastPersistedPreferredRoute = UserDefaults.standard.string(forKey: Self.preferredRouteKey)
        speechFileStore.removeOrphanedDownloads()
        if let retained = speechFileStore.restorePreparedSpeech() {
            speechResponseID = retained.responseID
            speechFileURL = retained.fileURL
        }
        super.init()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(audioSessionWasInterrupted(_:)),
            name: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance()
        )
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    func apply(configuration: WatchTerminalConfiguration) {
        guard settings.save(configuration) else {
            errorMessage = "Could not save the Watch terminal setup."
            return
        }
        stopSpeech()
        restartIfNeeded()
    }

    var terminalInputIsReady: Bool {
        status == .live && isConnectionConfirmed
    }

    func cachedHistoryPage(
        containing range: Range<Int>,
        paneID: String
    ) -> WatchTerminalHistoryPage? {
        historyPages.last { $0.paneID == paneID && $0.contains(range) }
    }

    func requestHistory(
        containing range: Range<Int>,
        paneID: String,
        historySize: Int
    ) {
        guard appIsForeground, isVisible, isConnectionConfirmed,
              !paneID.isEmpty, range.lowerBound >= 0,
              range.lowerBound < range.upperBound,
              range.upperBound <= historySize,
              cachedHistoryPage(containing: range, paneID: paneID) == nil,
              let client else { return }

        let pageStart = max(0, min(historySize, range.upperBound) - 192)
        if historyRequest?.paneID == paneID, historyRequest?.start == pageStart { return }
        historyTask?.cancel()
        historyRequest = (paneID, pageStart)
        isHistoryLoading = true
        let generation = connectionGeneration
        historyTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if self.connectionGeneration == generation,
                   self.historyRequest?.paneID == paneID,
                   self.historyRequest?.start == pageStart {
                    self.historyRequest = nil
                    self.historyTask = nil
                    self.isHistoryLoading = false
                }
            }
            do {
                let page = try await client.historyPage(start: pageStart)
                guard !Task.isCancelled,
                      self.connectionGeneration == generation,
                      page.paneID == paneID else { return }
                var retained = self.historyPages.filter {
                    $0.paneID == paneID && $0.start != page.start
                }
                retained.append(page)
                self.historyPages = Array(retained.suffix(3))
            } catch is CancellationError {
                return
            } catch {
                // History is read-only and opportunistic. Keep the confirmed
                // live route and input readiness independent from page failure.
                return
            }
        }
    }

    var canSpeakLastResponse: Bool {
        guard !isSpeechLoading, !isSpeechPlaying,
              let speechResponseID, !speechResponseID.isEmpty,
              let speechFileURL,
              FileManager.default.fileExists(atPath: speechFileURL.path) else { return false }
        // A complete local WAV is playable without a currently live terminal
        // route. If fresh metadata exists, it must still identify that response.
        guard let speech = frame?.speech else { return true }
        if speech.generating { return false }
        return !speech.available || speech.responseID == speechResponseID
    }

    /// Prepare exactly one complete final-response WAV while the terminal face
    /// remains foregrounded. Playback stays explicit and never begins until the
    /// authenticated download has finished and the entire file is local.
    private func prepareSpeechIfNeeded() {
        guard appIsForeground, isVisible,
              !isSpeechLoading, !isSpeechPlaying, speechRetryTask == nil,
              let speech = frame?.speech,
              speech.available, !speech.generating, !speech.responseID.isEmpty,
              failedSpeechResponseID != speech.responseID,
              exhaustedSpeechResponseID != speech.responseID,
              let configuration = settings.configuration else { return }
        if speechResponseID == speech.responseID,
           let speechFileURL,
           FileManager.default.fileExists(atPath: speechFileURL.path) {
            return
        }

        stopSpeech(resetPreparationFailures: false)
        speechErrorMessage = nil
        isSpeechLoading = true
        speechResponseID = speech.responseID
        let responseID = speech.responseID
        let preparationID = UUID()
        let preferredRoute = client?.selectedBaseURL ?? rememberedPreferredRoute(for: configuration)
        let speechClient = WatchTerminalClient(
            configuration: configuration,
            preferredBaseURL: preferredRoute
        )
        self.speechClient = speechClient
        trace("speech_prepare_start attempt=\(speechRetryAttempt + 1)")
        speechPreparationID = preparationID
        speechTask = Task { @MainActor [weak self] in
            guard let self else { return }
            var downloadedURL: URL?
            defer {
                speechClient.close()
                if self.speechClient === speechClient { self.speechClient = nil }
                if self.speechPreparationID == preparationID {
                    self.isSpeechLoading = false
                    self.speechTask = nil
                    self.speechPreparationID = nil
                }
                if let downloadedURL, downloadedURL != self.speechFileURL {
                    try? FileManager.default.removeItem(at: downloadedURL)
                }
            }
            do {
                _ = try await speechClient.preflight()
                downloadedURL = try await speechClient.speechAudio(responseID: responseID)
                try Task.checkCancellation()
                guard self.speechPreparationID == preparationID,
                      self.appIsForeground,
                      self.isVisible,
                      self.frame?.speech?.responseID == responseID,
                      self.frame?.speech?.available == true,
                      let downloadedURL else {
                    throw CancellationError()
                }
                self.speechFileURL = try self.retainPreparedSpeech(
                    from: downloadedURL,
                    responseID: responseID
                )
                self.speechRetryAttempt = 0
                self.exhaustedSpeechResponseID = nil
                self.trace("speech_prepare_ready")
            } catch is CancellationError {
                self.trace("speech_prepare_cancelled")
                return
            } catch {
                guard self.speechPreparationID == preparationID else { return }
                self.speechResponseID = nil
                if let clientError = error as? WatchTerminalClientError,
                   WatchTerminalSpeechRetryPolicy.shouldRetry(clientError),
                   self.appIsForeground,
                   self.isVisible,
                   self.frame?.speech?.responseID == responseID {
                    self.speechErrorMessage = nil
                    self.scheduleSpeechRetry(responseID: responseID)
                } else {
                    self.failedSpeechResponseID = responseID
                    self.speechErrorMessage = error.localizedDescription
                    self.trace("speech_prepare_failed_permanently")
                }
            }
        }
    }

    private func retainPreparedSpeech(from sourceURL: URL, responseID: String) throws -> URL {
        try speechFileStore.retainPreparedSpeech(from: sourceURL, responseID: responseID)
    }

    private func discardPreparedSpeech() {
        if let speechFileURL,
           speechFileURL.standardizedFileURL != speechFileStore.preparedFileURL?.standardizedFileURL {
            try? FileManager.default.removeItem(at: speechFileURL)
        }
        speechFileStore.discardPreparedSpeech()
        speechFileURL = nil
        speechResponseID = nil
    }

    private func scheduleSpeechRetry(responseID: String) {
        guard speechRetryAttempt < WatchTerminalSpeechRetryPolicy.maximumAttempts else {
            exhaustedSpeechResponseID = responseID
            trace("speech_prepare_retry_exhausted")
            return
        }
        speechRetryAttempt += 1
        let delay = WatchTerminalSpeechRetryPolicy.delaySeconds(afterFailure: speechRetryAttempt)
        trace("speech_prepare_retry_scheduled attempt=\(speechRetryAttempt) delay=\(delay)")
        speechRetryTask?.cancel()
        speechRetryTask = Task { @MainActor [weak self] in
            do {
                try await Task.sleep(for: .seconds(delay))
            } catch {
                return
            }
            guard let self else { return }
            self.speechRetryTask = nil
            guard self.appIsForeground,
                  self.isVisible,
                  self.frame?.speech?.responseID == responseID else { return }
            self.prepareSpeechIfNeeded()
        }
    }

    private func rememberedPreferredRoute(for configuration: WatchTerminalConfiguration) -> URL? {
        guard let raw = UserDefaults.standard.string(forKey: Self.preferredRouteKey),
              let route = URL(string: raw),
              configuration.candidateBaseURLs.contains(where: { $0.absoluteString == route.absoluteString }) else {
            return nil
        }
        return route
    }

    private func rememberPreferredRoute(_ route: URL?) {
        guard let route else { return }
        let value = route.absoluteString
        guard lastPersistedPreferredRoute != value else { return }
        UserDefaults.standard.set(value, forKey: Self.preferredRouteKey)
        lastPersistedPreferredRoute = value
    }

    /// Parsing ANSI rows is pure but comparatively expensive on Watch. Retain a
    /// tiny exact-input LRU so periodic redraws and unrelated UI changes reuse
    /// identical spans without changing bytes, styles, wrapping, or row order.
    func parsedANSILines(_ lines: [String]) -> [[WatchTerminalANSISpan]] {
        if let index = ansiParseCache.firstIndex(where: { $0.lines == lines }) {
            let entry = ansiParseCache.remove(at: index)
            ansiParseCache.append(entry)
            return entry.spans
        }
        let entry = ANSIParseCacheEntry(lines: lines, spans: WatchTerminalANSIParser.parse(lines: lines))
        if ansiParseCache.count >= Self.ansiParseCacheLimit {
            ansiParseCache.removeFirst()
        }
        ansiParseCache.append(entry)
        return entry.spans
    }

    private func trace(_ event: String) {
        logger.notice("\(event, privacy: .public) status=\(self.status.label, privacy: .public) confirmed=\(self.isConnectionConfirmed) visible=\(self.isVisible) foreground=\(self.appIsForeground) active=\(self.sceneIsActive)")
    }

    func toggleSpeech() {
        if isSpeechPlaying {
            stopSpeech()
            return
        }
        guard canSpeakLastResponse,
              speechResponseID != nil,
              speechFileURL != nil else { return }

        speechErrorMessage = nil
        activateAndPlayPreparedSpeech(from: 0, showsLoadingIndicator: true)
    }

    /// watchOS only grants supported wrist-down/background playback to sessions
    /// using the long-form route policy. Its asynchronous activation API must be
    /// used so the system can select or request an eligible local audio route.
    private func activateAndPlayPreparedSpeech(
        from playbackTime: TimeInterval,
        showsLoadingIndicator: Bool
    ) {
        guard let speechFileURL,
              FileManager.default.fileExists(atPath: speechFileURL.path) else {
            isSpeechPlaying = false
            speechErrorMessage = WatchTerminalClientError.invalidAudio.localizedDescription
            return
        }

        let activationID = UUID()
        speechActivationID = activationID
        isSpeechPlaying = true
        if showsLoadingIndicator { isSpeechLoading = true }

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(
                .playback,
                mode: .spokenAudio,
                policy: .longFormAudio,
                options: []
            )
        } catch {
            speechActivationID = nil
            isSpeechLoading = false
            isSpeechPlaying = false
            speechErrorMessage = error.localizedDescription
            return
        }

        session.activate(options: []) { [weak self] activated, error in
            Task { @MainActor [weak self] in
                guard let self, self.speechActivationID == activationID else { return }
                self.speechActivationID = nil
                self.isSpeechLoading = false
                guard activated else {
                    self.isSpeechPlaying = false
                    self.speechErrorMessage = error?.localizedDescription
                        ?? "The Watch could not activate an audio route."
                    return
                }
                guard self.speechFileURL == speechFileURL,
                      FileManager.default.fileExists(atPath: speechFileURL.path) else {
                    self.isSpeechPlaying = false
                    self.speechErrorMessage = WatchTerminalClientError.invalidAudio.localizedDescription
                    try? session.setActive(false, options: .notifyOthersOnDeactivation)
                    return
                }

                do {
                    let player = try AVAudioPlayer(contentsOf: speechFileURL)
                    player.delegate = self
                    guard player.prepareToPlay() else {
                        throw WatchTerminalClientError.invalidAudio
                    }
                    player.currentTime = min(max(0, playbackTime), player.duration)
                    self.speechPlayer?.stop()
                    self.speechPlayer = player
                    guard player.play() else {
                        self.speechPlayer = nil
                        throw WatchTerminalClientError.invalidAudio
                    }
                    self.speechInterruptionResumeTime = nil
                    self.isSpeechPlaying = true
                } catch {
                    self.isSpeechPlaying = false
                    self.speechErrorMessage = error.localizedDescription
                    try? session.setActive(false, options: .notifyOthersOnDeactivation)
                }
            }
        }
    }

    func stopSpeech(clearError: Bool = true, resetPreparationFailures: Bool = true) {
        speechPreparationID = nil
        speechActivationID = nil
        speechClient?.close()
        speechClient = nil
        speechTask?.cancel()
        speechTask = nil
        speechRetryTask?.cancel()
        speechRetryTask = nil
        speechPlayer?.stop()
        speechPlayer = nil
        discardPreparedSpeech()
        speechInterruptionResumeTime = nil
        isSpeechLoading = false
        isSpeechPlaying = false
        if resetPreparationFailures {
            failedSpeechResponseID = nil
            exhaustedSpeechResponseID = nil
            speechRetryAttempt = 0
        }
        if clearError { speechErrorMessage = nil }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    @objc nonisolated private func audioSessionWasInterrupted(_ notification: Notification) {
        let typeValue = (notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? NSNumber)?.uintValue
        let optionsValue = (notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? NSNumber)?.uintValue ?? 0
        Task { @MainActor [weak self] in
            self?.handleAudioSessionInterruption(typeValue: typeValue, optionsValue: optionsValue)
        }
    }

    private func handleAudioSessionInterruption(typeValue: UInt?, optionsValue: UInt) {
        guard let typeValue,
              let type = AVAudioSession.InterruptionType(rawValue: typeValue),
              isSpeechPlaying else { return }
        switch type {
        case .began:
            speechInterruptionResumeTime = speechPlayer?.currentTime ?? 0
        case .ended:
            let options = AVAudioSession.InterruptionOptions(rawValue: optionsValue)
            guard options.contains(.shouldResume), speechFileURL != nil else {
                speechPlayer = nil
                isSpeechPlaying = false
                speechErrorMessage = "JARVIS speech was interrupted by the system. Tap Read to resume."
                return
            }
            activateAndPlayPreparedSpeech(
                from: speechInterruptionResumeTime ?? speechPlayer?.currentTime ?? 0,
                showsLoadingIndicator: false
            )
        @unknown default:
            break
        }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            self?.stopSpeech(clearError: false)
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.stopSpeech(clearError: false)
            self.speechErrorMessage = error?.localizedDescription ?? "The JARVIS voice audio could not be played."
        }
    }

    func sceneDidBecomeActive() {
        let resumedFromInactive = appIsForeground && !sceneIsActive
        appIsForeground = true
        sceneIsActive = true
        trace("scene_active resumed_from_inactive=\(resumedFromInactive)")

        guard isVisible else { return }
        guard pollTask != nil, client != nil else {
            restartIfNeeded(preserveLiveStatus: frame != nil)
            return
        }

        if status == .offline {
            // The normal retry loop may be waiting after a route failure. A
            // foreground wake is an explicit opportunity to retry now.
            restartIfNeeded(preserveLiveStatus: frame != nil)
        } else if resumedFromInactive {
            // Keep a healthy URLSession/route instead of flashing orange and
            // rebuilding it for every wrist raise or tap. If watchOS suspended
            // the in-flight long poll and it does not resume, recover once
            // after a bounded grace period while keeping the last frame live.
            scheduleWakeRecovery()
        }
    }

    func sceneDidEnterAlwaysOn() {
        sceneIsActive = false
        trace("scene_inactive_always_on")
        wakeRecoveryTask?.cancel()
        wakeRecoveryTask = nil
        guard !appIsForeground else { return }
        appIsForeground = true
        restartIfNeeded(preserveLiveStatus: frame != nil)
    }

    func sceneDidEnterBackground() {
        sceneIsActive = false
        appIsForeground = false
        trace("scene_background")
        // watchOS suspends arbitrary terminal networking in true background.
        // Retain the last confirmed live frame instead of falsely declaring the
        // persistent tmux session offline, then reconnect immediately on wake.
        // An already-started local response continues independently. A fully
        // prepared local WAV is retained; only unfinished foreground network
        // preparation is cancelled by true background suspension.
        stop(
            markOffline: false,
            preserveSpeechPlayback: isSpeechPlaying,
            preservePreparedSpeech: !isSpeechLoading && speechFileURL != nil
        )
    }

    func setVisible(_ visible: Bool) {
        isVisible = visible
        trace("terminal_visible=\(visible)")
        if visible {
            if pollTask == nil || client == nil {
                restartIfNeeded(preserveLiveStatus: frame != nil)
            }
        } else {
            // Leaving the Terminal face must stop its networking, never an
            // already-started local response or the retained tmux/session state.
            // Input stays disabled until a fresh authenticated frame confirms
            // the recreated route.
            stop(markOffline: false, preserveSpeechPlayback: isSpeechPlaying)
        }
    }

    func sendText(_ text: String, appendReturn: Bool = true) {
        let bytes = Data(text.utf8)
        guard !bytes.isEmpty else { return }
        if controlLatched {
            guard bytes.count == 1, let byte = bytes.first,
                  let control = WatchTerminalKeyBytes.control(byte) else {
                errorMessage = "Ctrl requires one ASCII character."
                return
            }
            controlLatched = false
            send(control, appendReturn: false)
        } else {
            send(bytes, appendReturn: appendReturn)
        }
    }

    func sendKey(_ bytes: Data) {
        if controlLatched, bytes.count == 1, let byte = bytes.first,
           let control = WatchTerminalKeyBytes.control(byte) {
            controlLatched = false
            send(control, appendReturn: false)
            return
        }
        controlLatched = false
        send(bytes, appendReturn: false)
    }

    func sendEnter() {
        controlLatched = false
        send(WatchTerminalKeyBytes.carriageReturn, appendReturn: false)
    }

    /// Backspace remains immediate and repeatable. Each tap attempts one exact
    /// DEL POST without entering the normal input loading state. Concurrent
    /// DEL requests are safe because terminald serializes its tmux writes, and
    /// no request is queued, retried, or replayed by the Watch.
    func sendBackspace() {
        controlLatched = false
        guard appIsForeground, isVisible, terminalInputIsReady, !isSending, let client else {
            if status != .notConfigured { errorMessage = "The terminal is not connected." }
            return
        }

        let trackingID = UUID()
        pendingBackspaceIDs.insert(trackingID)
        pendingBackspaceCount = pendingBackspaceIDs.count
        let generation = connectionGeneration
        let input = WatchTerminalInput(data: WatchTerminalKeyBytes.backspace, appendReturn: false)
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                self.pendingBackspaceIDs.remove(trackingID)
                self.pendingBackspaceCount = self.pendingBackspaceIDs.count
            }
            do {
                try await client.send(input)
                guard self.connectionGeneration == generation else { return }
                self.errorMessage = nil
            } catch is CancellationError {
                return
            } catch {
                guard self.connectionGeneration == generation else { return }
                self.errorMessage = "Backspace was not confirmed: \(error.localizedDescription)"
            }
        }
    }

    private func restartIfNeeded(preserveLiveStatus: Bool = false) {
        let keepsLiveStatus = preserveLiveStatus && frame != nil && status != .notConfigured
        let previouslySelectedRoute = client?.selectedBaseURL
        // Foreground route recovery must not interrupt active playback, discard
        // a prepared WAV, or cancel the independent speech download. True
        // background and deliberate page exit still cancel unfinished work.
        stop(
            markOffline: !keepsLiveStatus,
            preserveSpeechPlayback: isSpeechPlaying,
            preservePreparedSpeech: isSpeechLoading || speechFileURL != nil
        )
        guard appIsForeground, isVisible else { return }
        guard let configuration = settings.configuration else {
            status = .notConfigured
            errorMessage = "Open iPhone JARVIS Settings to provision the Watch terminal."
            return
        }
        let preferredRoute = previouslySelectedRoute ?? rememberedPreferredRoute(for: configuration)
        let client = WatchTerminalClient(
            configuration: configuration,
            preferredBaseURL: preferredRoute
        )
        self.client = client
        status = keepsLiveStatus ? .live : .connecting
        errorMessage = nil
        trace("route_restart retained_frame=\(keepsLiveStatus) preferred=\(preferredRoute != nil)")
        pollTask = Task { @MainActor [weak self] in
            guard let self else { return }
            // A newly created route must confirm itself immediately instead of
            // long-polling the last foreground sequence before showing recovery.
            var sequence = 0
            while !Task.isCancelled, self.appIsForeground, self.isVisible {
                do {
                    let next = try await client.frame(after: sequence)
                    guard !Task.isCancelled else { return }
                    let recoveredRoute = !self.isConnectionConfirmed
                    let frameChanged = self.frame != next
                    if let previous = self.frame,
                       (!previous.paneID.isEmpty && previous.paneID != next.paneID
                        || next.historySize < previous.historySize),
                       !self.historyPages.isEmpty {
                        self.historyPages.removeAll()
                    }
                    if frameChanged { self.frame = next }
                    if !self.isConnectionConfirmed { self.isConnectionConfirmed = true }
                    self.pollFailureStartedAt = nil
                    self.rememberPreferredRoute(client.selectedBaseURL)
                    let nextResponseID = next.speech?.available == true ? next.speech?.responseID : nil
                    if frameChanged || recoveredRoute, let nextResponseID {
                        if self.failedSpeechResponseID != nil,
                           self.failedSpeechResponseID != nextResponseID {
                            self.failedSpeechResponseID = nil
                        }
                        if self.exhaustedSpeechResponseID != nil,
                           self.exhaustedSpeechResponseID != nextResponseID {
                            self.exhaustedSpeechResponseID = nil
                            self.speechRetryAttempt = 0
                        } else if recoveredRoute,
                                  self.exhaustedSpeechResponseID == nextResponseID {
                            // A newly authenticated route earns one new bounded
                            // preparation window for the retained response.
                            self.exhaustedSpeechResponseID = nil
                            self.speechRetryAttempt = 0
                        }
                    }
                    if frameChanged,
                       next.speech?.generating == true
                        || (nextResponseID != nil
                            && self.speechResponseID != nil
                            && nextResponseID != self.speechResponseID) {
                        // Replace stale prepared audio, but never interrupt a WAV
                        // that the user explicitly started. Missing metadata does
                        // not invalidate a complete retained local response.
                        if !self.isSpeechPlaying { self.stopSpeech() }
                    }
                    if recoveredRoute { self.trace("route_confirmed") }
                    sequence = next.sequence
                    self.successfulPollCount += 1
                    self.wakeRecoveryTask?.cancel()
                    self.wakeRecoveryTask = nil
                    if self.status != .live { self.status = .live }
                    if self.errorMessage != nil { self.errorMessage = nil }
                    self.prepareSpeechIfNeeded()
                } catch is CancellationError {
                    return
                } catch {
                    guard !Task.isCancelled else { return }
                    let wasConfirmed = self.isConnectionConfirmed
                    self.isConnectionConfirmed = false
                    if wasConfirmed { self.trace("route_poll_failed") }
                    self.wakeRecoveryTask?.cancel()
                    self.wakeRecoveryTask = nil
                    if self.frame == nil {
                        self.status = .offline
                        self.errorMessage = error.localizedDescription
                    } else {
                        let now = Date()
                        if self.pollFailureStartedAt == nil { self.pollFailureStartedAt = now }
                        let failureAge = now.timeIntervalSince(self.pollFailureStartedAt ?? now)
                        if !self.sceneIsActive || failureAge < 12 {
                            // Debounce route handoffs while retaining the last
                            // confirmed frame. Input is already fail-closed by
                            // isConnectionConfirmed until a poll succeeds.
                            self.status = .live
                            self.errorMessage = nil
                        } else {
                            self.status = .offline
                            self.errorMessage = error.localizedDescription
                        }
                    }
                    try? await Task.sleep(for: .seconds(1))
                }
            }
        }
    }

    private func scheduleWakeRecovery() {
        wakeRecoveryTask?.cancel()
        let generation = connectionGeneration
        let observedPollCount = successfulPollCount
        wakeRecoveryTask = Task { @MainActor [weak self] in
            do {
                // A normal terminald long poll completes in at most 1.5 seconds.
                // Seven seconds also covers the pinned session's resource
                // timeout when a request was frozen during Always On.
                try await Task.sleep(for: .seconds(7))
            } catch {
                return
            }
            guard let self,
                  self.connectionGeneration == generation,
                  self.appIsForeground,
                  self.sceneIsActive,
                  self.isVisible,
                  self.status == .live,
                  self.successfulPollCount == observedPollCount else { return }
            self.restartIfNeeded(preserveLiveStatus: true)
        }
    }

    private func stop(
        markOffline: Bool = true,
        preserveSpeechPlayback: Bool = false,
        preservePreparedSpeech: Bool = false
    ) {
        connectionGeneration += 1
        isConnectionConfirmed = false
        pollFailureStartedAt = nil
        if !preserveSpeechPlayback && !preservePreparedSpeech { stopSpeech() }
        wakeRecoveryTask?.cancel()
        wakeRecoveryTask = nil
        historyTask?.cancel()
        historyTask = nil
        historyRequest = nil
        isHistoryLoading = false
        pollTask?.cancel()
        pollTask = nil
        client?.close()
        client = nil
        isSending = false
        pendingBackspaceIDs.removeAll()
        pendingBackspaceCount = 0
        if markOffline, settings.configuration != nil, status != .notConfigured { status = .offline }
    }

    private func send(_ data: Data, appendReturn: Bool) {
        guard appIsForeground, isVisible, terminalInputIsReady, !isSending,
              pendingBackspaceCount == 0, let client else {
            if status != .notConfigured { errorMessage = "The terminal is not connected." }
            return
        }
        isSending = true
        let generation = connectionGeneration
        let input = WatchTerminalInput(data: data, appendReturn: appendReturn)
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if self.connectionGeneration == generation { self.isSending = false }
            }
            do {
                try await client.send(input)
                guard self.connectionGeneration == generation else { return }
                self.errorMessage = nil
            } catch is CancellationError {
                return
            } catch {
                guard self.connectionGeneration == generation else { return }
                self.errorMessage = "Input was not confirmed: \(error.localizedDescription)"
            }
        }
    }
}

struct WatchTerminalView: View {
    @ObservedObject var controller: WatchTerminalController
    let isActive: Bool
    let onAdvancePage: (() -> Void)?
    @Environment(\.isLuminanceReduced) private var isLuminanceReduced
    @State private var showingKeyPalette = false
    @State private var keyboardDraft = ""
    @State private var crownPosition = 0.0
    @State private var scrollOffset = 0
    @FocusState private var crownIsFocused: Bool

    private var normalInputIsEnabled: Bool {
        controller.terminalInputIsReady
            && !controller.isSending
            && controller.pendingBackspaceCount == 0
    }

    private var backspaceIsEnabled: Bool {
        controller.terminalInputIsReady && !controller.isSending
    }

    init(
        controller: WatchTerminalController,
        isActive: Bool = true,
        onAdvancePage: (() -> Void)? = nil
    ) {
        self.controller = controller
        self.isActive = isActive
        self.onAdvancePage = onAdvancePage
    }

    var body: some View {
        VStack(spacing: 2) {
            terminal
            inputDock
        }
        .padding(.horizontal, 8)
        .padding(.top, 6)
        .padding(.bottom, 8)
        .background(Color.black.ignoresSafeArea())
        .overlay(alignment: .bottom) {
            if showingKeyPalette {
                keyPalette
                    .padding(.horizontal, 3)
                    .padding(.bottom, 42)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.16), value: showingKeyPalette)
        .focusable(isActive)
        .focused($crownIsFocused)
        .digitalCrownRotation(
            $crownPosition,
            // tmux retains 100,000 history rows in addition to the live screen.
            from: -100_100,
            through: 0,
            by: 1,
            sensitivity: .medium,
            isContinuous: false,
            isHapticFeedbackEnabled: true
        )
        .onChange(of: crownPosition) { _, newValue in
            guard let frame = controller.frame else { return }
            let requestedOffset = WatchTerminalCrownHistory.scrollOffset(
                crownPosition: newValue,
                maximumOffset: frame.absoluteOutputEnd
            )
            if scrollOffset != requestedOffset { scrollOffset = requestedOffset }
            crownIsFocused = true
        }
        .onAppear {
            controller.setVisible(isActive)
            crownIsFocused = isActive
        }
        .onChange(of: isActive) { _, active in
            controller.setVisible(active)
            crownIsFocused = active
        }
        .onDisappear {
            crownIsFocused = false
            controller.setVisible(false)
        }
        .alert(
            "Speech unavailable",
            isPresented: Binding(
                get: { controller.speechErrorMessage != nil },
                set: { if !$0 { controller.speechErrorMessage = nil } }
            )
        ) {
            Button("OK") { controller.speechErrorMessage = nil }
        } message: {
            Text(controller.speechErrorMessage ?? "The JARVIS voice could not be played.")
        }
    }

    private var terminal: some View {
        GeometryReader { geometry in
            ZStack(alignment: .topLeading) {
                Color(red: 0.008, green: 0.022, blue: 0.028)

                if let frame = controller.frame {
                    mirroredTerminal(frame: frame, geometry: geometry)
                } else {
                    waitingTerminal
                }

                terminalStatusOverlay
            }
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 24).onEnded { value in
                    guard value.translation.height < -60,
                          abs(value.translation.height) > abs(value.translation.width),
                          let onAdvancePage else { return }
                    // Touch remains page navigation only. Terminal history is
                    // controlled exclusively by the focused Digital Crown.
                    onAdvancePage()
                }
            )
        }
    }

    private func mirroredTerminal(
        frame: WatchTerminalFrame,
        geometry: GeometryProxy
    ) -> some View {
        let headerHeight = CGFloat(39)
        let contentWidth = max(1, geometry.size.width - 10)
        // Keep the original accepted FIT typography for every terminal row.
        // The mode button remains removed; this one fixed presentation requires
        // neither local wrapping nor horizontal panning.
        let outputFontSize = CGFloat(
            WatchTerminalLayout.mirrorFontSize(
                availableWidth: Double(contentWidth),
                terminalColumns: frame.columns
            )
        )
        let outputLineHeight = CGFloat(
            WatchTerminalLayout.lineHeight(fontSize: Double(outputFontSize))
        )
        let outputColumns = max(1, frame.columns)

        let allLocalStyles = controller.parsedANSILines(frame.ansiLines)
        let editorRange = frame.liveEditorRange
        let editorFontSize = outputFontSize
        let editorLineHeight = outputLineHeight
        let editorStyles: [[WatchTerminalANSISpan]] = editorRange.map { range in
            let cursorLine = frame.liveCursorLineIndex - range.lowerBound
            let cursorStart = max(0, frame.cursorColumn - outputColumns + 4)
            return Array(allLocalStyles[range]).enumerated().map { index, spans in
                WatchTerminalANSIParser.viewport(
                    line: spans,
                    start: index == cursorLine ? cursorStart : 0,
                    columns: outputColumns
                )
            }
        } ?? []
        let editorHeight = editorLineHeight * CGFloat(editorStyles.count)
        let outputHeight = max(
            outputLineHeight,
            geometry.size.height - headerHeight - editorHeight
        )
        let maximumVisualLines = max(1, Int(outputHeight / outputLineHeight))
        let maximumSourceRows = maximumVisualLines
        let safeOffset = min(
            max(0, scrollOffset),
            frame.maximumOutputScrollOffset(maximumSourceRows: maximumSourceRows)
        )
        let absoluteEnd = max(0, frame.absoluteOutputEnd - safeOffset)
        let absoluteStart = max(0, absoluteEnd - maximumSourceRows)
        let requiredRange = absoluteStart..<absoluteEnd
        let localANSI = frame.localANSILines(inAbsoluteRange: requiredRange)
        let pageANSI = controller.cachedHistoryPage(
            containing: requiredRange,
            paneID: frame.paneID
        )?.ansiLines(in: requiredRange)
        let sourceANSI = localANSI ?? pageANSI ?? []
        let wrappedOutput = Array(
            WatchTerminalANSIParser.wrapped(
                lines: controller.parsedANSILines(sourceANSI),
                displayColumns: outputColumns
            ).suffix(maximumVisualLines)
        )
        let historyRequestRange: Range<Int>? = localANSI == nil
            && pageANSI == nil
            && requiredRange.lowerBound < requiredRange.upperBound
            && requiredRange.upperBound <= frame.historySize
                ? requiredRange
                : nil

        return VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(wrappedOutput.enumerated()), id: \.offset) { _, spans in
                    terminalLine(
                        spans,
                        fontSize: outputFontSize,
                        lineHeight: outputLineHeight,
                        width: contentWidth
                    )
                }
            }
            .frame(width: contentWidth, height: outputHeight, alignment: .bottomLeading)
            .clipped()
            .overlay {
                if historyRequestRange != nil && controller.isHistoryLoading {
                    ProgressView()
                        .controlSize(.mini)
                }
            }

            if !editorStyles.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(editorStyles.enumerated()), id: \.offset) { _, spans in
                        terminalLine(
                            spans,
                            fontSize: editorFontSize,
                            lineHeight: editorLineHeight,
                            width: contentWidth
                        )
                    }
                }
                .frame(width: contentWidth, height: editorHeight, alignment: .topLeading)
                .clipped()
            }
        }
        .padding(.horizontal, 5)
        .padding(.top, headerHeight)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .clipped()
        .accessibilityLabel("Mirrored Pi terminal")
        .accessibilityValue(safeOffset == 0 ? "Live" : "Scrolled back \(safeOffset) rows")
        .task(id: historyRequestRange) {
            if let historyRequestRange {
                controller.requestHistory(
                    containing: historyRequestRange,
                    paneID: frame.paneID,
                    historySize: frame.historySize
                )
            }
        }
        .task(id: safeOffset) {
            if scrollOffset != safeOffset { scrollOffset = safeOffset }
            let synchronizedPosition = WatchTerminalCrownHistory.crownPosition(scrollOffset: safeOffset)
            if crownPosition != synchronizedPosition { crownPosition = synchronizedPosition }
        }
    }

    private func terminalLine(
        _ spans: [WatchTerminalANSISpan],
        fontSize: CGFloat,
        lineHeight: CGFloat,
        width: CGFloat
    ) -> some View {
        HStack(spacing: 0) {
            ForEach(Array(spans.enumerated()), id: \.offset) { _, span in
                terminalSpan(span, fontSize: fontSize)
            }
        }
        .frame(width: width, height: lineHeight, alignment: .leading)
        .clipped()
    }

    private func terminalSpan(_ span: WatchTerminalANSISpan, fontSize: CGFloat) -> some View {
        let defaultForeground = Color(red: 0.94, green: 0.94, blue: 0.94)
        let defaultBackground = Color.black
        let rawForeground = terminalForegroundColor(span.style.foreground, defaultColor: defaultForeground)
        let rawBackground = terminalColor(span.style.background, defaultColor: defaultBackground)
        let foreground = span.style.inverse ? rawBackground : rawForeground
        let background = span.style.inverse ? rawForeground : rawBackground
        let visibleText = span.style.hidden
            ? String(repeating: " ", count: span.text.count)
            : span.text
        var text = Text(verbatim: visibleText)
            .font(.system(
                size: fontSize,
                weight: span.style.bold ? .bold : .regular,
                design: .monospaced
            ))
        if span.style.italic { text = text.italic() }
        if span.style.underline { text = text.underline() }
        if span.style.strikethrough { text = text.strikethrough() }
        return text
            .foregroundStyle(foreground.opacity(span.style.dim ? 0.82 : 1))
            .background(background)
            .fixedSize(horizontal: true, vertical: false)
    }

    private func terminalForegroundColor(_ color: WatchTerminalANSIColor, defaultColor: Color) -> Color {
        guard case .rgb(let value) = color else { return defaultColor }
        let brightened = WatchTerminalLayout.brightenedForeground(value)
        return Color(
            red: Double(brightened.red) / 255,
            green: Double(brightened.green) / 255,
            blue: Double(brightened.blue) / 255
        )
    }

    private func terminalColor(_ color: WatchTerminalANSIColor, defaultColor: Color) -> Color {
        guard case .rgb(let value) = color else { return defaultColor }
        return Color(
            red: Double(value.red) / 255,
            green: Double(value.green) / 255,
            blue: Double(value.blue) / 255
        )
    }

    private var waitingTerminal: some View {
        VStack(spacing: 7) {
            if controller.status == .connecting { ProgressView().controlSize(.small) }
            Text(controller.errorMessage ?? "Waiting for the Mac terminal")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 12)
        .padding(.top, 20)
    }

    private var terminalStatusOverlay: some View {
        ZStack(alignment: .top) {
            Text("JARVIS")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, alignment: .center)
                .accessibilityAddTraits(.isHeader)

            HStack(spacing: 5) {
                Image(systemName: "terminal.fill")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(WatchJarvisStyle.accent)
                    .accessibilityHidden(true)
                terminalStatusIndicator
                if scrollOffset > 0 {
                    Text("↑\(scrollOffset)")
                        .font(.system(size: 8, weight: .bold, design: .monospaced))
                        .foregroundStyle(WatchJarvisStyle.accent)
                        .accessibilityLabel("Scrolled back \(scrollOffset) terminal rows")
                }
                Spacer(minLength: 0)
                Button {
                    controller.toggleSpeech()
                    crownIsFocused = true
                } label: {
                    Group {
                        if controller.isSpeechLoading {
                            ProgressView()
                                .controlSize(.small)
                                .scaleEffect(0.78)
                        } else {
                            Image(systemName: controller.isSpeechPlaying ? "stop.fill" : "speaker.wave.2.fill")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(
                                    controller.isSpeechPlaying || controller.canSpeakLastResponse
                                        ? WatchJarvisStyle.accent
                                        : Color.secondary
                                )
                        }
                    }
                    .frame(width: 44, height: 35)
                    .background(
                        Color.white.opacity(0.09),
                        in: RoundedRectangle(cornerRadius: 8, style: .continuous)
                    )
                }
                .buttonStyle(.plain)
                .disabled(
                    (controller.isSpeechLoading && !controller.isSpeechPlaying)
                        || (!controller.isSpeechPlaying && !controller.canSpeakLastResponse)
                )
                .accessibilityLabel(controller.isSpeechPlaying ? "Stop JARVIS speech" : "Read last JARVIS response")
                .accessibilityValue(
                    controller.isSpeechLoading
                        ? "Preparing complete audio"
                        : controller.canSpeakLastResponse ? "Ready" : "Unavailable"
                )
                .accessibilityHint("Plays the fully downloaded final response through the Watch speaker")
            }
            .padding(.horizontal, 7)
        }
        .padding(.top, 2)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    @ViewBuilder
    private var terminalStatusIndicator: some View {
        if isLuminanceReduced {
            Image(systemName: controller.frame == nil ? "circle.dotted" : "checkmark.circle.fill")
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(controller.frame == nil ? Color.secondary : Color.white)
                .frame(width: 8, height: 8)
                .accessibilityLabel("Terminal status")
                .accessibilityValue(
                    controller.frame == nil
                        ? "Waiting for the first terminal frame"
                        : "Session retained; live networking resumes when active"
                )
        } else {
            Circle()
                .fill(controller.status.color)
                .frame(width: 7, height: 7)
                .accessibilityLabel("Terminal status")
                .accessibilityValue(controller.status.label)
        }
    }

    private var inputDock: some View {
        HStack(spacing: 3) {
            Button {
                showingKeyPalette.toggle()
            } label: {
                dockLabel(symbol: showingKeyPalette ? "xmark" : "command", title: "Keys", emphasized: false)
            }
            .buttonStyle(.plain)
            .disabled(!normalInputIsEnabled)
            .accessibilityLabel(showingKeyPalette ? "Hide terminal keys" : "Show terminal keys")

            ZStack {
                // Retain the direct keyboard-first TextField behavior while
                // suppressing watchOS's oversized default field chrome. The
                // shared dock label below owns the only visible button surface.
                TextField("", text: $keyboardDraft, prompt: Text("Input").foregroundStyle(Color.clear))
                    .textFieldStyle(.plain)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .submitLabel(.done)
                    .onSubmit {
                        stageInput(keyboardDraft)
                        keyboardDraft = ""
                    }
                    .frame(maxWidth: .infinity, minHeight: 35, maxHeight: 35)
                    .opacity(0.01)
                    .clipped()

                dockLabel(symbol: "keyboard", title: "Input", emphasized: false)
                    .allowsHitTesting(false)
            }
            .frame(maxWidth: .infinity, minHeight: 35, maxHeight: 35)
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .disabled(!normalInputIsEnabled)
            .accessibilityLabel("Input text at the Pi cursor")
            .accessibilityHint("Opens the Apple Watch keyboard first. Text is inserted without submitting.")

            Button {
                controller.sendKey(WatchTerminalKeyBytes.slash)
            } label: {
                Text("/")
                    .font(.system(size: 15, weight: .bold, design: .monospaced))
                    .foregroundStyle(WatchJarvisStyle.accent)
                    .frame(width: 28, height: 35)
                    .background(Color.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(!normalInputIsEnabled)
            .accessibilityLabel("Slash")
            .accessibilityHint("Inserts one slash at the Pi cursor.")

            Button {
                controller.sendBackspace()
            } label: {
                Image(systemName: "delete.backward.fill")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(WatchJarvisStyle.accent)
                    .frame(width: 28, height: 35)
                    .background(Color.white.opacity(0.09), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(!backspaceIsEnabled)
            .accessibilityLabel("Backspace current Pi input")
            .accessibilityHint("Sends one immediate delete without showing a loading indicator.")

            Button {
                showingKeyPalette = false
                controller.sendEnter()
            } label: {
                Image(systemName: "return")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color.black)
                    .frame(width: 28, height: 35)
                    .background(WatchJarvisStyle.accent, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(!normalInputIsEnabled)
            .accessibilityLabel("Enter current Pi input")
            .accessibilityHint("Sends one terminal Return byte to submit at the Pi cursor.")
        }
        .frame(height: 39)
    }

    private func stageInput(_ input: String) {
        let message = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else { return }
        controller.sendText(message, appendReturn: false)
    }

    private func dockLabel(symbol: String, title: String, emphasized: Bool) -> some View {
        HStack(spacing: 2) {
            Image(systemName: symbol)
                .font(.system(size: emphasized ? 12 : 10, weight: .bold))
            Text(title)
                .font(.system(size: emphasized ? 9 : 8, weight: .bold))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .foregroundStyle(emphasized ? Color.black : Color.primary)
        .frame(maxWidth: .infinity, minHeight: 35)
        .background(
            emphasized ? WatchJarvisStyle.accent : Color.white.opacity(0.09),
            in: RoundedRectangle(cornerRadius: 8, style: .continuous)
        )
    }

    private var keyPalette: some View {
        VStack(spacing: 3) {
            HStack(spacing: 3) {
                terminalKey("Esc", accessibility: "Escape") { controller.sendKey(WatchTerminalKeyBytes.escape) }
                terminalKey("Ctrl", accessibility: "Control modifier", selected: controller.controlLatched) {
                    controller.controlLatched.toggle()
                }
                terminalKey("Tab", accessibility: "Tab") { controller.sendKey(WatchTerminalKeyBytes.tab) }
            }
            HStack(spacing: 3) {
                terminalKey("↑", accessibility: "Up arrow") { controller.sendKey(WatchTerminalKeyBytes.up) }
                terminalKey("↓", accessibility: "Down arrow") { controller.sendKey(WatchTerminalKeyBytes.down) }
            }
        }
        .padding(5)
        .background(Color.black.opacity(0.96), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(WatchJarvisStyle.accent.opacity(0.24), lineWidth: 1)
        }
    }

    private func terminalKey(
        _ title: String,
        accessibility: String,
        selected: Bool = false,
        requiresLiveTerminal: Bool = true,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: title.count > 2 ? 9 : 12, weight: .bold, design: .monospaced))
                .frame(maxWidth: .infinity, minHeight: 28)
                .background(selected ? WatchJarvisStyle.accent.opacity(0.35) : Color.white.opacity(0.10), in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .disabled(
            requiresLiveTerminal
                && (!controller.terminalInputIsReady
                    || controller.isSending
                    || controller.pendingBackspaceCount > 0)
        )
        .accessibilityLabel(accessibility)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
