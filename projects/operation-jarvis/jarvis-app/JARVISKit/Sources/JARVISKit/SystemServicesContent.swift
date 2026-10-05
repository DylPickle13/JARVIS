import SwiftUI

public enum SystemServicesScope: String, Identifiable, Sendable {
    case services, minecraft
    public var id: String { rawValue }
    public var title: String { self == .minecraft ? "Minecraft" : "Services" }
    public func services(in presentation: SystemDashboardPresentation) -> [SystemDashboardService] {
        self == .minecraft ? presentation.minecraftServices : presentation.backgroundServices
    }
}

/// Pure cached-state rendering. Platforms own presentation, scrolling and refresh.
/// No service actions, network requests, timers or optimistic status reconstruction.
public struct SystemServicesContent: View {
    public let presentation: SystemDashboardPresentation
    public let scope: SystemServicesScope
    public let compact: Bool
    public let accent: Color
    public let warning: Color
    public let surface: Color

    public init(presentation: SystemDashboardPresentation, scope: SystemServicesScope = .services,
                compact: Bool = false, accent: Color, warning: Color, surface: Color) {
        self.presentation = presentation
        self.scope = scope
        self.compact = compact
        self.accent = accent
        self.warning = warning
        self.surface = surface
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 8 : 12) {
            Text(presentation.isConnected ? "Read-only · cached observations" : "Offline · current status unverified")
                .font(.caption).foregroundStyle(.secondary)
            if scope.services(in: presentation).isEmpty {
                Text("Service inventory unavailable or empty").font(.callout).foregroundStyle(.secondary)
            }
            ForEach(scope.services(in: presentation)) { service in
                VStack(alignment: .leading, spacing: compact ? 4 : 6) {
                    HStack(alignment: .top, spacing: 7) {
                        Image(systemName: symbol(service.row.state))
                            .foregroundStyle(color(service.row.state)).accessibilityHidden(true)
                        Text(service.row.title).font(compact ? .callout.weight(.semibold) : .headline)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Text(service.row.detail).font(compact ? .caption : .subheadline)
                        .foregroundStyle(color(service.row.state))
                        .fixedSize(horizontal: false, vertical: true)
                    Text(service.row.ageText).font(.caption2).foregroundStyle(.secondary)
                    Text("\(service.requirement) · \(service.executionMode)")
                        .font(.caption2).foregroundStyle(.secondary)
                    if !compact {
                        if let description = service.description {
                            Text(description).font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(Array(service.technicalDetails.enumerated()), id: \.offset) { _, detail in
                            Text(detail).font(.caption.monospaced()).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(compact ? 8 : 12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .jarvisGlassSurface(surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous), glass: true)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("system-service-\(service.id)")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityIdentifier("system-services-list")
    }

    private func color(_ state: SystemHealthState) -> Color {
        switch state {
        case .healthy: return accent
        case .issue: return warning
        default: return .secondary
        }
    }

    private func symbol(_ state: SystemHealthState) -> String {
        switch state {
        case .healthy: return "checkmark.circle.fill"
        case .issue: return "exclamationmark.triangle.fill"
        case .unknown: return "questionmark.circle"
        case .checking: return "clock"
        case .inactive: return "pause.circle"
        }
    }
}
