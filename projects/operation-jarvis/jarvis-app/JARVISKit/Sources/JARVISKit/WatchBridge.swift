import Foundation
#if canImport(WatchConnectivity)
import WatchConnectivity
#endif

// WatchConnectivity bridge between the iPhone app and the watch app.
//
// M0 scope: session setup + reachability so both apps can report connection
// status. The full relay (watch requests state, iPhone proxies to jarvisd)
// and endpoint/token sync land in M3/M4 per the plan — the message-passing
// seams are here so that work is additive.
//
// Roles:
//   - On the WATCH, `isPhoneReachable` tells us we can relay through the phone.
//   - On the PHONE, `isWatchReachable` tells us we can push state to the watch.

public protocol WatchBridgeDelegate: AnyObject {
    /// The peer sent a `{ "type": "stateRequest" }` message.
    func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge)
    /// The peer sent a `{ "type": "state", "payload": <StateSnapshot JSON> }`.
    func watchBridgeDidReceiveState(_ bridge: WatchBridge, json: Data)
}

#if canImport(WatchConnectivity)

public final class WatchBridge: NSObject, @unchecked Sendable {
    public static let shared = WatchBridge()

    public weak var delegate: WatchBridgeDelegate?

    public private(set) var isWatchReachable = false
    public private(set) var isPhoneReachable = false
    public private(set) var isActivationNeeded = false

    private var session: WCSession? { WCSession.isSupported() ? WCSession.default : nil }

    private override init() {
        super.init()
    }

    public func start() {
        guard let session else { return }
        session.delegate = self
        session.activate()
    }

    // MARK: - Outgoing messages

    /// Ask the peer (iPhone) for a fresh state snapshot.
    public func requestState() {
        guard let session, session.isReachable else { return }
        session.sendMessage(["type": "stateRequest"], replyHandler: nil, errorHandler: nil)
    }

    /// Send a state snapshot (JSON) to the peer (watch).
    public func sendState(json: Data) {
        guard let session, session.isReachable else { return }
        session.sendMessage(["type": "state", "payload": json], replyHandler: nil, errorHandler: nil)
    }
}

extension WatchBridge: WCSessionDelegate {
    public func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        isActivationNeeded = (activationState != .activated)
    }

#if os(iOS)
    // Required on iOS; marked unavailable on watchOS, so gate by platform.
    public func sessionDidBecomeInactive(_ session: WCSession) {}
    public func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
#endif

    public func session(_ session: WCSession, watchDidBecomeAvailableWithError error: Error?) {
        isWatchReachable = (error == nil)
    }

    public func session(_ session: WCSession, phoneDidBecomeAvailableWithError error: Error?) {
        isPhoneReachable = (error == nil)
    }

    public func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        switch message["type"] as? String {
        case "stateRequest":
            delegate?.watchBridgeDidReceiveStateRequest(self)
        case "state":
            if let data = message["payload"] as? Data {
                delegate?.watchBridgeDidReceiveState(self, json: data)
            }
        default:
            break
        }
        replyHandler([:])
    }
}

#else

// Non-watchConnectivity platforms (e.g. macOS when unit-testing the package):
// a no-op stub with the same surface so dependent code compiles everywhere.
public final class WatchBridge: NSObject, @unchecked Sendable {
    public static let shared = WatchBridge()
    public weak var delegate: WatchBridgeDelegate?
    public private(set) var isWatchReachable = false
    public private(set) var isPhoneReachable = false
    public private(set) var isActivationNeeded = true
    public func start() {}
    public func requestState() {}
    public func sendState(json: Data) {}
}

#endif
