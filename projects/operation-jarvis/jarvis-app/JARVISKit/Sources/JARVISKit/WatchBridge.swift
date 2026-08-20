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

public protocol WatchBridgeDelegate: AnyObject {
    func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge)
    func watchBridgeDidReceiveState(_ bridge: WatchBridge, json: Data)
    func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String)
    func watchBridgeDidReceivePlugCommand(_ bridge: WatchBridge, name: String, isOn: Bool, requestID: String)
    func watchBridgeDidReceiveCommandResult(_ bridge: WatchBridge, requestID: String, result: CommandResult)
    func watchBridgeDidReceiveCommandError(_ bridge: WatchBridge, requestID: String, error: WatchCommandError)
}

public extension WatchBridgeDelegate {
    func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String) {}
    func watchBridgeDidReceivePlugCommand(_ bridge: WatchBridge, name: String, isOn: Bool, requestID: String) {}
    func watchBridgeDidReceiveCommandResult(_ bridge: WatchBridge, requestID: String, result: CommandResult) {}
    func watchBridgeDidReceiveCommandError(_ bridge: WatchBridge, requestID: String, error: WatchCommandError) {}
}

#if canImport(WatchConnectivity)

public final class WatchBridge: NSObject, @unchecked Sendable {
    public static let shared = WatchBridge()

    public weak var delegate: WatchBridgeDelegate?

    private let lock = NSLock()
    private var _isWatchReachable = false
    private var _isPhoneReachable = false
    private var _isActivationNeeded = false

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

    public func sendState(json: Data) {
        send(WatchMessage(type: "state", payload: json))
    }

    @discardableResult
    public func sendPlugCommand(name: String, isOn: Bool, requestID: String = UUID().uuidString) -> Bool {
        let payload = try? JSONEncoder().encode(PlugIntent(name: name, isOn: isOn))
        return send(
            WatchMessage(type: "plugCommand", requestID: requestID, payload: payload),
            queueIfUnreachable: true
        )
    }

    @discardableResult
    public func sendCommandResult(requestID: String, result: CommandResult) -> Bool {
        let payload = try? JSONEncoder().encode(result)
        return send(WatchMessage(type: "commandResult", requestID: requestID, payload: payload), queueIfUnreachable: true)
    }

    @discardableResult
    public func sendCommandError(requestID: String, message: String) -> Bool {
        let payload = try? JSONEncoder().encode(WatchCommandError(message: message))
        return send(WatchMessage(type: "commandError", requestID: requestID, payload: payload), queueIfUnreachable: true)
    }

    public func updateApplicationContext(stateJSON: Data?, endpoint: String? = nil) {
        guard let session, session.activationState == .activated else { return }
        #if os(iOS)
        guard session.isPaired, session.isWatchAppInstalled else { return }
        #endif
        var context: [String: Any] = ["version": 1, "sentAt": ISO8601DateFormatter().string(from: Date())]
        if let stateJSON { context["state"] = stateJSON }
        if let endpoint { context["endpoint"] = endpoint }
        do {
            try session.updateApplicationContext(context)
        } catch {
            // The next foreground activation will retry with the latest cache.
        }
    }

    @discardableResult
    private func send(_ message: WatchMessage, queueIfUnreachable: Bool = false) -> Bool {
        guard let session, session.activationState == .activated else { return false }
        var dictionary: [String: Any] = [
            "version": message.version,
            "type": message.type,
            "requestID": message.requestID,
            "sentAt": message.sentAt,
        ]
        if let payload = message.payload { dictionary["payload"] = payload }
        trace("send type=\(message.type) activation=\(session.activationState.rawValue) reachable=\(session.isReachable)")
        if session.isReachable {
            session.sendMessage(dictionary, replyHandler: { [weak self] reply in
                self?.trace("ack type=\(message.type)")
                self?.handle(reply)
            }) { [weak self] error in
                self?.trace("send failed type=\(message.type) error=\(error.localizedDescription)")
                // Reachability can change between the check and delivery.
                // Queue the exact same request ID so the phone's bounded
                // deduplication cache makes this reliable without double writes.
                if queueIfUnreachable {
                    session.transferUserInfo(dictionary)
                    self?.trace("queued fallback type=\(message.type)")
                }
            }
            return true
        }
        guard queueIfUnreachable else {
            trace("not reachable type=\(message.type)")
            return false
        }
        session.transferUserInfo(dictionary)
        trace("queued type=\(message.type)")
        return true
    }

    // MARK: - Receive

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
            delegate?.watchBridgeDidReceiveStateRequest(self)
        case "state":
            if let data = raw["payload"] as? Data {
                delegate?.watchBridgeDidReceiveState(self, json: data)
            }
        case "commandResult":
            guard let data = raw["payload"] as? Data,
                  let result = try? JSONDecoder().decode(CommandResult.self, from: data) else { return }
            delegate?.watchBridgeDidReceiveCommandResult(self, requestID: requestID, result: result)
        case "commandError":
            guard let data = raw["payload"] as? Data,
                  let error = try? JSONDecoder().decode(WatchCommandError.self, from: data) else { return }
            delegate?.watchBridgeDidReceiveCommandError(self, requestID: requestID, error: error)
        case "plugCommand":
            guard let data = raw["payload"] as? Data,
                  let intent = try? JSONDecoder().decode(PlugIntent.self, from: data) else { return }
            delegate?.watchBridgeDidReceivePlugCommand(self, name: intent.name, isOn: intent.isOn, requestID: requestID)
        default:
            break
        }
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
    public func sendState(json: Data) {}
    @discardableResult
    public func sendPlugCommand(name: String, isOn: Bool, requestID: String = UUID().uuidString) -> Bool { false }
    @discardableResult
    public func sendCommandResult(requestID: String, result: CommandResult) -> Bool { false }
    @discardableResult
    public func sendCommandError(requestID: String, message: String) -> Bool { false }
    public func updateApplicationContext(stateJSON: Data?, endpoint: String? = nil) {}
}

#endif
