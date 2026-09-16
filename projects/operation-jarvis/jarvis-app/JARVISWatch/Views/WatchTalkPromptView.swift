import SwiftUI
import JARVISKit

/// A face tap only opens this composer. Send is the sole submission boundary.
struct WatchTalkPromptView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var prompt = ""
    @State private var sending = false
    @State private var message: String?
    @State private var submissionUnconfirmed = false
    let onSent: (JARVISTerminalSlot) -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("What would you like to send?")
                        .font(.headline)
                    // watchOS supplies its native keyboard/dictation editor.
                    TextField("Prompt", text: $prompt)
                        .accessibilityLabel("Prompt to JARVIS")
                        .disabled(sending || submissionUnconfirmed)
                    if let message {
                        Text(message)
                            .font(.caption)
                            .accessibilityLabel("Submission status: \(message)")
                    }
                    Button(action: send) {
                        if sending {
                            ProgressView("Sending…")
                        } else {
                            Label("Send", systemImage: "paperplane.fill")
                        }
                    }
                    .disabled(sending || submissionUnconfirmed || prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Button(submissionUnconfirmed ? "Close" : "Cancel") { dismiss() }
                        .disabled(sending)
                }
                .padding()
            }
            .navigationTitle("Talk to JARVIS")
        }
        .interactiveDismissDisabled(sending)
    }

    private func send() {
        guard !sending, !submissionUnconfirmed else { return }
        sending = true
        message = nil
        let value = prompt
        // Never retry automatically: an ambiguous network result may have sent.
        Task { @MainActor in
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
}
