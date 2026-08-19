import SwiftUI
import JARVISKit

// M0 watch connect view: proves the watch can reach jarvisd directly (LAN at
// home) and render a snapshot. The full Glance/Controls UI and the
// relay-through-iPhone path (away from home) land in M3/M4.
struct WatchConnectView: View {
    @StateObject private var model = WatchConnectModel()

    var body: some View {
        VStack(spacing: 10) {
            // Connection dot + label.
            HStack(spacing: 6) {
                Circle()
                    .fill(model.dotColor)
                    .frame(width: 10, height: 10)
                Text(model.statusText)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 4)

            if let s = model.lastState?.summary {
                statsGrid(s)
            } else {
                if model.connectionState == .connecting {
                    ProgressView()
                } else {
                    Text(model.errorMessage ?? "Not connected")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
            }

            Spacer(minLength: 4)

            Button {
                Task { await model.connect() }
            } label: {
                Label(model.connectionState == .connecting ? "…" : "Connect",
                      systemImage: "link")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.plain)
            .background(Color.accentColor.opacity(0.15), in: Capsule())
            .tint(Color.accentColor)
            .disabled(model.connectionState == .connecting)
        }
        .padding(12)
        .task { await model.refreshIfConfigured() }
    }

    private func statsGrid(_ s: Summary) -> some View {
        Grid(horizontalSpacing: 14, verticalSpacing: 8) {
            GridRow {
                stat("Plugs", "\(s.plugsOn ?? 0)/\(s.plugsTotal ?? 0)", "powerplug.fill")
                stat("Purifier", s.purifierOn == true ? "on" : "off", "fanblades")
            }
            GridRow {
                stat("PM2.5", s.pm25.map { "\($0)" } ?? "—", "aqi.medium")
                stat("Pi", "\(s.piActive ?? 0)", "cpu")
            }
        }
    }

    private func stat(_ label: String, _ value: String, _ symbol: String) -> some View {
        VStack(spacing: 2) {
            Image(systemName: symbol)
                .font(.caption)
                .foregroundStyle(Color.accentColor)
            Text(value)
                .font(.title3.weight(.bold))
                .monospacedDigit()
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

@MainActor
final class WatchConnectModel: ObservableObject {
    @Published var connectionState: ConnectionState = .idle
    @Published var errorMessage: String?
    @Published var lastState: StateSnapshot?

    let store = EndpointStore()
    let client = JarvisClient()

    var dotColor: Color {
        switch connectionState {
        case .connected: return .green
        case .failed: return .red
        case .connecting: return .orange
        case .idle: return .secondary
        }
    }

    var statusText: String {
        switch connectionState {
        case .connected: return "Connected"
        case .failed: return "Offline"
        case .connecting: return "Connecting"
        case .idle: return "Idle"
        }
    }

    func refreshIfConfigured() async {
        // Auto-discover (home LAN / Tailscale) — no saved endpoint required.
        await refresh()
    }

    func connect() async {
        await refresh()
    }

    func refresh() async {
        connectionState = .connecting
        errorMessage = nil

        // Candidate list: saved endpoint first (if any), then the defaults.
        let candidates = JarvisEndpoints.candidates(override: store.endpointURL)
        guard let discovered = await client.discover(candidates) else {
            lastState = nil
            connectionState = .failed
            errorMessage = "Unreachable (tried \(candidates.count))"
            return
        }
        store.endpointURLString = discovered.absoluteString
        let endpoint = JarvisEndpoint(baseURL: discovered, token: store.token ?? "")
        do {
            _ = try await client.health(endpoint)
            lastState = try await client.state(endpoint)
            connectionState = .connected
        } catch let e as JarvisError {
            connectionState = .failed
            errorMessage = e.errorDescription
        } catch {
            connectionState = .failed
            errorMessage = error.localizedDescription
        }
    }
}

#Preview {
    WatchConnectView()
}
