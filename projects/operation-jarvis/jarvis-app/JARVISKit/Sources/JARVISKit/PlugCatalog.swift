import Foundation

/// One plug advertised by jarvisd. The daemon's map key is the canonical
/// command identifier; the Apple clients derive presentation at runtime so a
/// catalogue change does not require a new app build.
public struct JARVISPlugDescriptor: Equatable, Identifiable, Sendable {
    public let id: String
    public let displayName: String
    public let isOn: Bool?
    public let stale: Bool

    public init(id: String, displayName: String, isOn: Bool?, stale: Bool) {
        self.id = id
        self.displayName = displayName
        self.isOn = isOn
        self.stale = stale
    }
}

public enum JARVISPlugCatalogError: LocalizedError, Equatable, Sendable {
    case unavailable
    case stale
    case unknownPlug(String)

    public var errorDescription: String? {
        switch self {
        case .unavailable:
            return "JARVIS plug status is unavailable."
        case .stale:
            return "JARVIS plug status is stale."
        case .unknownPlug(let id):
            return "The JARVIS plug \(JARVISPlugCatalog.displayName(for: id)) is no longer available."
        }
    }
}

public enum JARVISPlugCatalog {
    /// Returns every daemon-advertised plug, including stale entries. Entity
    /// queries may use these for name resolution, but writes must separately
    /// call `freshPlug` and fail closed.
    public static func descriptors(from snapshot: StateSnapshot) -> [JARVISPlugDescriptor] {
        guard let subsystem = snapshot.subsystems?.plugs,
              let plugs = subsystem.plugs else { return [] }
        // Overall snapshot staleness can come from unrelated Pi, service, or
        // network collectors. Only plug-scoped evidence may disable plugs.
        let sharedStale = snapshot.ok == false
            || subsystem.ok != true
            || subsystem.stale == true
        return plugs.map { id, state in
            JARVISPlugDescriptor(
                id: id,
                displayName: displayName(for: id),
                isOn: state.isOn,
                stale: sharedStale || state.ok != true || state.stale == true || state.isOn == nil
            )
        }
        .sorted {
            let ordered = $0.displayName.localizedCaseInsensitiveCompare($1.displayName)
            return ordered == .orderedSame ? $0.id < $1.id : ordered == .orderedAscending
        }
    }

    /// Validates that an exact daemon identifier is present and safe to use for
    /// a desired-state write. Cached or partially known state cannot pass.
    public static func freshPlug(id: String, in snapshot: StateSnapshot) throws -> JARVISPlugDescriptor {
        guard snapshot.ok,
              let subsystem = snapshot.subsystems?.plugs,
              subsystem.ok == true,
              subsystem.stale != true,
              let states = subsystem.plugs else {
            throw snapshot.subsystems?.plugs == nil ? JARVISPlugCatalogError.unavailable : .stale
        }
        guard let state = states[id] else { throw JARVISPlugCatalogError.unknownPlug(id) }
        guard state.ok == true, state.stale != true, state.isOn != nil else {
            throw JARVISPlugCatalogError.stale
        }
        return JARVISPlugDescriptor(
            id: id,
            displayName: displayName(for: id),
            isOn: state.isOn,
            stale: false
        )
    }

    /// Conservative speech matching. Exact normalized identifiers/titles win;
    /// otherwise return every prefix/containment match so Siri can disambiguate
    /// instead of selecting a plug using fuzzy guessing.
    public static func matching(_ spokenName: String, in descriptors: [JARVISPlugDescriptor]) -> [JARVISPlugDescriptor] {
        let query = normalizedName(spokenName)
        guard !query.isEmpty else { return descriptors }
        let exact = descriptors.filter {
            normalizedName($0.id) == query || normalizedName($0.displayName) == query
        }
        if !exact.isEmpty { return exact }
        return descriptors.filter {
            containsPhrase(query, in: normalizedName($0.id))
                || containsPhrase(query, in: normalizedName($0.displayName))
                || containsPhrase(normalizedName($0.displayName), in: query)
        }
    }

    public static func displayName(for id: String) -> String {
        let words = id
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
            .split(whereSeparator: { $0.isWhitespace })
        return words.map { raw in
            let word = String(raw)
            if word.count <= 2 { return word.uppercased() }
            return word.prefix(1).uppercased() + word.dropFirst()
        }
        .joined(separator: " ")
    }

    public static func normalizedName(_ value: String) -> String {
        let scalars = value.lowercased().unicodeScalars.map { scalar -> Character in
            CharacterSet.alphanumerics.contains(scalar) ? Character(String(scalar)) : " "
        }
        return String(scalars)
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")
    }

    private static func containsPhrase(_ phrase: String, in candidate: String) -> Bool {
        candidate == phrase
            || candidate.hasPrefix(phrase + " ")
            || candidate.hasSuffix(" " + phrase)
            || candidate.contains(" " + phrase + " ")
    }
}
