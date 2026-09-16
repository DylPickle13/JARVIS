import SwiftUI
import WatchKit
import JARVISKit

/// watchOS resolves the universal link locally. No WatchConnectivity or phone fallback.
struct WatchSpotifyLauncherView: View {
    @Environment(\.scenePhase) private var scenePhase
    @State private var requested = false
    let onClose: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                Image(systemName: "music.note").font(.title)
                Text("Spotify").font(.headline)
                Text(requested
                     ? "If Spotify didn’t open, check that it’s installed on your Watch or use its own complication."
                     : "Opening Spotify on this Watch…")
                    .font(.caption)
                Button("Close", action: onClose)
            }
            .padding()
        }
        .task(id: scenePhase) {
            guard scenePhase == .active, !requested else { return }
            do { try await Task.sleep(for: .milliseconds(250)) }
            catch { return }
            guard !Task.isCancelled, !requested else { return }
            requested = true
            // This API has no success callback. Do not interpret an attempt,
            // or a scene transition, as verified launch of Spotify.
            WKApplication.shared().openSystemURL(JARVISWatchSpotifyRoute.destination)
        }
    }
}
