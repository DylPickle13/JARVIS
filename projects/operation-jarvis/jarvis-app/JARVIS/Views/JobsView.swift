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
            }
            .task {
                await app.refreshJobs()
                await consumeRequestedResult()
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
                            ScheduledJobRow(
                                thread: thread,
                                unreadCount: app.unreadScheduledJobResultCount(for: thread.id)
                            )
                        }
                        .buttonStyle(.plain)

                        if thread.id != threads.last?.id {
                            Divider()
                                .padding(.leading, 16)
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
    let unreadCount: Int

    private var job: ScheduledJob? { thread.job }
    private var hasFailure: Bool { JobsPresentation.hasCurrentIssue(job) }
    private var statusText: String {
        guard let job else { return "Archived" }
        if !job.enabled { return "Disabled" }
        return hasFailure ? "Issue" : "Active"
    }
    private var cadenceText: String {
        guard let job else { return "Schedule no longer configured" }
        return JobsPresentation.cadence(kind: job.kind, schedule: job.schedule)
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    if unreadCount > 0 {
                        Circle()
                            .fill(JarvisPalette.accent)
                            .frame(width: 7, height: 7)
                            .accessibilityHidden(true)
                    }
                    Text(JarvisFormat.displayName(thread.name))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(dynamicTypeSize.isAccessibilitySize ? 2 : 1)
                }

                Text(cadenceText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? 2 : 1)
            }

            Spacer(minLength: 8)

            if hasFailure {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(JarvisPalette.warning)
                    .accessibilityHidden(true)
            } else if job?.enabled == false {
                Image(systemName: "pause.circle.fill")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            } else if job == nil {
                Image(systemName: "archivebox.fill")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            }

            Image(systemName: "chevron.right")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
                .accessibilityHidden(true)
        }
        .padding(.vertical, 10)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityHint("Opens this job's message history")
    }

    private var accessibilityLabel: String {
        let unread = unreadCount > 0
            ? ", \(unreadCount) unread result\(unreadCount == 1 ? "" : "s")"
            : ""
        return "\(JarvisFormat.displayName(thread.name)), \(statusText)\(unread), \(cadenceText)"
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

    private var newestSequence: Int? {
        thread?.messages.map(\.sequence).max()
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
            .refreshable {
                await app.refreshJobs()
                app.markScheduledJobRead(jobID: jobID)
            }
            .onAppear {
                app.markScheduledJobRead(jobID: jobID)
                if let focusedSequence {
                    proxy.scrollTo(focusedSequence, anchor: .top)
                }
            }
            .onChange(of: newestSequence) { _, _ in
                app.markScheduledJobRead(jobID: jobID)
            }
        }
    }
}

private struct JobThreadHeader: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let thread: ScheduledJobThread

    private var hasFailure: Bool {
        JobsPresentation.hasCurrentIssue(thread.job)
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
