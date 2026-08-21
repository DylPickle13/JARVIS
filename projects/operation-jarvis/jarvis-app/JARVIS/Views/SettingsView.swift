import SwiftUI
import JARVISKit

// Settings tab — connection management + app info.
//
// Holds the endpoint override (advanced; blank = auto-detect), the Connect /
// Reset actions, the live status, and a small "About" block. This is the
// former M0 connect screen, now one of the four tabs.

struct SettingsView: View {
    @EnvironmentObject var app: AppState

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    settingsHero
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets())
                }
                connectionSection
                statusSection
                if app.connectionState == .failed, let error = app.errorMessage {
                    errorSection(error)
                }
                aboutSection
            }
            .scrollContentBackground(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle("Settings")
        }
    }

    private var settingsHero: some View {
        HStack(spacing: 14) {
            JARVISMark(size: 54)
            VStack(alignment: .leading, spacing: 3) {
                Text("JARVIS")
                    .font(.headline.weight(.bold))
                    .tracking(1.4)
                Text("Native control plane")
                    .font(.subheadline.weight(.semibold))
                Text(app.connectionState == .connected ? "Connected and ready" : "Connection and app preferences")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .background(JarvisPalette.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(JarvisPalette.cyan.opacity(0.16), lineWidth: 0.8)
        }
        .accessibilityElement(children: .combine)
    }

    // MARK: - Connection

    private var connectionSection: some View {
        Section {
            TextField("Endpoint (optional)", text: $app.endpointDraft, prompt: Text("auto-detect: LAN or Tailscale"))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .font(.body.monospaced())
                .padding(.vertical, 4)

            Button {
                Task { await app.connect() }
            } label: {
                HStack {
                    Spacer()
                    if app.connectionState == .connecting {
                        ProgressView().frame(width: 20)
                        Text("Connecting…")
                    } else {
                        Label("Connect", systemImage: "link")
                    }
                    Spacer()
                }
            }
            .disabled(app.connectionState == .connecting)

            Button(role: .destructive) {
                app.clearConnection()
            } label: {
                Label("Reset connection", systemImage: "arrow.counterclockwise")
                    .frame(maxWidth: .infinity)
            }
        } header: {
            Text("Connection")
        } footer: {
            Text("JARVIS finds the Mac automatically (home LAN or Tailscale) — no token needed. Leave the endpoint blank to auto-detect, or enter one to force it.")
        }
    }

    // MARK: - Status

    @ViewBuilder
    private var statusSection: some View {
        switch app.connectionState {
        case .connected: connectedStatus
        case .connecting: connectingStatus
        case .failed: failedStatus
        case .idle: idleStatus
        }
    }

    private var connectedStatus: some View {
        Section("Status") {
            statusBadgeRow
            if let uptime = app.lastHealth?.uptimeSeconds {
                LabeledContent("Uptime", value: JarvisFormat.uptime(uptime))
            }
            networkAndUsingRows
        }
    }

    private var statusBadgeRow: some View {
        LabeledContent("Status") {
            ConnectionBadge(state: .connected, detail: "jarvisd \(app.lastHealth?.version ?? "")")
        }
    }

    @ViewBuilder
    private var networkAndUsingRows: some View {
        if let net = app.lastState?.subsystems?.network {
            LabeledContent("LAN IP", value: net.macLanIp ?? "—")
            LabeledContent("Tailscale IP", value: net.tailscaleIp ?? "—")
        }
        if let using = usingString {
            LabeledContent("Using", value: using)
        }
    }

    private var usingString: String? {
        guard let ep = app.currentEndpoint, let host = ep.host else { return nil }
        let port = ep.port.map { "\($0)" } ?? "8790"
        return host + ":" + port
    }

    private var connectingStatus: some View {
        Section("Status") {
            HStack {
                ProgressView()
                Text("Connecting to jarvisd…")
            }
        }
    }

    private var failedStatus: some View {
        Section("Status") {
            LabeledContent("Status") { ConnectionBadge(state: .failed, detail: "offline") }
        }
    }

    private var idleStatus: some View {
        Section("Status") {
            LabeledContent("Status") { ConnectionBadge(state: .idle, detail: "not connected") }
        }
    }

    // MARK: - Error

    private func errorSection(_ message: String) -> some View {
        Section {
            Label {
                Text(message).font(.callout).foregroundStyle(.red)
            } icon: {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
            }
        } header: {
            Text("Error")
        }
    }

    // MARK: - About

    private var aboutSection: some View {
        Section("About") {
            LabeledContent("App", value: "JARVIS")
            LabeledContent("Daemon", value: "jarvisd \(app.lastHealth?.version ?? "—")")
            LabeledContent("Version", value: appVersion)
        }
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(v) (\(b))"
    }
}

#Preview {
    SettingsView().environmentObject(AppState())
}
