import Foundation

/// iPhone-only row selection. Keep the full observation set for warnings,
/// update indicators and motion; hidden idle hosts are not missing hosts.
public struct OMLXHomePresentation: Equatable, Sendable {
    public let visibleRows: [OMLXServerSummary]
    public let status: String?

    public init(rows: [OMLXServerSummary]) {
        visibleRows = rows.filter {
            $0.fresh && [.loading, .queued, .prefill, .processing, .generating].contains($0.phase)
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
            status = visibleRows.isEmpty ? "Idle" : nil
        }
    }
}
