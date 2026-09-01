import Foundation
import JARVISKit

extension AppState: WatchBridgeDelegate {
    public nonisolated func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge, requestID: String) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            if self.currentEndpoint == nil || self.connectionState != .connected {
                await self.refresh()
            } else {
                await self.fetchState()
                if self.connectionState != .connected { await self.refresh() }
            }
            guard self.connectionState == .connected,
                  self.stateErrorMessage == nil,
                  let state = self.lastState,
                  let data = try? JSONEncoder().encode(state) else { return }
            // This correlated reply is the only immediate state publication.
            // performFetchState already updated latest-value application context.
            bridge.sendState(json: data, requestID: requestID)
        }
    }

    public nonisolated func watchBridgeDidReceiveState(_ bridge: WatchBridge, json: Data) {
        Task { @MainActor [weak self] in
            guard let self,
                  let state = try? JSONDecoder().decode(StateSnapshot.self, from: json),
                  WatchStatePublicationPolicy.shouldAccept(state, over: self.lastState) else { return }
            self.lastState = state
            SnapshotStore().save(state)
        }
    }

    public nonisolated func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String) {
        Task { @MainActor [weak self] in
            guard let self, let url = JarvisEndpointURLPolicy.parse(endpoint) else { return }
            self.store.endpointURLString = url.absoluteString
            self.endpointDraft = url.absoluteString
        }
    }

    public nonisolated func watchBridgeDidReceivePlugCommand(
        _ bridge: WatchBridge,
        name: String,
        isOn: Bool,
        requestID: String
    ) {
        #if DEBUG
        NSLog("[JARVIS AppState] received Watch plug command %@ desired=%@", name, isOn ? "on" : "off")
        #endif
        Task { @MainActor [weak self] in
            guard let self, !name.isEmpty, !requestID.isEmpty else {
                if !requestID.isEmpty { bridge.sendCommandError(requestID: requestID, message: "The plug command was invalid.") }
                return
            }

            if let cached = self.watchCommandResponses[requestID] {
                sendWatchCommandResponse(cached, bridge: bridge, requestID: requestID)
                return
            }
            guard self.watchCommandInFlight.insert(requestID).inserted else { return }

            let result = await self.executeWatchPlugCommand(name, isOn: isOn)
            let entry = result.ok
                ? WatchCommandCacheEntry(result: result, error: nil)
                : WatchCommandCacheEntry(result: nil, error: result.error ?? "The plug command failed.")
            self.rememberWatchCommand(requestID, entry: entry)
            sendWatchCommandResponse(entry, bridge: bridge, requestID: requestID)
            // A correlated result has been delivered, so release duplicate
            // suppression before the best-effort state refresh can suspend.
            self.watchCommandInFlight.remove(requestID)
            if result.ok { await self.fetchState() }
        }
    }

    public nonisolated func watchBridgeDidReceivePurifierCommand(
        _ bridge: WatchBridge,
        command: WatchPurifierCommand,
        requestID: String
    ) {
        #if DEBUG
        NSLog("[JARVIS AppState] received Watch purifier command setting=%@", command.setting.rawValue)
        #endif
        Task { @MainActor [weak self] in
            guard let self, command.isValid, !requestID.isEmpty else {
                if !requestID.isEmpty {
                    bridge.sendCommandError(requestID: requestID, message: "The air-purifier command was invalid.")
                }
                return
            }

            if let cached = self.watchCommandResponses[requestID] {
                sendWatchCommandResponse(cached, bridge: bridge, requestID: requestID)
                return
            }
            guard self.watchCommandInFlight.insert(requestID).inserted else { return }

            let result = await self.executeWatchPurifierCommand(command)
            let entry = result.ok
                ? WatchCommandCacheEntry(result: result, error: nil)
                : WatchCommandCacheEntry(result: nil, error: result.error ?? "The air-purifier command failed.")
            self.rememberWatchCommand(requestID, entry: entry)
            sendWatchCommandResponse(entry, bridge: bridge, requestID: requestID)
            self.watchCommandInFlight.remove(requestID)
        }
    }

    public nonisolated func watchBridgeDidReceiveCommandResult(
        _ bridge: WatchBridge,
        requestID: String,
        result: CommandResult
    ) {}

    public nonisolated func watchBridgeDidReceiveCommandError(
        _ bridge: WatchBridge,
        requestID: String,
        error: WatchCommandError
    ) {}

    public nonisolated func watchBridgeDidReceivePushRegistration(
        _ bridge: WatchBridge,
        registration: JARVISPushRegistration
    ) {
        Task { @MainActor in
            PushNotificationCoordinator.shared.receiveWatchRegistration(registration)
        }
    }

    public nonisolated func watchBridgeDidReceivePushPreference(
        _ bridge: WatchBridge,
        enabled: Bool
    ) {}
}

@MainActor
private func sendWatchCommandResponse(
    _ entry: WatchCommandCacheEntry,
    bridge: WatchBridge,
    requestID: String
) {
    if let result = entry.result {
        bridge.sendCommandResult(requestID: requestID, result: result)
    } else {
        bridge.sendCommandError(requestID: requestID, message: entry.error ?? "The Watch command failed.")
    }
}
