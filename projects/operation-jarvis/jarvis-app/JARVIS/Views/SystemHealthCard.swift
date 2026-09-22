import SwiftUI
import JARVISKit

struct SystemHealthCard: View {
    let snapshot: StateSnapshot?
    let requestStartedAt: Date?
    let active: Bool
    @State private var expanded = false

    var body: some View {
        TimelineView(.animation(minimumInterval: 5, paused: !active)) { _ in
            // The timeline only schedules age updates. Its last tick can predate
            // a newly received snapshot, so evaluate against the render-time clock.
            let health = SystemHealthPresentation(snapshot: snapshot,
                requestStartedAt: requestStartedAt)
            MinimalCard(padding: 11) {
                DisclosureGroup(isExpanded: $expanded) {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(health.rows) { row in
                            HStack(alignment: .top, spacing: 8) {
                                Image(systemName: symbol(row.state))
                                    .foregroundStyle(color(row.state))
                                    .accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(row.title).font(.subheadline.weight(.medium))
                                    Text(row.detail).font(.caption)
                                    Text(row.ageText).font(.caption2).foregroundStyle(.secondary)
                                }
                                Spacer(minLength: 0)
                            }
                            .accessibilityElement(children: .combine)
                        }
                        Text("Cached service and integration checks. No automatic recovery.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 8)
                } label: {
                    HStack(spacing: 8) {
                        Label("System health", systemImage: "heart.text.square")
                            .font(.subheadline.weight(.semibold))
                        Spacer(minLength: 0)
                        Text(health.summary)
                            .font(.caption)
                            .foregroundStyle(color(health.state))
                            .multilineTextAlignment(.trailing)
                    }
                }
                .tint(.secondary)
            }
        }
    }

    private func color(_ state: SystemHealthState) -> Color {
        switch state {
        case .healthy: return .green
        case .issue: return JarvisPalette.warning
        default: return .secondary
        }
    }

    private func symbol(_ state: SystemHealthState) -> String {
        switch state {
        case .healthy: return "checkmark.circle"
        case .issue: return "exclamationmark.triangle"
        case .unknown: return "questionmark.circle"
        case .checking: return "clock"
        case .inactive: return "pause.circle"
        }
    }
}
