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
assert 'allowsMotion && !reducedLuminance && !reduceMotion' in art
assert 'JARVISWidgetTimerAnimationFont.isAvailable' in art
assert 'widgetRenderingMode' not in art and 'renderingMode == .fullColor' not in art
assert 'ResonanceFrame(phase: 0, movingOnly: false, subdued: animate)' in art
assert 'ForEach(0..<24' in art
assert 'JARVISWidgetTimerFrameWindow(frameIndex: index, frameCount: 24' in art
assert '.widgetAccentable()' in art and '.accessibilityHidden(true)' in art
for forbidden in ['Timer(', 'TimelineView(', 'URLSession', 'repeatForever', 'reloadTimelines']:
    assert forbidden not in art, forbidden
print('Resonance static fallback, motion gating, and unchanged routing contracts passed.')
