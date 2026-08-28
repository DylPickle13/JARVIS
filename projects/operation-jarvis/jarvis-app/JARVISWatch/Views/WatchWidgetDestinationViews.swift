import AppIntents
import SwiftUI
import WatchKit
import JARVISKit

struct JARVISWatchWidgetDestinationSheet: View {
    let destination: JARVISWatchWidgetDestination
    let openTerminal: () -> Void

    @ViewBuilder
    var body: some View {
        switch destination {
        case .quickActions:
            JARVISWatchQuickActionsView(openTerminal: openTerminal)
        case .nowPlaying:
            // Apple's public system surface controls the current audio source,
            // including Spotify, without attempting an unsupported app launch.
            NowPlayingView()
        }
    }
}

private struct JARVISWatchQuickActionsView: View {
    @Environment(\.dismiss) private var dismiss
    let openTerminal: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            Label("JARVIS Shortcuts", systemImage: "square.grid.2x2.fill")
                .font(.headline)
                .lineLimit(1)

            Button(intent: SendPromptToJARVISIntent()) {
                Label("Talk to JARVIS", systemImage: "waveform")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)

            Button {
                dismiss()
                openTerminal()
            } label: {
                Label("Pi Terminal", systemImage: "terminal")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
        }
        .padding(.horizontal, 8)
        .accessibilityElement(children: .contain)
    }
}
