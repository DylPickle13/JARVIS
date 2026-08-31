import Foundation
import SwiftUI

enum JobResultRichText {
    static let maximumLinks = 20
    static let maximumURLBytes = 2_048

    static func attributedString(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace,
            failurePolicy: .returnPartiallyParsedIfPossible
        )
        var attributed = (try? AttributedString(markdown: text, options: options))
            ?? AttributedString(text)
        let candidates = attributed.runs.compactMap { run -> LinkCandidate? in
            guard let url = run.link else { return nil }
            return LinkCandidate(range: run.range, url: url)
        }

        var accepted = 0
        for candidate in candidates {
            if accepted < maximumLinks, isSafe(candidate.url) {
                accepted += 1
            } else {
                attributed[candidate.range].link = nil
            }
        }
        return attributed
    }

    static func plainText(_ text: String) -> String {
        String(attributedString(text).characters)
    }

    static func links(in attributed: AttributedString) -> [URL] {
        attributed.runs.compactMap(\.link)
    }

    private static func isSafe(_ url: URL) -> Bool {
        guard url.absoluteString.utf8.count <= maximumURLBytes,
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              let host = url.host, !host.isEmpty,
              url.user == nil,
              url.password == nil else { return false }
        return true
    }

    private struct LinkCandidate {
        let range: Range<AttributedString.Index>
        let url: URL
    }
}

struct LinkedJobResultText: View {
    let text: String

    var body: some View {
        Text(JobResultRichText.attributedString(text))
            .font(.callout)
            .tint(JarvisPalette.accent)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
