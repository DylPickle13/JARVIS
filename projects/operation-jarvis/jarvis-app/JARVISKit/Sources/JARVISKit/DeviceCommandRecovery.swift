import Foundation

/// A single read-only reconciliation after an uncertain write. Never dispatches,
/// retries a command, changes routes, or bypasses a device/cloud cooldown.
public enum DeviceCommandRecovery {
    public struct Observation: Sendable {
        public let state: StateSnapshot
        public let confirmation: CommandResult?
    }

    public static func observe(client: any JarvisAPI, endpoint: JarvisEndpoint,
                               action: String, params: [String: JSONValue], notBefore: Date) async -> Observation? {
        guard ["plug-on", "plug-off", "purifier-set"].contains(action), !Task.isCancelled else { return nil }
        do {
            let state = try await client.cachedState(endpoint)
            guard !Task.isCancelled else { return nil }
            return Observation(state: state, confirmation: confirmation(action: action, params: params, state: state, notBefore: notBefore))
        } catch { return nil }
    }

    public static func confirmation(action: String, params: [String: JSONValue], state: StateSnapshot, notBefore: Date) -> CommandResult? {
        guard state.ok else { return nil }
        let summary = "Requested state confirmed after uncertain delivery; command was not resent."
        if action == "plug-on" || action == "plug-off" {
            guard observedAfter(state.subsystems?.plugs?.updatedAt, notBefore),
                  case .string(let name)? = params["plug"],
                  let plug = try? JARVISPlugCatalog.freshPlug(id: name, in: state),
                  plug.isOn == (action == "plug-on") else { return nil }
            return CommandResult(ok: true, action: action,
                plug: .init(name: name, is_on: plug.isOn), summary: summary)
        }
        guard action == "purifier-set", case .string(let setting)? = params["setting"] else { return nil }
        let command: WatchPurifierCommand?
        switch setting {
        case "power":
            guard case .string(let value)? = params["value"], ["on", "off"].contains(value) else { return nil }
            command = .power(value == "on")
        case "mode":
            guard case .string(let value)? = params["value"] else { return nil }
            command = .mode(value)
        case "speed":
            guard case .number(let value)? = params["level"], value.isFinite,
                  (1...4).contains(value), value.rounded() == value else { return nil }
            command = .speed(Int(value))
        default: return nil
        }
        let deviceID: String?
        if let value = params["deviceID"] {
            guard case .string(let id) = value else { return nil }
            deviceID = id
        } else { deviceID = nil }
        guard let target = command?.targeting(deviceID), target.isValid,
              let purifier = state.subsystems?.purifier?.selected(deviceID),
              observedAfter(purifier.updatedAt, notBefore),
              purifier.ok == true, purifier.stale != true, purifier.verificationPending != true,
              target.matches(purifier) else { return nil }
        return CommandResult(ok: true, action: action, summary: summary)
    }

    private static func observedAfter(_ value: String?, _ start: Date) -> Bool {
        guard let value else { return false }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let observed = parser.date(from: value) ?? ISO8601DateFormatter().date(from: value) else { return false }
        return observed >= start && observed <= Date().addingTimeInterval(5)
    }
}

public extension JarvisError {
    var mayHaveDeliveredCommand: Bool {
        switch self {
        case .transport, .decoding: return true
        case .http(let status, _): return (300..<400).contains(status) || status == 408 || status >= 500
        case .notConfigured, .badURL: return false
        }
    }
}
