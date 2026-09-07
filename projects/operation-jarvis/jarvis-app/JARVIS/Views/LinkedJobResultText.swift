import Foundation
import JARVISKit
import SwiftUI

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
