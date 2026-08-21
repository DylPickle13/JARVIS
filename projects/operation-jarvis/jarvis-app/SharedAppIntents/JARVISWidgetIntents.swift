import AppIntents
import Foundation
import WidgetKit
import JARVISKit

@available(iOS 17.0, watchOS 10.0, *)
struct SetPlugIntent: AppIntent {
    static let title: LocalizedStringResource = "Set JARVIS Plug"
    static let description = IntentDescription("Turn one approved JARVIS plug on or off.")
    static var openAppWhenRun: Bool { false }

    @Parameter(title: "Plug")
    var plug: String

    @Parameter(title: "On")
    var isOn: Bool

    init() {
        plug = ""
        isOn = false
    }

    init(plug: String, isOn: Bool) {
        self.plug = plug
        self.isOn = isOn
    }

    func perform() async throws -> some IntentResult {
        guard !plug.isEmpty else { throw JARVISWidgetIntentError.invalidPlug }
        let store = EndpointStore(defaults: JARVISSharedStore.defaults)
        let client = JarvisClient()
        let url: URL?
        if let saved = store.endpointURL {
            url = saved
        } else {
            url = await client.discover(JarvisEndpoints.candidates(override: nil), timeout: 3)
        }
        guard let url else { throw JARVISWidgetIntentError.unreachable }
        let result = try await client.command(
            JarvisEndpoint(baseURL: url, token: store.token ?? ""),
            action: isOn ? "plug-on" : "plug-off",
            params: ["plug": .string(plug)]
        )
        guard result.ok else {
            throw JARVISWidgetIntentError.commandFailed(result.error ?? "The plug command failed.")
        }
        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }
}

@available(iOS 17.0, watchOS 10.0, *)
enum JARVISPlugChoice: String, AppEnum, CaseIterable {
    case familyRoomLight = "family-room-light"
    case lamp
    case pedalboard
    case tv

    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "JARVIS Plug")
    static let caseDisplayRepresentations: [JARVISPlugChoice: DisplayRepresentation] = [
        .familyRoomLight: DisplayRepresentation(title: "Family Room Light", image: .init(systemName: "lightbulb")),
        .lamp: DisplayRepresentation(title: "Lamp", image: .init(systemName: "lamp.table")),
        .pedalboard: DisplayRepresentation(title: "Pedalboard", image: .init(systemName: "music.note")),
        .tv: DisplayRepresentation(title: "TV", image: .init(systemName: "tv")),
    ]

    var widgetDisplayName: String {
        switch self {
        case .familyRoomLight: return "Family Room Light"
        case .lamp: return "Lamp"
        case .pedalboard: return "Pedalboard"
        case .tv: return "TV"
        }
    }
}

@available(iOS 17.0, watchOS 10.0, *)
struct SelectJARVISPlugIntent: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "Select JARVIS Plug"
    static let description = IntentDescription("Choose the plug displayed by this widget.")

    @Parameter(title: "Plug")
    var plug: JARVISPlugChoice?

    init() {
        plug = .lamp
    }
}

enum JARVISWidgetIntentError: LocalizedError, Sendable {
    case invalidPlug
    case unreachable
    case commandFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidPlug: return "No plug was selected."
        case .unreachable: return "JARVIS is currently unreachable."
        case .commandFailed(let message): return message
        }
    }
}
