import AppIntents
import Foundation
import JARVISKit

struct SendPromptToJARVISIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to JARVIS"
    static let description = IntentDescription("Send a spoken prompt to the active JARVIS Pi session.")
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

    /// One normalized prompt and one Return are attempted exactly once. The
    /// value question above is the only app-provided dialogue; completion and
    /// failure results are deliberately silent.
    func perform() async throws -> some IntentResult {
        let outcome = await JARVISSiriPromptRuntime.submit(prompt)
        guard outcome == .sent else { return .result() }

        JARVISSiriNavigation.requestTerminalPresentation()
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
        JARVISSiriNavigation.requestTerminalPresentation()
        return .result()
    }
}
#endif

enum JARVISSiriNavigation {
    static let terminalRequestNotification = Notification.Name("com.operation-jarvis.siri-terminal-requested")
    static let terminalURL = URL(string: "jarvis://terminal")!
    private static let terminalRequestKey = "jarvis.siri-terminal-requested"

    static func isTerminalURL(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "jarvis" else { return false }
        return url.host?.lowercased() == "terminal"
    }

    static func requestTerminalPresentation(
        defaults: UserDefaults = .standard,
        notificationCenter: NotificationCenter = .default
    ) {
        defaults.set(true, forKey: terminalRequestKey)
        notificationCenter.post(name: terminalRequestNotification, object: nil)
    }

    @discardableResult
    static func consumeTerminalPresentationRequest(defaults: UserDefaults = .standard) -> Bool {
        guard defaults.bool(forKey: terminalRequestKey) else { return false }
        defaults.removeObject(forKey: terminalRequestKey)
        return true
    }
}

enum JARVISSiriPromptOutcome: Equatable {
    case sent
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
    typealias SlotLoader = () -> JARVISTerminalSlot
    typealias Delivery = (WatchTerminalConfiguration, JARVISTerminalSlot, WatchTerminalInput) async throws -> Void

    static func submit(
        _ rawPrompt: String,
        configurationLoader: ConfigurationLoader = { JARVISTerminalConfigurationStore.load() },
        slotLoader: SlotLoader = { JARVISTerminalSlot.load() },
        delivery: Delivery = { configuration, slot, input in
            let client = WatchTerminalClient(configuration: configuration)
            defer { client.close() }
            _ = try await client.preflight(slot: slot)
            try await client.send(input)
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
            // UserDefaults.standard is device-local: iPhone Siri follows the
            // last iPhone slot while Watch Siri follows the last Watch slot.
            let slot = slotLoader()
            let input = WatchTerminalInput(
                session: slot,
                data: Data(normalized.utf8),
                appendReturn: true
            )
            try await delivery(configuration, slot, input)
            return .sent
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
