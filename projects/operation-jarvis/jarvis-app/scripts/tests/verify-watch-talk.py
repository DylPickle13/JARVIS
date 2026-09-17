#!/usr/bin/env python3
"""Bounded source contracts; not a substitute for physical Watch acceptance."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
read = lambda path: (root / path).read_text()
widget = read('JARVISWatchWidget/LauncherWidget.swift')
view = read('JARVISWatch/Views/WatchTalkPromptView.swift')
route = read('JARVISWatch/Views/WatchConnectView.swift')
runtime = read('HostAppIntents/JARVISPromptRuntime.swift')
assert 'JARVISWatchTalkWidget.v1' in widget
assert 'JARVISWatchLauncherWidget.v2' in widget
assert 'JARVISWidgetIcon' in widget and 'JARVISWidgetIconAccented' in widget
assert 'jarvis://talk' in widget
assert 'JARVISWatchTalkWidget()' in read('JARVISWatchWidget/JARVISWatchWidgetBundle.swift')
assert 'JARVISPromptNavigation.isTalkURL(url)' in route
assert 'showTalkPrompt = true' in route
assert 'notifications.showPermissionExplanation || showTalkPrompt' in route
assert 'presentTextInputController(withSuggestions: nil, allowedInputMode: .plain)' in view
assert 'TextField(' not in view and 'Button(action: send)' not in view
assert 'await finishInput(results)' in view
assert 'guard !completion.consumed else { return }' in view
assert 'guard let value = completion.consume(results) else {' in view
assert 'inputPresented = true' in view
assert '.sheet(isPresented: $showTalkPrompt)' not in route
assert 'WatchTalkPromptView(onCancel:' in route
assert 'NavigationStack {' not in view
assert 'TextFieldLink("Open input"' in view
assert '_ = completion.consume(nil)' in view
assert view.count('JARVISPromptRuntime.submit(') == 1
assert 'case .unconfirmed:' in view and 'submissionUnconfirmed = true' in view
assert '.interactiveDismissDisabled(sending)' in view
assert 'client.preflightNewSessionPrompt()' in runtime
assert 'client.sendToNewSession(prompt)' in runtime
assert 'client.send(' not in runtime
assert not (root / 'HostAppIntents/JARVISSiriShortcuts.swift').exists()
for folder in ['HostAppIntents', 'JARVIS', 'JARVISWatch']:
    for path in (root / folder).rglob('*.swift'):
        source = path.read_text()
        for forbidden in ['AppShortcutsProvider', 'SendPromptToJARVISIntent',
                          'OpenJARVISTerminalIntent', 'updateAppShortcutParameters']:
            assert forbidden not in source, (path, forbidden)
print('Watch Talk source contracts passed (physical behavior not tested).')

art = read('JARVISWatchWidget/ResonanceArtwork.swift')
assert 'JARVISResonanceArtwork()' in widget
assert 'JARVISWidgetTimerAnimationFont.register()' in widget
assert 'ResonanceStaticFrame(simplified: reducedLuminance)' in art
assert art.count('Canvas {') == 1
assert '.widgetAccentable()' in art and '.accessibilityHidden(true)' in art
assert '@Environment(\\.accessibilityReduceMotion)' in art
assert '!reducedLuminance && !reduceMotion && JARVISWidgetTimerAnimationFont.isAvailable' in art
assert 'private let frameCount = 32' in art
assert 'JARVISWidgetTimerFrameWindow(' in art and '.id(animates)' in art
assert 'phase: Double(index) / Double(frameCount)' in art
assert 'var phase: Double? = nil' in art
assert 'if let phase, !simplified {' in art
assert 'for index in 0..<3' in art
assert 'triangle(1.02 - 0.72 * u)' in art
assert 'StrokeStyle(lineWidth: 2.8, lineJoin: .round)' in art
assert 'sqrt(max(0, sin(.pi * u)))' in art
assert 'triangle(0.22)' in art
assert 'CascadeFieldGeometry' not in art and 'linearGradient' not in art
assert 'func triangle(_ insetScale: CGFloat) -> Path' in art
assert 'CGPoint(x: -39, y: -34), CGPoint(x: 39, y: -34)' in art
assert 'CGPoint(x: 42, y: -29), CGPoint(x: 3, y: 37)' in art
assert 'path.closeSubpath()' in art
assert 'context.stroke(triangle(1)' in art
assert 'context.stroke(triangle(0.84)' in art
assert 'triangle(simplified ? 0.62 : 0.65)' in art
for forbidden in ['Timer(', 'TimelineView(', 'URLSession', 'repeatForever',
                  'reloadTimelines', '.animation(', 'Date(', 'Color(red:', '.blur(']:
    assert forbidden not in art, forbidden
print('Surge Cascade: 32 timer-selected phases; static reduced-luminance/Reduce Motion/font fallback.')
