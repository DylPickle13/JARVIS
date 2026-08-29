import Foundation
#if canImport(WatchConnectivity)
import WatchConnectivity
#endif

/// Shared WatchConnectivity message envelope. `payload` is JSON data so the
/// phone and watch do not depend on NSDictionary type bridging details.
public struct WatchMessage: Codable, Equatable, Sendable {
    public let version: Int
    public let type: String
    public let requestID: String
    public let sentAt: String
    public let payload: Data?

    public init(type: String, requestID: String = UUID().uuidString, payload: Data? = nil) {
        self.version = 1
        self.type = type
        self.requestID = requestID
        self.sentAt = ISO8601DateFormatter().string(from: Date())
        self.payload = payload
    }
}

/// Delivery-time guard for interactive Watch writes. The limit is deliberately
/// shorter than the Watch's 30-second response timeout, so a command queued by
/// an older app build cannot first reach the iPhone after its UI has timed out.
public enum WatchRelayCommandPolicy {
    public static let maximumDeliveryAge: TimeInterval = 25
    public static let maximumFutureClockSkew: TimeInterval = 5

    public static func isFresh(sentAt: String?, now: Date = Date()) -> Bool {
        guard let sentAt, let date = parseTimestamp(sentAt) else { return false }
        let age = now.timeIntervalSince(date)
        return age >= -maximumFutureClockSkew && age <= maximumDeliveryAge
    }

    private static func parseTimestamp(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value)
    }
}

public enum WatchPurifierSetting: String, Codable, Equatable, Sendable {
    case power
    case mode
    case speed
}

/// A closed, validated purifier command surface for WatchConnectivity. The
/// Watch cannot relay arbitrary jarvisd actions or parameters through it.
public struct WatchPurifierCommand: Codable, Equatable, Sendable {
    public static let supportedModes = ["auto", "manual", "sleep", "pet"]

    public let setting: WatchPurifierSetting
    public let value: String?
    public let level: Int?

    private init(setting: WatchPurifierSetting, value: String? = nil, level: Int? = nil) {
        self.setting = setting
        self.value = value
        self.level = level
    }

    public static func power(_ isOn: Bool) -> WatchPurifierCommand {
        WatchPurifierCommand(setting: .power, value: isOn ? "on" : "off")
    }

    public static func mode(_ mode: String) -> WatchPurifierCommand? {
        let normalized = mode.lowercased()
        guard supportedModes.contains(normalized) else { return nil }
        return WatchPurifierCommand(setting: .mode, value: normalized)
    }

    public static func speed(_ level: Int) -> WatchPurifierCommand? {
        guard (1...4).contains(level) else { return nil }
        return WatchPurifierCommand(setting: .speed, level: level)
    }

    public var isValid: Bool {
        switch setting {
        case .power:
            return level == nil && (value == "on" || value == "off")
        case .mode:
            return level == nil && value.map(Self.supportedModes.contains) == true
        case .speed:
            return value == nil && level.map { (1...4).contains($0) } == true
        }
    }

    public var parameters: [String: JSONValue] {
        switch setting {
        case .power, .mode:
            return ["setting": .string(setting.rawValue), "value": .string(value ?? "")]
        case .speed:
            return ["setting": .string(setting.rawValue), "level": .number(Double(level ?? 0))]
        }
    }

    public func matches(_ purifier: PurifierSubsystem) -> Bool {
        switch setting {
        case .power:
            return purifier.isOn == (value == "on")
        case .mode:
            return purifier.mode?.lowercased() == value
        case .speed:
            return purifier.mode?.lowercased() == "manual"
                && (purifier.fanSetLevel ?? purifier.fanLevel) == level
        }
    }
}

public protocol WatchBridgeDelegate: AnyObject {
    func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge, requestID: String)
    func watchBridgeDidReceiveState(_ bridge: WatchBridge, json: Data)
    func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String)
    func watchBridgeDidReceiveTerminalConfiguration(_ bridge: WatchBridge, configuration: WatchTerminalConfiguration)
    func watchBridgeDidReceivePlugCommand(_ bridge: WatchBridge, name: String, isOn: Bool, requestID: String)
    func watchBridgeDidReceivePurifierCommand(_ bridge: WatchBridge, command: WatchPurifierCommand, requestID: String)
    func watchBridgeDidReceiveCommandResult(_ bridge: WatchBridge, requestID: String, result: CommandResult)
    func watchBridgeDidReceiveCommandError(_ bridge: WatchBridge, requestID: String, error: WatchCommandError)
}

public extension WatchBridgeDelegate {
    func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge, requestID: String) {}
    func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String) {}
    func watchBridgeDidReceiveTerminalConfiguration(_ bridge: WatchBridge, configuration: WatchTerminalConfiguration) {}
    func watchBridgeDidReceivePlugCommand(_ bridge: WatchBridge, name: String, isOn: Bool, requestID: String) {}
    func watchBridgeDidReceivePurifierCommand(_ bridge: WatchBridge, command: WatchPurifierCommand, requestID: String) {}
    func watchBridgeDidReceiveCommandResult(_ bridge: WatchBridge, requestID: String, result: CommandResult) {}
    func watchBridgeDidReceiveCommandError(_ bridge: WatchBridge, requestID: String, error: WatchCommandError) {}
}

public enum WatchRelayFailure: LocalizedError, Equatable, Sendable {
    case unavailable
    case confirmationUnavailable
    case timedOut
    case cancelled
    case rejected(String)

    public var errorDescription: String? {
        switch self {
        case .unavailable: return "The iPhone relay is unavailable."
        case .confirmationUnavailable: return "The iPhone relay result could not be confirmed."
        case .timedOut: return "The iPhone relay timed out before its result was confirmed."
        case .cancelled: return "The iPhone relay was cancelled."
        case .rejected(let message): return message
        }
    }
}

#if canImport(WatchConnectivity)

public final class WatchBridge: NSObject, @unchecked Sendable {
    public static let shared = WatchBridge()

    public weak var delegate: WatchBridgeDelegate?

    private let lock = NSLock()
    private var _isWatchReachable = false
    private var _isPhoneReachable = false
    private var _isActivationNeeded = false
    private var pendingStateRequests: [String: CheckedContinuation<Result<Data, WatchRelayFailure>, Never>] = [:]
    private var pendingCommandRequests: [String: CheckedContinuation<Result<CommandResult, WatchRelayFailure>, Never>] = [:]
    private var latestStateJSON: Data?
    private var latestEndpoint: String?
    private var latestTerminalConfiguration: Data?

    public var isWatchReachable: Bool {
        lock.lock(); defer { lock.unlock() }
        return _isWatchReachable
    }

    public var isPhoneReachable: Bool {
        lock.lock(); defer { lock.unlock() }
        return _isPhoneReachable
    }

    public var isActivationNeeded: Bool {
        lock.lock(); defer { lock.unlock() }
        return _isActivationNeeded
    }

    private var session: WCSession? {
        WCSession.isSupported() ? WCSession.default : nil
    }

    private override init() {
        super.init()
    }

    private func trace(_ message: String) {
        #if DEBUG
        #if os(iOS)
        NSLog("[JARVIS WatchBridge iPhone] %@", message)
        #else
        NSLog("[JARVIS WatchBridge Watch] %@", message)
        #endif
        #endif
    }

    private func sessionDetails(_ session: WCSession) -> String {
        #if os(iOS)
        return "paired=\(session.isPaired) installed=\(session.isWatchAppInstalled)"
        #else
        return "companionAppInstalled=\(session.isCompanionAppInstalled)"
        #endif
    }

    public func start() {
        guard let session else { return }
        session.delegate = self
        session.activate()
        updateReachability(session)
        trace("start activation=\(session.activationState.rawValue) reachable=\(session.isReachable) \(sessionDetails(session))")
    }

    // MARK: - Outgoing messages

    /// Ask the peer for a fresh state snapshot. This is an immediate request;
    /// callers must fall back to application context/cache if unreachable.
    public func requestState() {
        send(WatchMessage(type: "stateRequest"))
    }

    public func sendState(json: Data, requestID: String = UUID().uuidString) {
        send(WatchMessage(type: "state", requestID: requestID, payload: json))
    }

    /// Correlated interactive plug write. It uses only immediate WCSession
    /// delivery and never leaves a command queued after the interaction ends.
    public func requestPlugCommand(
        name: String,
        isOn: Bool,
        timeout: Duration = .seconds(30)
    ) async -> Result<CommandResult, WatchRelayFailure> {
        guard !name.isEmpty,
              let payload = try? JSONEncoder().encode(PlugIntent(name: name, isOn: isOn)) else {
            return .failure(.rejected("The plug command was invalid."))
        }
        return await requestCommand(type: "plugCommand", payload: payload, timeout: timeout)
    }

    /// Correlated interactive purifier write with the same immediate-only
    /// delivery and exactly-once continuation behavior as plug commands.
    public func requestPurifierCommand(
        _ command: WatchPurifierCommand,
        timeout: Duration = .seconds(30)
    ) async -> Result<CommandResult, WatchRelayFailure> {
        guard command.isValid,
              let payload = try? JSONEncoder().encode(command) else {
            return .failure(.rejected("The air-purifier command was invalid."))
        }
        return await requestCommand(type: "purifierCommand", payload: payload, timeout: timeout)
    }

    private func requestCommand(
        type: String,
        payload: Data,
        timeout: Duration
    ) async -> Result<CommandResult, WatchRelayFailure> {
        let requestID = UUID().uuidString
        let message = WatchMessage(type: type, requestID: requestID, payload: payload)
        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                lock.lock()
                pendingCommandRequests[requestID] = continuation
                lock.unlock()
                guard !Task.isCancelled else {
                    completeCommandRequest(requestID, with: .failure(.cancelled))
                    return
                }
                guard send(message, onDeliveryFailure: { [weak self] in
                    self?.completeCommandRequest(requestID, with: .failure(.confirmationUnavailable))
                }) else {
                    completeCommandRequest(requestID, with: .failure(.unavailable))
                    return
                }
                Task { [weak self] in
                    try? await Task.sleep(for: timeout)
                    self?.completeCommandRequest(requestID, with: .failure(.timedOut))
                }
            }
        }, onCancel: { [weak self] in
            self?.completeCommandRequest(requestID, with: .failure(.cancelled))
        })
    }

    /// Fetches a fresh snapshot through the phone with request correlation.
    /// Ordinary foreground refreshes may continue using fire-and-forget state
    /// requests and application context.
    public func requestStateData(timeout: Duration = .seconds(15)) async -> Result<Data, WatchRelayFailure> {
        let requestID = UUID().uuidString
        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                lock.lock()
                pendingStateRequests[requestID] = continuation
                lock.unlock()
                guard !Task.isCancelled else {
                    completeStateRequest(requestID, with: .failure(.cancelled))
                    return
                }
                guard send(WatchMessage(type: "stateRequest", requestID: requestID)) else {
                    completeStateRequest(requestID, with: .failure(.unavailable))
                    return
                }
                Task { [weak self] in
                    try? await Task.sleep(for: timeout)
                    self?.completeStateRequest(requestID, with: .failure(.timedOut))
                }
            }
        }, onCancel: { [weak self] in
            self?.completeStateRequest(requestID, with: .failure(.cancelled))
        })
    }

    @discardableResult
    public func sendCommandResult(requestID: String, result: CommandResult) -> Bool {
        let payload = try? JSONEncoder().encode(result)
        return send(WatchMessage(type: "commandResult", requestID: requestID, payload: payload))
    }

    @discardableResult
    public func sendCommandError(requestID: String, message: String) -> Bool {
        let payload = try? JSONEncoder().encode(WatchCommandError(message: message))
        return send(WatchMessage(type: "commandError", requestID: requestID, payload: payload))
    }

    public func updateApplicationContext(stateJSON: Data?, endpoint: String? = nil) {
        lock.lock()
        if let stateJSON { latestStateJSON = stateJSON }
        if let endpoint { latestEndpoint = endpoint }
        lock.unlock()
        publishLatestApplicationContext()
    }

    /// Publishes the target-local terminal credential to the paired Watch.
    /// WatchConnectivity protects this device-to-device transfer; the value is
    /// never included in logs or the repository.
    public func publishTerminalConfiguration(_ configuration: WatchTerminalConfiguration) {
        guard configuration.isValid,
              let payload = try? JSONEncoder().encode(configuration) else { return }
        lock.lock()
        latestTerminalConfiguration = payload
        lock.unlock()
        publishLatestApplicationContext()
        send(WatchMessage(type: "terminalConfiguration", payload: payload))
    }

    private func publishLatestApplicationContext() {
        guard let session, session.activationState == .activated else { return }
        #if os(iOS)
        guard session.isPaired, session.isWatchAppInstalled else { return }
        #endif
        lock.lock()
        let stateJSON = latestStateJSON
        let endpoint = latestEndpoint
        let terminalConfiguration = latestTerminalConfiguration
        lock.unlock()
        var context: [String: Any] = ["version": 1, "sentAt": ISO8601DateFormatter().string(from: Date())]
        if let stateJSON { context["state"] = stateJSON }
        if let endpoint { context["endpoint"] = endpoint }
        if let terminalConfiguration { context["terminalConfiguration"] = terminalConfiguration }
        do {
            try session.updateApplicationContext(context)
        } catch {
            // The next foreground activation will retry with the latest cache.
        }
    }

    @discardableResult
    private func send(
        _ message: WatchMessage,
        onDeliveryFailure: (() -> Void)? = nil
    ) -> Bool {
        guard let session, session.activationState == .activated, session.isReachable else {
            trace("not reachable type=\(message.type)")
            return false
        }
        var dictionary: [String: Any] = [
            "version": message.version,
            "type": message.type,
            "requestID": message.requestID,
            "sentAt": message.sentAt,
        ]
        if let payload = message.payload { dictionary["payload"] = payload }
        trace("send type=\(message.type) activation=\(session.activationState.rawValue) reachable=true")
        session.sendMessage(dictionary, replyHandler: { [weak self] reply in
            self?.trace("ack type=\(message.type)")
            self?.handle(reply)
        }) { [weak self] error in
            self?.trace("send failed type=\(message.type) error=\(error.localizedDescription)")
            // A delivery callback can race with peer execution, so callers must
            // treat this as unconfirmed and must never retry the write.
            onDeliveryFailure?()
        }
        return true
    }

    // MARK: - Receive

    private func completeStateRequest(
        _ requestID: String,
        with result: Result<Data, WatchRelayFailure>
    ) {
        lock.lock()
        let continuation = pendingStateRequests.removeValue(forKey: requestID)
        lock.unlock()
        continuation?.resume(returning: result)
    }

    private func completeCommandRequest(
        _ requestID: String,
        with result: Result<CommandResult, WatchRelayFailure>
    ) {
        lock.lock()
        let continuation = pendingCommandRequests.removeValue(forKey: requestID)
        lock.unlock()
        continuation?.resume(returning: result)
    }

    private func updateReachability(_ session: WCSession) {
        lock.lock()
        #if os(iOS)
        _isWatchReachable = session.isReachable
        #else
        _isPhoneReachable = session.isReachable
        #endif
        lock.unlock()
    }

    private func handle(_ raw: [String: Any]) {
        guard let type = raw["type"] as? String else { return }
        trace("receive type=\(type)")
        let requestID = raw["requestID"] as? String ?? ""
        switch type {
        case "stateRequest":
            delegate?.watchBridgeDidReceiveStateRequest(self, requestID: requestID)
        case "state":
            if let data = raw["payload"] as? Data {
                lock.lock()
                let hasPendingRequest = pendingStateRequests[requestID] != nil
                lock.unlock()
                if hasPendingRequest {
                    completeStateRequest(requestID, with: .success(data))
                } else {
                    delegate?.watchBridgeDidReceiveState(self, json: data)
                }
            }
        case "commandResult":
            guard let data = raw["payload"] as? Data,
                  let result = try? JSONDecoder().decode(CommandResult.self, from: data) else { return }
            lock.lock()
            let hasPendingRequest = pendingCommandRequests[requestID] != nil
            lock.unlock()
            if hasPendingRequest {
                completeCommandRequest(requestID, with: .success(result))
            } else {
                delegate?.watchBridgeDidReceiveCommandResult(self, requestID: requestID, result: result)
            }
        case "commandError":
            guard let data = raw["payload"] as? Data,
                  let error = try? JSONDecoder().decode(WatchCommandError.self, from: data) else { return }
            lock.lock()
            let hasPendingRequest = pendingCommandRequests[requestID] != nil
            lock.unlock()
            if hasPendingRequest {
                completeCommandRequest(requestID, with: .failure(.rejected(error.message)))
            } else {
                delegate?.watchBridgeDidReceiveCommandError(self, requestID: requestID, error: error)
            }
        case "plugCommand":
            guard validateCommandDelivery(raw, requestID: requestID),
                  let data = raw["payload"] as? Data,
                  let intent = try? JSONDecoder().decode(PlugIntent.self, from: data) else { return }
            delegate?.watchBridgeDidReceivePlugCommand(self, name: intent.name, isOn: intent.isOn, requestID: requestID)
        case "purifierCommand":
            guard validateCommandDelivery(raw, requestID: requestID),
                  let data = raw["payload"] as? Data,
                  let command = try? JSONDecoder().decode(WatchPurifierCommand.self, from: data),
                  command.isValid else { return }
            delegate?.watchBridgeDidReceivePurifierCommand(self, command: command, requestID: requestID)
        case "terminalConfiguration":
            guard let data = raw["payload"] as? Data,
                  let configuration = try? JSONDecoder().decode(WatchTerminalConfiguration.self, from: data),
                  configuration.isValid else { return }
            delegate?.watchBridgeDidReceiveTerminalConfiguration(self, configuration: configuration)
        default:
            break
        }
    }

    private func validateCommandDelivery(_ raw: [String: Any], requestID: String) -> Bool {
        guard WatchRelayCommandPolicy.isFresh(sentAt: raw["sentAt"] as? String) else {
            trace("rejected expired command request=\(requestID)")
            if !requestID.isEmpty {
                sendCommandError(
                    requestID: requestID,
                    message: "This Watch command expired before it reached the iPhone."
                )
            }
            return false
        }
        return true
    }
}

extension WatchBridge: WCSessionDelegate {
    public func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        lock.lock()
        _isActivationNeeded = error != nil || activationState != .activated
        lock.unlock()
        updateReachability(session)
        trace("activation complete=\(activationState.rawValue) reachable=\(session.isReachable) \(sessionDetails(session)) error=\(error?.localizedDescription ?? "none")")
        if activationState == .activated {
            handleApplicationContext(session.receivedApplicationContext)
        }
    }

    public func sessionReachabilityDidChange(_ session: WCSession) {
        updateReachability(session)
        trace("reachability changed=\(session.isReachable)")
    }

#if os(iOS)
    public func sessionDidBecomeInactive(_ session: WCSession) {}

    public func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
#endif

    public func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        handle(message)
    }

    public func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        handle(message)
        replyHandler(["ok": true])
    }

    private func handleApplicationContext(_ applicationContext: [String: Any]) {
        if let endpoint = applicationContext["endpoint"] as? String, !endpoint.isEmpty {
            delegate?.watchBridgeDidReceiveEndpoint(self, endpoint: endpoint)
        }
        if let state = applicationContext["state"] as? Data {
            delegate?.watchBridgeDidReceiveState(self, json: state)
        }
        if let data = applicationContext["terminalConfiguration"] as? Data,
           let configuration = try? JSONDecoder().decode(WatchTerminalConfiguration.self, from: data),
           configuration.isValid {
            delegate?.watchBridgeDidReceiveTerminalConfiguration(self, configuration: configuration)
        }
    }

    public func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        handleApplicationContext(applicationContext)
    }

    public func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        handle(userInfo)
    }
}

private struct PlugIntent: Codable, Sendable {
    let name: String
    let isOn: Bool
}

#else

// A no-op surface keeps `swift test` on macOS independent of WatchConnectivity.
public final class WatchBridge: NSObject, @unchecked Sendable {
    public static let shared = WatchBridge()
    public weak var delegate: WatchBridgeDelegate?
    public private(set) var isWatchReachable = false
    public private(set) var isPhoneReachable = false
    public private(set) var isActivationNeeded = true
    public func start() {}
    public func requestState() {}
    public func sendState(json: Data, requestID: String = UUID().uuidString) {}
    public func requestPlugCommand(
        name: String,
        isOn: Bool,
        timeout: Duration = .seconds(30)
    ) async -> Result<CommandResult, WatchRelayFailure> { .failure(.unavailable) }
    public func requestPurifierCommand(
        _ command: WatchPurifierCommand,
        timeout: Duration = .seconds(30)
    ) async -> Result<CommandResult, WatchRelayFailure> { .failure(.unavailable) }
    public func requestStateData(timeout: Duration = .seconds(15)) async -> Result<Data, WatchRelayFailure> {
        .failure(.unavailable)
    }
    @discardableResult
    public func sendCommandResult(requestID: String, result: CommandResult) -> Bool { false }
    @discardableResult
    public func sendCommandError(requestID: String, message: String) -> Bool { false }
    public func updateApplicationContext(stateJSON: Data?, endpoint: String? = nil) {}
    public func publishTerminalConfiguration(_ configuration: WatchTerminalConfiguration) {}
}

#endif
