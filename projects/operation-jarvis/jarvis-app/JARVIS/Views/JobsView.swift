import Foundation
import SwiftUI
import JARVISKit

struct JobsView: View {
    private enum Route: Hashable {
        case thread(jobID: String, focusedSequence: Int?)
    }

    @EnvironmentObject private var app: AppState
    @Binding var requestedResultSequence: Int?
    @State private var path: [Route] = []

    private var sections: ScheduledJobThreadSections {
        JobsPresentation.threads(
            jobs: app.lastScheduledJobs,
            results: app.lastScheduledJobResults
        )
    }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if !sections.scheduled.isEmpty || !sections.archived.isEmpty {
                        summaryStrip
                    }

                    if let error = app.scheduledJobsErrorMessage {
                        messageCard(
                            title: "Schedules unavailable",
                            detail: error,
                            systemImage: "exclamationmark.triangle.fill",
                            color: JarvisPalette.warning
                        )
                    }
                    if let error = app.scheduledJobResultsErrorMessage {
                        messageCard(
                            title: "Message history unavailable",
                            detail: error,
                            systemImage: "exclamationmark.triangle.fill",
                            color: JarvisPalette.warning
                        )
                    }

                    if isInitiallyLoading {
                        loadingCard
                    } else if sections.scheduled.isEmpty && sections.archived.isEmpty {
                        messageCard(
                            title: "No scheduled jobs",
                            detail: "Configured cron jobs and their retained messages will appear here.",
                            systemImage: "calendar.badge.clock",
                            color: .secondary
                        )
                    } else {
                        if !sections.scheduled.isEmpty {
                            jobGroup(title: "Scheduled Jobs", threads: sections.scheduled)
                        }
                        if !sections.archived.isEmpty {
                            jobGroup(title: "Archived Jobs", threads: sections.archived)
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 16)
            }
            .scrollIndicators(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle("Jobs")
            .navigationDestination(for: Route.self) { route in
                switch route {
                case let .thread(jobID, focusedSequence):
                    JobThreadView(jobID: jobID, focusedSequence: focusedSequence)
                        .id(route)
                }
            }
            .refreshable {
                await app.refreshJobs()
                app.markScheduledJobResultsRead()
            }
            .task {
                await app.refreshJobs()
                await consumeRequestedResult()
                app.markScheduledJobResultsRead()
            }
            .onChange(of: requestedResultSequence) { _, _ in
                Task { await consumeRequestedResult() }
            }
        }
    }

    private var isInitiallyLoading: Bool {
        (app.scheduledJobsLoading || app.scheduledJobResultsLoading)
            && app.lastScheduledJobs.isEmpty
            && app.lastScheduledJobResults.isEmpty
    }

    private var summaryStrip: some View {
        let enabled = app.lastScheduledJobs.filter(\.enabled).count
        let issues = app.lastScheduledJobs.filter { job in
            job.lastStatus == "error" || (job.consecutiveErrors ?? 0) > 0
        }.count
        return HStack(spacing: 0) {
            summaryMetric(
                value: String(enabled),
                label: "Active",
                systemImage: "calendar.badge.clock",
                color: JarvisPalette.accent
            )
            summaryDivider
            summaryMetric(
                value: String(app.lastScheduledJobResults.count),
                label: "Messages",
                systemImage: "text.bubble.fill",
                color: JarvisPalette.accent
            )
            summaryDivider
            summaryMetric(
                value: String(issues),
                label: issues == 1 ? "Issue" : "Issues",
                systemImage: issues == 0 ? "checkmark.circle.fill" : "exclamationmark.triangle.fill",
                color: issues == 0 ? JarvisPalette.accent : JarvisPalette.warning
            )
        }
        .padding(.vertical, 12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(JarvisPalette.accent.opacity(0.12), lineWidth: 0.75)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(enabled) active jobs, \(app.lastScheduledJobResults.count) retained messages, \(issues) issues")
    }

    private func summaryMetric(value: String, label: String, systemImage: String, color: Color) -> some View {
        VStack(spacing: 3) {
            HStack(spacing: 5) {
                Image(systemName: systemImage)
                    .font(.caption.weight(.semibold))
                Text(value)
                    .font(.headline.monospacedDigit())
            }
            .foregroundStyle(color)
            Text(label)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private var summaryDivider: some View {
        Divider()
            .frame(height: 31)
    }

    private func jobGroup(title: String, threads: [ScheduledJobThread]) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title.uppercased())
                .font(.caption2.weight(.semibold))
                .tracking(0.7)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 3)

            MinimalCard {
                VStack(spacing: 0) {
                    ForEach(threads) { thread in
                        NavigationLink(
                            value: Route.thread(jobID: thread.id, focusedSequence: nil)
                        ) {
                            ScheduledJobRow(thread: thread)
                        }
                        .buttonStyle(.plain)

                        if thread.id != threads.last?.id {
                            Divider()
                                .padding(.leading, 49)
                        }
                    }
                }
            }
        }
    }

    private var loadingCard: some View {
        MinimalCard {
            HStack(spacing: 10) {
                ProgressView()
                Text("Loading scheduled jobs…")
                    .font(.subheadline.weight(.medium))
                Spacer()
            }
        }
    }

    private func messageCard(title: String, detail: String, systemImage: String, color: Color) -> some View {
        MinimalCard {
            HStack(alignment: .top, spacing: 11) {
                Image(systemName: systemImage)
                    .foregroundStyle(color)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.subheadline.weight(.semibold))
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
    }

    @MainActor
    private func consumeRequestedResult() async {
        guard let sequence = requestedResultSequence, sequence > 0 else { return }
        await app.fetchScheduledJobResult(sequence: sequence)
        if let result = app.scheduledJobResult(sequence: sequence) {
            path = [.thread(jobID: result.jobId, focusedSequence: sequence)]
        }
        requestedResultSequence = nil
    }
}

private struct ScheduledJobRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let thread: ScheduledJobThread

    private var job: ScheduledJob? { thread.job }
    private var latest: ScheduledJobResult? { thread.latestMessage }
    private var hasFailure: Bool {
        job?.lastStatus == "error"
            || (job?.consecutiveErrors ?? 0) > 0
            || latest?.status == "error"
    }
    private var statusColor: Color {
        guard let job else { return .secondary }
        if !job.enabled { return .secondary }
        return hasFailure ? JarvisPalette.warning : JarvisPalette.accent
    }
    private var statusText: String {
        guard let job else { return "Archived" }
        if !job.enabled { return "Disabled" }
        return hasFailure ? "Issue" : "Active"
    }
    private var symbol: String {
        guard let job else { return "archivebox.fill" }
        return JobsPresentation.scheduleSymbol(kind: job.kind)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            ZStack {
                Circle()
                    .fill(statusColor.opacity(0.13))
                Image(systemName: symbol)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(statusColor)
            }
            .frame(width: 38, height: 38)

            VStack(alignment: .leading, spacing: 5) {
                titleRow

                if let job {
                    Label(
                        JobsPresentation.cadence(kind: job.kind, schedule: job.schedule),
                        systemImage: "clock"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)

                    if let next = JarvisFormat.localDateTime(job.nextRunAt) {
                        Text("Next · \(next)")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                } else {
                    Text("Schedule no longer configured")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Text(latest.map { JobResultRichText.plainText($0.summary) } ?? "No retained messages")
                    .font(.caption)
                    .foregroundStyle(latest?.status == "error" ? JarvisPalette.warning : .secondary)
                    .lineLimit(2)

                HStack(spacing: 5) {
                    Text("\(thread.messages.count) message\(thread.messages.count == 1 ? "" : "s")")
                    if let relative = latest.map({ JarvisFormat.relativeTime($0.finishedAt) }), !relative.isEmpty {
                        Text("·")
                        Text(relative)
                    }
                }
                .font(.caption2.monospacedDigit())
                .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 5)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(JarvisFormat.displayName(thread.name)), \(statusText), \(thread.messages.count) retained messages")
        .accessibilityHint("Opens this job's message history")
    }

    @ViewBuilder
    private var titleRow: some View {
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .top, spacing: 6) {
                    jobTitle(lineLimit: 2)
                    Spacer(minLength: 4)
                    chevron
                }
                statusBadge
            }
        } else {
            HStack(spacing: 7) {
                jobTitle(lineLimit: 1)
                Spacer(minLength: 4)
                statusBadge
                chevron
            }
        }
    }

    private func jobTitle(lineLimit: Int) -> some View {
        Text(JarvisFormat.displayName(thread.name))
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.primary)
            .lineLimit(lineLimit)
    }

    private var statusBadge: some View {
        Text(statusText)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(statusColor)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(statusColor.opacity(0.1), in: Capsule())
    }

    private var chevron: some View {
        Image(systemName: "chevron.right")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.tertiary)
            .padding(.top, 2)
    }
}

private struct JobThreadView: View {
    @EnvironmentObject private var app: AppState
    let jobID: String
    let focusedSequence: Int?

    private var thread: ScheduledJobThread? {
        let sections = JobsPresentation.threads(
            jobs: app.lastScheduledJobs,
            results: app.lastScheduledJobResults
        )
        return (sections.scheduled + sections.archived).first { $0.id == jobID }
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if let thread {
                        JobThreadHeader(thread: thread)
                            .padding(.bottom, 12)

                        MinimalSectionHeader(
                            title: "Messages",
                            systemImage: "text.bubble.fill",
                            detail: String(thread.messages.count)
                        )
                        .padding(.bottom, 4)

                        if thread.messages.isEmpty {
                            MinimalCard {
                                VStack(alignment: .leading, spacing: 4) {
                                    Label("No retained messages", systemImage: "tray")
                                        .font(.subheadline.weight(.semibold))
                                    Text("Silent successful runs are summarized above. Output-bearing runs and failures will appear here.")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(.top, 6)
                        } else {
                            ForEach(thread.messages) { result in
                                JobChannelMessage(
                                    result: result,
                                    isFocused: focusedSequence == result.sequence
                                )
                                .id(result.sequence)

                                if result.sequence != thread.messages.last?.sequence {
                                    Divider()
                                        .padding(.leading, 50)
                                }
                            }
                        }
                    } else {
                        MinimalCard {
                            Label("This scheduled job is unavailable.", systemImage: "exclamationmark.triangle")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(16)
            }
            .scrollIndicators(.hidden)
            .background(JarvisBackdrop())
            .navigationTitle(thread.map { JarvisFormat.displayName($0.name) } ?? "Job")
            .navigationBarTitleDisplayMode(.inline)
            .refreshable { await app.refreshJobs() }
            .onAppear {
                if let focusedSequence {
                    proxy.scrollTo(focusedSequence, anchor: .top)
                }
            }
        }
    }
}

private struct JobThreadHeader: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let thread: ScheduledJobThread

    private var hasFailure: Bool {
        thread.job?.lastStatus == "error" || (thread.job?.consecutiveErrors ?? 0) > 0
    }
    private var color: Color {
        guard let job = thread.job else { return .secondary }
        if !job.enabled { return .secondary }
        return hasFailure ? JarvisPalette.warning : JarvisPalette.accent
    }

    var body: some View {
        MinimalCard {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    ZStack {
                        Circle().fill(color.opacity(0.13))
                        Image(systemName: thread.job.map { JobsPresentation.scheduleSymbol(kind: $0.kind) } ?? "archivebox.fill")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(color)
                    }
                    .frame(width: 38, height: 38)

                    VStack(alignment: .leading, spacing: 1) {
                        Text(JarvisFormat.displayName(thread.name))
                            .font(.headline)
                        Text(statusText)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(color)
                    }
                    Spacer(minLength: 0)
                }

                if let description = thread.job?.description, !description.isEmpty {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(dynamicTypeSize.isAccessibilitySize ? 4 : 3)
                }

                Divider()

                if let job = thread.job {
                    detailRow(
                        JobsPresentation.cadence(kind: job.kind, schedule: job.schedule),
                        systemImage: "clock"
                    )
                    if JobsPresentation.cadence(kind: job.kind, schedule: job.schedule) == "Custom schedule" {
                        detailRow(job.schedule, systemImage: "terminal")
                            .monospaced()
                    }
                    if let next = JarvisFormat.localDateTime(job.nextRunAt) {
                        detailRow("Next · \(next)", systemImage: "calendar.badge.clock")
                    }
                    detailRow(
                        "\(JobsPresentation.runCount(job.runCount)) total runs",
                        systemImage: "number"
                    )
                    if let errors = job.consecutiveErrors, errors > 0 {
                        detailRow(
                            "\(errors) consecutive failure\(errors == 1 ? "" : "s")",
                            systemImage: "exclamationmark.triangle.fill",
                            foreground: JarvisPalette.warning
                        )
                    }
                } else {
                    detailRow("Schedule no longer configured", systemImage: "archivebox")
                }
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var statusText: String {
        guard let job = thread.job else { return "Archived history" }
        if !job.enabled { return "Disabled" }
        return hasFailure ? "Needs attention" : "Active"
    }

    private func detailRow(
        _ text: String,
        systemImage: String,
        foreground: Color = .secondary
    ) -> some View {
        Label(text, systemImage: systemImage)
            .font(.caption)
            .foregroundStyle(foreground)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private struct JobChannelMessage: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let result: ScheduledJobResult
    let isFocused: Bool

    private var failed: Bool { result.status == "error" }
    private var color: Color { failed ? JarvisPalette.warning : JarvisPalette.accent }
    private var timestamp: String {
        JarvisFormat.localDateTime(result.finishedAt) ?? result.finishedAt
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle().fill(color.opacity(0.15))
                Image(systemName: failed ? "exclamationmark" : "checkmark")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(color)
            }
            .frame(width: 38, height: 38)
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 7) {
                messageIdentity

                if let error = result.error, !error.isEmpty {
                    messageContent(title: "Failure", text: error, color: JarvisPalette.warning)
                }
                if let output = result.output, !output.isEmpty {
                    LinkedJobResultText(text: output)
                }
                if (result.error?.isEmpty ?? true) && (result.output?.isEmpty ?? true) {
                    LinkedJobResultText(text: result.summary)
                }

                HStack(spacing: 5) {
                    Text(String(format: "%.1fs", result.durationSeconds))
                    Text("·")
                    Text("Result #\(result.sequence)")
                    if let exitCode = result.exitCode {
                        Text("·")
                        Text("Exit \(exitCode)")
                    }
                    if result.truncated {
                        Text("·")
                        Text("Truncated")
                            .foregroundStyle(JarvisPalette.warning)
                    }
                }
                .font(.caption2.monospacedDigit())
                .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal, 4)
        .padding(.vertical, 12)
        .background(
            isFocused ? JarvisPalette.accent.opacity(0.075) : Color.clear,
            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
        )
        .overlay {
            if isFocused {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(JarvisPalette.accent.opacity(0.58), lineWidth: 1)
            }
        }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var messageIdentity: some View {
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: 2) {
                senderAndStatus
                Text(timestamp)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.tertiary)
            }
        } else {
            HStack(alignment: .firstTextBaseline, spacing: 7) {
                senderAndStatus
                Spacer(minLength: 4)
                Text(timestamp)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
        }
    }

    private var senderAndStatus: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Text(JarvisFormat.displayName(result.jobName))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.primary)
            Text(failed ? "Failed" : "Completed")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(color)
        }
    }

    private func messageContent(title: String, text: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.caption2.weight(.bold))
                .tracking(0.6)
                .foregroundStyle(color)
            LinkedJobResultText(text: text)
        }
    }
}
