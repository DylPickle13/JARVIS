import AppIntents
import Foundation
import JARVISKit

struct SendPromptToJARVISIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to JARVIS"
    static let description = IntentDescription("Send a spoken prompt to an unused New JARVIS Pi session, or refuse if none are available.")
    #if os(watchOS)
    static var openAppWhenRun: Bool { true }
    #else
    static var openAppWhenRun: Bool { false }
    #endif

    /// Siri resolves this required free-form value in a supported second turn.
    /// The user's answer authorizes one immediate, non-retried submission.
    @Parameter(
        title: "Prompt",
        requestValueDialog: IntentDialog("What would you like me to send to JARVIS?")
    )
    var prompt: String

    /// One normalized prompt is submitted exactly once to a host-selected New slot. The
    /// value question above is the only app-provided dialogue; completion and
    /// other failure results are deliberately silent. No capacity is an explicit refusal.
    func perform() async throws -> some IntentResult {
        let outcome = await JARVISSiriPromptRuntime.submit(prompt)
        if outcome == .noNewSession { throw JARVISNewSessionError.noAvailableSession }
        guard case .sent(let slot) = outcome else { return .result() }

        await JARVISSiriNavigation.requestTerminalPresentation(slot: slot)
        #if os(iOS)
        if #available(iOS 18.2, *) {
            return .result(opensIntent: OpenJARVISTerminalIntent(target: .terminal))
        }
        #endif
        return .result()
    }
}

#if os(iOS)
enum JARVISTerminalDestination: String, AppEnum {
    case terminal

    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "JARVIS Terminal")
    static let caseDisplayRepresentations: [Self: DisplayRepresentation] = [
        .terminal: DisplayRepresentation(title: "Pi Terminal")
    ]
}

/// OpenIntent is the supported custom-app handoff for this Siri flow. Unlike
/// OpenURLIntent, it does not require a public universal link.
struct OpenJARVISTerminalIntent: OpenIntent {
    static let title: LocalizedStringResource = "Open JARVIS Terminal"
    static var isDiscoverable: Bool { false }

    @Parameter(title: "Destination")
    var target: JARVISTerminalDestination

    init() {}

    init(target: JARVISTerminalDestination) {
        self.target = target
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        // The originating intent already persisted the exact destination. Do not
        // repost a last-selected-slot request after that destination was consumed.
        return .result()
    }
}
#endif

enum JARVISSiriNavigation {
    static let terminalRequestNotification = Notification.Name("com.operation-jarvis.siri-terminal-requested")
    static let terminalURL = URL(string: "jarvis://terminal")!
    private static let terminalRequestKey = "jarvis.siri-new-terminal-slot-requested"

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

enum JARVISSiriPromptOutcome: Equatable {
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

enum JARVISSiriPromptRuntime {
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
    ) async -> JARVISSiriPromptOutcome {
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
