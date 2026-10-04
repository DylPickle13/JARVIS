import Foundation

/// Explicit Pi metadata only; never infer a topic from a slot, prompt or tmux ID.
public enum PiSessionName {
    public static let maximumCharacters = 256

    public static func validated(_ value: String?) -> String? {
        guard let value else { return nil }
        for scalar in value.unicodeScalars {
            switch scalar.properties.generalCategory {
            case .control, .lineSeparator, .paragraphSeparator: return nil
            default: break
            }
            let code = scalar.value
            if (0x202A...0x202E).contains(code) || (0x2066...0x2069).contains(code)
                || [0x061C, 0x200E, 0x200F].contains(code) { return nil }
        }
        let name = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.unicodeScalars.count <= maximumCharacters else { return nil }
        return name
    }

    public static func cardTitle(name: String?, lifecycle: PiSessionLifecycle) -> String {
        validated(name) ?? (lifecycle == .new ? "New session" : "Unnamed session")
    }
}
