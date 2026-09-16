# iPhone terminal keyboard viewport

## Build180 regression — do not redeploy

The owner reported that opening the Pi keyboard covered the terminal on iOS27. Build180 attempted a native keyboard-layout-guide constraint. Although its iOS26.5 simulator tests passed, the owner reported the terminal invisible and the purple toolbar at the top after physical installation. Build180 is rejected for further deployment. The exact OS27 layout failure was not reproduced on the26.5 simulator, including a subsequent ZStack/TabView regression attempt; passing simulator tests did not establish physical acceptance.

## Correction

`JARVIS/Terminal/PiTerminalView.swift` explicitly fills the SwiftUI parent proposal using GeometryReader and representable sizeThatFits. It no longer uses keyboardLayoutGuide or a keyboard-dependent Auto Layout chain to determine terminal height.

The native viewport lays out the existing terminal and46pt toolbar from bounded view dimensions. Keyboard frame notifications are converted from the screen coordinate space into this viewport; only a full-width docked keyboard intersecting its bottom reduces available height. Parent resizing therefore does not subtract the keyboard height twice. Hidden/empty/invalid full-screen frames and floating keyboards do not collapse the terminal. The child toolbar hosting controller has its own safe-area avoidance disabled so it cannot independently move the buttons. Notification animation duration/curve are respected; keyboard dismissal and ancestor layout recalculate bounds.

The same terminal/controller is retained. No SSH/session replacement, terminal input, clipboard-policy changes, or Watch-source changes. Existing attachment compile flag and toolbar controls remain intact.

## Qualification

103 iOS tests pass with Xcode27/SDK27 on iOS26.5 simulator. Coverage includes safe-area/portrait/landscape bounds, bounded keyboard intersections, zero/hidden/floating/full-screen frames, no double inset, constant46pt toolbar, row shrink/restoration and retained identity/no emitted bytes. Real proxy show/hide is exercised twice with a deterministic260pt custom input view in ZStack/TabView; the terminal must initially exceed500pt and remain above200pt when open. A retained screenshot shows local fixture text above the bottom toolbar (no live terminal contents or SSH connection).

Normal software keyboard and physical iOS27 acceptance are still required: visible terminal and bottom toolbar before opening, keyboard button and pull-up gesture, typing/backspace, dismissal, rotation, external keyboard, selection/paste/attachments. The simulator custom input view is not physical keyboard acceptance.

Build/signing/deployment evidence is kept separately. Preserve rejected180 evidence and use new immutable candidate/continuation baselines. Watch deployment remains paused while correcting the iPhone regression.
