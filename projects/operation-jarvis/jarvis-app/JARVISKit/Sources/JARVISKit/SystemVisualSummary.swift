import Foundation

/// Visual groups never strengthen the underlying cached evidence.
public struct SystemVisualGroup: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let rows: [SystemHealthRow]
    public var state: SystemHealthState {
        guard !rows.isEmpty else { return .unknown }
        for state: SystemHealthState in [.issue, .unknown, .checking, .healthy, .inactive] {
            if rows.contains(where: { $0.state == state }) { return state }
        }
        return .unknown
    }
    public var accessibilityText: String {
        "\(title), \(state.rawValue). " + (rows.isEmpty ? "No cached evidence" : rows.map {
            "\($0.title): \($0.detail). \($0.ageText)"
        }.joined(separator: ". "))
    }
}

public extension SystemDashboardPresentation {
    var visualGroups: [SystemVisualGroup] {
        let rows = subsystemRows
        var groups: [SystemVisualGroup] = [
            .init(id: "services", title: "Services", rows: backgroundServices.map(\.row)
                + rows.filter { ["services", "backend"].contains($0.id) })
        ]
        if hasMinecraftServices {
            groups.append(.init(id: "minecraft", title: "Minecraft", rows: minecraftServices.map(\.row)))
        }
        groups += [
            .init(id: "pi", title: "Pi", rows: rows.filter { ["pi", "codexQuota"].contains($0.id) }),
            .init(id: "network", title: "Network", rows: rows.filter { $0.id == "network" })
        ]
        guard includesDeviceCoverage else {
            // Older hosts retain their aggregate scope; never invent device evidence.
            return groups + [
                .init(id: "devices", title: "Devices", rows: rows.filter { ["plugs", "purifier"].contains($0.id) }),
                .init(id: "security", title: "Security", rows: rows.filter { $0.id == "security" })
            ]
        }
        let computer = ["keyboard-watcher", "keyboard", "mouse", "led-strip", "room-audio-mac"]
        let security = ["hub", "door-sensor", "motion-sensor", "sensor-reader", "front-doorbell", "indoor-camera", "room-audio-pi"]
        let cast = ["family-room-tv", "family-room-speaker"]
        func checks(_ ids: [String]) -> [SystemHealthRow] {
            ids.map { id in
                rows.first { $0.id == "device:\(id)" } ?? .init(
                    id: "device:\(id)", title: id, state: .unknown,
                    detail: "No configured check evidence", ageSeconds: nil)
            }
        }
        let grouped = Set((computer + security + cast).map { "device:\($0)" })
        groups += [
            .init(id: "computer", title: "Computer", rows: checks(computer)),
            .init(id: "security", title: "Security", rows: checks(security)),
            .init(id: "cast", title: "Cast playback", rows: checks(cast)),
            .init(id: "devices", title: "Devices", rows: rows.filter {
                ["plugs", "purifier", "deviceCoverage"].contains($0.id)
                    || ($0.id.hasPrefix("device:") && !grouped.contains($0.id))
            })
        ]
        return groups
    }

    /// Describe observation age, never pretend it is the failure's start time.
    var visualException: String? {
        guard isConnected else { return "Offline · cached evidence" }
        let groups = visualGroups.filter { [.issue, .unknown, .checking].contains($0.state) }
        if !groups.contains(where: { $0.state == .issue }),
           subsystemRows.contains(where: { $0.id == "backendHealth" && $0.state == .issue }) {
            return "Backend summary · issue"
        }
        guard let group = groups.first(where: { $0.state == .issue }) ?? groups.first else {
            // Overall backend evidence still constrains the ring/header, but is
            // not falsely attributed to Services when a different check failed.
            guard let overall = subsystemRows.first(where: { $0.id == "backendHealth" }),
                  [.issue, .unknown, .checking].contains(overall.state) else { return nil }
            return "Backend summary · \(overall.state == .issue ? "issue" : "unverified")"
        }
        let suffix = groups.count > 1 ? " · +\(groups.count - 1)" : ""
        return "\(group.title) · \(group.state == .issue ? "issue" : "unverified")\(suffix)"
    }
}
