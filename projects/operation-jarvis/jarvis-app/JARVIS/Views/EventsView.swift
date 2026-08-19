import SwiftUI
import JARVISKit

// Events tab — live activity feed from jarvisd.
//
// Polls /api/v1/events every ~5 s while the tab is open (auto) and supports
// pull-to-refresh. One inset-grouped row per event: a status glyph (✓/✗), the
// action, a one-line summary, and a compact relative timestamp. Newest first.

struct EventsView: View {
    @EnvironmentObject var app: AppState

    private let pollInterval: Duration = .seconds(5)

    var body: some View {
        NavigationStack {
            Group {
                if app.connectionState == .connecting {
                    connecting
                } else if app.connectionState != .connected {
                    notConnected
                } else if app.lastEvents.isEmpty {
                    empty
                } else {
                    eventList
                }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Events")
            .task { await pollLoop() }
        }
    }

    // MARK: - List

    private var eventList: some View {
        List {
            Section {
                ForEach(app.lastEvents.sorted { $0.seq > $1.seq }) { event in
                    EventRow(event: event)
                }
            } header: {
                Text("\(app.lastEvents.count) recent · auto-refreshes every 5 s")
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await app.fetchEvents() }
    }

    // MARK: - Empty / disconnected states

    private var connecting: some View {
        VStack {
            Card {
                HStack(spacing: 12) {
                    ProgressView()
                    Text("Connecting to jarvisd…")
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
        .padding(.horizontal)
    }

    private var notConnected: some View {
        VStack {
            Card {
                VStack(spacing: 12) {
                    Image(systemName: "wifi.slash")
                        .font(.system(size: 34))
                        .foregroundStyle(.secondary)
                    Text("Not connected")
                        .font(.headline)
                    Text("Connect from the Settings tab to see live events.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
            }
            Spacer()
        }
        .padding(.horizontal)
    }

    private var empty: some View {
        VStack {
            Card {
                VStack(spacing: 12) {
                    Image(systemName: "list.bullet.rectangle")
                        .font(.system(size: 34))
                        .foregroundStyle(.secondary)
                    Text("No events yet")
                        .font(.headline)
                    Text("Activity from plugs, the purifier, and system actions will appear here.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
            }
            Spacer()
        }
        .padding(.horizontal)
    }

    // MARK: - Polling

    private func pollLoop() async {
        while !Task.isCancelled {
            await app.fetchEvents()
            try? await Task.sleep(for: pollInterval)
        }
    }
}

// MARK: - Row

private struct EventRow: View {
    let event: EventItem

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            statusIcon
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(event.action ?? event.eventType ?? "event")
                        .font(.body)
                        .lineLimit(1)
                    Spacer()
                    Text(JarvisFormat.relativeTime(event.at ?? event.receivedAt))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                if let summary = event.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                } else if let error = event.error, !error.isEmpty {
                    Text(error)
                        .font(.subheadline)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch event.ok {
        case true:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case false:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(.red)
        case nil:
            Image(systemName: "circle.dotted")
                .foregroundStyle(.secondary)
        }
    }

    private var accessibilityText: String {
        let status = event.ok == true ? "success" : (event.ok == false ? "failure" : "info")
        let title = event.action ?? event.eventType ?? "event"
        let detail = event.summary ?? event.error ?? ""
        return "\(status): \(title). \(detail) \(JarvisFormat.relativeTime(event.at ?? event.receivedAt)) ago"
    }
}

#Preview {
    EventsView().environmentObject(AppState())
}
