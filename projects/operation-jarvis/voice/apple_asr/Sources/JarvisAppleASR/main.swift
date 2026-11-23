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
    let sampleRate: Double
    let finalizeEvery: Double?

    init(_ raw: [String]) throws {
        guard let command = raw.first, ["health", "install-assets", "transcribe", "stream"].contains(command) else {
            throw CLIError("usage: jarvis-apple-asr <health|install-assets|transcribe|stream> [--engine speech|dictation] [--locale en-CA] [--file input.wav] [--context phrase] [--sample-rate 16000] [--finalize-every 10]")
        }

        var engine = Engine.speech
        var localeIdentifier = "en-CA"
        var fileURL: URL?
        var contexts: [String] = []
        var sampleRate = 16000.0
        var finalizeEvery: Double?
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
            case "--sample-rate":
                guard let rate = Double(value), rate > 0 else {
                    throw CLIError("invalid sample rate: \(value)")
                }
                sampleRate = rate
            case "--finalize-every":
                guard let seconds = Double(value), seconds > 0 else {
                    throw CLIError("invalid finalize interval: \(value)")
                }
                finalizeEvery = seconds
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
        self.sampleRate = sampleRate
        self.finalizeEvery = finalizeEvery
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

// MARK: - Stream mode (resident dictation worker)

/// Lock-guarded stream-time clock, updated by the PCM reader thread.
/// Stream time (not wall clock) drives `finalizeAndFinish(through:)` so the
/// worker stays correct even when it fast-forwards through a backlog.
private final class StreamClock: @unchecked Sendable {
    private let lock = NSLock()
    private var time: Double = 0
    func set(_ t: Double) {
        lock.lock()
        time = t
        lock.unlock()
    }
    func get() -> Double {
        lock.lock()
        defer { lock.unlock() }
        return time
    }
}

/// Reads 16-bit mono PCM from stdin and yields `AnalyzerInput` buffers
/// (300 ms chunks) stamped with stream time, for `SpeechAnalyzer.analyzeSequence(_:)`.
/// NOTE: `AnalyzerInput`'s buffer inits require **Int16 PCM** (the framework
/// traps on Float32 — "Failed precondition: Audio sample data must be 16-bit
/// signed integers"), so the buffer is built as `.pcmFormatInt16` and the
/// stdin bytes (already Int16) are copied in directly.
private func makeStdinPCMStream(sampleRate: Double, chunkFrames: Int, clock: StreamClock) -> AsyncStream<AnalyzerInput> {
    let (stream, continuation) = AsyncStream<AnalyzerInput>.makeStream()
    guard let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: 1, interleaved: false) else {
        continuation.finish()
        return stream
    }
    Thread.detachNewThread {
        let handle = FileHandle.standardInput
        var carry = [Int16]()
        var nextSample: Int64 = 0
        let timescale = Int32(sampleRate)
        while true {
            let data = handle.readData(ofLength: 4096)
            if data.isEmpty { break }
            data.withUnsafeBytes { raw in
                carry.append(contentsOf: raw.bindMemory(to: Int16.self))
            }
            while carry.count >= chunkFrames {
                let frame = Array(carry.prefix(chunkFrames))
                carry.removeFirst(chunkFrames)
                guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(chunkFrames)) else { continue }
                buffer.frameLength = AVAudioFrameCount(chunkFrames)
                for (i, s) in frame.enumerated() {
                    buffer.int16ChannelData![0][i] = s
                }
                // Sample-accurate timestamps (no Double drift — the framework
                // rejects inputs whose start "overlaps or precedes" the prior).
                let input = AnalyzerInput(
                    buffer: buffer,
                    bufferStartTime: CMTime(value: nextSample, timescale: timescale)
                )
                nextSample += Int64(chunkFrames)
                clock.set(Double(nextSample) / sampleRate)
                continuation.yield(input)
            }
        }
        // Flush the tail (partial chunk) so the final words reach the engine.
        if carry.count > 0,
           let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(carry.count)) {
            buffer.frameLength = AVAudioFrameCount(carry.count)
            for (i, s) in carry.enumerated() {
                buffer.int16ChannelData![0][i] = s
            }
            let input = AnalyzerInput(
                buffer: buffer,
                bufferStartTime: CMTime(value: nextSample, timescale: timescale)
            )
            clock.set(Double(nextSample) / sampleRate)
            continuation.yield(input)
        }
        continuation.finish()
    }
    return stream
}

/// Consumes the dictation results stream, emitting one JSON line per result.
/// Each result carries its stream-time range; the server maps stream time to
/// wall clock and merges overlapping ranges (revisable-partials safe).
private func consumeDictationResults(_ module: DictationTranscriber) async {
    do {
        var seq = 0
        for try await result in module.results {
            emitJSON([
                "type": "result",
                "seq": seq,
                "text": String(result.text.characters),
                "tStart": CMTimeGetSeconds(result.range.start),
                "tEnd": CMTimeGetSeconds(result.range.end),
                "finalizedAt": CMTimeGetSeconds(result.resultsFinalizationTime),
            ])
            seq += 1
        }
    } catch {
        emitJSON(["type": "result-error", "error": error.localizedDescription], to: .standardError)
    }
}

private func stream(arguments: Arguments) async throws -> [String: Any] {
    guard arguments.engine == .dictation else {
        throw CLIError("stream mode supports the dictation engine only")
    }
    let chunkFrames = Int((arguments.sampleRate * 0.3).rounded())  // 300 ms
    let locale = try await selectedDictationLocale(arguments.requestedLocale)
    let module = dictationModule(locale: locale)
    try await requireInstalled([module], locale: locale)

    let compatible = await module.availableCompatibleAudioFormats
    let summary = compatible.map { String(format: "%.0fHz/%dch", $0.sampleRate, Int($0.channelCount)) }
    FileHandle.standardError.write(Data(("compatible formats: \(summary.joined(separator: ", "))\n").utf8))

    // Start consuming results before feeding, mirroring the transcribe path.
    async let resultsDone: Void = consumeDictationResults(module)
    let analyzer = SpeechAnalyzer(
        modules: [module],
        options: .init(priority: .userInitiated, modelRetention: .lingering)
    )
    try await configureContext(analyzer, phrases: arguments.contextualStrings)

    emitJSON([
        "type": "started",
        "engine": arguments.engine.backendName,
        "locale": locale.identifier,
        "sampleRate": Int(arguments.sampleRate),
        "chunkMs": Int((Double(chunkFrames) / arguments.sampleRate) * 1000),
    ])

    let clock = StreamClock()
    let input = makeStdinPCMStream(sampleRate: arguments.sampleRate, chunkFrames: chunkFrames, clock: clock)
    do {
        let feedDone = StreamClock()
        let feedTask = Task {
            do {
                _ = try await analyzer.analyzeSequence(input)
            } catch {
                emitJSON(["type": "analyze-error", "error": error.localizedDescription], to: .standardError)
            }
            feedDone.set(1)
        }
        // Rolling finalization: the dictation engine only emits a result when
        // an utterance is complete (silence-gated), so periodically finalize
        // "through" the current stream time to flush completed utterances.
        // NOTE: `finalize(through:)` is non-terminal — the analyzer keeps
        // accepting input afterwards. (`finalizeAndFinish(through:)` ends the
        // sequence, which would kill the rolling stream.)
        if let every = arguments.finalizeEvery, every > 0 {
            var lastFinalized = 0.0
            while feedDone.get() < 1 {
                try await Task.sleep(for: .seconds(1))
                let t = clock.get()
                if t - lastFinalized >= every {
                    do {
                        try await analyzer.finalize(
                            through: CMTime(value: Int64(t * arguments.sampleRate), timescale: Int32(arguments.sampleRate))
                        )
                        lastFinalized = t
                    } catch {
                        emitJSON(["type": "finalize-error", "error": error.localizedDescription], to: .standardError)
                    }
                }
            }
        }
        await feedTask.value
        try await analyzer.finalizeAndFinishThroughEndOfInput()
    } catch {
        emitJSON(["type": "analyze-error", "error": error.localizedDescription], to: .standardError)
        await analyzer.cancelAndFinishNow()
    }
    await resultsDone
    emitJSON(["type": "done"])
    return ["ok": true, "command": "stream"]
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
            case "stream":
                response = try await stream(arguments: arguments)
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
