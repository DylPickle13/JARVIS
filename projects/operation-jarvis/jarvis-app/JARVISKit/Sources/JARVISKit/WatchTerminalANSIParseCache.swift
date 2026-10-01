import Foundation

/// Reuses only the unchanged prefix of the previous parse, including its SGR
/// state. This is a rendering cache, never a source of terminal frames or input
/// readiness. Any changed row invalidates that row and the entire suffix.
public struct WatchTerminalANSIParseCache {
    private var lines: [String] = []
    private var spans: [[WatchTerminalANSISpan]] = []
    private var endingStyles: [WatchTerminalANSIStyle] = []
    public private(set) var lastParsedRowCount = 0

    public init() {}

    public mutating func parse(lines next: [String]) -> [[WatchTerminalANSISpan]] {
        var prefix = 0
        while prefix < min(lines.count, next.count), lines[prefix] == next[prefix] {
            prefix += 1
        }
        spans.removeSubrange(prefix..<spans.count)
        endingStyles.removeSubrange(prefix..<endingStyles.count)
        var style = endingStyles.last ?? WatchTerminalANSIStyle()
        lastParsedRowCount = next.count - prefix
        for line in next.dropFirst(prefix) {
            spans.append(WatchTerminalANSIParser.parse(line: line, style: &style))
            endingStyles.append(style)
        }
        lines = next
        return spans
    }
}
