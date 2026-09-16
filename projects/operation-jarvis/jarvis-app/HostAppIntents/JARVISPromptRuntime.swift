import Foundation
import JARVISKit

enum JARVISPromptNavigation {
    // Keep persisted routing keys compatible with existing installations.
    static let terminalRequestNotification = Notification.Name("com.operation-jarvis.siri-terminal-requested")
    static let terminalURL = URL(string: "jarvis://terminal")!
    private static let terminalRequestKey = "jarvis.siri-new-terminal-slot-requested"

    static func isTalkURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "jarvis" && url.host?.lowercased() == "talk"
    }

    static func isTerminalURL(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "jarvis" else { return false }
        return url.host?.lowercased() == "terminal"
    }

    @MainActor
    static func requestTerminalPresentation(
        slot: JARVISTerminalSlot,
        defaults: UserDefaults = .standard,
        notificationCenter: NotificationCenter = .default
    ) {
        defaults.set(slot.rawValue, forKey: terminalRequestKey)
        notificationCenter.post(name: terminalRequestNotification, object: nil)
    }

    @discardableResult
    @MainActor
    static func consumeTerminalPresentationRequest(
        defaults: UserDefaults = .standard,
        select: (JARVISTerminalSlot) -> Bool
    ) -> Bool {
        guard let slot = JARVISTerminalSlot(rawValue: defaults.integer(forKey: terminalRequestKey)),
              select(slot) else { return false } // retain request while a picker/input operation blocks navigation
        defaults.removeObject(forKey: terminalRequestKey)
        return true
    }
}

enum JARVISPromptOutcome: Equatable {
    case sent(JARVISTerminalSlot)
    case noNewSession
    case empty
    case invalidControls
    case tooLong
    case notProvisioned
    case locked
    case offline
    case identityMismatch
    case rejected
    case unconfirmed
}

enum JARVISPromptRuntime {
    typealias ConfigurationLoader = () -> JARVISTerminalConfigurationLoadResult
    typealias Delivery = (WatchTerminalConfiguration, String) async throws -> JARVISTerminalSlot

    static func submit(
        _ rawPrompt: String,
        configurationLoader: ConfigurationLoader = { JARVISTerminalConfigurationStore.load() },
        delivery: Delivery = { configuration, prompt in
            let client = WatchTerminalClient(configuration: configuration)
            defer { client.close() }
            try await client.preflightNewSessionPrompt()
            return try await client.sendToNewSession(prompt)
        }
    ) async -> JARVISPromptOutcome {
        let normalized: String
        do {
            normalized = try JARVISSpokenPrompt.normalize(rawPrompt)
        } catch JARVISSpokenPromptError.empty {
            return .empty
        } catch JARVISSpokenPromptError.containsControlCharacters {
            return .invalidControls
        } catch JARVISSpokenPromptError.tooLong {
            return .tooLong
        } catch {
            return .invalidControls
        }

        let configuration: WatchTerminalConfiguration
        switch configurationLoader() {
        case .configured(let value):
            configuration = value
        case .missing, .invalid:
            return .notProvisioned
        case .locked:
            return .locked
        }

        do {
            let slot = try await delivery(configuration, normalized)
            return .sent(slot)
        } catch JARVISNewSessionError.noAvailableSession {
            return .noNewSession
        } catch WatchTerminalClientError.certificateRejected {
            return .identityMismatch
        } catch WatchTerminalClientError.rejected(_) {
            return .rejected
        } catch WatchTerminalClientError.submissionUnconfirmed {
            return .unconfirmed
        } catch is CancellationError {
            return .unconfirmed
        } catch WatchTerminalClientError.notConnected {
            return .offline
        } catch WatchTerminalClientError.offline {
            return .offline
        } catch {
            return .offline
        }
    }
}

/// One native input presentation can authorize at most one submission.
/// Consume cancellation/empty results too, so duplicate callbacks cannot send.
struct JARVISTalkInputCompletion {
    private(set) var consumed = false

    mutating func consume(_ results: [Any]?) -> String? {
        guard !consumed else { return nil }
        consumed = true
        guard let value = results?.first as? String,
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return value
    }
}
