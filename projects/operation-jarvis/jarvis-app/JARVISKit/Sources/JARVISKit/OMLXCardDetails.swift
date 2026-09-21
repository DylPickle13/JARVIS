import Foundation

/// Static presentation from fresh activity. No timers, scrolling, inferred
/// progress, or combined request speeds. Full identities remain in VoiceOver.
public struct OMLXCardDetails: Equatable, Sendable {
    public let modelNames: [String]
    public let modelLabel: String
    public let speed: Double?
    public let activeRequests: Int?
    public let queuedRequests: Int?

    public init(server: OMLXServerStatus) {
        let models = (server.models ?? []).sorted { $0.id < $1.id }
        modelNames = models.map(\.id)
        activeRequests = Self.total(models.map(\.activeRequests))
        queuedRequests = Self.total(models.map(\.queuedRequests))
        let busy = models.filter { $0.phase != .ready }
        let requests = models.flatMap(\.requests).filter { $0.phase != .queued }
        let request = activeRequests == 1 && requests.count == 1 ? requests.first : nil
        speed = server.phase == .generating ? request?.tokensPerSecond.flatMap {
            $0.isFinite && $0 > 0 ? $0 : nil
        } : nil
        if busy.count > 1 || (activeRequests ?? 0) > 1 || requests.count > 1 {
            modelLabel = "Multi"
        } else if let model = busy.first ?? models.first {
            let suffix = models.count > 1 ? " +\(models.count - 1)" : ""
            modelLabel = Self.shortName(model.id) + suffix
        } else {
            modelLabel = "No models"
        }
    }

    /// Drop publisher/quantization chatter; retain the family/version and full
    /// parameter count. Unknown families retain their name rather than guessing.
    public static func shortName(_ id: String) -> String {
        let name = String(id.split(separator: "/").last ?? Substring(id))
            .replacingOccurrences(of: "_", with: "-")
        var label = name
        if let range = name.range(of: #"(?i)^.*?-\d+(?:\.\d+)?[BM](?=$|-)"#, options: .regularExpression) {
            label = String(name[range])
        } else {
            label = label.replacingOccurrences(of: #"(?i)-(?:\d+bit|[qu]\d+(?:-[a-z0-9]+)?|bf16|fp16|mlx)$"#,
                                               with: "", options: .regularExpression)
        }
        return label.replacingOccurrences(of: #"(?i)^Qwen(?=\d)"#, with: "Q", options: .regularExpression)
    }

    public var speedText: String {
        guard let speed else { return "—" }
        if speed >= 1000 { return speed.formatted(.number.notation(.compactName).precision(.fractionLength(0...1))) }
        return speed.formatted(.number.precision(.fractionLength(0)))
    }

    public var accessibilityValue: String {
        let names = modelNames.isEmpty ? "No models loaded" : "Models: " + modelNames.joined(separator: ", ")
        let rate = speed.map { "Average generation speed \($0.formatted()) tokens per second" } ?? "Generation speed unavailable"
        return [names, rate,
                "Active requests \(activeRequests.map(String.init) ?? "unavailable")",
                "Queued requests \(queuedRequests.map(String.init) ?? "unavailable")"].joined(separator: ". ")
    }

    private static func total(_ values: [Int]) -> Int? {
        guard values.allSatisfy({ $0 >= 0 }) else { return nil }
        return values.reduce(0) { sum, value in
            let (result, overflow) = sum.addingReportingOverflow(value)
            return overflow ? Int.max : result
        }
    }
}
