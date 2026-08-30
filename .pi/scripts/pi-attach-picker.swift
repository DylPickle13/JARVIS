import AppKit
import Foundation

private struct ExistingAttachment: Codable {
    let id: String
    let name: String
    let sizeBytes: Int64
}

private struct AttachmentLimits: Codable {
    let maxFiles: Int
    let maxFileBytes: Int64
    let maxTotalBytes: Int64
}

private struct PickerRequest: Codable {
    let version: Int
    let existing: [ExistingAttachment]
    let limits: AttachmentLimits
}

private struct PickerResult: Codable {
    let version: Int
    let cancelled: Bool
    let keepIds: [String]
    let paths: [String]
}

private enum AttachmentRow {
    case existing(ExistingAttachment)
    case added(url: URL, sizeBytes: Int64)

    var name: String {
        switch self {
        case .existing(let item): return item.name
        case .added(let url, _): return url.lastPathComponent
        }
    }

    var sizeBytes: Int64 {
        switch self {
        case .existing(let item): return item.sizeBytes
        case .added(_, let sizeBytes): return sizeBytes
        }
    }

    var source: String {
        switch self {
        case .existing: return "Staged"
        case .added: return "New"
        }
    }
}

private func emit(_ result: PickerResult) {
    let encoder = JSONEncoder()
    guard let data = try? encoder.encode(result) else {
        FileHandle.standardError.write(Data("Could not encode attachment picker result.\n".utf8))
        exit(1)
    }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

private func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("\(message)\n".utf8))
    exit(2)
}

private final class PickerController: NSObject, NSApplicationDelegate, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate {
    private let request: PickerRequest
    private var rows: [AttachmentRow]
    private var window: NSWindow!
    private var tableView: NSTableView!
    private var finishing = false

    init(request: PickerRequest) {
        self.request = request
        self.rows = request.existing.map(AttachmentRow.existing)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildWindow()
        NSApplication.shared.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()

        if rows.isEmpty {
            DispatchQueue.main.async { [weak self] in
                self?.openFilePanel(isInitialSelection: true)
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        finish(cancelled: true)
        return false
    }

    func numberOfRows(in tableView: NSTableView) -> Int {
        rows.count
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard rows.indices.contains(row), let identifier = tableColumn?.identifier else { return nil }
        let item = rows[row]
        let value: String
        switch identifier.rawValue {
        case "size":
            value = ByteCountFormatter.string(fromByteCount: item.sizeBytes, countStyle: .file)
        case "source":
            value = item.source
        default:
            value = item.name
        }

        let cell = NSTableCellView()
        let label = NSTextField(labelWithString: value)
        label.translatesAutoresizingMaskIntoConstraints = false
        label.lineBreakMode = .byTruncatingMiddle
        cell.addSubview(label)
        cell.textField = label
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 4),
            label.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -4),
            label.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
        ])
        return cell
    }

    @objc private func addFiles(_ sender: Any?) {
        openFilePanel(isInitialSelection: false)
    }

    @objc private func removeSelected(_ sender: Any?) {
        let selected = tableView.selectedRowIndexes
        guard !selected.isEmpty else {
            NSSound.beep()
            return
        }
        for index in selected.reversed() {
            rows.remove(at: index)
        }
        tableView.reloadData()
    }

    @objc private func clearFiles(_ sender: Any?) {
        rows.removeAll()
        tableView.reloadData()
    }

    @objc private func cancel(_ sender: Any?) {
        finish(cancelled: true)
    }

    @objc private func done(_ sender: Any?) {
        finish(cancelled: false)
    }

    private func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 680, height: 420),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Attachments for the next Pi message"
        window.delegate = self
        window.center()
        window.isReleasedWhenClosed = false

        let content = NSView()
        content.translatesAutoresizingMaskIntoConstraints = false
        window.contentView = content

        let message = NSTextField(wrappingLabelWithString: "Add files, remove staged files, or clear the list. Changes are applied only when you click Done; Cancel preserves the current selection.")
        message.translatesAutoresizingMaskIntoConstraints = false

        tableView = NSTableView()
        tableView.delegate = self
        tableView.dataSource = self
        tableView.allowsMultipleSelection = true
        tableView.usesAlternatingRowBackgroundColors = true
        tableView.headerView = NSTableHeaderView()
        tableView.setAccessibilityLabel("Files staged for the next Pi message")

        let nameColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("name"))
        nameColumn.title = "File"
        nameColumn.width = 430
        nameColumn.minWidth = 220
        let sizeColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("size"))
        sizeColumn.title = "Size"
        sizeColumn.width = 110
        let sourceColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("source"))
        sourceColumn.title = "Status"
        sourceColumn.width = 80
        tableView.addTableColumn(nameColumn)
        tableView.addTableColumn(sizeColumn)
        tableView.addTableColumn(sourceColumn)

        let scrollView = NSScrollView()
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = true
        scrollView.borderType = .bezelBorder
        scrollView.documentView = tableView

        let addButton = NSButton(title: "Add Files…", target: self, action: #selector(addFiles(_:)))
        let removeButton = NSButton(title: "Remove Selected", target: self, action: #selector(removeSelected(_:)))
        let clearButton = NSButton(title: "Clear", target: self, action: #selector(clearFiles(_:)))
        let cancelButton = NSButton(title: "Cancel", target: self, action: #selector(cancel(_:)))
        cancelButton.keyEquivalent = "\u{1b}"
        let doneButton = NSButton(title: "Done", target: self, action: #selector(done(_:)))
        doneButton.keyEquivalent = "\r"
        doneButton.bezelStyle = .rounded

        let leftButtons = NSStackView(views: [addButton, removeButton, clearButton])
        leftButtons.translatesAutoresizingMaskIntoConstraints = false
        leftButtons.orientation = .horizontal
        leftButtons.spacing = 8
        let rightButtons = NSStackView(views: [cancelButton, doneButton])
        rightButtons.translatesAutoresizingMaskIntoConstraints = false
        rightButtons.orientation = .horizontal
        rightButtons.spacing = 8

        content.addSubview(message)
        content.addSubview(scrollView)
        content.addSubview(leftButtons)
        content.addSubview(rightButtons)

        NSLayoutConstraint.activate([
            message.topAnchor.constraint(equalTo: content.topAnchor, constant: 18),
            message.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 18),
            message.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -18),

            scrollView.topAnchor.constraint(equalTo: message.bottomAnchor, constant: 14),
            scrollView.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 18),
            scrollView.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -18),
            scrollView.bottomAnchor.constraint(equalTo: leftButtons.topAnchor, constant: -16),

            leftButtons.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 18),
            leftButtons.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -18),
            rightButtons.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -18),
            rightButtons.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -18),
            leftButtons.trailingAnchor.constraint(lessThanOrEqualTo: rightButtons.leadingAnchor, constant: -12),
        ])
    }

    private func openFilePanel(isInitialSelection: Bool) {
        guard !finishing else { return }
        let panel = NSOpenPanel()
        panel.title = "Add files to Pi"
        panel.message = "Choose one or more files to stage for your next message."
        panel.prompt = "Add"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        panel.resolvesAliases = true
        panel.treatsFilePackagesAsDirectories = false

        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self else { return }
            if response == .OK {
                self.add(urls: panel.urls)
            } else if isInitialSelection && self.rows.isEmpty {
                self.finish(cancelled: true)
            }
        }
    }

    private func add(urls: [URL]) {
        var additions: [(URL, Int64)] = []
        let existingPaths = Set(rows.compactMap { row -> String? in
            if case .added(let url, _) = row { return url.standardizedFileURL.path }
            return nil
        })
        var seenPaths = existingPaths

        do {
            for rawURL in urls {
                let url = rawURL.standardizedFileURL
                guard !seenPaths.contains(url.path) else { continue }
                let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                guard values.isRegularFile == true, let fileSize = values.fileSize, fileSize >= 0 else {
                    throw PickerValidationError("Only regular files can be attached: \(url.lastPathComponent)")
                }
                let size = Int64(fileSize)
                guard size <= request.limits.maxFileBytes else {
                    throw PickerValidationError("\(url.lastPathComponent) exceeds the per-file attachment limit.")
                }
                additions.append((url, size))
                seenPaths.insert(url.path)
            }

            guard rows.count + additions.count <= request.limits.maxFiles else {
                throw PickerValidationError("A maximum of \(request.limits.maxFiles) attachments may be staged at once.")
            }
            let total = rows.reduce(Int64(0)) { $0 + $1.sizeBytes } + additions.reduce(Int64(0)) { $0 + $1.1 }
            guard total <= request.limits.maxTotalBytes else {
                throw PickerValidationError("The selected files exceed the total staged-attachment limit.")
            }
            rows.append(contentsOf: additions.map { .added(url: $0.0, sizeBytes: $0.1) })
            tableView.reloadData()
        } catch {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "Could not add files"
            alert.informativeText = error.localizedDescription
            alert.beginSheetModal(for: window)
        }
    }

    private func finish(cancelled: Bool) {
        guard !finishing else { return }
        finishing = true
        let keepIds: [String]
        let paths: [String]
        if cancelled {
            keepIds = request.existing.map(\.id)
            paths = []
        } else {
            keepIds = rows.compactMap { row in
                if case .existing(let item) = row { return item.id }
                return nil
            }
            paths = rows.compactMap { row in
                if case .added(let url, _) = row { return url.path }
                return nil
            }
        }
        emit(PickerResult(version: 1, cancelled: cancelled, keepIds: keepIds, paths: paths))
        window.orderOut(nil)
        NSApplication.shared.stop(nil)
    }
}

private struct PickerValidationError: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var errorDescription: String? { message }
}

guard CommandLine.arguments.count == 2,
      let data = CommandLine.arguments[1].data(using: .utf8),
      let request = try? JSONDecoder().decode(PickerRequest.self, from: data),
      request.version == 1,
      request.limits.maxFiles > 0,
      request.limits.maxFileBytes > 0,
      request.limits.maxTotalBytes > 0,
      request.existing.count <= request.limits.maxFiles,
      request.existing.allSatisfy({ $0.sizeBytes >= 0 && $0.sizeBytes <= request.limits.maxFileBytes })
else {
    fail("The native attachment picker received an invalid request.")
}

let application = NSApplication.shared
private let controller = PickerController(request: request)
application.delegate = controller
application.setActivationPolicy(.regular)
application.run()
