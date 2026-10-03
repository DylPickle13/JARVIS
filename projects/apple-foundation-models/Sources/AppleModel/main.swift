import Foundation
import FoundationModels
import ImageIO
import Darwin

struct CLIError: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { description = message }
}

struct Arguments {
    var command = "help"
    var instructions = "Be helpful and concise."
    var text: [String] = []
    var images: [String] = []
    var maxTokens = 1024
    var json = false
    var stream = false
    var stdin = false

    init(_ args: [String]) throws {
        guard let first = args.first else { return }
        command = first
        guard ["ask", "status", "help", "--help", "-h"].contains(first) else {
            throw CLIError("Unknown command: \(first). Use apple-model help.")
        }
        var i = 1
        while i < args.count {
            let arg = args[i]
            func value() throws -> String {
                i += 1
                guard i < args.count else { throw CLIError("Missing value for \(arg)") }
                return args[i]
            }
            switch arg {
            case "--json": json = true
            case "--stream": stream = true
            case "--stdin": stdin = true
            case "--instructions": instructions = try value()
            case "--image": images.append(try value())
            case "--max-tokens":
                let raw = try value()
                guard let n = Int(raw), (1...2048).contains(n) else {
                    throw CLIError("--max-tokens must be an integer from 1 to 2048.")
                }
                maxTokens = n
            case "--": text.append(contentsOf: args.dropFirst(i + 1)); i = args.count
            default:
                guard !arg.hasPrefix("-") else { throw CLIError("Unknown option: \(arg)") }
                text.append(arg)
            }
            i += 1
        }
        if command != "ask" && (stream || stdin || !images.isEmpty || !text.isEmpty || instructions != "Be helpful and concise." || maxTokens != 1024) {
            throw CLIError("Generation options are only valid with ask.")
        }
    }
}

func output(_ text: String, to handle: FileHandle = .standardOutput) {
    handle.write(Data(text.utf8))
}
func emit(_ object: [String: Any], to handle: FileHandle = .standardOutput) throws {
    let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
    handle.write(data)
    handle.write(Data([10]))
}

@main struct AppleModel {
    static let help = """
    apple-model — local Apple Foundation Models (macOS 27+)

    apple-model status [--json]
    apple-model ask [OPTIONS] [PROMPT]

    --image PATH          Local image; repeat for multiple images (up to 8)
    --instructions TEXT   System instructions
    --stdin               Read UTF-8 stdin (also automatic when piped)
    --max-tokens N        Output cap, 1–2048 (default 1024)
    --stream              Stream text; with --json emit NDJSON events
    --json                JSON response envelope (not guided generation)
    --                    Treat remaining arguments as prompt text

    Text and images only. No native audio/video input, tools, cloud fallback,
    persistent history, or silent context truncation. Ctrl-C terminates the process.
    """

    static func main() async {
        // Default SIGINT/SIGTERM behavior intentionally terminates this short-lived CLI.
        // Do not keep a resident service or continue a request after caller cancellation.
        let raw = Array(CommandLine.arguments.dropFirst())
        var json = false
        var stream = false
        do {
            let args = try Arguments(raw)
            json = args.json
            stream = args.stream
            if ["help", "--help", "-h"].contains(args.command) {
                output(help + "\n")
                return
            }
            let model = SystemLanguageModel.default
            if args.command == "status" {
                let status: [String: Any] = [
                    "backend": "SystemLanguageModel.default", "localOnly": true,
                    "available": model.isAvailable, "availability": String(describing: model.availability),
                    "variant": model.variant.displayName,
                    "publicOnDeviceVariants": [SystemLanguageModel.Variant.core3.displayName, SystemLanguageModel.Variant.coreAdvanced3.displayName],
                    "contextTokens": model.contextSize, "cliMaxOutputTokens": 2048,
                    "vision": model.capabilities.contains(.vision),
                    "reasoning": model.capabilities.contains(.reasoning),
                    "guidedGeneration": model.capabilities.contains(.guidedGeneration),
                    "toolCalling": model.capabilities.contains(.toolCalling),
                    "cliInputModalities": ["text", "image"], "modelIdentity": NSNull()
                ]
                if json { try emit(status) }
                else {
                    output("Backend: SystemLanguageModel.default (on-device only)\nAvailability: \(model.availability)\nVariant: \(model.variant.displayName)\nContext: \(model.contextSize) tokens\nVision: \(model.capabilities.contains(.vision))\nReasoning: \(model.capabilities.contains(.reasoning))\nCLI input: text + images\nExact weights/version: not exposed\n")
                }
                return
            }
            guard model.isAvailable else { throw CLIError("On-device model unavailable: \(model.availability). Enable Apple Intelligence and allow its model download to finish.") }
            guard args.images.count <= 8 else { throw CLIError("At most 8 images per request.") }
            if !args.images.isEmpty && !model.capabilities.contains(.vision) {
                throw CLIError("The selected on-device model does not advertise vision support.")
            }
            var text = args.text.joined(separator: " ")
            if args.stdin || isatty(STDIN_FILENO) == 0 {
                let data = FileHandle.standardInput.readDataToEndOfFile()
                guard let input = String(data: data, encoding: .utf8) else { throw CLIError("stdin must be UTF-8 text; pass images with --image.") }
                if !input.isEmpty { text += (text.isEmpty ? "" : "\n\n") + input }
            }
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !args.images.isEmpty else { throw CLIError("Supply a prompt, piped text, or --image.") }
            if text.isEmpty { text = "Describe the supplied images." }
            var attachments: [Attachment<ImageAttachmentContent>] = []
            for path in args.images {
                let expanded = (path as NSString).expandingTildeInPath
                let url = URL(fileURLWithPath: expanded)
                guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                      CGImageSourceGetCount(source) > 0,
                      CGImageSourceCreateImageAtIndex(source, 0, nil) != nil else {
                    throw CLIError("Cannot decode local image: \(path). Audio/video and remote URLs are not accepted.")
                }
                if CGImageSourceGetCount(source) > 1 { throw CLIError("Multi-frame image not accepted: \(path). Extract individual frames first.") }
                attachments.append(Attachment(imageURL: url))
            }
            let prompt = Prompt {
                text
                for (index, attachment) in attachments.enumerated() {
                    "Image \(index + 1):"
                    attachment
                }
            }
            let session = LanguageModelSession(model: model, instructions: args.instructions)
            let options = GenerationOptions(maximumResponseTokens: args.maxTokens)
            if stream {
                var previous = ""
                for try await snapshot in session.streamResponse(to: prompt, options: options) {
                    let current = snapshot.content
                    guard current.hasPrefix(previous) else { throw CLIError("Non-append response received; retry without --stream.") }
                    let delta = String(current.dropFirst(previous.count))
                    if !delta.isEmpty {
                        if json { try emit(["type": "delta", "text": delta]) }
                        else { output(delta) }
                    }
                    previous = current
                }
                if json { try emit(["type": "done", "text": previous]) }
                else { output("\n") }
            } else {
                let response = try await session.respond(to: prompt, options: options)
                if json { try emit(["text": response.content, "backend": "SystemLanguageModel.default", "localOnly": true]) }
                else { output(response.content + "\n") }
            }
        } catch {
            if json {
                try? emit(["type": "error", "error": String(describing: error)], to: stream ? .standardOutput : .standardError)
            } else { output("apple-model: \(error)\n", to: .standardError) }
            exit(1)
        }
    }
}
