import Foundation

public enum JARVISPlugCommandDisposition: Equatable, Sendable {
    case alreadyInDesiredState
    case changed
}

public struct JARVISPlugCommandOutcome: Equatable, Sendable {
    public let plug: JARVISPlugDescriptor
    public let desiredState: Bool
    public let disposition: JARVISPlugCommandDisposition

    public init(
        plug: JARVISPlugDescriptor,
        desiredState: Bool,
        disposition: JARVISPlugCommandDisposition
    ) {
        self.plug = plug
        self.desiredState = desiredState
        self.disposition = disposition
    }
}

public enum JARVISPlugCommandError: LocalizedError, Equatable, Sendable {
    case unreachable(String)
    case catalogue(JARVISPlugCatalogError)
    case rejected(String)
    case deliveryUnconfirmed(String)
    case resultUnconfirmed(String)

    /// A Watch may safely try the iPhone relay only when the direct path failed
    /// before a write was attempted. A transport failure during POST is
    /// deliberately not retried because the first write may have succeeded.
    public var allowsWatchRelayFallback: Bool {
        if case .unreachable = self { return true }
        return false
    }

    public var errorDescription: String? {
        switch self {
        case .unreachable(let message):
            return message.isEmpty ? "JARVIS is unreachable." : message
        case .catalogue(let error):
            return error.errorDescription
        case .rejected(let message):
            return message.isEmpty ? "JARVIS rejected the plug command." : message
        case .deliveryUnconfirmed:
            return "JARVIS may have received the command, but the result could not be confirmed."
        case .resultUnconfirmed(let name):
            return "JARVIS could not confirm the state of \(name)."
        }
    }
}

/// Direct jarvisd plug access shared by Siri on iPhone and Watch. This type
/// discovers the daemon, validates fresh state before writing, uses explicit
/// desired-state actions, and confirms the resulting state before returning.
public final class JARVISDirectPlugController: @unchecked Sendable {
    private let client: any JarvisAPI
    private let endpointStore: EndpointStore
    private let snapshotStore: SnapshotStore
    private let discoveryTimeout: TimeInterval

    public init(
        client: any JarvisAPI = JarvisClient(),
        endpointStore: EndpointStore = EndpointStore(defaults: JARVISSharedStore.defaults),
        snapshotStore: SnapshotStore = SnapshotStore(),
        discoveryTimeout: TimeInterval = 3
    ) {
        self.client = client
        self.endpointStore = endpointStore
        self.snapshotStore = snapshotStore
        self.discoveryTimeout = discoveryTimeout
    }

    public func cachedState() -> StateSnapshot? {
        snapshotStore.load()?.state
    }

    @discardableResult
    public func fetchFreshState() async throws -> StateSnapshot {
        let endpoint = try await resolveEndpoint()
        do {
            let state = try await client.state(endpoint)
            snapshotStore.save(state)
            return state
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as JarvisError {
            throw JARVISPlugCommandError.unreachable(error.errorDescription ?? "JARVIS is unreachable.")
        } catch {
            throw JARVISPlugCommandError.unreachable(error.localizedDescription)
        }
    }

    public func setPlug(id: String, isOn: Bool) async throws -> JARVISPlugCommandOutcome {
        let endpoint = try await resolveEndpoint()
        let before: StateSnapshot
        do {
            before = try await client.state(endpoint)
            snapshotStore.save(before)
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as JarvisError {
            throw JARVISPlugCommandError.unreachable(error.errorDescription ?? "JARVIS is unreachable.")
        } catch {
            throw JARVISPlugCommandError.unreachable(error.localizedDescription)
        }

        let plug: JARVISPlugDescriptor
        do {
            plug = try JARVISPlugCatalog.freshPlug(id: id, in: before)
        } catch let error as JARVISPlugCatalogError {
            throw JARVISPlugCommandError.catalogue(error)
        }
        if plug.isOn == isOn {
            return JARVISPlugCommandOutcome(
                plug: plug,
                desiredState: isOn,
                disposition: .alreadyInDesiredState
            )
        }

        let action = isOn ? "plug-on" : "plug-off"
        let result: CommandResult
        do {
            result = try await client.command(endpoint, action: action, params: ["plug": .string(id)])
        } catch is CancellationError {
            // Cancellation after dispatch is also an unknown result and must not
            // silently trigger a second path.
            throw JARVISPlugCommandError.deliveryUnconfirmed(plug.displayName)
        } catch let error as JarvisError {
            throw JARVISPlugCommandError.deliveryUnconfirmed(error.errorDescription ?? plug.displayName)
        } catch {
            throw JARVISPlugCommandError.deliveryUnconfirmed(error.localizedDescription)
        }
        guard result.ok else {
            throw JARVISPlugCommandError.rejected(result.error ?? "The plug command failed.")
        }
        if let resultName = result.plug?.name, resultName != id {
            throw JARVISPlugCommandError.resultUnconfirmed(plug.displayName)
        }
        if result.plug?.is_on == isOn {
            let confirmed = JARVISPlugDescriptor(
                id: id,
                displayName: plug.displayName,
                isOn: isOn,
                stale: false
            )
            snapshotStore.applyConfirmedPlugState(name: id, isOn: isOn)
            return JARVISPlugCommandOutcome(plug: confirmed, desiredState: isOn, disposition: .changed)
        }

        // Older daemon responses may omit the plug payload. One authoritative
        // read may confirm success; otherwise Siri must report it as unknown.
        do {
            let after = try await client.state(endpoint)
            snapshotStore.save(after)
            let confirmed = try JARVISPlugCatalog.freshPlug(id: id, in: after)
            guard confirmed.isOn == isOn else {
                throw JARVISPlugCommandError.resultUnconfirmed(plug.displayName)
            }
            return JARVISPlugCommandOutcome(plug: confirmed, desiredState: isOn, disposition: .changed)
        } catch let error as JARVISPlugCommandError {
            throw error
        } catch {
            throw JARVISPlugCommandError.resultUnconfirmed(plug.displayName)
        }
    }

    private func resolveEndpoint() async throws -> JarvisEndpoint {
        let candidates = JarvisEndpoints.candidates(override: endpointStore.endpointURL)
        guard let url = await client.discover(candidates, timeout: discoveryTimeout) else {
            throw JARVISPlugCommandError.unreachable("JARVIS is unreachable.")
        }
        endpointStore.endpointURLString = url.absoluteString
        return JarvisEndpoint(baseURL: url, token: endpointStore.token ?? "")
    }
}
