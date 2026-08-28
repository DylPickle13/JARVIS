import SwiftUI
import JARVISKit

struct DeveloperSigningSettingsView: View {
    @EnvironmentObject private var app: AppState
    @State private var localSigningStatus = LocalSigningStatus.current()
    @State private var showRenewalConfirmation = false
    @State private var showSignedComponents = false
    @State private var showRenewalExplanation = false

    var body: some View {
        Form {
            Section("Signing Status") {
                TimelineView(.periodic(from: .now, by: 60)) { context in
                    signingOverview(at: context.date)
                }
            }

            Section {
                TimelineView(.periodic(from: .now, by: 60)) { context in
                    DisclosureGroup(isExpanded: $showSignedComponents) {
                        VStack(spacing: 0) {
                            ForEach(
                                Array(LocalSigningStatus.expectedBundleIdentifiers.enumerated()),
                                id: \.offset
                            ) { index, bundleIdentifier in
                                signingProfileRow(bundleIdentifier: bundleIdentifier, at: context.date)
                                if index < LocalSigningStatus.expectedBundleIdentifiers.count - 1 {
                                    Divider().padding(.leading, 38)
                                }
                            }
                        }
                    } label: {
                        HStack {
                            Label("Signed Components", systemImage: "square.stack.3d.up.fill")
                            Spacer()
                            Text("\(validProfileCount(at: context.date))/4")
                                .font(.caption.monospacedDigit().weight(.semibold))
                                .foregroundStyle(
                                    validProfileCount(at: context.date) == 4
                                        ? JarvisPalette.cyan
                                        : Color.red
                                )
                        }
                    }
                }
            }

            Section {
                Button {
                    showRenewalConfirmation = true
                } label: {
                    HStack {
                        Spacer()
                        if app.signingRenewalLoading || app.signingRenewalStatus?.running == true {
                            ProgressView().frame(width: 20)
                            Text(signingPhaseTitle(app.signingRenewalStatus))
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
            } header: {
                Text("Renewal")
            } footer: {
                Text("The Mac creates four Personal Team profiles, audits one exact archive, and installs it only on your private allowlisted iPhone and Apple Watch.")
            }

            if let status = app.signingRenewalStatus {
                if status.running || status.phase == "failed" || status.phase == "queued" {
                    Section(status.phase == "failed" ? "Renewal Failed" : "Renewal Progress") {
                        if status.running {
                            TimelineView(.periodic(from: .now, by: 1)) { context in
                                signingProgressSummary(status, at: context.date)
                            }
                        } else {
                            signingProgressSummary(status, at: Date())
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
                } else if status.phase == "succeeded" {
                    Section("Last Renewal") {
                        signingSuccessSummary(status)
                    }
                }
            }

            Section {
                DisclosureGroup("How Renewal Works · 7 Steps", isExpanded: $showRenewalExplanation) {
                    VStack(spacing: 0) {
                        ForEach(Array(SigningRenewalStep.allCases.enumerated()), id: \.offset) { index, step in
                            renewalExplanationRow(
                                step,
                                number: index + 1,
                                isLast: index == SigningRenewalStep.allCases.count - 1
                            )
                        }
                    }
                }
            }

            if let error = app.signingRenewalErrorMessage {
                Section("Connection Error") {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
        }
        .compactSettingsForm(title: "Developer Signing")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await app.fetchSigningRenewalStatus() }
                } label: {
                    if app.signingRenewalLoading {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .disabled(app.signingRenewalLoading)
                .accessibilityLabel("Refresh renewal status")
            }
        }
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
        .alert("Renew JARVIS signing?", isPresented: $showRenewalConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Renew for 7 Days") {
                Task { _ = await app.startSigningRenewal() }
            }
        } message: {
            Text("Keep this iPhone and Apple Watch nearby and unlocked. Renewal continues on the Mac if JARVIS briefly closes while the new iPhone build is installed.")
        }
    }

    private func signingOverview(at date: Date) -> some View {
        let expiration = localSigningStatus.earliestExpiration
        let active = localSigningStatus.hasAllExpectedProfiles && (expiration ?? .distantPast) > date
        let color = active
            ? SettingsPresentation.signingColor(expiration: expiration, at: date)
            : Color.red
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
                    Text(
                        expiration.map {
                            SettingsPresentation.signingCountdown(to: $0, at: date)
                        } ?? "Profile expiration unavailable"
                    )
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(color)
                }
                Spacer(minLength: 0)
            }

            ProgressView(value: windowProgress)
                .tint(color)

            if let expiration {
                LabeledContent("Expires") {
                    Text(expiration.formatted(date: .abbreviated, time: .shortened))
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
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
                Text(
                    profile.map {
                        "Valid until \($0.expirationDate.formatted(date: .abbreviated, time: .shortened))"
                    } ?? "Embedded profile missing"
                )
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
                        Image(systemName: status.phase == "failed" ? "xmark" : "clock")
                            .font(.headline.weight(.bold))
                            .foregroundStyle(signingProgressColor(status))
                    }
                }
                .frame(width: 38, height: 38)

                VStack(alignment: .leading, spacing: 2) {
                    Text(signingPhaseTitle(status))
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

            if status.iPhoneInstalled == true || status.watchInstalled == true {
                verificationBadges(status)
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .contain)
    }

    private func signingSuccessSummary(_ status: SigningRenewalStatus) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(JarvisPalette.cyan.opacity(0.14))
                    Image(systemName: "checkmark")
                        .font(.headline.weight(.bold))
                        .foregroundStyle(JarvisPalette.cyan)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Renewal complete").font(.headline)
                    if let completed = status.completedDate {
                        Text(completed.formatted(date: .abbreviated, time: .shortened))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if let elapsed = signingElapsed(status, at: status.completedDate ?? Date()) {
                    Text(elapsed)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            verificationBadges(status)
        }
        .padding(.vertical, 3)
        .accessibilityElement(children: .contain)
    }

    private func verificationBadges(_ status: SigningRenewalStatus) -> some View {
        HStack(spacing: 8) {
            signingDeviceBadge("iPhone", systemImage: "iphone", verified: status.iPhoneInstalled == true)
            signingDeviceBadge("Watch", systemImage: "applewatch", verified: status.watchInstalled == true)
        }
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

    private func renewalExplanationRow(
        _ step: SigningRenewalStep,
        number: Int,
        isLast: Bool
    ) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(String(number))
                .font(.caption.monospacedDigit().weight(.bold))
                .foregroundStyle(JarvisPalette.cyan)
                .frame(width: 26, height: 26)
                .background(JarvisPalette.cyan.opacity(0.12), in: Circle())

            VStack(alignment: .leading, spacing: 3) {
                Text(signingStepTitle(step))
                    .font(.subheadline.weight(.semibold))
                Text(signingStepDetail(step))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, isLast ? 7 : 9)
        .accessibilityElement(children: .combine)
    }

    private func signingDeviceBadge(_ title: String, systemImage: String, verified: Bool) -> some View {
        Label(
            "\(title) \(verified ? "verified" : "not confirmed")",
            systemImage: verified ? "checkmark.circle.fill" : systemImage
        )
        .font(.caption.weight(.semibold))
        .foregroundStyle(verified ? JarvisPalette.cyan : Color.secondary)
        .padding(.horizontal, 9)
        .padding(.vertical, 6)
        .background((verified ? JarvisPalette.cyan : Color.secondary).opacity(0.1), in: Capsule())
    }

    private func validProfileCount(at date: Date) -> Int {
        LocalSigningStatus.expectedBundleIdentifiers.reduce(into: 0) { count, bundleIdentifier in
            if let profile = localSigningStatus.profiles.first(where: { $0.bundleIdentifier == bundleIdentifier }),
               profile.expirationDate > date {
                count += 1
            }
        }
    }

    private func signingPhaseTitle(_ status: SigningRenewalStatus?) -> String {
        switch status?.phase {
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
}
