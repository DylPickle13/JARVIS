import Foundation

#if canImport(AppIntents)
import AppIntents
#if canImport(WidgetKit)
import WidgetKit
#endif

@available(iOS 17.0, watchOS 10.0, *)
public struct SetPlugIntent: AppIntent {
    public static let title: LocalizedStringResource = "Set JARVIS Plug"
    public static let description = IntentDescription("Turn one approved JARVIS plug on or off.")
    public static var openAppWhenRun: Bool { false }

    @Parameter(title: "Plug")
    public var plug: String

    @Parameter(title: "On")
    public var isOn: Bool

    public init() {
        self.plug = ""
        self.isOn = false
    }

    public init(plug: String, isOn: Bool) {
        self.plug = plug
        self.isOn = isOn
    }

    public func perform() async throws -> some IntentResult {
        guard !plug.isEmpty else { throw JARVISIntentError.invalidPlug }
        let store = EndpointStore(defaults: JARVISSharedStore.defaults)
        let client = JarvisClient()
        let url: URL?
        if let saved = store.endpointURL {
            url = saved
        } else {
            url = await client.discover(JarvisEndpoints.candidates(override: nil), timeout: 3)
        }
        guard let url else { throw JARVISIntentError.unreachable }
        let endpoint = JarvisEndpoint(baseURL: url, token: store.token ?? "")
        let result = try await client.command(
            endpoint,
            action: isOn ? "plug-on" : "plug-off",
            params: ["plug": .string(plug)]
        )
        guard result.ok else { throw JARVISIntentError.commandFailed(result.error ?? "The plug command failed.") }
        #if canImport(WidgetKit)
        WidgetCenter.shared.reloadAllTimelines()
        #endif
        return .result()
    }
}

public enum JARVISIntentError: LocalizedError, Sendable {
    case invalidPlug
    case unreachable
    case commandFailed(String)

    public var errorDescription: String? {
        switch self {
        case .invalidPlug: return "No plug was selected."
        case .unreachable: return "JARVIS is currently unreachable."
        case .commandFailed(let message): return message
        }
    }
}
#endif
