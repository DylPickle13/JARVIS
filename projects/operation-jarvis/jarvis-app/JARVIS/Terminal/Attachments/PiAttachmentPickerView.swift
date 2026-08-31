import CoreTransferable
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

struct PiAttachmentPhotoTransfer: Transferable, Sendable {
    let url: URL
    let displayName: String

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .image, shouldAttemptToOpenInPlace: false) { received in
            let manager = FileManager.default
            let directory = manager.temporaryDirectory
                .appendingPathComponent("JARVIS-Pi-Photo-\(UUID().uuidString)", isDirectory: true)
            try manager.createDirectory(
                at: directory,
                withIntermediateDirectories: false,
                attributes: [
                    .posixPermissions: 0o700,
                    .protectionKey: FileProtectionType.complete,
                ]
            )
            do {
                var directoryValues = URLResourceValues()
                directoryValues.isExcludedFromBackup = true
                var mutableDirectory = directory
                try mutableDirectory.setResourceValues(directoryValues)
                let name = PiAttachmentTemporaryStore.sanitizeDisplayName(
                    received.file.lastPathComponent
                )
                let destination = directory.appendingPathComponent(UUID().uuidString.lowercased())
                let values = try received.file.resourceValues(forKeys: [
                    .isRegularFileKey,
                    .isSymbolicLinkKey,
                    .fileSizeKey,
                ])
                guard values.isRegularFile == true,
                      values.isSymbolicLink != true,
                      let fileSize = values.fileSize,
                      fileSize >= 0,
                      Int64(fileSize) <= 2 * 1024 * 1024 * 1024 else {
                    throw PiAttachmentTransportError.rejected("Only regular photo files can be attached.")
                }
                try manager.copyItem(at: received.file, to: destination)
                try manager.setAttributes(
                    [
                        .posixPermissions: 0o600,
                        .protectionKey: FileProtectionType.complete,
                    ],
                    ofItemAtPath: destination.path
                )
                var resourceValues = URLResourceValues()
                resourceValues.isExcludedFromBackup = true
                var mutableDestination = destination
                try mutableDestination.setResourceValues(resourceValues)
                return PiAttachmentPhotoTransfer(url: destination, displayName: name)
            } catch {
                try? manager.removeItem(at: directory)
                throw error
            }
        }
    }
}

struct PiAttachmentPickerView: View {
    @ObservedObject var controller: PiTerminalController

    @State private var photoItems: [PhotosPickerItem] = []
    @State private var showingFileImporter = false
    @State private var loadingPhotos = false
    @State private var photoLoadID: UUID?
    @State private var photoLoadTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                sourceBar
                Divider()
                attachmentList
                statusArea
            }
            .navigationTitle("Attachments")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { controller.dismissAttachmentSheet() }
                        .accessibilityHint("Cancels current attachment work and removes temporary copies")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { controller.commitAttachmentDraft() }
                        .fontWeight(.semibold)
                        .disabled(!controller.canCommitAttachmentDraft || loadingPhotos)
                }
            }
        }
        .interactiveDismissDisabled(controller.isAttachmentBusy || loadingPhotos)
        .fileImporter(
            isPresented: $showingFileImporter,
            allowedContentTypes: [.data],
            allowsMultipleSelection: true
        ) { result in
            switch result {
            case .success(let urls): controller.addAttachmentFileURLs(urls)
            case .failure(let error): controller.reportAttachmentPickerError(error)
            }
        } onCancellation: {}
        .onChange(of: photoItems) { _, items in
            guard !items.isEmpty else { return }
            loadPhotos(items)
        }
        .onDisappear {
            photoLoadID = nil
            photoLoadTask?.cancel()
            photoLoadTask = nil
            loadingPhotos = false
        }
    }

    private var sourceBar: some View {
        HStack(spacing: 12) {
            PhotosPicker(
                selection: $photoItems,
                maxSelectionCount: max(controller.attachmentRemainingCount, 1),
                matching: .images,
                preferredItemEncoding: .current
            ) {
                Label("Photos", systemImage: "photo.on.rectangle")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(
                controller.attachmentRemainingCount == 0
                    || controller.isAttachmentBusy
                    || loadingPhotos
            )

            Button {
                showingFileImporter = true
            } label: {
                Label("Files", systemImage: "folder")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(
                controller.attachmentRemainingCount == 0
                    || controller.isAttachmentBusy
                    || loadingPhotos
            )
        }
        .padding()
    }

    @ViewBuilder
    private var attachmentList: some View {
        if controller.attachmentDraft.isEmpty {
            ContentUnavailableView(
                "No Attachments",
                systemImage: "paperclip",
                description: Text("Choose Photos or Files for the next Pi message.")
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            List {
                ForEach(controller.attachmentDraft) { item in
                    HStack(spacing: 12) {
                        Image(systemName: item.localFile == nil ? "checkmark.icloud" : "doc")
                            .foregroundStyle(item.localFile == nil ? JarvisPalette.accent : .secondary)
                            .frame(width: 22)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.displayName)
                                .font(.body)
                                .lineLimit(2)
                            Text(formatBytes(item.sizeBytes))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button {
                            controller.removeAttachmentDraftItem(item.id)
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                        .disabled(controller.isAttachmentBusy || loadingPhotos)
                        .accessibilityLabel("Remove \(item.displayName)")
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .listStyle(.plain)
        }
    }

    private var statusArea: some View {
        VStack(spacing: 8) {
            if let progress = controller.attachmentProgress {
                ProgressView(value: progress)
                    .tint(JarvisPalette.accent)
                    .accessibilityLabel("Attachment upload progress")
                    .accessibilityValue("\(Int(progress * 100)) percent")
            } else if controller.isAttachmentBusy || loadingPhotos {
                ProgressView()
                    .tint(JarvisPalette.accent)
            }

            if loadingPhotos {
                Text("Preparing photos…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else if let status = controller.attachmentStatusText {
                Text(status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let error = controller.attachmentError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            HStack {
                Text("\(controller.attachmentDraft.count)/\(controller.attachmentLimits.maxFiles) files")
                Spacer()
                Text(formatBytes(controller.attachmentTotalBytes))
                if !controller.attachmentDraft.isEmpty {
                    Button("Clear") { controller.clearAttachmentDraft() }
                        .disabled(controller.isAttachmentBusy || loadingPhotos)
                }
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(.thinMaterial)
    }

    private func loadPhotos(_ items: [PhotosPickerItem]) {
        photoLoadTask?.cancel()
        let loadID = UUID()
        photoLoadID = loadID
        loadingPhotos = true
        photoLoadTask = Task {
            var transfers: [PiAttachmentPhotoTransfer] = []
            do {
                for item in items {
                    try Task.checkCancellation()
                    guard let transfer = try await item.loadTransferable(
                        type: PiAttachmentPhotoTransfer.self
                    ) else {
                        throw PiAttachmentTransportError.rejected(
                            "A selected photo could not be read."
                        )
                    }
                    transfers.append(transfer)
                }
                try Task.checkCancellation()
                let accepted = await MainActor.run {
                    guard photoLoadID == loadID else { return false }
                    photoItems = []
                    loadingPhotos = false
                    photoLoadID = nil
                    photoLoadTask = nil
                    controller.addTransferredPhotos(
                        transfers.map { (url: $0.url, displayName: $0.displayName) }
                    )
                    return true
                }
                if !accepted { Self.removePhotoTransfers(transfers) }
            } catch {
                Self.removePhotoTransfers(transfers)
                await MainActor.run {
                    guard photoLoadID == loadID else { return }
                    photoItems = []
                    loadingPhotos = false
                    photoLoadID = nil
                    photoLoadTask = nil
                    if !(error is CancellationError) {
                        controller.reportAttachmentPickerError(error)
                    }
                }
            }
        }
    }

    nonisolated private static func removePhotoTransfers(
        _ transfers: [PiAttachmentPhotoTransfer]
    ) {
        let temporaryRoot = FileManager.default.temporaryDirectory.standardizedFileURL
        for transfer in transfers {
            let directory = transfer.url.deletingLastPathComponent().standardizedFileURL
            guard directory.deletingLastPathComponent() == temporaryRoot,
                  directory.lastPathComponent.hasPrefix("JARVIS-Pi-Photo-") else {
                continue
            }
            try? FileManager.default.removeItem(at: directory)
        }
    }

    private func formatBytes(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .binary
        formatter.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        return formatter.string(fromByteCount: bytes)
    }
}
