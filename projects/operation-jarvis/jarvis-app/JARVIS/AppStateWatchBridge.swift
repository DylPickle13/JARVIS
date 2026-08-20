import Foundation
import JARVISKit

extension AppState: WatchBridgeDelegate {
    public nonisolated func watchBridgeDidReceiveStateRequest(_ bridge: WatchBridge) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            if self.lastState == nil { await self.fetchState() }
            guard let state = self.lastState, let data = try? JSONEncoder().encode(state) else { return }
            bridge.sendState(json: data)
            bridge.updateApplicationContext(stateJSON: data, endpoint: self.currentEndpoint?.absoluteString)
        }
    }

    public nonisolated func watchBridgeDidReceiveState(_ bridge: WatchBridge, json: Data) {
        Task { @MainActor [weak self] in
            guard let self, let state = try? JSONDecoder().decode(StateSnapshot.self, from: json) else { return }
            self.lastState = state
            SnapshotStore().save(state)
        }
    }

    public nonisolated func watchBridgeDidReceiveEndpoint(_ bridge: WatchBridge, endpoint: String) {
        Task { @MainActor [weak self] in
            guard let self, let url = URL(string: endpoint), url.scheme != nil, url.host != nil else { return }
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
            let entry: WatchCommandCacheEntry
            if result.ok {
                entry = WatchCommandCacheEntry(result: result, error: nil)
                self.rememberWatchCommand(requestID, entry: entry)
                sendWatchCommandResponse(entry, bridge: bridge, requestID: requestID)
                await self.fetchState()
            } else {
                let message = result.error ?? "The plug command failed."
                entry = WatchCommandCacheEntry(result: nil, error: message)
                self.rememberWatchCommand(requestID, entry: entry)
                sendWatchCommandResponse(entry, bridge: bridge, requestID: requestID)
            }
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
        bridge.sendCommandError(requestID: requestID, message: entry.error ?? "The plug command failed.")
    }
}
