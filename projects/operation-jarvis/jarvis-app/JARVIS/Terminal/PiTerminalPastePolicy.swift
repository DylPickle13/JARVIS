import Foundation

/// Pure text policy. Only an explicit user paste may reach this path.
enum PiTerminalPastePolicy {
    static let maximumUTF8Bytes = 64 * 1024

    enum Failure: Error, Equatable, LocalizedError {
        case empty, tooLarge, controlCharacters, requiresSingleLine
        var errorDescription: String? {
            switch self {
            case .empty: return "The clipboard does not contain text."
            case .tooLarge: return "Paste is limited to 64 KiB of text."
            case .controlCharacters: return "This text contains terminal control characters and cannot be pasted safely."
            case .requiresSingleLine: return "This terminal does not support safe multiline paste. Paste as one line instead."
            }
        }
    }

    static func normalized(_ text: String) throws -> String {
        guard !text.isEmpty else { throw Failure.empty }
        guard text.utf8.count <= maximumUTF8Bytes else { throw Failure.tooLarge }
        guard !text.unicodeScalars.contains(where: {
            ($0.value < 32 && ![9, 10, 13].contains($0.value)) || (127...159).contains($0.value)
        }) else { throw Failure.controlCharacters }
        return text.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
    }

    static func needsReview(_ text: String) -> Bool { text.contains("\n") || text.contains("\t") }

    static func bytes(_ text: String, bracketed: Bool, singleLine: Bool = false) throws -> [UInt8] {
        var value = try normalized(text)
        if singleLine { value = value.replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "\t", with: " ") }
        guard bracketed || !needsReview(value) else { throw Failure.requiresSingleLine }
        // Reject ESC above even in bracketed mode: pasted text cannot inject an end delimiter.
        return Array((bracketed ? "\u{1b}[200~" + value + "\u{1b}[201~" : value).utf8)
    }
}

struct PiTerminalPasteReview: Identifiable {
    let id: UUID
    let preview: String
    let supportsMultiline: Bool
}
