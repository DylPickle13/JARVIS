import SwiftUI
import UIKit

/// Native, user-authorized clipboard access. Capture the session inside the
/// provider callback, before asynchronously loading its contents.
struct PiTerminalPasteControl: UIViewRepresentable {
    let receive: ([NSItemProvider]) -> Void

    final class Receiver: UIView {
        var receive: (([NSItemProvider]) -> Void)?
        override init(frame: CGRect) {
            super.init(frame: frame)
            pasteConfiguration = UIPasteConfiguration(forAccepting: NSString.self)
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
        override func paste(itemProviders: [NSItemProvider]) { receive?(itemProviders) }
    }

    func makeCoordinator() -> Receiver { Receiver(frame: .zero) }
    static func buttonConfiguration() -> UIPasteControl.Configuration {
        let configuration = UIPasteControl.Configuration()
        configuration.displayMode = .iconOnly
        configuration.cornerStyle = .capsule
        configuration.baseForegroundColor = UIColor(JarvisPalette.accent)
        configuration.baseBackgroundColor = .clear
        return configuration
    }

    func makeUIView(context: Context) -> UIPasteControl {
        let control = UIPasteControl(configuration: Self.buttonConfiguration())
        context.coordinator.receive = receive
        control.target = context.coordinator
        control.accessibilityLabel = "Paste into terminal"
        return control
    }
    func updateUIView(_ uiView: UIPasteControl, context: Context) {
        context.coordinator.receive = receive
    }
}
