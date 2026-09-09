import SwiftUI
import JARVISKit

struct OMLXStatusCard: View {
    let endpoint: JarvisEndpoint?
    let active: Bool
    @StateObject private var model: OMLXStatusModel
    @State private var selectedServer: String?

    init(client: any JarvisAPI, endpoint: JarvisEndpoint?, active: Bool) {
        self.endpoint = endpoint
        self.active = active
        _model = StateObject(wrappedValue: OMLXStatusModel(fetch: { try await client.omlxStatus($0) }))
    }

    private struct PollKey: Hashable {
        let url: URL?
        let token: String?
        let active: Bool
    }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1, paused: !active)) { context in
            MinimalCard {
                VStack(alignment: .leading, spacing: 12) {
                    Label("oMLX", systemImage: "cpu")
                        .font(.subheadline.weight(.semibold))
                        .accessibilityAddTraits(.isHeader)
                    ForEach(OMLXSnapshot.serverIDs, id: \.self) { id in
                        if id != OMLXSnapshot.serverIDs.first { Divider() }
                        Button { selectedServer = id } label: {
                            serverContent(id, now: context.date, expanded: false)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityHint("Show read-only model details")
                    }
                }
            }
        }
        .task(id: PollKey(url: endpoint?.baseURL, token: endpoint?.token, active: active)) {
            await model.run(endpoint: active ? endpoint : nil)
        }
        .sheet(isPresented: Binding(get: { selectedServer != nil }, set: { if !$0 { selectedServer = nil } })) {
            NavigationStack {
                ScrollView {
                    TimelineView(.animation(minimumInterval: 1, paused: !active)) { context in
                        if let selectedServer {
                            serverContent(selectedServer, now: context.date, expanded: true).padding()
                        }
                    }
                }
                .background(JarvisBackdrop())
                .navigationTitle("oMLX details")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { selectedServer = nil }
                } }
            }
            .presentationDetents([.medium, .large])
        }
    }

    private func serverContent(_ id: String, now: Date, expanded: Bool) -> some View {
        OMLXServerContent(id: id, server: model.snapshot?.servers.first { $0.id == id },
            now: now, requestStartedAt: model.requestStartedAt,
            available: active && model.isPolling && !model.unavailable,
            checking: model.snapshot == nil && model.isPolling && !model.unavailable,
            expanded: expanded)
    }
}

struct OMLXServerContent: View {
    let id: String
    let server: OMLXServerStatus?
    let now: Date
    let requestStartedAt: Date?
    let available: Bool
    let checking: Bool
    let expanded: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var fresh: Bool { available && server?.isFresh(requestStartedAt: requestStartedAt, now: now) == true }
    private var phase: OMLXPhase { server?.phase ?? .unknown }
    private var title: String {
        if fresh { return phase.title }
        if checking { return "Checking" }
        return server?.lastSuccessAt != nil ? "Stale" : "Unavailable"
    }
    private var tone: Color { fresh ? OMLXFormat.tone(phase) : .secondary }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline) { serverName; Spacer(minLength: 8); status }
                VStack(alignment: .leading, spacing: 5) { serverName; status }
            }
            if fresh, let server {
                if server.models?.isEmpty == true {
                    Text("No models loaded").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(expanded ? (server.models ?? []) : server.busyModels) { model in
                    modelRow(model)
                }
                if !expanded, !server.idleModels.isEmpty {
                    let count = server.idleModels.count
                    Text("\(count) model\(count == 1 ? "" : "s") loaded · \(server.busyModels.isEmpty ? "No active requests" : "Idle")")
                        .font(.caption).foregroundStyle(.secondary)
                }
                memory(server)
            } else if !checking {
                Text(server?.error == "Authentication required." ? "Authentication required" : "Activity unavailable")
                    .font(.caption).foregroundStyle(.secondary)
                if let age = server?.sourceAge(requestStartedAt: requestStartedAt, now: now) {
                    Text("Last successful update \(OMLXFormat.duration(age)) ago")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                if expanded, let server, !(server.models ?? []).isEmpty {
                    Text("Previously loaded models — not live")
                        .font(.caption.weight(.semibold)).padding(.top, 8)
                    ForEach(server.models ?? []) { model in
                        Text(model.id).font(.subheadline).textSelection(.enabled)
                    }
                }
            }
            if expanded {
                Text(id).font(.caption2).foregroundStyle(.secondary)
                Text("Read-only · Updates while Home is active")
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .monospacedDigit()
    }

    private var serverName: some View {
        Text(id == "mac-mini-64" ? "Mac mini · 64 GB" : "Mac mini · 16 GB")
            .font(.subheadline.weight(.medium))
    }
    private var status: some View {
        HStack(spacing: 5) {
            Circle().fill(tone).frame(width: 6, height: 6).accessibilityHidden(true)
            Text(title).font(.caption.weight(.medium)).foregroundStyle(tone)
        }
        .fixedSize(horizontal: !dynamicTypeSize.isAccessibilitySize, vertical: true)
    }

    private func modelRow(_ model: OMLXModelStatus) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(model.id).font(.subheadline)
                .lineLimit(expanded || dynamicTypeSize.isAccessibilitySize ? nil : 2)
                .fixedSize(horizontal: false, vertical: true)
            if expanded || (server?.busyModels.count ?? 0) > 1 {
                Text(model.phase.title).font(.caption).foregroundStyle(OMLXFormat.tone(model.phase))
            }
            if model.isLoading, let elapsed = model.loadingElapsedSeconds {
                Text("Loading · \(OMLXFormat.duration(elapsed)) elapsed").font(.caption).foregroundStyle(.secondary)
            } else {
                if model.activeRequests > 1 || model.queuedRequests > 0 {
                    Text("\(model.activeRequests) active\(model.queuedRequests > 0 ? " · \(model.queuedRequests) queued" : "")")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if expanded || model.requests.count == 1 {
                    ForEach(model.requests) { request in
                        VStack(alignment: .leading, spacing: 3) {
                            if expanded {
                                Text(request.phase.title + (request.queuePosition.map { " · Position \($0)" } ?? ""))
                                    .font(.caption.weight(.medium))
                            }
                            if let fraction = request.prefillFraction {
                                ProgressView(value: fraction).tint(.blue)
                                    .accessibilityLabel("Prompt processing")
                                    .accessibilityValue("\(Int(fraction * 100)) percent")
                            }
                            Text(OMLXFormat.metrics(request)).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            if expanded {
                if let bytes = model.observedBytes, bytes > 0 {
                    Text("≈ \(OMLXFormat.bytes(bytes)) observed at load")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                if let bytes = model.estimatedBytes, bytes > 0 {
                    Text("\(OMLXFormat.bytes(bytes)) estimated model size")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, expanded ? 6 : 0)
    }

    @ViewBuilder private func memory(_ server: OMLXServerStatus) -> some View {
        if let used = server.memoryUsedBytes, used >= 0 {
            let limit = server.memoryLimitBytes.flatMap { $0 > 0 ? $0 : nil }
            let label = server.memoryKind == "process" ? "oMLX process" : "Model memory"
            Text("\(label) · \(OMLXFormat.bytes(used))\(limit.map { " / \(OMLXFormat.bytes($0)) budget" } ?? "")")
                .font(.caption2).foregroundStyle(.secondary)
        }
        if let pressure = server.memoryPressure, ["soft", "hard", "critical"].contains(pressure) {
            Label("Memory pressure · \(pressure)", systemImage: "exclamationmark.triangle")
                .font(.caption2).foregroundStyle(JarvisPalette.warning)
        }
    }
}

enum OMLXFormat {
    static func tone(_ phase: OMLXPhase) -> Color {
        switch phase {
        case .generating, .processing: return .green
        case .prefill: return .blue
        case .loading, .queued: return JarvisPalette.warning
        case .ready: return .secondary
        case .unknown: return JarvisPalette.warning
        }
    }
    static func duration(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0, seconds < Double(Int.max) else { return "—" }
        if seconds < 60 { return "\(Int(seconds))s" }
        if seconds < 3600 { return "\(Int(seconds / 60))m \(Int(seconds.truncatingRemainder(dividingBy: 60)))s" }
        return "\(Int(seconds / 3600))h \(Int(seconds.truncatingRemainder(dividingBy: 3600) / 60))m"
    }
    static func bytes(_ bytes: Double) -> String {
        guard bytes.isFinite, bytes >= 0 else { return "—" }
        return (bytes / 1_073_741_824).formatted(.number.precision(.fractionLength(1))) + " GiB"
    }
    static func metrics(_ request: OMLXRequestStatus) -> String {
        var parts: [String] = []
        if request.phase == .prefill, let done = request.processedTokens, let total = request.totalTokens, done >= 0, total > 0 {
            parts.append("\(done.formatted()) / \(total.formatted()) tokens")
        }
        if request.phase == .generating, let tokens = request.generatedTokens, tokens >= 0 {
            parts.append("\(tokens.formatted()) tokens")
        }
        if [.generating, .prefill].contains(request.phase), let speed = request.tokensPerSecond, speed.isFinite, speed > 0 {
            parts.append(speed.formatted(.number.precision(.fractionLength(1))) + (request.phase == .generating ? " tok/s avg" : " tok/s"))
        }
        if let elapsed = request.elapsedSeconds { parts.append(duration(elapsed)) }
        if let age = request.lastActivityAgeSeconds, age >= 3 { parts.append("Last activity \(duration(age)) ago") }
        return parts.isEmpty ? "Metrics unavailable" : parts.joined(separator: " · ")
    }
}
