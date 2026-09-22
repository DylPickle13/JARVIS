import Foundation
import Combine

/// iPhone-only maintenance state. Never exported through WatchConnectivity.
@MainActor
final class PiSessionMaintenanceController: ObservableObject {
    @Published private(set) var isWorking = false
    @Published private(set) var message: String?
    @Published private(set) var completed = 0
    @Published private(set) var operationID: String?
    @Published private(set) var canRetrySubmission = false

    private static let pendingKey = "jarvis.pi-maintenance.pending-operation"
    private static let hostKey = "jarvis.pi-maintenance.pending-host"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        operationID = defaults.string(forKey: Self.pendingKey)
        if operationID != nil {
            message = "A previous restart needs a status check. It may have continued on the Mac."
        }
    }

    func run(configuration: PiTerminalConfiguration, trustedHostKey: String?, start: Bool,
             onSuccess: @escaping @MainActor () -> Void) {
        guard !isWorking else { return }
        let host = "\(configuration.username)@\(configuration.host.lowercased()):\(configuration.port)"
        if operationID != nil, defaults.string(forKey: Self.hostKey) != host {
            message = "Reconnect to the original SSH host to check the pending restart."
            return
        }
        guard trustedHostKey?.isEmpty == false else {
            message = "Connect and trust the Mac in Pi Terminal before restarting sessions."
            return
        }
        let identifier = operationID ?? UUID().uuidString.lowercased()
        operationID = identifier
        defaults.set(identifier, forKey: Self.pendingKey)
        defaults.set(host, forKey: Self.hostKey)
        isWorking = true
        canRetrySubmission = false
        message = start ? "Requesting restart…" : "Checking restart status…"
        Task {
            defer { isWorking = false }
            do {
                let transport = PiMaintenanceSSHTransport()
                var action = start ? "start" : "status"
                // Bound foreground polling; the host worker continues independently.
                for _ in 0..<180 {
                    let result = try await transport.send(
                        action: action, operationID: identifier,
                        configuration: configuration, trustedHostKey: trustedHostKey)
                    guard result.operationID == identifier,
                          (0...10).contains(result.completed) else {
                        throw MaintenanceError.invalidResponse
                    }
                    completed = result.completed
                    message = result.message
                    switch result.state {
                    case "queued", "running":
                        message = "Restarting sessions… \(completed)/10"
                    case "succeeded":
                        guard completed == 10 else { throw MaintenanceError.invalidResponse }
                        clearPending()
                        onSuccess()
                        return
                    case "failed":
                        message = "Restart stopped after \(completed)/10 sessions. \(result.message)"
                        clearPending()
                        return
                    case "notFound":
                        canRetrySubmission = true
                        return
                    case "unknown":
                        return
                    default:
                        throw MaintenanceError.invalidResponse
                    }
                    action = "status"
                    try await Task.sleep(for: .seconds(2))
                }
                message = "The restart may still be running on the Mac. Check status before trying again."
            } catch {
                message = "Could not confirm restart status: \(error.localizedDescription) The Mac may still be working; check status before restarting again."
            }
        }
    }

    private func clearPending() {
        operationID = nil
        defaults.removeObject(forKey: Self.pendingKey)
        defaults.removeObject(forKey: Self.hostKey)
    }

    private enum MaintenanceError: LocalizedError {
        case invalidResponse
        var errorDescription: String? { "The Mac returned an invalid maintenance response." }
    }
}
