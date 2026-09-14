import SwiftUI

/// A plain toolbar action, not an invisible/modified UIPasteControl. The explicit
/// tap uses the same permission-respecting, session-bound paste path as Cmd-V.
struct PiTerminalPasteControl: View {
    let paste: () -> Void

    var body: some View {
        Button(action: paste) {
            Image(systemName: "doc.on.clipboard")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(JarvisPalette.accent)
                .frame(width: 46, height: 46)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Paste into terminal")
        .accessibilityHint("Paste clipboard text without pressing Enter")
    }
}
