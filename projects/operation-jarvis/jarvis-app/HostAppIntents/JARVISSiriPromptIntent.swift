import AppIntents
import Foundation
import JARVISKit

struct SendPromptToJARVISIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to JARVIS"
    static let description = IntentDescription("Send a spoken prompt to the active JARVIS Pi session.")
    static var openAppWhenRun: Bool { false }

    @Parameter(
        title: "Prompt",
        requestValueDialog: IntentDialog("What would you like me to send to JARVIS?")
    )
    var prompt: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        switch await JARVISSiriPromptRuntime.submit(prompt) {
        case .sent:
            return .result(dialog: IntentDialog("Sent to JARVIS."))
        case .empty:
            return .result(dialog: IntentDialog("I didn’t hear a prompt."))
        case .invalidControls:
            return .result(dialog: IntentDialog("That prompt contains unsupported characters."))
        case .tooLong:
            return .result(dialog: IntentDialog("That prompt is too long for JARVIS."))
        case .notProvisioned:
            return .result(dialog: IntentDialog("Open JARVIS Settings and set up the terminal first."))
        case .locked:
            return .result(dialog: IntentDialog("Unlock this device and try again."))
        case .offline:
            return .result(dialog: IntentDialog("The JARVIS terminal is offline."))
        case .identityMismatch:
            return .result(dialog: IntentDialog("The JARVIS terminal identity could not be verified."))
        case .rejected:
            return .result(dialog: IntentDialog("JARVIS did not accept the prompt."))
        case .unconfirmed:
            return .result(dialog: IntentDialog("Send was not confirmed; check JARVIS."))
        }
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
    typealias Delivery = (WatchTerminalConfiguration, WatchTerminalInput) async throws -> Void

    static func submit(
        _ rawPrompt: String,
        configurationLoader: ConfigurationLoader = { JARVISTerminalConfigurationStore.load() },
        delivery: Delivery = { configuration, input in
            let client = WatchTerminalClient(configuration: configuration)
            defer { client.close() }
            _ = try await client.preflight()
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
            let input = WatchTerminalInput(data: Data(normalized.utf8), appendReturn: true)
            try await delivery(configuration, input)
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
