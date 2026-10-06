import Foundation

/// iPhone-only row selection. Fresh loaded/loading inventory, not request
/// activity, owns visibility. Keep all observations for peer warnings and motion.
public struct OMLXHomePresentation: Equatable, Sendable {
    public let visibleRows: [OMLXServerSummary]
    public let status: String?

    public init(rows: [OMLXServerSummary]) {
        visibleRows = rows.filter {
            $0.fresh && $0.phase != .unknown && $0.details?.modelNames.isEmpty == false
        }
        let uncertain = rows.filter { !$0.fresh || $0.phase == .unknown }
        if rows.isEmpty {
            status = "Checking"
        } else if uncertain.count == rows.count {
            let statuses = Set(uncertain.map(\.status))
            status = statuses.count == 1 ? uncertain[0].status : "Status unknown"
        } else if let row = uncertain.first {
            status = "\(row.compactServerLabel) \(row.status.lowercased())"
        } else {
            if visibleRows.isEmpty {
                status = "No models loaded"
            } else {
                status = visibleRows.allSatisfy { $0.phase == .ready } ? "Idle" : nil
            }
        }
    }
}
