# iPhone terminal keyboard viewport

The owner reported that opening the Pi keyboard (button or gesture) covered the terminal on iOS 27 instead of reducing its viewport.

## Fix

`JARVIS/Terminal/PiTerminalView.swift` now embeds the terminal and the existing 46pt key bar in one `UIViewControllerRepresentable`. The key bar's bottom is constrained to UIKit's `keyboardLayoutGuide.topAnchor`; the terminal ends at the key bar's top. This does not depend on SwiftUI `TabView` propagating a keyboard safe-area change from the terminal's invisible UIKit text responder.

- Docked keyboard: terminal bounds/row count shrink above the toolbar.
- Dismissal/external keyboard: the guide returns to the available bottom safe area.
- Rotation/ancestor safe-area changes: native constraints recalculate, without cached keyboard heights or duplicate SwiftUI padding.
- Floating keyboards do not shrink the entire terminal unnecessarily.
- Existing terminal/controller identity is retained. Normal SwiftTerm size callbacks resize the existing SSH PTY; no session replacement/reconnect or terminal input is introduced.
- Toolbar controls, clipboard safeguards, attachment flag, keyboard button/gestures, responder lifecycle, SSH implementation and Watch source are unchanged.

## Qualification

102 iOS tests passed, including the existing toolbar/clipboard and Watch-card regressions. Two new tests verify portrait/landscape available-space changes, reduced/restored row counts, constant toolbar height, no emitted bytes, retained terminal identity, and two keyboard show/hide cycles inside a SwiftUI TabView using the real keyboard proxy with a deterministic 260pt custom input view. No test connects to a live Pi session.

Tests run with Xcode 27 / SDK 27 on an iOS 26.5 simulator, not iOS 27. A separate attempt with the normal software keyboard produced no displayed keyboard in this simulator session (terminal remained full-height); its failed result is retained outside Git. The repeatable regression uses a custom input view rather than treating that attempt as a passing software-keyboard test.

Physical iOS 27 verification remains required: keyboard button and pull-up gesture, typing/backspace, interactive dismissal, rotation, external keyboard, session switching, selection/paste and attachments. Devices remain disconnected and deployment is paused. Watch179's sealed payload is unchanged; a new iPhone candidate is required for this fix. Signing/deployment evidence is stored separately from source.
