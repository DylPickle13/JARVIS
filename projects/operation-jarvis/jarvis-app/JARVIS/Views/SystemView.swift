import SwiftUI
import JARVISKit

struct SystemView: View {
    @EnvironmentObject var app: AppState
    @State private var stopTarget: String?

    var body: some View {
        NavigationStack {
            Group {
                if app.connectionState == .connecting {
                    connecting
                } else if app.connectionState != .connected {
                    notConnected
                } else if !app.servicesLoaded && app.servicesLoading {
                    loading
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
                    .disabled(app.servicesLoading || app.connectionState != .connected)
                }
            }
            .confirmationDialog(
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

    private var connecting: some View {
        VStack { loadingCard("Connecting to jarvisd…"); Spacer() }
            .padding(.horizontal)
    }

    private var loading: some View {
        VStack { loadingCard("Loading services…"); Spacer() }
            .padding(.horizontal)
    }

    private func loadingCard(_ text: String) -> some View {
        Card {
            HStack(spacing: 12) {
                ProgressView()
                Text(text).foregroundStyle(.secondary)
            }
        }
    }

    private var content: some View {
        ScrollView {
            VStack(spacing: 16) {
                if let error = app.servicesErrorMessage {
                    OperationErrorCard(message: error)
                }
                if let error = app.operationErrorMessage {
                    OperationErrorCard(message: error)
                }
                if app.servicesLoaded && app.lastServices.isEmpty {
                    Card { Text("No registered services.").foregroundStyle(.secondary) }
                } else {
                    ForEach(serviceNames, id: \.self) { name in
                        if let service = app.lastServices[name] {
                            serviceCard(name: name, service: service)
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

    private var serviceNames: [String] { app.lastServices.keys.sorted() }

    @ViewBuilder
    private func serviceCard(name: String, service: ServiceActionResult) -> some View {
        let isKnown = service.ok
        let isLoaded = service.loaded ?? service.running != nil
        let isRunning = service.running == true
        let busy = app.isOperationBusy("service:\(name)")
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 10) {
                    Circle()
                        .fill(!isKnown ? Color.orange : (isRunning ? Color.green : Color.secondary))
                        .frame(width: 10, height: 10)
                    Text(JarvisFormat.displayName(name)).font(.headline)
                    Spacer()
                    Text(!isKnown ? "Unknown" : (isRunning ? "Running" : (isLoaded ? "Stopped" : "Unloaded")))
                        .font(.subheadline)
                        .foregroundStyle(!isKnown ? .orange : (isRunning ? .green : .secondary))
                }
                if let description = service.description, !description.isEmpty {
                    Text(description).font(.subheadline).foregroundStyle(.secondary)
                }
                if isRunning, let pid = service.pid {
                    Text("PID \(pid)").font(.caption).foregroundStyle(.tertiary)
                } else if !isKnown, let error = service.error {
                    Text(error).font(.caption).foregroundStyle(.orange)
                }
                HStack(spacing: 12) {
                    if isRunning {
                        Button(role: .destructive) { stopTarget = name } label: {
                            Label("Stop", systemImage: "stop.fill").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(busy)
                    } else {
                        Button { Task { await perform(name, "start") } } label: {
                            Label("Start", systemImage: "play.fill").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(busy || !isKnown)
                    }
                    Button { Task { await perform(name, "restart") } } label: {
                        Label("Restart", systemImage: "arrow.clockwise").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(busy || !isKnown)
                }
                if busy {
                    ProgressView("Applying action…")
                        .font(.caption)
                        .accessibilityLabel("Applying service action")
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    private var daemonCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                Label("jarvisd", systemImage: "gearshape.2").font(.headline)
                if let version = app.lastHealth?.version {
                    LabeledContent("Version", value: version).font(.subheadline)
                }
                if let uptime = app.lastHealth?.uptimeSeconds {
                    LabeledContent("Uptime", value: JarvisFormat.uptime(uptime)).font(.subheadline)
                }
                if app.lastHealth == nil {
                    Text("Daemon info unavailable.").font(.subheadline).foregroundStyle(.secondary)
                }
            }
        }
    }

    private var notConnected: some View {
        VStack {
            Card {
                VStack(spacing: 12) {
                    Image(systemName: "wifi.slash").font(.system(size: 34)).foregroundStyle(.secondary)
                    Text("Not connected").font(.headline)
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

    private func refresh() async {
        await app.fetchServices()
        await app.fetchHealth()
    }

    private func perform(_ name: String, _ action: String) async {
        _ = await app.runServiceAction(name, action)
    }
}

#Preview {
    SystemView().environmentObject(AppState())
}
