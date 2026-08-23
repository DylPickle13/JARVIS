import Foundation
import JARVISKit

@MainActor
final class WatchTerminalProvisioningSettings: ObservableObject {
    @Published private(set) var isProvisioned: Bool
    @Published private(set) var endpoint: String
    @Published private(set) var errorMessage: String?

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.endpoint = defaults.string(forKey: JARVISTerminalConfigurationStore.endpointKey) ?? ""
        if case .configured = JARVISTerminalConfigurationStore.load(defaults: defaults) {
            self.isProvisioned = true
        } else {
            self.isProvisioned = false
        }
    }

    var configuration: WatchTerminalConfiguration? {
        guard case .configured(let configuration) = JARVISTerminalConfigurationStore.load(defaults: defaults) else {
            return nil
        }
        return configuration
    }

    @discardableResult
    func save(provisioningCode: String) -> Bool {
        guard let configuration = WatchTerminalConfiguration.fromProvisioningCode(provisioningCode) else {
            errorMessage = "The Watch terminal setup code is invalid."
            return false
        }
        guard JARVISTerminalConfigurationStore.save(configuration, defaults: defaults) else {
            errorMessage = "Could not save the Watch terminal token in Keychain."
            return false
        }
        endpoint = configuration.endpoint
        isProvisioned = true
        errorMessage = nil
        return true
    }
}
