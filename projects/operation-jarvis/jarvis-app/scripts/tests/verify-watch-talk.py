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
assert 'Button(action: send)' in view
assert 'guard !sending, !submissionUnconfirmed else { return }' in view
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
