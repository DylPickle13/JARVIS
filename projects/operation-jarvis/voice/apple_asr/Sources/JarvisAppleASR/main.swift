import AVFAudio
import Darwin
import Foundation
import Speech

private enum Engine: String {
    case speech
    case dictation

    init(argument: String) throws {
        switch argument.lowercased() {
        case "speech", "apple", "apple-speech", "speech-transcriber":
            self = .speech
        case "dictation", "apple-dictation", "dictation-transcriber":
            self = .dictation
        default:
            throw CLIError("unsupported engine: \(argument)")
        }
    }

    var backendName: String {
        switch self {
        case .speech: "apple-speech"
        case .dictation: "apple-dictation"
        }
    }
}

private struct CLIError: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var errorDescription: String? { message }
}

private struct Arguments {
    let command: String
    let engine: Engine
    let requestedLocale: Locale
    let fileURL: URL?
    let contextualStrings: [String]

    init(_ raw: [String]) throws {
        guard let command = raw.first, ["health", "install-assets", "transcribe"].contains(command) else {
            throw CLIError("usage: jarvis-apple-asr <health|install-assets|transcribe> [--engine speech|dictation] [--locale en-CA] [--file input.wav] [--context phrase]")
        }

        var engine = Engine.speech
        var localeIdentifier = "en-CA"
        var fileURL: URL?
        var contexts: [String] = []
        var index = 1
        while index < raw.count {
            let option = raw[index]
            guard index + 1 < raw.count else {
                throw CLIError("missing value for \(option)")
            }
            let value = raw[index + 1]
            switch option {
            case "--engine":
                engine = try Engine(argument: value)
            case "--locale":
                localeIdentifier = value
            case "--file":
                fileURL = URL(fileURLWithPath: value)
            case "--context":
                let phrase = value.trimmingCharacters(in: .whitespacesAndNewlines)
                if !phrase.isEmpty, !contexts.contains(phrase), contexts.count < 100 {
                    contexts.append(phrase)
                }
            default:
                throw CLIError("unknown option: \(option)")
            }
            index += 2
        }

        if command == "transcribe", fileURL == nil {
            throw CLIError("--file is required for transcription")
        }

        self.command = command
        self.engine = engine
        self.requestedLocale = Locale(identifier: localeIdentifier)
        self.fileURL = fileURL
        self.contextualStrings = contexts
    }
}

private func assetStatusName(_ status: AssetInventory.Status) -> String {
    switch status {
    case .unsupported: "unsupported"
    case .supported: "supported"
    case .downloading: "downloading"
    case .installed: "installed"
    @unknown default: "unknown"
    }
}

private func emitJSON(_ payload: [String: Any], to handle: FileHandle = .standardOutput) {
    do {
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        handle.write(data)
        handle.write(Data("\n".utf8))
    } catch {
        handle.write(Data("{\"ok\":false,\"error\":\"failed to encode JSON\"}\n".utf8))
    }
}

private func selectedSpeechLocale(_ requested: Locale) async throws -> Locale {
    guard SpeechTranscriber.isAvailable else {
        throw CLIError("SpeechTranscriber is unavailable on this Mac")
    }
    guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: requested) else {
        throw CLIError("SpeechTranscriber does not support locale \(requested.identifier)")
    }
    return locale
}

private func selectedDictationLocale(_ requested: Locale) async throws -> Locale {
    guard let locale = await DictationTranscriber.supportedLocale(equivalentTo: requested) else {
        throw CLIError("DictationTranscriber does not support locale \(requested.identifier)")
    }
    return locale
}

private func speechModule(locale: Locale) -> SpeechTranscriber {
    SpeechTranscriber(locale: locale, preset: .transcription)
}

private func dictationModule(locale: Locale) -> DictationTranscriber {
    DictationTranscriber(
        locale: locale,
        contentHints: [.shortForm, .farField],
        transcriptionOptions: [.punctuation],
        reportingOptions: [],
        attributeOptions: []
    )
}

private func collectSpeechResults(_ transcriber: SpeechTranscriber) async throws -> String {
    var transcript = ""
    for try await result in transcriber.results {
        transcript += String(result.text.characters)
    }
    return transcript.split(whereSeparator: \Character.isWhitespace).joined(separator: " ")
}

private func collectDictationResults(_ transcriber: DictationTranscriber) async throws -> String {
    var transcript = ""
    for try await result in transcriber.results {
        transcript += String(result.text.characters)
    }
    return transcript.split(whereSeparator: \Character.isWhitespace).joined(separator: " ")
}

private func configureContext(_ analyzer: SpeechAnalyzer, phrases: [String]) async throws {
    guard !phrases.isEmpty else { return }
    let context = AnalysisContext()
    context.contextualStrings = [.general: Array(phrases.prefix(100))]
    try await analyzer.setContext(context)
}

private func requireInstalled(_ modules: [any SpeechModule], locale: Locale) async throws {
    let status = await AssetInventory.status(forModules: modules)
    guard status == .installed else {
        throw CLIError("speech assets for \(locale.identifier) are \(assetStatusName(status)); run install-assets first")
    }
}

private func installAssets(_ modules: [any SpeechModule], locale: Locale) async throws -> [String: Any] {
    var status = await AssetInventory.status(forModules: modules)
    if status != .installed {
        guard status != .unsupported else {
            throw CLIError("speech assets for \(locale.identifier) are unsupported")
        }
        if let request = try await AssetInventory.assetInstallationRequest(supporting: modules) {
            try await request.downloadAndInstall()
        }
        status = await AssetInventory.status(forModules: modules)
    }
    guard status == .installed else {
        throw CLIError("speech assets for \(locale.identifier) did not finish installing; status=\(assetStatusName(status))")
    }
    let reserved = try await AssetInventory.reserve(locale: locale)
    let reservedLocales = await AssetInventory.reservedLocales
    let localeReserved = reserved || reservedLocales.contains(where: { $0.identifier == locale.identifier })
    return [
        "assetStatus": assetStatusName(status),
        "localeReserved": localeReserved,
    ]
}

private func health(arguments: Arguments) async throws -> [String: Any] {
    switch arguments.engine {
    case .speech:
        let locale = try await selectedSpeechLocale(arguments.requestedLocale)
        let module = speechModule(locale: locale)
        let status = await AssetInventory.status(forModules: [module])
        return [
            "ok": true,
            "command": "health",
            "engine": arguments.engine.backendName,
            "requestedLocale": arguments.requestedLocale.identifier,
            "locale": locale.identifier,
            "available": SpeechTranscriber.isAvailable,
            "assetStatus": assetStatusName(status),
        ]
    case .dictation:
        let locale = try await selectedDictationLocale(arguments.requestedLocale)
        let module = dictationModule(locale: locale)
        let status = await AssetInventory.status(forModules: [module])
        return [
            "ok": true,
            "command": "health",
            "engine": arguments.engine.backendName,
            "requestedLocale": arguments.requestedLocale.identifier,
            "locale": locale.identifier,
            "available": true,
            "assetStatus": assetStatusName(status),
        ]
    }
}

private func install(arguments: Arguments) async throws -> [String: Any] {
    var response: [String: Any]
    switch arguments.engine {
    case .speech:
        let locale = try await selectedSpeechLocale(arguments.requestedLocale)
        let module = speechModule(locale: locale)
        response = try await installAssets([module], locale: locale)
        response["locale"] = locale.identifier
    case .dictation:
        let locale = try await selectedDictationLocale(arguments.requestedLocale)
        let module = dictationModule(locale: locale)
        response = try await installAssets([module], locale: locale)
        response["locale"] = locale.identifier
    }
    response["ok"] = true
    response["command"] = "install-assets"
    response["engine"] = arguments.engine.backendName
    response["requestedLocale"] = arguments.requestedLocale.identifier
    return response
}

private func transcribe(arguments: Arguments) async throws -> [String: Any] {
    guard let fileURL = arguments.fileURL else {
        throw CLIError("--file is required for transcription")
    }
    guard FileManager.default.fileExists(atPath: fileURL.path) else {
        throw CLIError("audio file does not exist")
    }

    let started = ContinuousClock.now
    let audioFile = try AVAudioFile(forReading: fileURL)
    let transcript: String
    let selectedLocale: Locale

    switch arguments.engine {
    case .speech:
        selectedLocale = try await selectedSpeechLocale(arguments.requestedLocale)
        let module = speechModule(locale: selectedLocale)
        try await requireInstalled([module], locale: selectedLocale)
        async let collected = collectSpeechResults(module)
        let analyzer = SpeechAnalyzer(
            modules: [module],
            options: .init(priority: .userInitiated, modelRetention: .lingering)
        )
        try await configureContext(analyzer, phrases: arguments.contextualStrings)
        if let lastSample = try await analyzer.analyzeSequence(from: audioFile) {
            try await analyzer.finalizeAndFinish(through: lastSample)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        transcript = try await collected
    case .dictation:
        selectedLocale = try await selectedDictationLocale(arguments.requestedLocale)
        let module = dictationModule(locale: selectedLocale)
        try await requireInstalled([module], locale: selectedLocale)
        async let collected = collectDictationResults(module)
        let analyzer = SpeechAnalyzer(
            modules: [module],
            options: .init(priority: .userInitiated, modelRetention: .lingering)
        )
        try await configureContext(analyzer, phrases: arguments.contextualStrings)
        if let lastSample = try await analyzer.analyzeSequence(from: audioFile) {
            try await analyzer.finalizeAndFinish(through: lastSample)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        transcript = try await collected
    }

    let elapsed = ContinuousClock.now - started
    let components = elapsed.components
    let elapsedSeconds = Double(components.seconds) + Double(components.attoseconds) / 1_000_000_000_000_000_000
    return [
        "ok": true,
        "command": "transcribe",
        "engine": arguments.engine.backendName,
        "requestedLocale": arguments.requestedLocale.identifier,
        "locale": selectedLocale.identifier,
        "transcript": transcript,
        "elapsedSeconds": elapsedSeconds,
    ]
}

@main
private struct JarvisAppleASR {
    static func main() async {
        do {
            let arguments = try Arguments(Array(CommandLine.arguments.dropFirst()))
            let response: [String: Any]
            switch arguments.command {
            case "health":
                response = try await health(arguments: arguments)
            case "install-assets":
                response = try await install(arguments: arguments)
            case "transcribe":
                response = try await transcribe(arguments: arguments)
            default:
                throw CLIError("unsupported command: \(arguments.command)")
            }
            emitJSON(response)
        } catch {
            emitJSON(
                [
                    "ok": false,
                    "error": error.localizedDescription,
                    "errorType": String(describing: type(of: error)),
                ],
                to: .standardError
            )
            Darwin.exit(EXIT_FAILURE)
        }
    }
}
