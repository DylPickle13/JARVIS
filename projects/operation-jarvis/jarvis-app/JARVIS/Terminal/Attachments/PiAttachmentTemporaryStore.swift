import CryptoKit
import Foundation

actor PiAttachmentTemporaryStore {
    private static let directoryPrefix = "JARVIS-Pi-Attach-"
    private var operationDirectories: [UUID: URL] = [:]

    init() {
        let temporaryRoot = FileManager.default.temporaryDirectory
        if let entries = try? FileManager.default.contentsOfDirectory(
            at: temporaryRoot,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ) {
            for entry in entries where
                entry.lastPathComponent.hasPrefix(Self.directoryPrefix)
                    || entry.lastPathComponent.hasPrefix("JARVIS-Pi-Photo-") {
                try? FileManager.default.removeItem(at: entry)
            }
        }
    }

    static func sanitizeDisplayName(_ value: String) -> String {
        let leaf = (value as NSString).lastPathComponent.precomposedStringWithCanonicalMapping
        let replaced = String(leaf.unicodeScalars.map { scalar -> Character in
            if scalar.value < 0x20 || scalar.value == 0x7f || "/\\:".unicodeScalars.contains(scalar) {
                return "_"
            }
            return Character(String(scalar))
        }).trimmingCharacters(in: .whitespacesAndNewlines)
        let safe = replaced.isEmpty ? "attachment" : replaced
        let rawExtension = (safe as NSString).pathExtension
        let extensionSuffix = rawExtension.isEmpty ? "" : ".\(rawExtension)"
        let extensionToKeep = extensionSuffix.utf8.count <= 32 ? extensionSuffix : ""
        let rawStem = extensionToKeep.isEmpty
            ? safe
            : (safe as NSString).deletingPathExtension
        let stem = truncateUtf8(
            rawStem.isEmpty ? "attachment" : rawStem,
            maximumBytes: 160 - extensionToKeep.utf8.count
        )
        return (stem.isEmpty ? "attachment" : stem) + extensionToKeep
    }

    private static func truncateUtf8(_ value: String, maximumBytes: Int) -> String {
        var bounded = ""
        for character in value {
            let candidate = bounded + String(character)
            guard candidate.utf8.count <= maximumBytes else { break }
            bounded = candidate
        }
        return bounded
    }

    func importSecurityScopedFile(
        _ sourceURL: URL,
        workflowID: UUID,
        limits: PiAttachmentLimits
    ) throws -> PiAttachmentLocalFile {
        let accessing = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if accessing { sourceURL.stopAccessingSecurityScopedResource() }
        }

        let coordinator = NSFileCoordinator()
        var coordinationError: NSError?
        var result: Result<PiAttachmentLocalFile, Error>?
        coordinator.coordinate(
            readingItemAt: sourceURL,
            options: [],
            error: &coordinationError
        ) { coordinatedURL in
            result = Result {
                try importRegularFile(
                    coordinatedURL,
                    displayName: sourceURL.lastPathComponent,
                    workflowID: workflowID,
                    limits: limits
                )
            }
        }
        if let result { return try result.get() }
        if coordinationError != nil {
            throw PiAttachmentTransportError.rejected(
                "The selected File Provider item is unavailable."
            )
        }
        throw PiAttachmentTransportError.rejected("The selected file could not be read.")
    }

    func importTransferredPhoto(
        _ sourceURL: URL,
        displayName: String,
        workflowID: UUID,
        limits: PiAttachmentLimits
    ) throws -> PiAttachmentLocalFile {
        guard let transferDirectory = Self.photoTransferDirectory(for: sourceURL) else {
            throw PiAttachmentTransportError.invalidRequest
        }
        defer {
            try? FileManager.default.removeItem(at: transferDirectory)
        }
        return try importRegularFile(
            sourceURL,
            displayName: displayName,
            workflowID: workflowID,
            limits: limits
        )
    }

    func remove(_ file: PiAttachmentLocalFile) {
        let parent = file.url.deletingLastPathComponent().standardizedFileURL
        guard operationDirectories.values.contains(where: {
            $0.standardizedFileURL == parent
        }) else { return }
        try? FileManager.default.removeItem(at: file.url)
    }

    func discardTransferredPhoto(_ sourceURL: URL) {
        guard let directory = Self.photoTransferDirectory(for: sourceURL) else { return }
        try? FileManager.default.removeItem(at: directory)
    }

    func cleanup(workflowID: UUID) {
        if let directory = operationDirectories.removeValue(forKey: workflowID) {
            try? FileManager.default.removeItem(at: directory)
        }
    }

    private static func photoTransferDirectory(for sourceURL: URL) -> URL? {
        let directory = sourceURL.deletingLastPathComponent().standardizedFileURL
        let temporaryRoot = FileManager.default.temporaryDirectory.standardizedFileURL
        guard directory.deletingLastPathComponent() == temporaryRoot,
              directory.lastPathComponent.hasPrefix("JARVIS-Pi-Photo-") else {
            return nil
        }
        return directory
    }

    private func privateDirectory(for workflowID: UUID) throws -> URL {
        if let directory = operationDirectories[workflowID] { return directory }
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(Self.directoryPrefix + workflowID.uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: false,
            attributes: [
                .posixPermissions: 0o700,
                .protectionKey: FileProtectionType.complete,
            ]
        )
        do {
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            var mutableDirectory = directory
            try mutableDirectory.setResourceValues(values)
            operationDirectories[workflowID] = directory
            return directory
        } catch {
            try? FileManager.default.removeItem(at: directory)
            throw error
        }
    }

    private func importRegularFile(
        _ sourceURL: URL,
        displayName: String,
        workflowID: UUID,
        limits: PiAttachmentLimits
    ) throws -> PiAttachmentLocalFile {
        try Task.checkCancellation()
        guard limits.isValid else { throw PiAttachmentTransportError.invalidRequest }
        let values = try sourceURL.resourceValues(forKeys: [
            .isRegularFileKey,
            .isSymbolicLinkKey,
            .fileSizeKey,
        ])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              let fileSize = values.fileSize, fileSize >= 0 else {
            throw PiAttachmentTransportError.rejected("Only regular files can be attached.")
        }
        let declaredSize = Int64(fileSize)
        guard declaredSize <= limits.maxFileBytes else {
            throw PiAttachmentTransportError.rejected("The selected file exceeds the per-file attachment limit.")
        }

        let safeName = Self.sanitizeDisplayName(displayName)
        let sourceExtension = (safeName as NSString).pathExtension
        let safeExtension = sourceExtension.range(
            of: "^[A-Za-z0-9]{1,16}$",
            options: .regularExpression
        ) == nil ? "" : ".\(sourceExtension.lowercased())"
        let destination = try privateDirectory(for: workflowID)
            .appendingPathComponent(UUID().uuidString.lowercased() + safeExtension)

        guard FileManager.default.createFile(
            atPath: destination.path,
            contents: nil,
            attributes: [
                .posixPermissions: 0o600,
                .protectionKey: FileProtectionType.complete,
            ]
        ) else {
            throw PiAttachmentTransportError.rejected("Could not create private attachment storage.")
        }

        var input: FileHandle?
        var output: FileHandle?
        var hash = SHA256()
        var written: Int64 = 0
        do {
            let inputHandle = try FileHandle(forReadingFrom: sourceURL)
            input = inputHandle
            let outputHandle = try FileHandle(forWritingTo: destination)
            output = outputHandle
            while let chunk = try inputHandle.read(upToCount: PiAttachmentProtocol.chunkSize), !chunk.isEmpty {
                try Task.checkCancellation()
                written += Int64(chunk.count)
                guard written <= declaredSize, written <= limits.maxFileBytes else {
                    throw PiAttachmentTransportError.rejected("The selected file changed or exceeded its limit while copying.")
                }
                hash.update(data: chunk)
                try outputHandle.write(contentsOf: chunk)
            }
            try Task.checkCancellation()
            try outputHandle.synchronize()
            try inputHandle.close()
            try outputHandle.close()
            guard written == declaredSize else {
                throw PiAttachmentTransportError.rejected("The selected file changed size while copying.")
            }
            var resourceValues = URLResourceValues()
            resourceValues.isExcludedFromBackup = true
            var mutableDestination = destination
            try mutableDestination.setResourceValues(resourceValues)
            let digest = hash.finalize().map { String(format: "%02x", $0) }.joined()
            return PiAttachmentLocalFile(
                id: UUID(),
                displayName: safeName,
                url: destination,
                sizeBytes: written,
                sha256: digest
            )
        } catch {
            try? input?.close()
            try? output?.close()
            try? FileManager.default.removeItem(at: destination)
            throw error
        }
    }
}
