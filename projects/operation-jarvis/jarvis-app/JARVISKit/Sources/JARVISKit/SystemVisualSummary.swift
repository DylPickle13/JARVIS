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
        return [
            .init(id: "services", title: "Services", rows: services.map(\.row) + rows.filter { ["services", "backend", "backendHealth"].contains($0.id) }),
            .init(id: "pi", title: "Pi", rows: rows.filter { ["pi", "codexQuota"].contains($0.id) }),
            .init(id: "network", title: "Network", rows: rows.filter { $0.id == "network" }),
            .init(id: "devices", title: "Devices", rows: rows.filter { ["plugs", "purifier"].contains($0.id) }),
            .init(id: "security", title: "Sensors", rows: rows.filter { $0.id == "security" })
        ]
    }

    /// Describe observation age, never pretend it is the failure's start time.
    var visualException: String? {
        guard isConnected else { return "Offline · cached evidence" }
        let groups = visualGroups.filter { [.issue, .unknown, .checking].contains($0.state) }
        guard let group = groups.first(where: { $0.state == .issue }) ?? groups.first else { return nil }
        let suffix = groups.count > 1 ? " · +\(groups.count - 1)" : ""
        return "\(group.title) · \(group.state == .issue ? "issue" : "unverified")\(suffix)"
    }
}
