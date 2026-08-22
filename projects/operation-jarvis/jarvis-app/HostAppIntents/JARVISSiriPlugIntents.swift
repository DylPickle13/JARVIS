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
                "Hey \(.applicationName), turn on a plug",
                "Hey \(.applicationName), turn on \(\.$plug)",
                "Hey \(.applicationName), turn on the \(\.$plug)",
            ],
            shortTitle: "Turn On Plug",
            systemImageName: "powerplug.fill"
        )
        AppShortcut(
            intent: TurnOffJARVISPlugIntent(),
            phrases: [
                "Hey \(.applicationName), turn off a plug",
                "Hey \(.applicationName), turn off \(\.$plug)",
                "Hey \(.applicationName), turn off the \(\.$plug)",
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

    static func seedCatalogue(_ plugs: [JARVISPlugDescriptor]) async {
        await catalogueCoordinator.seed(plugs)
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

/// Persistently tracks which catalogue and phrase schema were advertised to
/// App Intents. Comparing two state snapshots is insufficient after an app
/// upgrade because both may contain the same cached plugs even though the new
/// provider has never published its parameter phrases on this device.
@MainActor
final class JARVISSiriParameterRegistrar {
    static let signatureKey = "jarvis.siri.parameter-signature.v1"

    private let defaults: UserDefaults
    private let schemaVersion: Int
    private let seed: ([JARVISPlugDescriptor]) async -> Void
    private let publish: () -> Void
    private var inFlightSignature: String?

    init(
        defaults: UserDefaults = JARVISSharedStore.defaults,
        schemaVersion: Int = 4,
        seed: @escaping ([JARVISPlugDescriptor]) async -> Void = { plugs in
            await JARVISSiriPlugRuntime.seedCatalogue(plugs)
        },
        publish: @escaping () -> Void = {
            JARVISAppShortcuts.updateAppShortcutParameters()
        }
    ) {
        self.defaults = defaults
        self.schemaVersion = schemaVersion
        self.seed = seed
        self.publish = publish
    }

    func updateIfNeeded(from state: StateSnapshot) {
        let plugs = JARVISPlugCatalog.descriptors(from: state)
        let signature = Self.signature(schemaVersion: schemaVersion, plugs: plugs)
        guard defaults.string(forKey: Self.signatureKey) != signature,
              inFlightSignature != signature else { return }
        inFlightSignature = signature

        Task { @MainActor [weak self] in
            guard let self else { return }
            // Seed before notifying App Intents so its burst of parameter
            // queries resolves locally instead of multiplying LAN requests.
            await self.seed(plugs)
            guard self.inFlightSignature == signature else { return }
            self.publish()
            self.defaults.set(signature, forKey: Self.signatureKey)
            self.inFlightSignature = nil
            NSLog("[JARVIS Siri] published %d plug parameter values", plugs.count)
        }
    }

    static func signature(schemaVersion: Int, plugs: [JARVISPlugDescriptor]) -> String {
        let catalogue = plugs
            .sorted { $0.id < $1.id }
            .map {
                let id = Data($0.id.utf8).base64EncodedString()
                let name = Data($0.displayName.utf8).base64EncodedString()
                return "\(id):\(name)"
            }
            .joined(separator: ",")
        return "schema=\(schemaVersion)|\(catalogue)"
    }
}

@MainActor
private let jarvisSiriParameterRegistrar = JARVISSiriParameterRegistrar()

/// Publish on the first fresh state after installation or a phrase-schema
/// update, and again after any add/remove/rename. The persisted signature makes
/// repeated 15-second foreground refreshes no-ops.
@MainActor
func updateJARVISSiriParametersIfNeeded(previous _: StateSnapshot?, current: StateSnapshot) {
    jarvisSiriParameterRegistrar.updateIfNeeded(from: current)
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
