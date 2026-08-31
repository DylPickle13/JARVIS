import Foundation

public enum JARVISNeuralCorePlugState: Equatable, Sendable {
    case on
    case off
    case unknown
}

/// A bounded, presentation-ready projection of real cached JARVIS state.
/// Status values never invent activity: stale inputs become nil/unknown and the
/// explicit WidgetKit gallery placeholder is the only illustrative state. The
/// Cathedral's decorative motion and luminance are intentionally independent.
public struct JARVISNeuralCoreTelemetry: Equatable, Sendable {
    public static let plugOrder = ["family-room-light", "lamp", "pedalboard", "tv"]

    public let signalLost: Bool
    public let piSessions: Int?
    public let illuminatedSpokes: Int
    public let plugStates: [JARVISNeuralCorePlugState]
    public let codexRemainingPercent: Double?
    public let codexIsCritical: Bool
    public let pm25: Int?
    public let linkLabel: String?

    public init(cached: CachedState?, placeholder: Bool = false, now: Date = Date()) {
        if placeholder {
            signalLost = false
            piSessions = 2
            illuminatedSpokes = 4
            plugStates = [.off, .on, .off, .off]
            codexRemainingPercent = 82
            codexIsCritical = false
            pm25 = 3
            linkLabel = "LAN"
            return
        }

        guard let cached else {
            signalLost = true
            piSessions = nil
            illuminatedSpokes = 0
            plugStates = Array(repeating: .unknown, count: Self.plugOrder.count)
            codexRemainingPercent = nil
            codexIsCritical = false
            pm25 = nil
            linkLabel = nil
            return
        }

        let snapshot = cached.state
        signalLost = !snapshot.ok || JARVISWidgetStateLoader.isStale(cached, now: now)

        let pi = snapshot.subsystems?.pi
        let piIsUsable = !signalLost && pi?.ok == true && pi?.stale != true
        let resolvedSessions = piIsUsable ? (pi?.active ?? snapshot.summary?.piActive) : nil
        piSessions = resolvedSessions
        illuminatedSpokes = min(max((resolvedSessions ?? 0) * 2, 0), 8)

        let plugs = snapshot.subsystems?.plugs
        let plugsAreUsable = !signalLost && plugs?.ok == true && plugs?.stale != true
        plugStates = Self.plugOrder.map { name in
            guard plugsAreUsable,
                  let plug = plugs?.plugs?[name],
                  plug.ok != false,
                  plug.stale != true,
                  let isOn = plug.isOn else { return .unknown }
            return isOn ? .on : .off
        }

        let quota = snapshot.subsystems?.codexQuota
        let quotaIsUsable = !signalLost
            && quota?.ok == true
            && quota?.available != false
            && quota?.stale != true
        let remaining = quotaIsUsable ? quota?.weekly?.remainingPercent : nil
        codexRemainingPercent = remaining.map { min(max($0, 0), 100) }
        codexIsCritical = codexRemainingPercent.map(CodexQuotaPresentationPolicy.isCritical) ?? false

        let purifier = snapshot.subsystems?.purifier
        let purifierIsUsable = !signalLost && purifier?.ok == true && purifier?.stale != true
        pm25 = purifierIsUsable ? (purifier?.pm25 ?? snapshot.summary?.pm25) : nil

        let network = snapshot.subsystems?.network
        let networkIsUsable = !signalLost && network?.ok == true && network?.stale != true
        if networkIsUsable, network?.macLanIp?.isEmpty == false {
            linkLabel = "LAN"
        } else if networkIsUsable, network?.tailscaleIp?.isEmpty == false {
            linkLabel = "TAILSCALE"
        } else {
            linkLabel = nil
        }
    }
}
