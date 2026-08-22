import AppIntents
import Foundation
import JARVISKit

/// A runtime entity backed exclusively by the current jarvisd plug map. No
/// production plug identifiers or display names are compiled into Siri.
struct JARVISPlugEntity: AppEntity {
    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "JARVIS Plug")
    static let defaultQuery = JARVISPlugEntityQuery()

    let id: String
    let name: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(name)", image: .init(systemName: "powerplug.fill"))
    }

    init(_ descriptor: JARVISPlugDescriptor) {
        id = descriptor.id
        name = descriptor.displayName
    }
}

struct JARVISPlugEntityQuery: EntityStringQuery {
    func entities(for identifiers: [JARVISPlugEntity.ID]) async throws -> [JARVISPlugEntity] {
        let available = await JARVISSiriPlugRuntime.catalogue()
        let byID = Dictionary(uniqueKeysWithValues: available.map { ($0.id, $0) })
        return identifiers.compactMap { byID[$0].map(JARVISPlugEntity.init) }
    }

    func entities(matching string: String) async throws -> [JARVISPlugEntity] {
        let available = await JARVISSiriPlugRuntime.catalogue()
        return JARVISPlugCatalog.matching(string, in: available).map(JARVISPlugEntity.init)
    }

    func suggestedEntities() async throws -> [JARVISPlugEntity] {
        let available = await JARVISSiriPlugRuntime.catalogue()
        return available.map(JARVISPlugEntity.init)
    }
}

struct TurnOnJARVISPlugIntent: AppIntent {
    static let title: LocalizedStringResource = "Turn On JARVIS Plug"
    static let description = IntentDescription("Turn on one currently configured JARVIS plug.")
    static var openAppWhenRun: Bool { false }

    @Parameter(
        title: "Plug",
        requestValueDialog: IntentDialog("Which JARVIS plug should I turn on?")
    )
    var plug: JARVISPlugEntity

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let outcome = try await JARVISSiriPlugRuntime.setPlug(id: plug.id, isOn: true)
        switch outcome.disposition {
        case .alreadyInDesiredState:
            return .result(dialog: IntentDialog("\(outcome.plug.displayName) is already on."))
        case .changed:
            return .result(dialog: IntentDialog("\(outcome.plug.displayName) is now on."))
        }
    }
}

struct TurnOffJARVISPlugIntent: AppIntent {
    static let title: LocalizedStringResource = "Turn Off JARVIS Plug"
    static let description = IntentDescription("Turn off one currently configured JARVIS plug.")
    static var openAppWhenRun: Bool { false }

    @Parameter(
        title: "Plug",
        requestValueDialog: IntentDialog("Which JARVIS plug should I turn off?")
    )
    var plug: JARVISPlugEntity

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let outcome = try await JARVISSiriPlugRuntime.setPlug(id: plug.id, isOn: false)
        switch outcome.disposition {
        case .alreadyInDesiredState:
            return .result(dialog: IntentDialog("\(outcome.plug.displayName) is already off."))
        case .changed:
            return .result(dialog: IntentDialog("\(outcome.plug.displayName) is now off."))
        }
    }
}

struct JARVISAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: TurnOnJARVISPlugIntent(),
            phrases: [
                "Tell \(.applicationName) to turn on \(\.$plug)",
                "Turn on \(\.$plug) with \(.applicationName)",
            ],
            shortTitle: "Turn On Plug",
            systemImageName: "powerplug.fill"
        )
        AppShortcut(
            intent: TurnOffJARVISPlugIntent(),
            phrases: [
                "Tell \(.applicationName) to turn off \(\.$plug)",
                "Turn off \(\.$plug) with \(.applicationName)",
            ],
            shortTitle: "Turn Off Plug",
            systemImageName: "powerplug"
        )
    }
}

enum JARVISSiriPlugRuntime {
    private static let direct = JARVISDirectPlugController()
    private static let catalogueCoordinator = JARVISSiriCatalogueCoordinator()

    static func catalogue() async -> [JARVISPlugDescriptor] {
        await catalogueCoordinator.catalogue {
            await loadCatalogue()
        }
    }

    static func seedCatalogue(from state: StateSnapshot) async {
        await catalogueCoordinator.seed(JARVISPlugCatalog.descriptors(from: state))
    }

    private static func loadCatalogue() async -> [JARVISPlugDescriptor] {
        do {
            let fresh = try await direct.fetchFreshState()
            return JARVISPlugCatalog.descriptors(from: fresh)
        } catch {
            #if os(watchOS)
            WatchBridge.shared.start()
            if case .success(let data) = await WatchBridge.shared.requestStateData(),
               let state = try? JSONDecoder().decode(StateSnapshot.self, from: data) {
                SnapshotStore().save(state)
                return JARVISPlugCatalog.descriptors(from: state)
            }
            #endif
            guard let cached = direct.cachedState() else { return [] }
            return JARVISPlugCatalog.descriptors(from: cached)
        }
    }

    static func setPlug(id: String, isOn: Bool) async throws -> JARVISPlugCommandOutcome {
        do {
            return try await direct.setPlug(id: id, isOn: isOn)
        } catch let directError as JARVISPlugCommandError {
            #if os(watchOS)
            guard directError.allowsWatchRelayFallback else { throw directError }
            return try await setPlugViaPhone(id: id, isOn: isOn)
            #else
            throw directError
            #endif
        }
    }

    #if os(watchOS)
    private static func setPlugViaPhone(id: String, isOn: Bool) async throws -> JARVISPlugCommandOutcome {
        WatchBridge.shared.start()
        let stateData: Data
        switch await WatchBridge.shared.requestStateData() {
        case .success(let data):
            stateData = data
        case .failure(let error):
            throw JARVISPlugCommandError.unreachable(error.errorDescription ?? "The iPhone relay is unavailable.")
        }
        guard let state = try? JSONDecoder().decode(StateSnapshot.self, from: stateData) else {
            throw JARVISPlugCommandError.unreachable("The iPhone returned invalid plug status.")
        }
        SnapshotStore().save(state)

        let plug: JARVISPlugDescriptor
        do {
            plug = try JARVISPlugCatalog.freshPlug(id: id, in: state)
        } catch let error as JARVISPlugCatalogError {
            throw JARVISPlugCommandError.catalogue(error)
        }
        // The correlated state confirms the entity exists, but the phone still
        // re-fetches immediately before deciding whether a POST is needed. Do
        // not short-circuit here from a snapshot that could race a state change.
        let result: CommandResult
        switch await WatchBridge.shared.requestPlugCommand(name: id, isOn: isOn) {
        case .success(let value):
            result = value
        case .failure(let error):
            throw JARVISPlugCommandError.rejected(error.errorDescription ?? "The iPhone relay failed.")
        }
        guard result.ok else {
            throw JARVISPlugCommandError.rejected(result.error ?? "The relayed plug command failed.")
        }
        guard result.plug?.name == id, result.plug?.is_on == isOn else {
            throw JARVISPlugCommandError.resultUnconfirmed(plug.displayName)
        }
        let confirmed = JARVISPlugDescriptor(
            id: id,
            displayName: plug.displayName,
            isOn: isOn,
            stale: false
        )
        SnapshotStore().applyConfirmedPlugState(name: id, isOn: isOn)
        let disposition: JARVISPlugCommandDisposition = result.summary == "already-in-desired-state"
            ? .alreadyInDesiredState
            : .changed
        return JARVISPlugCommandOutcome(plug: confirmed, desiredState: isOn, disposition: disposition)
    }
    #endif
}

/// Call only when the set of daemon-advertised identifiers changes. This asks
/// Siri and Shortcuts to regenerate parameterized phrases after add/remove/
/// rename without polling or embedding a fixed list in the app.
func updateJARVISSiriParametersIfNeeded(previous: StateSnapshot?, current: StateSnapshot) {
    let oldIDs = Set(previous.map { JARVISPlugCatalog.descriptors(from: $0).map(\.id) } ?? [])
    let newIDs = Set(JARVISPlugCatalog.descriptors(from: current).map(\.id))
    guard oldIDs != newIDs else { return }
    Task {
        // Seed before notifying App Intents so its burst of parameter queries
        // resolves from one known-fresh catalogue instead of multiplying LAN
        // discovery and state requests.
        await JARVISSiriPlugRuntime.seedCatalogue(from: current)
        JARVISAppShortcuts.updateAppShortcutParameters()
    }
}

private actor JARVISSiriCatalogueCoordinator {
    private struct InFlight {
        let generation: Int
        let task: Task<[JARVISPlugDescriptor], Never>
    }

    private let retention: TimeInterval = 15
    private var cached: (savedAt: Date, plugs: [JARVISPlugDescriptor])?
    private var inFlight: InFlight?
    private var generation = 0

    func catalogue(
        loader: @escaping @Sendable () async -> [JARVISPlugDescriptor]
    ) async -> [JARVISPlugDescriptor] {
        if let cached, Date().timeIntervalSince(cached.savedAt) < retention {
            return cached.plugs
        }
        if let inFlight {
            let result = await inFlight.task.value
            return generation == inFlight.generation ? result : (cached?.plugs ?? result)
        }

        let requestGeneration = generation
        let task = Task { await loader() }
        inFlight = InFlight(generation: requestGeneration, task: task)
        let result = await task.value
        if generation == requestGeneration {
            cached = (Date(), result)
            inFlight = nil
            return result
        }
        return cached?.plugs ?? result
    }

    func seed(_ plugs: [JARVISPlugDescriptor]) {
        generation += 1
        inFlight?.task.cancel()
        inFlight = nil
        cached = (Date(), plugs)
    }
}
