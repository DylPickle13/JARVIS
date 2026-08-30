import Foundation
import SwiftUI
import JARVISKit

struct JobsView: View {
    enum Section: String, CaseIterable, Identifiable {
        case inbox = "Inbox"
        case schedules = "Schedules"
        var id: Self { self }
    }

    @EnvironmentObject private var app: AppState
    @Binding var requestedResultSequence: Int?
    @State private var section: Section = .inbox
    @State private var path: [Int] = []

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    Picker("Jobs section", selection: $section) {
                        ForEach(Section.allCases) { item in
                            Text(item.rawValue).tag(item)
                        }
                    }
                    .pickerStyle(.segmented)

                    switch section {
                    case .inbox:
                        inbox
                    case .schedules:
                        schedules
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 16)
            }
            .background(JarvisBackdrop())
            .navigationTitle("Jobs")
            .navigationDestination(for: Int.self) { sequence in
                ScheduledJobResultDetail(sequence: sequence)
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

    @ViewBuilder
    private var inbox: some View {
        if let error = app.scheduledJobResultsErrorMessage {
            messageCard(
                title: "Result history unavailable",
                detail: error,
                systemImage: "exclamationmark.triangle.fill",
                color: JarvisPalette.warning
            )
        }

        if app.scheduledJobResultsLoading && app.lastScheduledJobResults.isEmpty {
            MinimalCard {
                HStack(spacing: 10) {
                    ProgressView()
                    Text("Loading job results…")
                        .font(.subheadline.weight(.medium))
                    Spacer()
                }
            }
        } else if app.lastScheduledJobResults.isEmpty {
            messageCard(
                title: "No local results yet",
                detail: "Future job output and every failure will appear here.",
                systemImage: "tray",
                color: .secondary
            )
        } else {
            ForEach(app.lastScheduledJobResults) { result in
                NavigationLink(value: result.sequence) {
                    resultCard(result)
                }
                .buttonStyle(.plain)
            }
        }
    }

    @ViewBuilder
    private var schedules: some View {
        if let error = app.scheduledJobsErrorMessage {
            messageCard(
                title: "Schedules unavailable",
                detail: error,
                systemImage: "exclamationmark.triangle.fill",
                color: JarvisPalette.warning
            )
        }

        if app.scheduledJobsLoading && app.lastScheduledJobs.isEmpty {
            MinimalCard {
                HStack(spacing: 10) {
                    ProgressView()
                    Text("Loading schedules…")
                        .font(.subheadline.weight(.medium))
                    Spacer()
                }
            }
        } else if app.lastScheduledJobs.isEmpty {
            messageCard(
                title: "No schedules configured",
                detail: "Scheduled-job management remains private and read-only here.",
                systemImage: "calendar.badge.clock",
                color: .secondary
            )
        } else {
            ForEach(app.lastScheduledJobs) { job in
                scheduleCard(job)
            }
        }
    }

    private func resultCard(_ result: ScheduledJobResult) -> some View {
        let failed = result.status == "error"
        return MinimalCard {
            HStack(alignment: .top, spacing: 11) {
                Image(systemName: failed ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(failed ? JarvisPalette.warning : JarvisPalette.accent)
                    .padding(.top, 1)

                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text(JarvisFormat.displayName(result.jobName))
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(1)
                        if result.truncated {
                            Text("TRUNCATED")
                                .font(.caption2.weight(.bold))
                                .foregroundStyle(JarvisPalette.warning)
                        }
                    }
                    Text(result.summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                    Text(JarvisFormat.localDateTime(result.finishedAt) ?? result.finishedAt)
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.tertiary)
                }
                Spacer(minLength: 6)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .padding(.top, 2)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(JarvisFormat.displayName(result.jobName)), \(failed ? "failed" : "completed"), \(result.summary)")
        .accessibilityHint("Opens the retained job result")
    }

    private func scheduleCard(_ job: ScheduledJob) -> some View {
        let failed = job.lastStatus == "error"
        return MinimalCard {
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 8) {
                    Circle()
                        .fill(job.enabled ? (failed ? JarvisPalette.warning : JarvisPalette.accent) : Color.secondary)
                        .frame(width: 8, height: 8)
                    Text(JarvisFormat.displayName(job.name))
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    Text(job.enabled ? "Enabled" : "Disabled")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Label(job.schedule, systemImage: "clock")
                    Spacer()
                    Text("\(job.runCount) runs")
                }
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                if let next = JarvisFormat.localDateTime(job.nextRunAt) {
                    Text("Next: \(next)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let description = job.description, !description.isEmpty {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let count = job.consecutiveErrors, count > 0 {
                    Text("\(count) consecutive failure\(count == 1 ? "" : "s")")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(JarvisPalette.warning)
                }
            }
        }
        .accessibilityElement(children: .combine)
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
        section = .inbox
        await app.fetchScheduledJobResult(sequence: sequence)
        if app.scheduledJobResult(sequence: sequence) != nil {
            if path.last != sequence { path.append(sequence) }
        }
        requestedResultSequence = nil
    }
}

private struct ScheduledJobResultDetail: View {
    @EnvironmentObject private var app: AppState
    let sequence: Int

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                if let result = app.scheduledJobResult(sequence: sequence) {
                    metadata(result)
                    if let error = result.error, !error.isEmpty {
                        contentCard(title: "Failure", text: error, color: JarvisPalette.warning)
                    }
                    if let output = result.output, !output.isEmpty {
                        contentCard(title: "Output", text: output, color: JarvisPalette.accent)
                    }
                    let links = safeLinks(in: [result.output, result.error].compactMap { $0 }.joined(separator: "\n"))
                    if !links.isEmpty {
                        MinimalCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Label("Links", systemImage: "link")
                                    .font(.subheadline.weight(.semibold))
                                ForEach(links, id: \.absoluteString) { url in
                                    Link(destination: url) {
                                        HStack {
                                            Text(url.host ?? url.absoluteString)
                                                .font(.caption)
                                                .lineLimit(1)
                                            Spacer()
                                            Image(systemName: "arrow.up.right")
                                                .font(.caption2.weight(.semibold))
                                        }
                                    }
                                }
                            }
                        }
                    }
                } else {
                    MinimalCard {
                        Label("This retained result is unavailable.", systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(16)
        }
        .background(JarvisBackdrop())
        .navigationTitle(app.scheduledJobResult(sequence: sequence).map { JarvisFormat.displayName($0.jobName) } ?? "Job Result")
        .navigationBarTitleDisplayMode(.inline)
        .task { await app.fetchScheduledJobResult(sequence: sequence) }
    }

    private func metadata(_ result: ScheduledJobResult) -> some View {
        let failed = result.status == "error"
        return MinimalCard {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Label(
                        failed ? "Failed" : "Completed",
                        systemImage: failed ? "exclamationmark.circle.fill" : "checkmark.circle.fill"
                    )
                    .font(.headline)
                    .foregroundStyle(failed ? JarvisPalette.warning : JarvisPalette.accent)
                    Spacer()
                    if result.truncated {
                        Text("TRUNCATED")
                            .font(.caption2.weight(.bold))
                            .foregroundStyle(JarvisPalette.warning)
                    }
                }
                Text(result.summary)
                    .font(.subheadline)
                Divider()
                metadataRow("Finished", JarvisFormat.localDateTime(result.finishedAt) ?? result.finishedAt)
                metadataRow("Duration", String(format: "%.1f seconds", result.durationSeconds))
                if let exitCode = result.exitCode { metadataRow("Exit", String(exitCode)) }
                metadataRow("Result", "#\(result.sequence)")
            }
        }
    }

    private func metadataRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value).multilineTextAlignment(.trailing)
        }
        .font(.caption.monospacedDigit())
    }

    private func contentCard(title: String, text: String, color: Color) -> some View {
        MinimalCard {
            VStack(alignment: .leading, spacing: 8) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(color)
                Text(text)
                    .font(.callout)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func safeLinks(in text: String) -> [URL] {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return [] }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        var seen = Set<String>()
        let links: [URL] = detector.matches(in: text, options: [], range: range).compactMap { match -> URL? in
            guard let url = match.url,
                  url.absoluteString.utf8.count <= 2_048,
                  let scheme = url.scheme?.lowercased(),
                  scheme == "http" || scheme == "https",
                  url.host != nil,
                  url.user == nil,
                  url.password == nil,
                  seen.insert(url.absoluteString).inserted else { return nil }
            return url
        }
        return Array(links.prefix(20))
    }
}
