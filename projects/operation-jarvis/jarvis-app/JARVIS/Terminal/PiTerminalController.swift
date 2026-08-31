import Combine
import Foundation
import Network

@MainActor
enum PiTerminalConnectionStatus: Equatable {
    case idle
    case connecting
    case connected
    case failed(String)
}

@MainActor
final class PiTerminalController: ObservableObject {
    @Published private(set) var status: PiTerminalConnectionStatus = .idle
    @Published private(set) var pendingHostTrust: PiPendingHostTrust?
    @Published private(set) var isControlLatched = false
    @Published private(set) var isTerminalFocused = false
    @Published private(set) var isAttachmentSheetPresented = false
    @Published private(set) var attachmentDraft: [PiAttachmentDraftItem] = []
    @Published private(set) var attachmentLimits = PiAttachmentLimits.safeFallback
    @Published private(set) var attachmentStatusText: String?
    @Published private(set) var attachmentError: String?
    @Published private(set) var attachmentProgress: Double?
    @Published private(set) var isAttachmentBusy = false

    let settings: PiTerminalSettings

    private weak var terminalView: PiTerminalHostView?
    private var isVisible = false
    private var appIsActive = false
    private var fallbackHost: String?
    private var pathMonitor: NWPathMonitor?
    private var networkAvailable = true
    private let attachmentTemporaryStore = PiAttachmentTemporaryStore()
    private var attachmentSnapshot: PiAttachmentSnapshot?
    private var attachmentWorkflowID: UUID?
    private var attachmentTaskID: UUID?
    private var attachmentTask: Task<Void, Never>?

    init(settings: PiTerminalSettings) {
        self.settings = settings
        startPathMonitor()
    }

    deinit {
        pathMonitor?.cancel()
    }

    func attach(_ view: PiTerminalHostView) {
        terminalView = view
        view.stateChanged = { [weak self] newStatus in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.status = newStatus
                if newStatus.isFailure {
                    _ = self.terminalView?.resignFirstResponder()
                    self.isTerminalFocused = false
                    self.cancelAttachmentWorkflow()
                }
            }
        }
        view.controlLatchChanged = { [weak self] latched in
            Task { @MainActor [weak self] in self?.isControlLatched = latched }
        }
        view.keyboardFocusChanged = { [weak self] focused in
            Task { @MainActor [weak self] in self?.isTerminalFocused = focused }
        }
        view.hostTrustRequested = { [weak self] request in
            Task { @MainActor [weak self] in
                guard let self else {
                    request.reject()
                    return
                }
#if DEBUG && targetEnvironment(simulator)
                if CommandLine.arguments.contains("-jarvisAutoTrustSSHHost") {
                    self.settings.trustHostKey(request.publicKey, host: request.host, port: request.port)
                    request.accept()
                    return
                }
#endif
                self.pendingHostTrust = request
            }
        }
        maybeConnect()
    }

    func detach(_ view: PiTerminalHostView) {
        guard terminalView === view else { return }
        cancelAttachmentWorkflow()
        _ = view.resignFirstResponder()
        view.disconnectSSH()
        terminalView = nil
        pendingHostTrust?.reject()
        pendingHostTrust = nil
        status = .idle
        isControlLatched = false
        isTerminalFocused = false
    }

    func sendTerminalBytes(_ bytes: [UInt8]) {
        terminalView?.sendAccessoryBytes(bytes)
    }

    func toggleControlLatch() {
        terminalView?.toggleControlLatch()
    }

    func pasteIntoTerminal() {
        terminalView?.paste(nil)
    }

    func toggleTerminalKeyboard() {
        guard let terminalView else { return }
        if terminalView.isTerminalKeyboardFocused {
            _ = terminalView.resignFirstResponder()
        } else {
            _ = terminalView.becomeFirstResponder()
        }
    }

    var canOpenAttachments: Bool {
        PiTerminalFeatureGate.nativeAttachmentsEnabled
            && status == .connected
            && terminalView != nil
            && !isAttachmentSheetPresented
    }

    var attachmentRemainingCount: Int {
        max(attachmentLimits.maxFiles - attachmentDraft.count, 0)
    }

    var attachmentTotalBytes: Int64 {
        attachmentDraft.reduce(0) { $0 + $1.sizeBytes }
    }

    var canCommitAttachmentDraft: Bool {
        attachmentWorkflowID != nil && attachmentSnapshot != nil && !isAttachmentBusy
    }

    func presentAttachmentSheet() {
        guard PiTerminalFeatureGate.nativeAttachmentsEnabled,
              status == .connected,
              let terminalView,
              !isAttachmentSheetPresented else { return }
        _ = terminalView.resignFirstResponder()
        attachmentWorkflowID = UUID()
        isAttachmentSheetPresented = true
        attachmentDraft = []
        attachmentSnapshot = nil
        attachmentError = nil
        attachmentProgress = nil
        startAttachmentTask(status: "Loading staged attachments…") { [weak self, weak terminalView] in
            guard let self, let terminalView else { throw PiAttachmentTransportError.unavailable }
            let request = PiAttachmentWireRequest.snapshot()
            let response = try await terminalView.performAttachmentRequest(request)
            try Task.checkCancellation()
            let snapshot = try response.validatedSnapshot(
                expectedOperation: request.operation,
                expectedRequestID: request.requestID
            )
            self.applyAttachmentSnapshot(snapshot)
            self.attachmentStatusText = nil
        }
    }

    func dismissAttachmentSheet() {
        cancelAttachmentWorkflow()
    }

    func addAttachmentFileURLs(_ urls: [URL]) {
        guard !urls.isEmpty,
              attachmentSnapshot != nil,
              let workflowID = attachmentWorkflowID else { return }
        guard urls.count <= attachmentRemainingCount else {
            attachmentError = "A maximum of \(attachmentLimits.maxFiles) attachments may be staged at once."
            return
        }
        startAttachmentTask(status: "Preparing files…") { [weak self] in
            guard let self else { return }
            var imported: [PiAttachmentLocalFile] = []
            do {
                for url in urls {
                    let file = try await self.attachmentTemporaryStore.importSecurityScopedFile(
                        url,
                        workflowID: workflowID,
                        limits: self.attachmentLimits
                    )
                    imported.append(file)
                    try Task.checkCancellation()
                    try self.validateAttachmentAdditions(imported)
                }
                try Task.checkCancellation()
                try self.validateAttachmentAdditions(imported)
                self.attachmentDraft.append(contentsOf: imported.map(PiAttachmentDraftItem.local))
                self.attachmentStatusText = nil
            } catch {
                for file in imported { await self.attachmentTemporaryStore.remove(file) }
                throw error
            }
        }
    }

    func addTransferredPhotos(_ photos: [(url: URL, displayName: String)]) {
        guard !photos.isEmpty else { return }
        guard attachmentSnapshot != nil,
              let workflowID = attachmentWorkflowID else {
            Task {
                for photo in photos {
                    await attachmentTemporaryStore.discardTransferredPhoto(photo.url)
                }
            }
            return
        }
        guard photos.count <= attachmentRemainingCount else {
            attachmentError = "A maximum of \(attachmentLimits.maxFiles) attachments may be staged at once."
            Task {
                for photo in photos {
                    await attachmentTemporaryStore.discardTransferredPhoto(photo.url)
                }
            }
            return
        }
        startAttachmentTask(status: "Preparing photos…") { [weak self] in
            guard let self else { return }
            var imported: [PiAttachmentLocalFile] = []
            do {
                for photo in photos {
                    let file = try await self.attachmentTemporaryStore.importTransferredPhoto(
                        photo.url,
                        displayName: photo.displayName,
                        workflowID: workflowID,
                        limits: self.attachmentLimits
                    )
                    imported.append(file)
                    try Task.checkCancellation()
                    try self.validateAttachmentAdditions(imported)
                }
                try Task.checkCancellation()
                try self.validateAttachmentAdditions(imported)
                self.attachmentDraft.append(contentsOf: imported.map(PiAttachmentDraftItem.local))
                self.attachmentStatusText = nil
            } catch {
                for file in imported { await self.attachmentTemporaryStore.remove(file) }
                for photo in photos {
                    await self.attachmentTemporaryStore.discardTransferredPhoto(photo.url)
                }
                throw error
            }
        }
    }

    func reportAttachmentPickerError(_ error: Error) {
        guard isAttachmentSheetPresented, attachmentWorkflowID != nil else { return }
        attachmentError = error.localizedDescription
        attachmentStatusText = nil
    }

    func removeAttachmentDraftItem(_ id: String) {
        guard !isAttachmentBusy,
              let index = attachmentDraft.firstIndex(where: { $0.id == id }) else { return }
        let removed = attachmentDraft.remove(at: index)
        if let local = removed.localFile {
            Task { await attachmentTemporaryStore.remove(local) }
        }
        attachmentError = nil
    }

    func clearAttachmentDraft() {
        guard !isAttachmentBusy else { return }
        let localFiles = attachmentDraft.compactMap(\.localFile)
        attachmentDraft = []
        attachmentError = nil
        Task {
            for file in localFiles { await attachmentTemporaryStore.remove(file) }
        }
    }

    func commitAttachmentDraft() {
        guard let snapshot = attachmentSnapshot,
              let workflowID = attachmentWorkflowID,
              let terminalView,
              status == .connected,
              !isAttachmentBusy else { return }
        let localFiles = attachmentDraft.compactMap(\.localFile)
        let keepIDs = attachmentDraft.compactMap(\.remoteID)
        do {
            try validateAttachmentSelection(attachmentDraft)
        } catch {
            attachmentError = error.localizedDescription
            return
        }
        let (expectedCommittedRevision, revisionOverflow) = snapshot.revision.addingReportingOverflow(1)
        guard !revisionOverflow,
              snapshot.revision < PiAttachmentProtocol.maximumSafeWireInteger else {
            attachmentError = PiAttachmentTransportError.invalidResponse.localizedDescription
            return
        }
        let requestID = UUID()
        let request = PiAttachmentWireRequest.reconcile(
            requestID: requestID,
            snapshot: snapshot,
            keepIds: keepIDs,
            files: localFiles
        )
        attachmentError = nil
        attachmentProgress = localFiles.isEmpty ? nil : 0
        startAttachmentTask(status: "Uploading attachments…") { [weak self, weak terminalView] in
            guard let self, let terminalView else { throw PiAttachmentTransportError.unavailable }
            do {
                let response = try await terminalView.performAttachmentRequest(
                    request,
                    files: localFiles
                ) { [weak self] sent, total in
                    Task { @MainActor [weak self] in
                        guard let self,
                              self.attachmentWorkflowID == workflowID,
                              total > 0 else { return }
                        self.attachmentProgress = min(max(Double(sent) / Double(total), 0), 1)
                    }
                }
                try Task.checkCancellation()
                let committed = try response.validatedSnapshot(
                    expectedOperation: request.operation,
                    expectedRequestID: request.requestID,
                    expectedGeneration: snapshot.generation,
                    expectedCommittedRevision: expectedCommittedRevision
                )
                try await self.finishCommittedAttachments(
                    committed,
                    workflowID: workflowID
                )
            } catch let error as PiAttachmentTransportError {
                do {
                    if case .ambiguous(let ambiguousID, let generation) = error {
                        try await self.resolveAmbiguousAttachment(
                            requestID: ambiguousID,
                            generation: generation,
                            expectedCommittedRevision: expectedCommittedRevision,
                            workflowID: workflowID,
                            terminalView: terminalView
                        )
                    } else {
                        throw error
                    }
                } catch {
                    await self.discardFailedAttachmentCommit(workflowID: workflowID)
                    throw error
                }
            } catch {
                await self.discardFailedAttachmentCommit(workflowID: workflowID)
                throw error
            }
        }
    }

    private func discardFailedAttachmentCommit(workflowID: UUID) async {
        await attachmentTemporaryStore.cleanup(workflowID: workflowID)
        guard attachmentWorkflowID == workflowID else { return }
        attachmentDraft.removeAll(where: { $0.localFile != nil })
        attachmentSnapshot = nil
        attachmentProgress = nil
    }

    private func resolveAmbiguousAttachment(
        requestID: UUID,
        generation: String,
        expectedCommittedRevision: Int,
        workflowID: UUID,
        terminalView: PiTerminalHostView
    ) async throws {
        attachmentStatusText = "Verifying attachment result…"
        let statusRequest = PiAttachmentWireRequest.requestStatus(
            generation: generation,
            targetRequestID: requestID
        )
        let statusResponse = try await terminalView.performAttachmentRequest(statusRequest)
        try Task.checkCancellation()
        guard statusResponse.ok,
              statusResponse.version == PiAttachmentProtocol.version,
              statusResponse.operation == statusRequest.operation,
              statusResponse.requestID == statusRequest.requestID,
              statusResponse.generation == generation,
              statusResponse.targetRequestID == requestID.uuidString.lowercased() else {
            throw PiAttachmentTransportError.invalidResponse
        }
        switch statusResponse.state {
        case "committed":
            guard let committedResponse = statusResponse.committedResponse else {
                throw PiAttachmentTransportError.invalidResponse
            }
            let committed = try committedResponse.validatedSnapshot(
                expectedRequestID: requestID.uuidString.lowercased(),
                expectedGeneration: generation,
                expectedCommittedRevision: expectedCommittedRevision
            )
            try await finishCommittedAttachments(committed, workflowID: workflowID)
        case "notCommitted":
            throw PiAttachmentTransportError.rejected(
                "The attachment upload did not commit. Review the selection before retrying."
            )
        default:
            throw PiAttachmentTransportError.rejected(
                "The attachment result is unknown. Refresh and review the live staged set; no retry was sent."
            )
        }
    }

    private func finishCommittedAttachments(
        _ snapshot: PiAttachmentSnapshot,
        workflowID: UUID
    ) async throws {
        try Task.checkCancellation()
        await attachmentTemporaryStore.cleanup(workflowID: workflowID)
        try Task.checkCancellation()
        guard attachmentWorkflowID == workflowID else {
            throw CancellationError()
        }
        applyAttachmentSnapshot(snapshot)
        attachmentWorkflowID = nil
        attachmentProgress = nil
        attachmentStatusText = nil
        isAttachmentSheetPresented = false
    }

    private func applyAttachmentSnapshot(_ snapshot: PiAttachmentSnapshot) {
        attachmentSnapshot = snapshot
        attachmentLimits = snapshot.limits
        attachmentDraft = snapshot.staged.map(PiAttachmentDraftItem.remote)
        attachmentError = nil
    }

    private func validateAttachmentAdditions(_ additions: [PiAttachmentLocalFile]) throws {
        let proposed = attachmentDraft + additions.map(PiAttachmentDraftItem.local)
        try validateAttachmentSelection(proposed)
    }

    private func validateAttachmentSelection(_ selection: [PiAttachmentDraftItem]) throws {
        guard attachmentLimits.isValid else { throw PiAttachmentTransportError.invalidRequest }
        guard selection.count <= attachmentLimits.maxFiles else {
            throw PiAttachmentTransportError.rejected(
                "A maximum of \(attachmentLimits.maxFiles) attachments may be staged at once."
            )
        }
        var total: Int64 = 0
        for item in selection {
            guard item.sizeBytes >= 0, item.sizeBytes <= attachmentLimits.maxFileBytes else {
                throw PiAttachmentTransportError.rejected(
                    "\(item.displayName) exceeds the per-file attachment limit."
                )
            }
            let (nextTotal, overflow) = total.addingReportingOverflow(item.sizeBytes)
            guard !overflow else { throw PiAttachmentTransportError.invalidRequest }
            total = nextTotal
        }
        guard total <= attachmentLimits.maxTotalBytes else {
            throw PiAttachmentTransportError.rejected(
                "The selected files exceed the total staged-attachment limit."
            )
        }
    }

    private func startAttachmentTask(
        status: String,
        operation: @escaping @MainActor () async throws -> Void
    ) {
        guard !isAttachmentBusy else { return }
        let taskID = UUID()
        attachmentTaskID = taskID
        isAttachmentBusy = true
        attachmentStatusText = status
        attachmentError = nil
        attachmentTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if self.attachmentTaskID == taskID {
                    self.isAttachmentBusy = false
                    self.attachmentTask = nil
                    self.attachmentTaskID = nil
                    if self.attachmentError != nil { self.attachmentStatusText = nil }
                }
            }
            do {
                try Task.checkCancellation()
                try await operation()
                try Task.checkCancellation()
            } catch is CancellationError {
                return
            } catch PiAttachmentTransportError.cancelled {
                return
            } catch {
                guard self.attachmentTaskID == taskID else { return }
                self.attachmentProgress = nil
                self.attachmentError = error.localizedDescription
            }
        }
    }

    private func cancelAttachmentWorkflow() {
        let workflowID = attachmentWorkflowID
        attachmentWorkflowID = nil
        let task = attachmentTask
        attachmentTask = nil
        attachmentTaskID = nil
        task?.cancel()
        isAttachmentBusy = false
        isAttachmentSheetPresented = false
        attachmentDraft = []
        attachmentSnapshot = nil
        attachmentStatusText = nil
        attachmentError = nil
        attachmentProgress = nil
        if let workflowID {
            Task { await attachmentTemporaryStore.cleanup(workflowID: workflowID) }
        }
    }

    func setVisible(_ visible: Bool, fallbackHost: String?) {
        isVisible = visible
        self.fallbackHost = fallbackHost
        if visible {
            maybeConnect()
        } else {
            cancelAttachmentWorkflow()
            pendingHostTrust?.reject()
            pendingHostTrust = nil
            _ = terminalView?.resignFirstResponder()
            terminalView?.disconnectSSH()
            status = .idle
            isTerminalFocused = false
        }
    }

    func sceneDidBecomeActive() {
        appIsActive = true
        maybeConnect(force: status.isFailure)
    }

    func sceneWillResignActive() {
        appIsActive = false
        cancelAttachmentWorkflow()
        pendingHostTrust?.reject()
        pendingHostTrust = nil
        _ = terminalView?.resignFirstResponder()
        terminalView?.disconnectSSH()
        status = .idle
        isTerminalFocused = false
    }

    func retry() {
        maybeConnect(force: true)
    }

    func reconnectAfterSettingsChange(fallbackHost: String?) {
        self.fallbackHost = fallbackHost
        cancelAttachmentWorkflow()
        pendingHostTrust?.reject()
        pendingHostTrust = nil
        terminalView?.disconnectSSH()
        status = .idle
        maybeConnect(force: true)
    }

    func trustPendingHost() {
        guard let request = pendingHostTrust else { return }
        settings.trustHostKey(request.publicKey, host: request.host, port: request.port)
        pendingHostTrust = nil
        request.accept()
    }

    func rejectPendingHost() {
        guard let request = pendingHostTrust else { return }
        pendingHostTrust = nil
        request.reject()
        status = .failed("The Mac’s SSH host key was not trusted.")
    }

    func forgetTrustedHost(fallbackHost: String?) {
        settings.forgetCurrentTrustedHost(fallbackHost: fallbackHost)
        reconnectAfterSettingsChange(fallbackHost: fallbackHost)
    }

    private func maybeConnect(force: Bool = false) {
        guard isVisible, appIsActive, networkAvailable, let terminalView else { return }
        guard let configuration = settings.configuration(fallbackHost: fallbackHost) else {
            status = .idle
            return
        }
        if !force, status == .connecting || status == .connected { return }
        let trustedKey = settings.trustedHostKey(host: configuration.host, port: configuration.port)
        status = .connecting
        terminalView.connect(configuration: configuration, trustedHostKey: trustedKey)
    }

    private func startPathMonitor() {
        let monitor = NWPathMonitor()
        pathMonitor = monitor
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor [weak self] in
                guard let self else { return }
                let wasAvailable = self.networkAvailable
                self.networkAvailable = path.status == .satisfied
                if self.networkAvailable, !wasAvailable {
                    self.maybeConnect(force: true)
                } else if !self.networkAvailable {
                    self.cancelAttachmentWorkflow()
                    _ = self.terminalView?.resignFirstResponder()
                    self.terminalView?.disconnectSSH()
                    self.status = .failed("The network is unavailable.")
                    self.isTerminalFocused = false
                }
            }
        }
        monitor.start(queue: DispatchQueue(label: "com.operation-jarvis.pi-terminal-path"))
    }
}

private extension PiTerminalConnectionStatus {
    var isFailure: Bool {
        if case .failed = self { return true }
        return false
    }
}
