import Foundation

struct LocalProvisioningProfile: Equatable, Sendable {
    let name: String
    let bundleIdentifier: String
    let uuid: String
    let expirationDate: Date
}

struct LocalSigningStatus: Equatable, Sendable {
    static let expectedBundleIdentifiers = [
        "com.operation-jarvis.jarvis",
        "com.operation-jarvis.jarvis.widget",
        "com.operation-jarvis.jarvis.watchkitapp",
        "com.operation-jarvis.jarvis.watchkitapp.widget",
    ]

    let profiles: [LocalProvisioningProfile]

    var earliestExpiration: Date? {
        profiles.map(\.expirationDate).min()
    }

    var hasAllExpectedProfiles: Bool {
        Set(profiles.map(\.bundleIdentifier)) == Set(Self.expectedBundleIdentifiers)
    }

    static func current(bundleURL: URL = Bundle.main.bundleURL) -> LocalSigningStatus {
        let targets: [(String, String, String)] = [
            ("iPhone app", "embedded.mobileprovision", expectedBundleIdentifiers[0]),
            ("iPhone widget", "PlugIns/JARVISWidget.appex/embedded.mobileprovision", expectedBundleIdentifiers[1]),
            ("Watch app", "Watch/JARVISWatch.app/embedded.mobileprovision", expectedBundleIdentifiers[2]),
            ("Watch widget", "Watch/JARVISWatch.app/PlugIns/JARVISWatchWidget.appex/embedded.mobileprovision", expectedBundleIdentifiers[3]),
        ]
        let profiles = targets.compactMap { name, relativePath, bundleIdentifier in
            profile(
                at: bundleURL.appendingPathComponent(relativePath),
                name: name,
                expectedBundleIdentifier: bundleIdentifier
            )
        }
        return LocalSigningStatus(profiles: profiles)
    }

    static func profile(
        at url: URL,
        name: String,
        expectedBundleIdentifier: String
    ) -> LocalProvisioningProfile? {
        guard let data = try? Data(contentsOf: url),
              let plist = embeddedPropertyList(in: data),
              let payload = try? PropertyListSerialization.propertyList(from: plist, format: nil),
              let dictionary = payload as? [String: Any],
              let uuid = dictionary["UUID"] as? String,
              let expirationDate = dictionary["ExpirationDate"] as? Date,
              let entitlements = dictionary["Entitlements"] as? [String: Any],
              let applicationIdentifier = entitlements["application-identifier"] as? String,
              applicationIdentifier.hasSuffix(".\(expectedBundleIdentifier)") else {
            return nil
        }
        return LocalProvisioningProfile(
            name: name,
            bundleIdentifier: expectedBundleIdentifier,
            uuid: uuid,
            expirationDate: expirationDate
        )
    }

    static func embeddedPropertyList(in data: Data) -> Data? {
        let xmlStart = Data("<?xml".utf8)
        let plistEnd = Data("</plist>".utf8)
        guard let start = data.range(of: xmlStart),
              let end = data.range(of: plistEnd, options: [], in: start.lowerBound..<data.endIndex),
              start.lowerBound < end.upperBound else {
            return nil
        }
        return data.subdata(in: start.lowerBound..<end.upperBound)
    }
}
