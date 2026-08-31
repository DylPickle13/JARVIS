import Foundation
import JARVISKit

struct ScheduledJobThread: Identifiable {
    let id: String
    let job: ScheduledJob?
    let name: String
    let messages: [ScheduledJobResult]

    var latestMessage: ScheduledJobResult? { messages.first }
    var isArchived: Bool { job == nil }
}

struct ScheduledJobThreadSections {
    let scheduled: [ScheduledJobThread]
    let archived: [ScheduledJobThread]
}

enum JobsPresentation {
    static func threads(
        jobs: [ScheduledJob],
        results: [ScheduledJobResult]
    ) -> ScheduledJobThreadSections {
        let orderedResults = results.sorted { lhs, rhs in lhs.sequence > rhs.sequence }
        let grouped = Dictionary(grouping: orderedResults, by: \.jobId)
        var scheduledIDs = Set<String>()

        let scheduled = jobs.compactMap { job -> ScheduledJobThread? in
            guard scheduledIDs.insert(job.id).inserted else { return nil }
            return ScheduledJobThread(
                id: job.id,
                job: job,
                name: job.name,
                messages: grouped[job.id] ?? []
            )
        }

        let archived = grouped.compactMap { jobID, messages -> ScheduledJobThread? in
            guard !scheduledIDs.contains(jobID), let latest = messages.first else { return nil }
            return ScheduledJobThread(
                id: jobID,
                job: nil,
                name: latest.jobName,
                messages: messages
            )
        }
        .sorted { lhs, rhs in
            (lhs.latestMessage?.sequence ?? 0) > (rhs.latestMessage?.sequence ?? 0)
        }

        return ScheduledJobThreadSections(scheduled: scheduled, archived: archived)
    }

    static func cadence(kind: String, schedule: String) -> String {
        switch kind {
        case "interval":
            return intervalCadence(schedule) ?? "Repeats · \(schedule)"
        case "once":
            return "Runs once"
        case "cron":
            return cronCadence(schedule) ?? "Custom schedule"
        default:
            return schedule
        }
    }

    static func scheduleSymbol(kind: String) -> String {
        switch kind {
        case "interval": return "arrow.clockwise"
        case "once": return "calendar.badge.checkmark"
        default: return "calendar.badge.clock"
        }
    }

    static func runCount(_ count: Int) -> String {
        count.formatted(.number.notation(.compactName))
    }

    private static func intervalCadence(_ schedule: String) -> String? {
        let pattern = #"^\+?(\d+)([smhd])$"#
        guard let expression = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return nil
        }
        let fullRange = NSRange(schedule.startIndex..<schedule.endIndex, in: schedule)
        guard let match = expression.firstMatch(in: schedule, range: fullRange),
              match.range == fullRange,
              let valueRange = Range(match.range(at: 1), in: schedule),
              let unitRange = Range(match.range(at: 2), in: schedule),
              let value = Int(schedule[valueRange]) else { return nil }

        let unit = schedule[unitRange].lowercased()
        let singular: String
        switch unit {
        case "s": singular = "second"
        case "m": singular = "minute"
        case "h": singular = "hour"
        case "d": singular = "day"
        default: return nil
        }
        return value == 1 ? "Every \(singular)" : "Every \(value) \(singular)s"
    }

    private static func cronCadence(_ schedule: String) -> String? {
        let fields = schedule.split(whereSeparator: \.isWhitespace)
        guard fields.count == 5,
              let minute = Int(fields[0]), (0...59).contains(minute),
              let hour = Int(fields[1]), (0...23).contains(hour),
              fields[2] == "*", fields[3] == "*" else { return nil }

        let time = localTime(hour: hour, minute: minute)
        switch fields[4] {
        case "*": return "Daily at \(time)"
        case "1-5": return "Weekdays at \(time)"
        default: return nil
        }
    }

    private static func localTime(hour: Int, minute: Int) -> String {
        var components = DateComponents()
        components.calendar = Calendar(identifier: .gregorian)
        components.timeZone = .current
        components.year = 2001
        components.month = 1
        components.day = 1
        components.hour = hour
        components.minute = minute
        guard let date = components.date else {
            return String(format: "%02d:%02d", hour, minute)
        }
        return date.formatted(date: .omitted, time: .shortened)
    }
}
