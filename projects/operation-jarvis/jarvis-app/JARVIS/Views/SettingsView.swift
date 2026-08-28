import SwiftUI
import JARVISKit

/// Compact settings index. Infrequent configuration and diagnostics remain
/// fully available one level deeper instead of occupying the primary viewport.
struct SettingsView: View {
    @EnvironmentObject var app: AppState
    @EnvironmentObject var piTerminal: PiTerminalController
    @State private var sshHost = ""
    @State private var sshPort = "22"
    @State private var sshUsername = ""
    @State private var sshPassword = ""
    @State private var sshSaved = false
    @State private var watchTerminalSetupCode = ""
    @State private var watchTerminalSent = false
    @State private var localSigningStatus = LocalSigningStatus.current()
    @State private var showSigningRenewalConfirmation = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 15) {
                    settingsGroup(title: "Connections") {
                        NavigationLink {
                            connectionDetail
                        } label: {
                            settingsRow(
                                title: "JARVIS daemon",
                                systemImage: "server.rack",
                                value: daemonSummary,
                                color: daemonColor
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            piTerminalDetail
                        } label: {
                            settingsRow(
                                title: "Pi terminal",
                                systemImage: "terminal.fill",
                                value: piTerminalSummary,
                                color: piTerminal.settings.hasPassword ? JarvisPalette.cyan : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            watchTerminalDetail
                        } label: {
                            settingsRow(
                                title: "Apple Watch",
                                systemImage: "applewatch",
                                value: app.watchTerminalProvisioning.isProvisioned ? "Provisioned" : "Setup required",
                                color: app.watchTerminalProvisioning.isProvisioned ? JarvisPalette.cyan : JarvisPalette.warning
                            )
                        }
                        .buttonStyle(.plain)
                    }

                    settingsGroup(title: "Developer") {
                        NavigationLink {
                            developerSigningDetail
                        } label: {
                            TimelineView(.periodic(from: .now, by: 60)) { context in
                                settingsRow(
                                    title: "Developer signing",
                                    systemImage: "checkmark.seal",
                                    value: signingSummary(at: context.date),
                                    color: signingColor(at: context.date)
                                )
                            }
                        }
                        .buttonStyle(.plain)
                    }

                    settingsGroup(title: "Support") {
                        NavigationLink {
                            diagnosticsDetail
                        } label: {
                            settingsRow(
                                title: "Diagnostics",
                                systemImage: "stethoscope",
                                value: diagnosticsSummary,
                                color: app.connectionState == .failed ? .red : .secondary
                            )
                        }
                        .buttonStyle(.plain)

                        settingsDivider

                        NavigationLink {
                            aboutDetail
                        } label: {
                            settingsRow(
                                title: "About JARVIS",
                                systemImage: "info.circle",
                                value: appVersion,
                                color: .secondary
                            )
                        }
                        .buttonStyle(.plain)
                    }

                    if app.connectionState == .failed, let error = app.errorMessage {
                        Label {
                            Text(error)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        } icon: {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(.red)
                        }
                        .padding(.horizontal, 4)
                        .accessibilityElement(children: .combine)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
            .scrollIndicators(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle("Settings")
            .onAppear {
                loadPiTerminalSettings()
                localSigningStatus = .current()
            }
        }
    }

    // MARK: - Compact index

    private func settingsGroup<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title.uppercased())
                .font(.caption2.weight(.semibold))
                .tracking(0.7)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 3)
            MinimalCard {
                VStack(spacing: 0) { content() }
            }
        }
    }

    private func settingsRow(
        title: String,
        systemImage: String,
        value: String,
        color: Color
    ) -> some View {
        HStack(spacing: 11) {
            Image(systemName: systemImage)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(JarvisPalette.cyan)
                .frame(width: 24)
            Text(title)
                .font(.body)
                .foregroundStyle(.primary)
            Spacer(minLength: 8)
            Text(value)
                .font(.caption.weight(.medium))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            Image(systemName: "chevron.right")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
    }

    private var settingsDivider: some View {
        Divider().padding(.leading, 35)
    }

    private var daemonSummary: String {
        switch app.connectionState {
        case .connected: return "Connected · \(networkLabel)"
        case .connecting: return "Connecting"
        case .failed: return "Offline"
        case .idle: return "Not connected"
        }
    }

    private var daemonColor: Color {
        switch app.connectionState {
        case .connected: return JarvisPalette.cyan
        case .connecting: return JarvisPalette.warning
        case .failed: return .red
        case .idle: return .secondary
        }
    }

    private var piTerminalSummary: String {
        piTerminal.settings.hasPassword ? "Configured" : "Setup required"
    }

    private var diagnosticsSummary: String {
        app.connectionState == .failed ? "Needs attention" : "Status and network"
    }

    private var networkLabel: String {
        guard let host = app.currentEndpoint?.host else { return "—" }
        if host.hasPrefix("100.") || host.hasSuffix(".ts.net") { return "Tailscale" }
        if host.hasPrefix("192.168") || host.hasPrefix("10.") || host.hasPrefix("172.") { return "LAN" }
        return host
    }

    // MARK: - JARVIS connection

    private var connectionDetail: some View {
        Form {
            Section("Status") {
                LabeledContent("JARVIS daemon") {
                    ConnectionBadge(state: app.connectionState, detail: daemonSummary)
                }
                if let uptime = app.lastHealth?.uptimeSeconds {
                    LabeledContent("Uptime", value: JarvisFormat.uptime(uptime))
                }
                if let using = usingString {
                    LabeledContent("Using", value: using)
                        .font(.callout)
                }
            }

            Section {
                TextField(
                    "Endpoint override",
                    text: $app.endpointDraft,
                    prompt: Text("Automatic · LAN or Tailscale")
                )
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .font(.body.monospaced())

                Button {
                    Task { await app.connect() }
                } label: {
                    HStack {
                        Spacer()
                        if app.connectionState == .connecting {
                            ProgressView().frame(width: 20)
                            Text("Connecting…")
                        } else {
                            Label("Connect", systemImage: "link")
                        }
                        Spacer()
                    }
                }
                .disabled(app.connectionState == .connecting)
            } header: {
                Text("Endpoint")
            } footer: {
                Text("Leave blank to discover the Mac automatically over the home LAN or Tailscale.")
            }

            Section {
                Button(role: .destructive) {
                    app.clearConnection()
                } label: {
                    Label("Reset connection", systemImage: "arrow.counterclockwise")
                        .frame(maxWidth: .infinity)
                }
            }

            if app.connectionState == .failed, let error = app.errorMessage {
                Section("Error") {
                    Label {
                        Text(error).font(.callout).foregroundStyle(.red)
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                    }
                }
            }
        }
        .compactSettingsForm(title: "JARVIS connection")
    }

    // MARK: - Pi terminal

    private var piTerminalDetail: some View {
        Form {
            Section {
                TextField(
                    "SSH host",
                    text: $sshHost,
                    prompt: Text(app.currentEndpoint?.host ?? "Automatic from JARVIS")
                )
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .font(.body.monospaced())

                TextField("SSH port", text: $sshPort)
                    .keyboardType(.numberPad)
                    .font(.body.monospaced())

                TextField("SSH username", text: $sshUsername)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.body.monospaced())

                SecureField("Mac login password", text: $sshPassword)
                    .textContentType(.password)
                    .font(.body.monospaced())
            } header: {
                Text("SSH login")
            } footer: {
                Text("A blank host follows JARVIS between LAN and Tailscale. Opening the JARVIS tab attaches to the persistent jarvis-ios tmux session.")
            }

            Section {
                Button {
                    sshSaved = piTerminal.settings.save(
                        host: sshHost,
                        portText: sshPort,
                        username: sshUsername,
                        password: sshPassword
                    )
                    if sshSaved {
                        piTerminal.reconnectAfterSettingsChange(fallbackHost: app.currentEndpoint?.host)
                    }
                } label: {
                    Label(
                        sshSaved ? "SSH login saved" : "Save SSH login",
                        systemImage: sshSaved ? "checkmark.circle.fill" : "key.fill"
                    )
                    .frame(maxWidth: .infinity)
                }

                Button(role: .destructive) {
                    piTerminal.forgetTrustedHost(fallbackHost: app.currentEndpoint?.host)
                } label: {
                    Label("Forget trusted SSH host", systemImage: "exclamationmark.arrow.triangle.2.circlepath")
                        .frame(maxWidth: .infinity)
                }

                if let error = piTerminal.settings.credentialError {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
        }
        .compactSettingsForm(title: "Pi terminal")
        .onAppear { loadPiTerminalSettings() }
    }

    private func loadPiTerminalSettings() {
        sshHost = piTerminal.settings.host
        sshPort = String(piTerminal.settings.port)
        sshUsername = piTerminal.settings.username
        sshPassword = piTerminal.settings.passwordForEditing()
        sshSaved = false
        watchTerminalSent = false
    }

    // MARK: - Watch terminal

    private var watchTerminalDetail: some View {
        Form {
            Section {
                LabeledContent(
                    "Status",
                    value: app.watchTerminalProvisioning.isProvisioned ? "Provisioned" : "Not provisioned"
                )
                if app.watchTerminalProvisioning.isProvisioned {
                    LabeledContent("Bridge", value: app.watchTerminalProvisioning.endpoint)
                        .font(.caption)
                }
            }

            Section {
                SecureField("Watch terminal setup code", text: $watchTerminalSetupCode)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.body.monospaced())

                Button {
                    guard app.watchTerminalProvisioning.save(provisioningCode: watchTerminalSetupCode),
                          let configuration = app.watchTerminalProvisioning.configuration else {
                        watchTerminalSent = false
                        return
                    }
                    WatchBridge.shared.publishTerminalConfiguration(configuration)
                    watchTerminalSetupCode = ""
                    watchTerminalSent = true
                } label: {
                    Label(
                        watchTerminalSent ? "Sent to Apple Watch" : "Save and send to Apple Watch",
                        systemImage: watchTerminalSent ? "checkmark.circle.fill" : "applewatch.radiowaves.left.and.right"
                    )
                    .frame(maxWidth: .infinity)
                }
                .disabled(watchTerminalSetupCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                if let error = app.watchTerminalProvisioning.errorMessage {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            } header: {
                Text("Provisioning")
            } footer: {
                Text("Paste the private code printed by scripts/jarvis-terminal-provisioning.sh. The token stays in Keychain and is transferred only to your paired Watch.")
            }
        }
        .compactSettingsForm(title: "Apple Watch")
    }

    // MARK: - Developer signing

    private var developerSigningDetail: some View {
        Form {
            Section("Signing status") {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    signingOverview(at: context.date)
                }
            }

            Section("Signed components") {
                TimelineView(.periodic(from: .now, by: 60)) { context in
                    VStack(spacing: 0) {
                        ForEach(Array(LocalSigningStatus.expectedBundleIdentifiers.enumerated()), id: \.offset) { index, bundleIdentifier in
                            signingProfileRow(bundleIdentifier: bundleIdentifier, at: context.date)
                            if index < LocalSigningStatus.expectedBundleIdentifiers.count - 1 {
                                Divider().padding(.leading, 38)
                            }
                        }
                    }
                }
            }

            Section {
                Button {
                    showSigningRenewalConfirmation = true
                } label: {
                    HStack {
                        Spacer()
                        if app.signingRenewalLoading || app.signingRenewalStatus?.running == true {
                            ProgressView().frame(width: 20)
                            Text(signingPhaseTitle)
                        } else {
                            Label("Renew for 7 Days", systemImage: "arrow.triangle.2.circlepath")
                        }
                        Spacer()
                    }
                }
                .disabled(
                    app.connectionState != .connected
                        || app.signingRenewalLoading
                        || app.signingRenewalStatus?.running == true
                        || app.signingRenewalStatus?.available != true
                )

                Button {
                    Task { await app.fetchSigningRenewalStatus() }
                } label: {
                    Label("Refresh renewal status", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .disabled(app.signingRenewalLoading)
            } header: {
                Text("Mac renewal")
            } footer: {
                Text("The Mac requests four fresh Personal Team profiles, builds clean approved source, audits one exact archive, and installs only that archive on your allowlisted iPhone and Apple Watch.")
            }

            if let status = app.signingRenewalStatus {
                Section("Renewal progress") {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        signingProgressSummary(status, at: context.date)
                    }

                    VStack(spacing: 0) {
                        ForEach(Array(SigningRenewalStep.allCases.enumerated()), id: \.offset) { index, step in
                            signingStepRow(
                                step,
                                status: status,
                                isLast: index == SigningRenewalStep.allCases.count - 1
                            )
                        }
                    }
                }
            }

            if let error = app.signingRenewalErrorMessage {
                Section("Connection error") {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
        }
        .compactSettingsForm(title: "Developer Signing")
        .onAppear { localSigningStatus = .current() }
        .onChange(of: app.signingRenewalStatus?.phase) { _, phase in
            if phase == "succeeded" {
                localSigningStatus = .current()
            }
        }
        .task(id: app.signingRenewalStatus?.running) {
            if app.signingRenewalStatus == nil {
                await app.fetchSigningRenewalStatus()
            }
            while !Task.isCancelled, app.signingRenewalStatus?.running == true {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                await app.fetchSigningRenewalStatus()
            }
        }
        .alert("Renew JARVIS signing?", isPresented: $showSigningRenewalConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Renew for 7 Days") {
                Task { _ = await app.startSigningRenewal() }
            }
        } message: {
            Text("Keep this iPhone and Apple Watch nearby and unlocked. The seven steps will continue on the Mac if JARVIS briefly closes while the renewed iPhone build is installed.")
        }
    }

    private var signingPhaseTitle: String {
        switch app.signingRenewalStatus?.phase {
        case "queued": return "Starting…"
        case "preparing": return "Checking devices…"
        case "provisioning": return "Creating profiles…"
        case "building": return "Building JARVIS…"
        case "auditing": return "Auditing archive…"
        case "installingIPhone": return "Installing iPhone…"
        case "installingWatch": return "Installing Watch…"
        case "verifying": return "Verifying and relaunching…"
        case "succeeded": return "Renewal complete"
        case "failed": return "Renewal failed"
        default: return "Ready to renew"
        }
    }

    private func signingOverview(at date: Date) -> some View {
        let expiration = localSigningStatus.earliestExpiration
        let active = localSigningStatus.hasAllExpectedProfiles && (expiration ?? .distantPast) > date
        let color = active ? signingColor(at: date) : Color.red
        let windowProgress = min(1, max(0, (expiration?.timeIntervalSince(date) ?? 0) / (7 * 86_400)))

        return VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(color.opacity(0.14))
                    Image(systemName: active ? "checkmark.seal.fill" : "exclamationmark.shield.fill")
                        .font(.title2)
                        .foregroundStyle(color)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 3) {
                    Text(active ? "Signing active" : "Signing attention required")
                        .font(.headline)
                    Text(expiration.map { signingCountdown(to: $0, at: date) } ?? "Profile expiration unavailable")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(color)
                }
                Spacer(minLength: 8)
                Text("\(localSigningStatus.profiles.count)/4")
                    .font(.title3.monospacedDigit().weight(.bold))
                    .foregroundStyle(color)
            }

            ProgressView(value: windowProgress)
                .tint(color)

            HStack {
                Text("Seven-day signing window")
                Spacer()
                if let expiration {
                    Text("Until \(expiration.formatted(date: .abbreviated, time: .shortened))")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }

    private func signingProfileRow(bundleIdentifier: String, at date: Date) -> some View {
        let profile = localSigningStatus.profiles.first { $0.bundleIdentifier == bundleIdentifier }
        let valid = (profile?.expirationDate ?? .distantPast) > date

        return HStack(spacing: 12) {
            Image(systemName: signingProfileIcon(bundleIdentifier))
                .frame(width: 26)
                .foregroundStyle(valid ? JarvisPalette.cyan : Color.red)
            VStack(alignment: .leading, spacing: 2) {
                Text(signingProfileName(bundleIdentifier))
                    .font(.subheadline.weight(.semibold))
                Text(profile.map { "Valid until \($0.expirationDate.formatted(date: .abbreviated, time: .shortened))" } ?? "Embedded profile missing")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Image(systemName: valid ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundStyle(valid ? JarvisPalette.cyan : Color.red)
                .accessibilityLabel(valid ? "Valid" : "Missing or expired")
        }
        .padding(.vertical, 7)
        .accessibilityElement(children: .combine)
    }

    private func signingProgressSummary(_ status: SigningRenewalStatus, at date: Date) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(signingProgressColor(status).opacity(0.14))
                    if status.running {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: status.phase == "succeeded" ? "checkmark" : status.phase == "failed" ? "xmark" : "clock")
                            .font(.headline.weight(.bold))
                            .foregroundStyle(signingProgressColor(status))
                    }
                }
                .frame(width: 38, height: 38)

                VStack(alignment: .leading, spacing: 2) {
                    Text(signingPhaseTitle)
                        .font(.headline)
                    if let stepNumber = status.displayedStepNumber {
                        Text("Step \(stepNumber) of \(SigningRenewalStep.allCases.count)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(signingProgressColor(status))
                    } else if status.phase == "queued" {
                        Text("Preparing seven-step renewal")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if let elapsed = signingElapsed(status, at: date) {
                    Text(elapsed)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 4) {
                ForEach(SigningRenewalStep.allCases, id: \.rawValue) { step in
                    Capsule()
                        .fill(signingStepColor(status.state(for: step)))
                        .frame(height: 5)
                }
            }
            .animation(.easeInOut(duration: 0.25), value: status.phase)

            if let message = status.message {
                Text(message)
                    .font(.callout)
                    .foregroundStyle(status.phase == "failed" ? Color.red : Color.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let expiration = status.expirationDate {
                LabeledContent("Renewed until") {
                    Text(expiration.formatted(date: .abbreviated, time: .shortened))
                        .multilineTextAlignment(.trailing)
                }
                .font(.subheadline)
            }

            if status.iPhoneInstalled == true || status.watchInstalled == true || status.phase == "succeeded" {
                HStack(spacing: 8) {
                    signingDeviceBadge("iPhone", systemImage: "iphone", verified: status.iPhoneInstalled == true)
                    signingDeviceBadge("Watch", systemImage: "applewatch", verified: status.watchInstalled == true)
                }
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .contain)
    }

    private func signingStepRow(
        _ step: SigningRenewalStep,
        status: SigningRenewalStatus,
        isLast: Bool
    ) -> some View {
        let state = status.state(for: step)

        return HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 0) {
                ZStack {
                    Circle()
                        .fill(signingStepColor(state).opacity(state == .pending ? 0.18 : 0.15))
                        .overlay(Circle().stroke(signingStepColor(state), lineWidth: state == .pending ? 1 : 1.5))
                    switch state {
                    case .completed:
                        Image(systemName: "checkmark").font(.caption.weight(.bold))
                    case .current:
                        ProgressView().controlSize(.mini).scaleEffect(0.72)
                    case .failed:
                        Image(systemName: "xmark").font(.caption.weight(.bold))
                    case .pending:
                        Image(systemName: "circle.fill").font(.system(size: 5))
                    }
                }
                .foregroundStyle(signingStepColor(state))
                .frame(width: 28, height: 28)

                if !isLast {
                    Rectangle()
                        .fill(state == .completed ? JarvisPalette.cyan.opacity(0.65) : Color.secondary.opacity(0.2))
                        .frame(width: 2, height: 28)
                }
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(signingStepTitle(step))
                    .font(.subheadline.weight(state == .current || state == .failed ? .bold : .semibold))
                    .foregroundStyle(state == .failed ? Color.red : state == .current ? JarvisPalette.cyan : Color.primary)
                Text(signingStepDetail(step))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.bottom, isLast ? 1 : 9)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue(signingStepStateLabel(state))
    }

    private func signingDeviceBadge(_ title: String, systemImage: String, verified: Bool) -> some View {
        Label("\(title) \(verified ? "verified" : "not confirmed")", systemImage: verified ? "checkmark.circle.fill" : systemImage)
            .font(.caption.weight(.semibold))
            .foregroundStyle(verified ? JarvisPalette.cyan : Color.secondary)
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background((verified ? JarvisPalette.cyan : Color.secondary).opacity(0.1), in: Capsule())
    }

    private func signingProgressColor(_ status: SigningRenewalStatus) -> Color {
        if status.phase == "failed" { return .red }
        if status.phase == "succeeded" { return JarvisPalette.cyan }
        return status.running ? JarvisPalette.cyan : .secondary
    }

    private func signingStepColor(_ state: SigningRenewalStepState) -> Color {
        switch state {
        case .completed, .current: return JarvisPalette.cyan
        case .failed: return .red
        case .pending: return .secondary
        }
    }

    private func signingElapsed(_ status: SigningRenewalStatus, at date: Date) -> String? {
        guard let start = status.startedDate else { return nil }
        let end = status.completedDate ?? date
        let seconds = max(0, Int(end.timeIntervalSince(start)))
        if seconds < 60 { return "\(seconds)s" }
        return "\(seconds / 60)m \(seconds % 60)s"
    }

    private func signingProfileName(_ bundleIdentifier: String) -> String {
        switch bundleIdentifier {
        case "com.operation-jarvis.jarvis": return "iPhone app"
        case "com.operation-jarvis.jarvis.widget": return "iPhone widget"
        case "com.operation-jarvis.jarvis.watchkitapp": return "Watch app"
        case "com.operation-jarvis.jarvis.watchkitapp.widget": return "Watch widget"
        default: return "Unknown component"
        }
    }

    private func signingProfileIcon(_ bundleIdentifier: String) -> String {
        switch bundleIdentifier {
        case "com.operation-jarvis.jarvis": return "iphone"
        case "com.operation-jarvis.jarvis.widget": return "square.grid.2x2.fill"
        case "com.operation-jarvis.jarvis.watchkitapp": return "applewatch"
        default: return "rectangle.stack.fill"
        }
    }

    private func signingStepTitle(_ step: SigningRenewalStep) -> String {
        switch step {
        case .preparing: return "Check Mac and paired devices"
        case .provisioning: return "Create four signing profiles"
        case .building: return "Build approved JARVIS source"
        case .auditing: return "Audit the exact archive"
        case .installingIPhone: return "Install iPhone and widget"
        case .installingWatch: return "Install Watch and widget"
        case .verifying: return "Verify and relaunch"
        }
    }

    private func signingStepDetail(_ step: SigningRenewalStep) -> String {
        switch step {
        case .preparing: return "Confirm the private allowlist, pairing, Developer Mode, and CoreDevice tunnels."
        case .provisioning: return "Request fresh Personal Team profiles from Apple for all four components."
        case .building: return "Compile clean approved main in an isolated worktree."
        case .auditing: return "Check profiles, devices, bundle IDs, entitlements, hierarchy, and signatures."
        case .installingIPhone: return "Install only the audited iPhone host and embedded widget through CoreDevice."
        case .installingWatch: return "Install the matching nested Watch app and widget, with one bounded tunnel retry."
        case .verifying: return "Confirm installed build numbers, expiration, and successful launch on both devices."
        }
    }

    private func signingStepStateLabel(_ state: SigningRenewalStepState) -> String {
        switch state {
        case .completed: return "Completed"
        case .current: return "In progress"
        case .pending: return "Pending"
        case .failed: return "Failed"
        }
    }

    private func signingSummary(at date: Date) -> String {
        guard let expiration = localSigningStatus.earliestExpiration else { return "Unavailable" }
        return signingCountdown(to: expiration, at: date)
    }

    private func signingCountdown(to expiration: Date, at date: Date) -> String {
        let seconds = Int(expiration.timeIntervalSince(date))
        guard seconds > 0 else { return "Expired" }
        let days = seconds / 86_400
        let hours = (seconds % 86_400) / 3_600
        if days > 0 { return "\(days)d \(hours)h remaining" }
        let minutes = max(1, (seconds % 3_600) / 60)
        return "\(hours)h \(minutes)m remaining"
    }

    private func signingColor(at date: Date) -> Color {
        guard let expiration = localSigningStatus.earliestExpiration else { return JarvisPalette.warning }
        let remaining = expiration.timeIntervalSince(date)
        if remaining <= 0 { return .red }
        if remaining <= 2 * 86_400 { return JarvisPalette.warning }
        return JarvisPalette.cyan
    }

    // MARK: - Diagnostics and About

    private var diagnosticsDetail: some View {
        Form {
            Section("Connection") {
                LabeledContent("Status") {
                    ConnectionBadge(state: app.connectionState, detail: daemonSummary)
                }
                LabeledContent("Endpoint", value: usingString ?? "—")
                LabeledContent("Daemon", value: "jarvisd \(app.lastHealth?.version ?? "—")")
                if let uptime = app.lastHealth?.uptimeSeconds {
                    LabeledContent("Uptime", value: JarvisFormat.uptime(uptime))
                }
            }

            Section("Network") {
                if let network = app.lastState?.subsystems?.network {
                    LabeledContent("LAN IP", value: network.macLanIp ?? "—")
                    LabeledContent("Tailscale IP", value: network.tailscaleIp ?? "—")
                } else {
                    LabeledContent("Network telemetry", value: "Unavailable")
                }
            }

            if let error = app.errorMessage {
                Section("Last error") {
                    Text(error).foregroundStyle(.red)
                }
            }
        }
        .compactSettingsForm(title: "Diagnostics")
    }

    private var aboutDetail: some View {
        Form {
            Section {
                LabeledContent("App", value: "JARVIS")
                LabeledContent("Version", value: appVersion)
                LabeledContent("Daemon", value: "jarvisd \(app.lastHealth?.version ?? "—")")
            }
        }
        .compactSettingsForm(title: "About JARVIS")
    }

    private var usingString: String? {
        guard let endpoint = app.currentEndpoint, let host = endpoint.host else { return nil }
        let port = endpoint.port.map(String.init) ?? "8790"
        return host + ":" + port
    }

    private var appVersion: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(version) (\(build))"
    }
}

private extension View {
    func compactSettingsForm(title: String) -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
    }
}

#Preview {
    let settings = PiTerminalSettings(defaults: UserDefaults(suiteName: "pi-settings-preview")!)
    return SettingsView()
        .environmentObject(AppState())
        .environmentObject(PiTerminalController(settings: settings))
}
