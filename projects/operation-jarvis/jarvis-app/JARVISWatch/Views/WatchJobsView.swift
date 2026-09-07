import Foundation
import JARVISKit
import SwiftUI

/// Full-screen fourth dashboard page. It intentionally uses custom in-page
/// navigation so the existing status-bar-free Watch pager keeps its geometry.
struct WatchJobsView: View {
    @ObservedObject var model: WatchJobsModel
    let onPreviousPage: () -> Void
    let resolveRoute: (ScheduledJobNavigationRequest) async -> Bool
    let onRouteConsumed: (ScheduledJobNavigationRequest) -> Void

    var body: some View {
        Group {
            if let thread = model.selectedThread {
                WatchJobThreadView(model: model, thread: thread)
            } else {
                jobsRoot
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .accessibilityAction(named: "Return to System", onPreviousPage)
    }

    private var jobsRoot: some View {
        WatchJobsCrownList {
            VStack(alignment: .leading, spacing: 8) {
                pageHeader

                if let pending = model.pendingRoute {
                    routeCard(pending)
                }

                if let error = model.scheduledJobsErrorMessage, !error.isEmpty {
                    warningCard(title: "Schedules unavailable", detail: error)
                }
                if let error = model.resultsErrorMessage, !error.isEmpty {
                    warningCard(title: "History unavailable", detail: error)
                }

                if model.isInitiallyLoading {
                    loadingCard
                } else if model.sections.scheduled.isEmpty && model.sections.archived.isEmpty {
                    emptyCard
                } else {
                    if !model.sections.scheduled.isEmpty {
                        threadSection(title: "Scheduled Jobs", threads: model.sections.scheduled)
                    }
                    if !model.sections.archived.isEmpty {
                        threadSection(title: "Archived Jobs", threads: model.sections.archived)
                    }
                }
            }
            .padding(.horizontal, 8)
            .padding(.top, 7)
            .padding(.bottom, 12)
        }
        .scrollIndicators(.hidden)

    }

    private var pageHeader: some View {
        HStack(spacing: 6) {
            Image(systemName: "calendar.badge.clock")
                .foregroundStyle(WatchJarvisStyle.accent)
            Text("Jobs")
                .font(.headline.weight(.bold))
            Spacer(minLength: 2)
            if model.unreadJobCount > 0 {
                Text("\(model.unreadJobCount)")
                    .font(.system(size: 9, weight: .bold, design: .rounded))
                    .foregroundStyle(.black)
                    .frame(minWidth: 20, minHeight: 20)
                    .background(WatchJarvisStyle.accent, in: Capsule())
                    .accessibilityLabel("\(model.unreadJobCount) unread job threads")
            }
            Button { Task { await model.refresh() } } label: {
                Image(systemName: "arrow.clockwise").frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .disabled(model.isRefreshing)
            .accessibilityLabel("Refresh Jobs")
            if model.isRefreshing {
                ProgressView()
                    .controlSize(.mini)
                    .accessibilityLabel("Refreshing Jobs")
            }
        }
    }

    private func threadSection(title: String, threads: [ScheduledJobThread]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased())
                .font(.system(size: 8, weight: .bold))
                .tracking(0.6)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 5)

            VStack(spacing: 0) {
                ForEach(threads) { thread in
                    Button {
                        model.openThread(jobID: thread.id)
                    } label: {
                        WatchScheduledJobRow(
                            thread: thread,
                            unreadCount: model.unreadResultCount(for: thread.id)
                        )
                    }
                    .buttonStyle(.plain)

                    if thread.id != threads.last?.id {
                        Divider().padding(.leading, 13)
                    }
                }
            }
            .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
        }
    }

    private func routeCard(_ route: ScheduledJobNavigationRequest) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 7) {
                if model.isResolvingRoute {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(WatchJarvisStyle.warning)
                }
                Text(model.isResolvingRoute ? "Opening result #\(route.resultSequence)…" : "Result #\(route.resultSequence) unavailable")
                    .font(.caption.weight(.semibold))
            }
            if let error = model.routeErrorMessage, !error.isEmpty {
                Text(error)
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !model.isResolvingRoute {
                HStack(spacing: 6) {
                    Button("Retry") {
                        Task {
                            if await resolveRoute(route) {
                                onRouteConsumed(route)
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    Button("Dismiss") {
                        if let dismissed = model.dismissPendingRoute() {
                            onRouteConsumed(dismissed)
                        }
                    }
                    .buttonStyle(.bordered)
                }
                .font(.caption2)
            }
        }
        .padding(9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(WatchJarvisStyle.warning.opacity(0.10), in: RoundedRectangle(cornerRadius: 13, style: .continuous))
    }

    private func warningCard(title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 7) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.caption2)
                .foregroundStyle(WatchJarvisStyle.warning)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.caption.weight(.semibold))
                Text(detail)
                    .font(.system(size: 8.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
        }
        .padding(8)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
    }

    private var loadingCard: some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text("Loading scheduled jobs…")
                .font(.caption.weight(.semibold))
            Spacer()
        }
        .padding(10)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var emptyCard: some View {
        VStack(spacing: 7) {
            Image(systemName: "calendar.badge.clock")
                .font(.title3)
                .foregroundStyle(.secondary)
            Text("No scheduled jobs")
                .font(.caption.weight(.semibold))
            Text("Configured jobs and retained messages will appear here.")
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
    }
}

private struct WatchScheduledJobRow: View {
    let thread: ScheduledJobThread
    let unreadCount: Int

    private var job: ScheduledJob? { thread.job }
    private var hasIssue: Bool { JobsPresentation.hasCurrentIssue(job) }
    private var cadence: String {
        guard let job else { return "Schedule no longer configured" }
        return JobsPresentation.cadence(kind: job.kind, schedule: job.schedule)
    }

    var body: some View {
        HStack(spacing: 8) {
            if unreadCount > 0 {
                Circle()
                    .fill(WatchJarvisStyle.accent)
                    .frame(width: 7, height: 7)
                    .shadow(color: WatchJarvisStyle.accent.opacity(0.6), radius: 3)
                    .accessibilityHidden(true)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(WatchFormat.displayName(thread.name))
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                Text(cadence)
                    .font(.system(size: 8.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer(minLength: 3)

            if hasIssue {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(WatchJarvisStyle.warning)
            } else if job?.enabled == false {
                Image(systemName: "pause.circle.fill")
                    .foregroundStyle(.secondary)
            } else if job == nil {
                Image(systemName: "archivebox.fill")
                    .foregroundStyle(.secondary)
            }

            Image(systemName: "chevron.right")
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(.tertiary)
        }
        .font(.caption2)
        .padding(.horizontal, 9)
        .padding(.vertical, 9)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityHint("Opens this job's message history")
    }

    private var accessibilityLabel: String {
        let state: String
        if job == nil { state = "Archived" }
        else if job?.enabled == false { state = "Disabled" }
        else if hasIssue { state = "Issue" }
        else { state = "Active" }
        let unread = unreadCount > 0 ? ", \(unreadCount) unread result\(unreadCount == 1 ? "" : "s")" : ""
        return "\(WatchFormat.displayName(thread.name)), \(state)\(unread), \(cadence)"
    }
}

private struct WatchJobThreadView: View {
    @ObservedObject var model: WatchJobsModel
    let thread: ScheduledJobThread

    private var currentThread: ScheduledJobThread {
        model.selectedThread ?? thread
    }

    private var newestSequence: Int? {
        currentThread.messages.map(\.sequence).max()
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 7) {
                    threadHeader

                    Text("MESSAGES · \(currentThread.messages.count)")
                        .font(.system(size: 8, weight: .bold))
                        .tracking(0.6)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 4)

                    if currentThread.messages.isEmpty {
                        Text("No retained messages")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(10)
                            .frame(maxWidth: .infinity)
                            .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                    } else {
                        ForEach(currentThread.messages) { result in
                            WatchJobMessage(
                                result: result,
                                isFocused: model.focusedResultSequence == result.sequence
                            )
                            .id(result.sequence)
                        }
                    }
                }
                .padding(.horizontal, 8)
                .padding(.top, 7)
                .padding(.bottom, 14)
            }
            .scrollIndicators(.hidden)
            .onAppear {
                model.markSelectedThreadRead()
                scrollToFocus(using: proxy)
            }
            .onChange(of: model.focusedResultSequence) { _, _ in
                scrollToFocus(using: proxy)
            }
            .onChange(of: newestSequence) { _, _ in
                model.markSelectedThreadRead()
            }
        }
    }

    private var threadHeader: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                Button { model.closeThread() } label: {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 10, weight: .bold))
                        .frame(width: 25, height: 25)
                        .background(Color.white.opacity(0.07), in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Back to Jobs")

                VStack(alignment: .leading, spacing: 1) {
                    Text(WatchFormat.displayName(currentThread.name))
                        .font(.system(size: 12, weight: .bold))
                        .lineLimit(2)
                    Text(statusText)
                        .font(.system(size: 8.5, weight: .semibold))
                        .foregroundStyle(statusColor)
                }
                Spacer(minLength: 0)
            }

            if let job = currentThread.job {
                Label(JobsPresentation.cadence(kind: job.kind, schedule: job.schedule), systemImage: "clock")
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let description = job.description, !description.isEmpty {
                    Text(description)
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                        .lineLimit(4)
                }
                HStack(spacing: 5) {
                    Text("\(JobsPresentation.runCount(job.runCount)) runs")
                    if let errors = job.consecutiveErrors, errors > 0 {
                        Text("· \(errors) failures")
                            .foregroundStyle(WatchJarvisStyle.warning)
                    }
                }
                .font(.system(size: 8, design: .monospaced))
                .foregroundStyle(.tertiary)
            } else {
                Label("Schedule no longer configured", systemImage: "archivebox")
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(9)
        .background(WatchJarvisStyle.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
    }

    private var statusText: String {
        guard let job = currentThread.job else { return "Archived history" }
        if !job.enabled { return "Disabled" }
        return JobsPresentation.hasCurrentIssue(job) ? "Needs attention" : "Active"
    }

    private var statusColor: Color {
        guard let job = currentThread.job, job.enabled else { return .secondary }
        return JobsPresentation.hasCurrentIssue(job) ? WatchJarvisStyle.warning : WatchJarvisStyle.accent
    }

    private func scrollToFocus(using proxy: ScrollViewProxy) {
        guard let sequence = model.focusedResultSequence else { return }
        Task { @MainActor in
            await Task.yield()
            proxy.scrollTo(sequence, anchor: .top)
        }
    }
}

private struct WatchJobMessage: View {
    let result: ScheduledJobResult
    let isFocused: Bool

    private var failed: Bool { result.status == "error" }
    private var color: Color { failed ? WatchJarvisStyle.warning : WatchJarvisStyle.accent }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Image(systemName: failed ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                    .foregroundStyle(color)
                Text(failed ? "Failed" : "Completed")
                    .font(.system(size: 10, weight: .semibold))
                Spacer(minLength: 3)
                Text(Self.localDateTime(result.finishedAt))
                    .font(.system(size: 7.5, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }

            if let error = result.error, !error.isEmpty {
                Text("FAILURE")
                    .font(.system(size: 8, weight: .bold))
                    .tracking(0.5)
                    .foregroundStyle(WatchJarvisStyle.warning)
                richText(error, color: WatchJarvisStyle.warning)
            }
            if let output = result.output, !output.isEmpty {
                richText(output, color: .primary)
            }
            if (result.error?.isEmpty ?? true), (result.output?.isEmpty ?? true) {
                richText(result.summary, color: .primary)
            }

            HStack(spacing: 4) {
                Text(String(format: "%.1fs", result.durationSeconds))
                Text("· #\(result.sequence)")
                if let exitCode = result.exitCode { Text("· Exit \(exitCode)") }
                if result.truncated {
                    Text("· Truncated").foregroundStyle(WatchJarvisStyle.warning)
                }
            }
            .font(.system(size: 7.5, design: .monospaced))
            .foregroundStyle(.tertiary)
        }
        .padding(9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            isFocused ? WatchJarvisStyle.accent.opacity(0.10) : WatchJarvisStyle.surface,
            in: RoundedRectangle(cornerRadius: 14, style: .continuous)
        )
        .overlay {
            if isFocused {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(WatchJarvisStyle.accent.opacity(0.65), lineWidth: 1)
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func richText(_ value: String, color: Color) -> some View {
        Text(JobResultRichText.attributedString(value))
            .font(.system(size: 9.5, design: .monospaced))
            .foregroundStyle(color)
            .tint(WatchJarvisStyle.accent)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private static func localDateTime(_ value: String) -> String {
        let fractional = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
        let ordinary = Date.ISO8601FormatStyle(includingFractionalSeconds: false)
        let date = (try? fractional.parse(value)) ?? (try? ordinary.parse(value))
        guard let date else { return value }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

/// Disable touch scrolling at the ScrollView itself. Crown movement scrolls
/// explicit 20-point anchors; the outer page owns vertical swipes instead.
private struct WatchJobsCrownList<Content: View>: View {
    @ViewBuilder let content: () -> Content
    @State private var contentHeight: CGFloat = 0
    @State private var crown = 0.0
    @FocusState private var crownFocused: Bool

    var body: some View {
        GeometryReader { viewport in
            let maximum = max(0, ceil((contentHeight - viewport.size.height) / 20))
            ScrollViewReader { proxy in
                ScrollView {
                    content()
                        .background(GeometryReader { geometry in
                            Color.clear.preference(key: JobsContentHeight.self, value: geometry.size.height)
                        })
                        .overlay(alignment: .top) {
                            VStack(spacing: 0) {
                                ForEach(0...Int(maximum), id: \.self) { index in
                                    Color.clear.frame(height: 20).id("jobs-crown-\(index)")
                                }
                            }
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                        }
                }
                .scrollDisabled(true)
                .focusable()
                .focused($crownFocused)
                .digitalCrownRotation($crown, from: 0, through: max(1, maximum), by: 1,
                    sensitivity: .medium, isContinuous: false, isHapticFeedbackEnabled: true)
                .onPreferenceChange(JobsContentHeight.self) { height in
                    contentHeight = height
                    crown = min(crown, max(0, ceil((height - viewport.size.height) / 20)))
                }
                .onChange(of: crown) { _, value in
                    proxy.scrollTo("jobs-crown-\(Int(min(maximum, max(0, value)).rounded()))", anchor: .top)
                }
                .onAppear { crownFocused = true }
                .accessibilityScrollAction { direction in
                    let step = max(1, viewport.size.height / 20)
                    if direction == .bottom { crown = min(maximum, crown + step) }
                    if direction == .top { crown = max(0, crown - step) }
                }
            }
        }
    }
}

private struct JobsContentHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}
