import Foundation
import SwiftUI
import JARVISKit

enum PiSessionIndicatorTone: Equatable {
    case offline
    case idle
    case running
    case new
    case compacting
    case unknown

    var color: Color {
        switch self {
        case .offline: return PiSessionLifecycle.offline.statusColor
        case .idle: return PiSessionLifecycle.idle.statusColor
        case .running: return PiSessionLifecycle.running.statusColor
        case .new: return PiSessionLifecycle.new.statusColor
        case .compacting: return PiSessionLifecycle.compacting.statusColor
        case .unknown: return PiSessionLifecycle.unknown.statusColor
        }
    }
}

struct PiSessionIndicatorPresentation: Equatable {
    let label: String
    let tone: PiSessionIndicatorTone
    var symbol: String {
        switch tone {
        case .running: return "waveform"
        case .compacting: return "arrow.down.right.and.arrow.up.left"
        case .idle: return "pause.fill"
        case .new: return "plus"
        case .offline: return "bolt.slash.fill"
        case .unknown: return "questionmark"
        }
    }
    var animatesIcon: Bool { tone == .running || tone == .compacting }
    var allowsActivityEdge: Bool { animatesIcon || tone == .idle }

    init(lifecycle: PiSessionLifecycle) {
        switch lifecycle {
        case .offline:
            label = "Offline"
            tone = .offline
        case .idle:
            label = "Idle"
            tone = .idle
        case .running:
            label = "Running"
            tone = .running
        case .new:
            label = "New"
            tone = .new
        case .compacting:
            label = "Compacting"
            tone = .compacting
        case .unknown:
            label = "Unknown"
            tone = .unknown
        }
    }
}

/// One independent, full-target card; routing remains on the enclosing button.
struct PiSessionCardContent: View {
    let sessionID: Int
    let lifecycle: PiSessionLifecycle
    let motionActive: Bool

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .caption) private var numberSize = 12.0
    @ScaledMetric(relativeTo: .body) private var iconSize = 18.0
    @ScaledMetric(relativeTo: .subheadline) private var statusSize = 14.0

    var body: some View {
        let presentation = PiSessionIndicatorPresentation(lifecycle: lifecycle)
        let color = presentation.tone.color
        MinimalCard(padding: 8, glass: true) {
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("\(sessionID)")
                        .font(.system(size: numberSize, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 4)
                    Image(systemName: presentation.symbol)
                        .font(.system(size: iconSize, weight: .semibold))
                        // Normalize SF Symbol line boxes; glyph choice must not resize a card.
                        .frame(height: iconSize)
                        .foregroundStyle(color)
                        .piSessionMotion(lifecycle: lifecycle, active: motionActive)
                        .accessibilityHidden(true)
                }
                Text(presentation.label)
                    .font(.system(size: statusSize, weight: .semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
                    .minimumScaleFactor(dynamicTypeSize.isAccessibilitySize ? 1 : 0.85)
            }
            .frame(maxWidth: .infinity, minHeight: 42, alignment: .leading)
        }
        .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Pi session \(sessionID), \(presentation.label.lowercased())")
    }
}

struct HomeView: View {
    @EnvironmentObject var app: AppState
    let onOpenPiTerminal: (JARVISTerminalSlot) -> Void

    init(onOpenPiTerminal: @escaping (JARVISTerminalSlot) -> Void = { _ in }) {
        self.onOpenPiTerminal = onOpenPiTerminal
    }
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.scenePhase) private var scenePhase
    private var usesAccessibilityLayout: Bool { dynamicTypeSize.isAccessibilitySize }
    private var gridColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 8), count: usesAccessibilityLayout ? 1 : 2)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    TabPageHeader(title: "JARVIS", animated: true,
                                  connected: app.connectionState == .connected, active: homeMotionActive,
                                  subtitle: connectionHeadline,
                                  subtitleColor: app.connectionState == .failed ? .red : .orange)
                        .accessibilityValue("\(connectionHeadline.isEmpty ? "Connected" : connectionHeadline), \(freshnessLabel)")

                    if let operationError = app.operationErrorMessage {
                        OperationErrorCard(message: operationError)
                    }

                    if app.connectionState == .connecting || (app.connectionState == .connected && app.lastState == nil) {
                        loadingCard
                    } else if app.connectionState == .connected, let state = app.lastState {
                        if state.loading == true && state.subsystems == nil {
                            loadingCard
                        } else {
                            piCard(state)
                            roomAudioCard
                            codexQuotaCard(state)
                            OMLXStatusCard(client: app.client,
                                endpoint: app.currentEndpoint.map { JarvisEndpoint(baseURL: $0, token: app.store.token ?? "") },
                                active: scenePhase == .active && app.activeSection == .home)
                        }
                    } else {
                        compactOfflineCard
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 6)
            }
            .scrollIndicators(.hidden)
            .background(JarvisBackdrop())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await app.refreshJARVIS(); await app.refreshRoomAudio() }
            .task(id: scenePhase == .active && app.activeSection == .home) {
                guard scenePhase == .active, app.activeSection == .home else { return }
                while !Task.isCancelled {
                    await app.refreshRoomAudio()
                    do { try await Task.sleep(for: .seconds(2)) } catch { return }
                }
            }
        }
    }

    private var homeMotionActive: Bool {
        scenePhase == .active && app.activeSection == .home
    }

    private var roomAudioCard: some View {
        TimelineView(.animation(minimumInterval: 1, paused: !homeMotionActive)) { context in
            let sessions = app.lastState?.subsystems?.pi?.mobileSessions
            let lifecycle = app.lastState?.subsystems?.pi?.stale == true ? PiSessionLifecycle.unknown
                : sessions?.first(where: { $0.sessionID == 10 })?.resolvedLifecycle ?? .unknown
            let presentation = PiSessionIndicatorPresentation(lifecycle: lifecycle)
            let activeSpeakers = RoomAudioSpeaker.allCases.filter { speaker in
                app.roomAudio[speaker]?.allowsStop == true &&
                    (app.roomAudioUpdatedAt[speaker].map { context.date.timeIntervalSince($0) <= 6 } ?? false)
            }
            let speakerSummary = RoomAudioSpeaker.allCases.map { speaker in
                let fresh = app.roomAudioUpdatedAt[speaker].map { context.date.timeIntervalSince($0) <= 6 } ?? false
                return "\(speaker.title): \(fresh ? app.roomAudio[speaker]?.title ?? "Unavailable" : "Unavailable")"
            }.joined(separator: " · ")
            MinimalCard(padding: 8) {
                HStack(spacing: 8) {
                    Button { onOpenPiTerminal(.roomAudio) } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text("10").font(.system(.caption, design: .monospaced).weight(.semibold)).foregroundStyle(.secondary)
                                Text("Room Audio").font(.subheadline.weight(.semibold))
                                    .lineLimit(1).minimumScaleFactor(0.85)
                                Spacer(minLength: 4)
                                Image(systemName: presentation.symbol).foregroundStyle(presentation.tone.color)
                                    .piSessionMotion(lifecycle: lifecycle, active: homeMotionActive)
                            }
                            Text(speakerSummary).font(.caption2).foregroundStyle(.secondary)
                                .lineLimit(1).minimumScaleFactor(0.85)
                        }
                        .frame(maxWidth: .infinity, minHeight: 42, alignment: .leading)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(JarvisPressStyle())
                    .accessibilityLabel("Room Audio, Pi session 10, \(presentation.label), \(speakerSummary)")
                    .accessibilityHint("Opens the shared Room Audio Pi session 10 terminal")
                    Button { Task { await app.stopAllRoomAudio() } } label: {
                        Image(systemName: "stop.fill").font(.caption)
                            .frame(width: 32, height: 32)
                            .background(JarvisPalette.warning.opacity(0.12), in: Circle())
                    }
                    .buttonStyle(JarvisPressStyle())
                    .disabled(activeSpeakers.isEmpty || !app.roomAudioStopping.isEmpty)
                    .accessibilityLabel("Stop current room audio on both speakers")
                }
            }
        }
    }

    // MARK: - Compact overview

    private var connectionHeadline: String {
        switch app.connectionState {
        case .connected:
            if app.isAwaitingFreshState { return "Loading status" }
            return app.lastState?.stale == true ? "Partial data" : ""
        case .connecting: return "Connecting"
        case .failed: return "Offline"
        case .idle: return "Ready to connect"
        }
    }

    private var freshnessLabel: String {
        if app.isAwaitingFreshState { return "Loading status" }
        if app.lastState?.stale == true { return "Some data delayed" }
        if app.connectionState == .connected, app.lastState != nil, app.lastState?.ageSeconds == nil {
            return "Status current"
        }
        return JarvisFormat.freshness(ageSeconds: app.lastState?.ageSeconds)
    }

    private var loadingCard: some View {
        MinimalCard {
            HStack(spacing: 10) {
                ProgressView()
                Text("Loading JARVIS status…")
                    .font(.subheadline.weight(.medium))
                Spacer()
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var compactOfflineCard: some View {
        MinimalCard {
            HStack(spacing: 12) {
                Image(systemName: "antenna.radiowaves.left.and.right.slash")
                    .foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(app.connectionState == .failed ? "JARVIS is offline" : "JARVIS is not connected")
                        .font(.subheadline.weight(.semibold))
                    if let error = app.errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                Spacer(minLength: 8)
                Button("Connect") { Task { await app.connect() } }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
            }
        }
    }

    // MARK: - Pi and Codex overview cards

    private func piCard(_ state: StateSnapshot) -> AnyView {
        guard let pi = state.subsystems?.pi, pi.ok == true else {
            return AnyView(
                MinimalCard {
                    compactUnavailableRow(title: "Pi sessions unavailable", detail: state.subsystems?.pi?.error)
                }
            )
        }

        let isStale = pi.stale == true
        let content = VStack(spacing: 8) {
            piSessionStatusRow(
                sessionIDs: [1, 2, 3],
                sessions: pi.mobileSessions,
                isStale: isStale
            )
            piSessionStatusRow(
                sessionIDs: [4, 5, 6],
                sessions: pi.mobileSessions,
                isStale: isStale
            )
            piSessionStatusRow(
                sessionIDs: [7, 8, 9],
                sessions: pi.mobileSessions,
                isStale: isStale
            )
        }

        if isStale {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Pi session data is stale.") })
        }
        return AnyView(content)
    }

    private func piSessionStatusRow(
        sessionIDs: [Int],
        sessions: [PiMobileSession]?,
        isStale: Bool
    ) -> some View {
        HStack(alignment: .top, spacing: 8) {
            ForEach(sessionIDs, id: \.self) { sessionID in
                Button {
                    guard let slot = JARVISTerminalSlot(rawValue: sessionID) else { return }
                    onOpenPiTerminal(slot)
                } label: {
                    let lifecycle = isStale
                        ? PiSessionLifecycle.unknown
                        : sessions?.first(where: { $0.sessionID == sessionID })?.resolvedLifecycle ?? .unknown
                    piSessionStatusSection(sessionID: sessionID, lifecycle: lifecycle)
                }
                .buttonStyle(JarvisPressStyle())
                .accessibilityHint("Opens Pi \(sessionID)'s terminal on the Terminal tab")
            }
        }
    }

    private func piSessionStatusSection(sessionID: Int, lifecycle: PiSessionLifecycle) -> some View {
        PiSessionCardContent(sessionID: sessionID, lifecycle: lifecycle,
            motionActive: scenePhase == .active && app.activeSection == .home
                && !app.isAwaitingFreshState)
    }

    private func codexQuotaCard(_ state: StateSnapshot) -> AnyView {
        guard let quota = state.subsystems?.codexQuota,
              quota.available == true,
              let remaining = quota.weekly?.remainingPercent else {
            return AnyView(
                unavailableCard(
                    title: "Codex quota unavailable",
                    detail: state.subsystems?.codexQuota?.lastError ?? state.subsystems?.codexQuota?.error
                )
            )
        }
        let color = codexQuotaColor(remaining)
        let content = MinimalCard(padding: 8) {
            if usesAccessibilityLayout {
                VStack(alignment: .leading, spacing: 8) {
                    codexQuotaRing(remaining: remaining, color: color)
                    codexQuotaDetails(quota, remaining: remaining, color: color)
                }
            } else {
                HStack(spacing: 12) {
                    codexQuotaRing(remaining: remaining, color: color)
                    codexQuotaDetails(quota, remaining: remaining, color: color)
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "Codex weekly quota, \(Int(remaining.rounded())) percent remaining, " +
            "\(codexQuotaResetLabel(quota.weekly)), \(codexFiveHourLabel(quota))"
        )
        if quota.stale == true {
            return AnyView(VStack(alignment: .leading, spacing: 2) { content; staleCaption("Codex quota data is stale.") })
        }
        return AnyView(content)
    }

    private func codexQuotaRing(remaining: Double, color: Color) -> some View {
        ZStack {
            Circle().stroke(color.opacity(0.16), lineWidth: 8)
            Circle()
                .trim(from: 0, to: CGFloat(min(max(remaining / 100, 0), 1)))
                .stroke(color, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                .rotationEffect(.degrees(-90))
            Text("\(Int(remaining.rounded()))%")
                .font(.headline.weight(.bold))
                .monospacedDigit()
                .foregroundStyle(color)
        }
        .frame(width: 58, height: 58)
    }

    private func codexQuotaDetails(
        _ quota: CodexQuotaSubsystem,
        remaining: Double,
        color: Color
    ) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text("Codex")
                    .font(.subheadline.weight(.semibold))
                Spacer(minLength: 2)
                if let plan = quota.planType, !plan.isEmpty {
                    Text(plan.replacingOccurrences(of: "_", with: " ").uppercased())
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(color)
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .background(color.opacity(0.12), in: Capsule())
                }
            }
            Text("Weekly remaining")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            Label(codexQuotaResetLabel(quota.weekly), systemImage: "calendar.badge.clock")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(spacing: 8) {
                Label(codexFiveHourLabel(quota), systemImage: "clock")
                if let credits = codexCreditsLabel(quota.creditBalance) {
                    Label(credits, systemImage: "bolt.circle")
                }
            }
            .font(.caption2.weight(.medium))
            .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func codexQuotaColor(_ remaining: Double) -> Color {
        CodexQuotaPresentationPolicy.isCritical(remainingPercent: remaining)
            ? JarvisPalette.critical
            : JarvisPalette.accent
    }

    private func codexQuotaResetLabel(_ window: CodexQuotaWindow?) -> String {
        let seconds: Int?
        if let resetAt = window?.resetAt, let date = JarvisFormat.parseISO8601(resetAt) {
            seconds = max(0, Int(date.timeIntervalSinceNow))
        } else {
            seconds = window?.resetAfterSeconds
        }
        guard let seconds else { return "Reset time unavailable" }
        if seconds < 60 { return "Resets in less than a minute" }
        if seconds < 3_600 { return "Resets in \(seconds / 60)m" }
        if seconds < 86_400 { return "Resets in \(seconds / 3_600)h \((seconds % 3_600) / 60)m" }
        return "Resets in \(seconds / 86_400)d \((seconds % 86_400) / 3_600)h"
    }

    private func codexFiveHourLabel(_ quota: CodexQuotaSubsystem) -> String {
        if let remaining = quota.fiveHour?.remainingPercent {
            return "5-hour \(Int(remaining.rounded()))% left"
        }
        if quota.fiveHourEnforced == false { return "5-hour paused" }
        return "5-hour unavailable"
    }

    private func codexCreditsLabel(_ balance: Double?) -> String? {
        guard let balance else { return nil }
        if balance >= 1_000 { return String(format: "%.1fK credits", balance / 1_000) }
        return "\(Int(balance.rounded())) credits"
    }

    // MARK: - Detail helpers

    @ViewBuilder
    private func unavailableCard(title: String, detail: String?) -> some View {
        Card {
            compactUnavailableRow(title: title, detail: detail)
        }
    }

    private func compactUnavailableRow(title: String, detail: String?) -> some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold))
                if let detail, !detail.isEmpty {
                    Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
            }
        } icon: {
            Image(systemName: "questionmark.circle").foregroundStyle(.secondary)
        }
    }

    private func staleCaption(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(JarvisPalette.warning)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Bindings


}

#Preview {
    HomeView().environmentObject(AppState())
}
