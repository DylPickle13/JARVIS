import SwiftUI
import WatchKit
import OSLog
import JARVISKit

/// Native Done confirms one submission. Cancellation and partial input never send.
struct WatchTalkPromptView: View {
    @Environment(\.scenePhase) private var scenePhase
    @State private var inputPresented = false
    @State private var completion = JARVISTalkInputCompletion()
    @State private var sending = false
    @State private var message: String?
    @State private var submissionUnconfirmed = false
    private let logger = Logger(subsystem: "com.operation-jarvis.jarvis.watchkitapp", category: "TalkInput")
    let onCancel: () -> Void
    let onSent: (JARVISTerminalSlot) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if sending {
                    ProgressView("Sending…")
                } else if let message {
                    Text(message).font(.caption)
                } else {
                    Text("Opening input…").font(.caption)
                }
                if !sending && !completion.consumed {
                    // Recovery only: the root-host automatic presentation is
                    // the normal route. This control can never submit partial input.
                    TextFieldLink("Open input", prompt: Text("What would you like to send?")) { value in
                        Task { @MainActor in await finishInput([value]) }
                    }
                    .disabled(!inputPresented)
                }
                Button(submissionUnconfirmed ? "Close" : "Cancel") {
                    _ = completion.consume(nil)
                    onCancel()
                }
                    .disabled(sending)
            }
            .padding()
        }
        .interactiveDismissDisabled(sending)
        .task(id: scenePhase) {
            guard scenePhase == .active, !inputPresented else { return }
            // This view is a root overlay, NOT a sheet or NavigationStack.
            // Allow the active host to settle before presenting native input.
            do { try await Task.sleep(for: .milliseconds(400)) }
            catch { return }
            guard !Task.isCancelled, !inputPresented else { return }
            guard let controller = WKApplication.shared().visibleInterfaceController else {
                inputPresented = true
                message = "Automatic input is unavailable. Tap Open input to continue."
                return
            }
            inputPresented = true
            logger.notice("Requesting native input from root host")
            controller.presentTextInputController(withSuggestions: nil, allowedInputMode: .plain) { results in
                Task { @MainActor in
                    await finishInput(results)
                }
            }
        }
    }

    @MainActor
    private func finishInput(_ results: [Any]?) async {
        guard !completion.consumed else { return }
        logger.notice("Native input completed; result present: \(results != nil)")
        guard let value = completion.consume(results) else {
            onCancel()
            return
        }
        sending = true
        message = nil
        // Preserve host-selected first-unused-slot admission. Never send to
        // the Watch's selected slot, and never automatically retry a failure.
        let outcome = await JARVISPromptRuntime.submit(value)
        sending = false
        switch outcome {
        case .sent(let slot):
            onSent(slot)
        case .noNewSession:
            message = "No unused New Pi session is available. Existing conversations were not changed."
        case .empty:
            message = "Enter a prompt first."
        case .invalidControls:
            message = "The prompt contains unsupported control characters."
        case .tooLong:
            message = "The prompt is too long. Shorten it and try again."
        case .notProvisioned:
            message = "Set up Watch terminal access in the iPhone JARVIS app first."
        case .locked:
            message = "Unlock your Watch to access terminal credentials."
        case .offline:
            message = "Could not connect to JARVIS. Check your connection."
        case .identityMismatch:
            message = "Server identity verification failed. Check terminal configuration."
        case .rejected:
            message = "JARVIS refused the prompt. Check terminal access and available sessions."
        case .unconfirmed:
            submissionUnconfirmed = true
            message = "Delivery is unconfirmed; the prompt may have been sent. Check your Pi sessions before sending again."
        }
    }
}
