import Foundation

/// Presentation-only details from an already-fresh snapshot. No additional fetches,
/// persisted telemetry, inferred progress, or combined per-request token rates.
public struct OMLXCardDetails: Equatable, Sendable {
    public let modelNames: [String]
    public let speed: Double?
    public let generatedTokens: Int?
    public let prefillFraction: Double?
    public let activeRequests: Int?
    public let queuedRequests: Int?
    public let loadedModels: Int
    public let memoryUsed: Double?
    public let memoryLimit: Double?
    public let memoryKind: String
    public let pressure: String

    public init(server: OMLXServerStatus) {
        let models = server.models ?? []
        modelNames = models.map(\.id).sorted()
        activeRequests = Self.total(models.map(\.activeRequests))
        queuedRequests = Self.total(models.map(\.queuedRequests))
        loadedModels = models.filter { !$0.isLoading }.count
        let requests = models.flatMap(\.requests).filter { $0.phase != .queued }
        // Never pick an arbitrary request when the server reports concurrent work.
        let request = activeRequests == 1 && requests.count == 1 ? requests.first : nil
        speed = server.phase == .generating ? Self.nonnegative(request?.tokensPerSecond).flatMap { $0 > 0 ? $0 : nil } : nil
        generatedTokens = server.phase == .generating ? request?.generatedTokens.flatMap { $0 >= 0 ? $0 : nil } : nil
        prefillFraction = server.phase == .prefill ? request?.prefillFraction : nil
        memoryUsed = Self.nonnegative(server.memoryUsedBytes)
        memoryLimit = Self.nonnegative(server.memoryLimitBytes).flatMap { $0 > 0 ? $0 : nil }
        memoryKind = server.memoryKind == "process" ? "Process" : server.memoryKind == "models" ? "Models" : "Memory"
        switch server.memoryPressure {
        case "ok": pressure = "Normal"
        case "soft": pressure = "Soft"
        case "hard": pressure = "Hard"
        case "critical": pressure = "Critical"
        default: pressure = "—"
        }
    }

    public func modelName(at index: Int) -> String {
        guard !modelNames.isEmpty else { return "No models loaded" }
        return modelNames[max(0, index) % modelNames.count]
    }

    public func text(for page: OMLXDetailPage) -> String {
        switch page {
        case .models(let index): return modelName(at: index)
        case .activity:
            if let activeRequests, activeRequests > 1 { return "\(Self.count(activeRequests)) active requests" }
            return "\(speedText) t/s · \(Self.count(generatedTokens)) tok · \(prefillText) prefill"
        case .speed: return "\(speedText) t/s avg"
        case .tokens: return "\(Self.count(generatedTokens)) tokens"
        case .prefill: return prefillText
        case .load: return "\(Self.count(activeRequests)) active · \(Self.count(queuedRequests)) queued · \(Self.count(loadedModels)) loaded"
        case .active: return "\(Self.count(activeRequests)) active"
        case .queued: return "\(Self.count(queuedRequests)) queued"
        case .loaded: return "\(Self.count(loadedModels)) loaded"
        case .memory: return "\(Self.gib(memoryUsed)) / \(Self.gib(memoryLimit)) GiB · \(pressure)"
        case .used: return "\(Self.gib(memoryUsed)) GiB"
        case .limit: return "\(Self.gib(memoryLimit)) GiB"
        case .pressure: return pressure
        }
    }

    /// VoiceOver gets full names and unabridged counts without chasing timed pages.
    public var accessibilityValue: String {
        let names = modelNames.isEmpty ? "No models loaded" : "Models: " + modelNames.joined(separator: ", ")
        let rate = speed.map { "Average generation speed \($0.formatted()) tokens per second" } ?? "Generation speed unavailable"
        let tokens = generatedTokens.map { "\($0.formatted()) generated tokens" } ?? "Generated tokens unavailable"
        return [names, rate, tokens, "Prefill \(prefillText)",
                "Active requests \(activeRequests.map(String.init) ?? "unavailable")",
                "Queued requests \(queuedRequests.map(String.init) ?? "unavailable")",
                "\(loadedModels) loaded models", "\(memoryKind) memory used \(Self.gib(memoryUsed)) GiB",
                "Memory limit \(Self.gib(memoryLimit)) GiB", "Memory pressure \(pressure)"].joined(separator: ". ")
    }

    private var speedText: String { speed.map { Self.number($0) } ?? "—" }
    private var prefillText: String { prefillFraction.map { "\(Int($0 * 100))%" } ?? "—" }
    private static func nonnegative(_ value: Double?) -> Double? {
        value.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
    }
    private static func total(_ values: [Int]) -> Int? {
        guard values.allSatisfy({ $0 >= 0 }) else { return nil }
        return values.reduce(0) { sum, value in
            let (result, overflow) = sum.addingReportingOverflow(value)
            return overflow ? Int.max : result
        }
    }
    private static func count(_ value: Int?) -> String { value.map { number(Double($0)) } ?? "—" }
    private static func number(_ value: Double) -> String {
        if value >= 10_000 { return value.formatted(.number.notation(.compactName).precision(.fractionLength(0...1))) }
        return value.formatted(.number.precision(.fractionLength(0)))
    }
    private static func gib(_ value: Double?) -> String {
        value.map { ($0 / 1_073_741_824).formatted(.number.precision(.fractionLength(1))) } ?? "—"
    }
}

public enum OMLXDetailPage: Equatable, Hashable, Sendable {
    case models(Int), activity, speed, tokens, prefill, load, active, queued, loaded, memory, used, limit, pressure

    public var title: String {
        switch self {
        case .models: return "Models"
        case .activity: return "Activity"
        case .speed: return "Activity · Speed"
        case .tokens: return "Activity · Tokens"
        case .prefill: return "Activity · Prefill"
        case .load: return "Load"
        case .active: return "Load · Active"
        case .queued: return "Load · Queued"
        case .loaded: return "Load · Models"
        case .memory: return "Memory"
        case .used: return "Memory · Used"
        case .limit: return "Memory · Limit"
        case .pressure: return "Memory · Pressure"
        }
    }

    public var shortTitle: String {
        switch self {
        case .speed: return "Speed"
        case .tokens: return "Tokens"
        case .prefill: return "Prefill"
        case .active: return "Active"
        case .queued: return "Queued"
        case .loaded: return "Loaded"
        case .used: return "Mem · Used"
        case .limit: return "Mem · Limit"
        case .pressure: return "Pressure"
        default: return title
        }
    }

    public static func sequence(modelCount: Int, narrow: Bool) -> [Self] {
        let models = (0..<max(1, modelCount)).map { Self.models($0) }
        // Narrow rows use more pages, not smaller text or hidden statistics.
        return models + (narrow
            ? [.speed, .tokens, .prefill, .active, .queued, .loaded, .used, .limit, .pressure]
            : [.activity, .load, .memory])
    }
}

/// Shared clock math for both rows. Native text measurement determines travel;
/// a model page waits for the slower row, including readable end holds.
public enum OMLXMarqueeTiming {
    public static let pageSeconds = 7.0
    public static let leadingHold = 1.5
    public static let trailingHold = 2.0

    public static func distance(content: Double, viewport: Double) -> Double {
        guard content.isFinite, viewport.isFinite, content > 0, viewport > 0 else { return 0 }
        return max(0, content - viewport)
    }
    public static func duration(content: Double, viewport: Double, speed: Double, reduceMotion: Bool) -> Double {
        let travel = distance(content: content, viewport: viewport)
        guard travel > 0, speed.isFinite, speed > 0 else { return pageSeconds }
        if reduceMotion {
            return (ceil(travel / max(1, viewport - 12)) + 1) * pageSeconds
        }
        return max(pageSeconds, leadingHold + travel / speed + trailingHold)
    }
    public static func offset(elapsed: Double, content: Double, viewport: Double, speed: Double, reduceMotion: Bool) -> Double {
        guard elapsed.isFinite, elapsed > 0, speed.isFinite, speed > 0 else { return 0 }
        let travel = distance(content: content, viewport: viewport)
        if reduceMotion {
            // Static overlapping segments reveal the whole name without sliding.
            return min(travel, floor(elapsed / pageSeconds) * max(1, viewport - 12))
        }
        return min(travel, max(0, elapsed - leadingHold) * speed)
    }
}
