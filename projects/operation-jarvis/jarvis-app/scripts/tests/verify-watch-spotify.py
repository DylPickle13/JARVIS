#!/usr/bin/env python3
"""Static launcher scope checks, not proof of physical Spotify launch."""
from pathlib import Path
root = Path(__file__).resolve().parents[2]
read = lambda p: (root / p).read_text()
view = read('JARVISWatch/Views/WatchSpotifyLauncherView.swift')
widget = read('JARVISWatchWidget/SpotifyLauncherWidget.swift')
route = read('JARVISWatch/Views/WatchConnectView.swift')
assert view.count('openSystemURL(') == 1
assert 'guard scenePhase == .active, !requested else { return }' in view
assert 'requested = true' in view
assert 'openSystemURL(JARVISWatchSpotifyRoute.destination)' in view
for forbidden in ['WatchBridge', 'WCSession', 'UIApplication', 'sendToNewSession', 'run-shortcut', 'spotify://']:
    assert forbidden not in view, forbidden
assert '.widgetURL(JARVISWatchSpotifyRoute.widgetURL)' in widget
assert 'JARVISWatchSpotifyWidget()' in read('JARVISWatchWidget/JARVISWatchWidgetBundle.swift')
assert 'JARVISWatchSpotifyRoute.accepts(url)' in route
assert 'guard !showTalkPrompt else { return }' in route
assert 'spotifyLaunchSequence += 1' in route and '.id(spotifyLaunchSequence)' in route
assert 'ForEach(0..<8' in widget and 'frameCount: 8' in widget
assert '!dimmed && !reduceMotion && JARVISWidgetTimerAnimationFont.isAvailable' in widget
for forbidden in ['Timer(', 'TimelineView(', 'URLSession', 'repeatForever']:
    assert forbidden not in widget
assert 'JARVISWatchSpotifyRoute' not in read('JARVIS/JARVISApp.swift')
print('Spotify Watch-only request, fixed destination, bounded animation and no phone/command fallback contracts passed.')
