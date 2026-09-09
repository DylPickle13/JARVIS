import SwiftUI

public enum OMLXFormat {
    public static let warning = Color(red: 0.96, green: 0.58, blue: 0.16)
    public static func tone(_ phase: OMLXPhase) -> Color {
        switch phase {
        case .generating, .processing: return .green
        case .prefill: return .blue
        case .loading, .queued: return OMLXFormat.warning
        case .ready: return .secondary
        case .unknown: return OMLXFormat.warning
        }
    }
    public static func duration(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0, seconds < Double(Int.max) else { return "—" }
        if seconds < 60 { return "\(Int(seconds))s" }
        if seconds < 3600 { return "\(Int(seconds / 60))m \(Int(seconds.truncatingRemainder(dividingBy: 60)))s" }
        return "\(Int(seconds / 3600))h \(Int(seconds.truncatingRemainder(dividingBy: 3600) / 60))m"
    }
    public static func bytes(_ bytes: Double) -> String {
        guard bytes.isFinite, bytes >= 0 else { return "—" }
        return (bytes / 1_073_741_824).formatted(.number.precision(.fractionLength(1))) + " GiB"
    }
    public static func metrics(_ request: OMLXRequestStatus) -> String {
        var parts: [String] = []
        if request.phase == .prefill, let done = request.processedTokens, let total = request.totalTokens, done >= 0, total > 0 {
            parts.append("\(done.formatted()) / \(total.formatted()) tokens")
        }
        if request.phase == .generating, let tokens = request.generatedTokens, tokens >= 0 {
            parts.append("\(tokens.formatted()) tokens")
        }
        if [.generating, .prefill].contains(request.phase), let speed = request.tokensPerSecond, speed.isFinite, speed > 0 {
            parts.append(speed.formatted(.number.precision(.fractionLength(1))) + (request.phase == .generating ? " tok/s avg" : " tok/s"))
        }
        if let elapsed = request.elapsedSeconds { parts.append(duration(elapsed)) }
        if let age = request.lastActivityAgeSeconds, age >= 3 { parts.append("Last activity \(duration(age)) ago") }
        return parts.isEmpty ? "Metrics unavailable" : parts.joined(separator: " · ")
    }
}

private extension View {
    @ViewBuilder func omlxTextSelection() -> some View {
        #if os(watchOS)
        self
        #else
        self.textSelection(.enabled)
        #endif
    }
}
