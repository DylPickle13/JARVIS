import SwiftUI
import JARVISKit

// System tab — service control + daemon info.
//
// One inset-grouped card per registered service (from jarvisd's services.json):
// a status dot, a friendly name, a one-line description, and Stop/Restart (or
// Start/Restart when stopped) controls. Stopping a running service asks for
// confirmation first. Commands go through AppState → jarvisd allowlist.
// Refreshes on appear, on pull, and every 15 s while the tab is open.

struct SystemView: View {
    @EnvironmentObject var app: AppState

    @State private var stopTarget: String?
    @State private var busyService: String?

    private let pollInterval: Duration = .seconds(15)

    var body: some View {
        NavigationStack {
            Group {
                if app.connectionState == .connecting {
                    connecting
                } else if app.connectionState != .connected {
                    notConnected
                } else {
                    content
                }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("System")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await refresh() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh services")
                }
            }
            .task { await pollLoop() }            .confirmationDialog(
                "Stop \(stopTarget.map(JarvisFormat.displayName) ?? "")?",
                isPresented: Binding(
                    get: { stopTarget != nil },
                    set: { if !$0 { stopTarget = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button("Stop service", role: .destructive) {
                    if let name = stopTarget {
                        Task { await perform(name, "stop") }
                    }
                    stopTarget = nil
                }
                Button("Cancel", role: .cancel) { stopTarget = nil }
            } message: {
                Text("This stops the service now. You can start it again from here.")
            }
        }
    }

    // MARK: - Content

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

    private var content: some View {
        ScrollView {
            VStack(spacing: 16) {
                if app.lastServices.isEmpty {
                    Card {
                        HStack(spacing: 12) {
                            ProgressView()
                            Text("Loading services…")
                                .foregroundStyle(.secondary)
                        }
                    }
                } else {
                    ForEach(serviceNames, id: \.self) { name in
                        if let svc = app.lastServices[name] {
                            serviceCard(name: name, svc: svc)
                        }
                    }
                }
                daemonCard
            }
            .padding(.horizontal)
            .padding(.bottom, 8)
        }
        .refreshable { await refresh() }
    }

    private var serviceNames: [String] {
        app.lastServices.keys.sorted()
    }

    @ViewBuilder
    private func serviceCard(name: String, svc: ServiceActionResult) -> some View {
        let isRunning = svc.running ?? false
        let isBusy = busyService == name
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 10) {
                    Circle()
                        .fill(isRunning ? Color.green : Color.secondary)
                        .frame(width: 10, height: 10)
                    Text(JarvisFormat.displayName(name))
                        .font(.headline)
                    Spacer()
                    Text(isRunning ? "Running" : "Stopped")
                        .font(.subheadline)
                        .foregroundStyle(isRunning ? .green : .secondary)
                }
                if let desc = svc.description, !desc.isEmpty {
                    Text(desc)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                if isRunning, let pid = svc.pid {
                    Text("PID \(pid)")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                HStack(spacing: 12) {
                    if isRunning {
                        Button(role: .destructive) {
                            stopTarget = name
                        } label: {
                            Label("Stop", systemImage: "stop.fill")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(isBusy)
                    } else {
                        Button {
                            Task { await perform(name, "start") }
                        } label: {
                            Label("Start", systemImage: "play.fill")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isBusy)
                    }
                    Button {
                        Task { await perform(name, "restart") }
                    } label: {
                        Label("Restart", systemImage: "arrow.clockwise")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(isBusy)
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var daemonCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                Label("jarvisd", systemImage: "gearshape.2")
                    .font(.headline)
                if let version = app.lastHealth?.version {
                    LabeledContent("Version", value: version)
                        .font(.subheadline)
                }
                if let up = app.lastHealth?.uptimeSeconds {
                    LabeledContent("Uptime", value: JarvisFormat.uptime(up))
                        .font(.subheadline)
                }
                if app.lastHealth == nil {
                    Text("Daemon info unavailable.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
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
                    Text("Connect from the Settings tab to manage services.")
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

    // MARK: - Actions

    private func refresh() async {
        await app.fetchServices()
        await app.fetchHealth()
    }

    private func perform(_ name: String, _ action: String) async {
        busyService = name
        defer { busyService = nil }
        await app.runServiceAction(name, action)
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: pollInterval)
        }
    }
}

#Preview {
    SystemView().environmentObject(AppState())
}
