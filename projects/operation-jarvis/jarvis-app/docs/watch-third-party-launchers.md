# Watch-only third-party launcher research

## Result

- **Spotify:** implementation prepared for physical validation. Spotify's live association file explicitly lists `2FNC3A47ZF.com.spotify.client.watchkitapp.watchkitextension` and the `/home` path. Apple's universal-link documentation supports opening another Watch app through `WKApplication.openSystemURL` / the older `WKExtension.openSystemURL`. This is substantially stronger evidence than assuming the iPhone `spotify:` scheme works on Watch.
- **Shortcuts:** blocked; no working supported third-party launch route established. Do not advertise a working JARVIS Shortcuts complication. The existing native Shortcuts complication remains the appropriate launcher.
- **Nothing deployed.** Owner disconnected devices and explicitly deferred deployment. No physical-device queries, installations, launches, or signing changes were performed during this research.

## Evidence and limitations

Sources checked September 15, 2026 (EDT):

1. [Spotify's live Apple App Site Association](https://open.spotify.com/.well-known/apple-app-site-association): production Watch extension + `/home` are present. This must be paired with Spotify's installed app entitlements and handling; the association file alone is not physical acceptance.
2. [Apple: allowing apps and websites to link to your content](https://developer.apple.com/documentation/xcode/allowing-apps-and-websites-to-link-to-your-content): explicitly demonstrates WatchKit opening a universal link in another application.
3. [Apple WWDC20: What's new in Universal Links](https://developer.apple.com/videos/play/wwdc2020/10098/), approximately 1:27–3:09: Watch universal links, local system handling, failure UI if the app is absent, and absence of a success callback. Do not infer target launch from the API call returning.
4. [Apple: widget links](https://developer.apple.com/documentation/widgetkit/linking-to-specific-app-scenes-from-your-widget-or-live-activity): widget links activate the containing app. The new complication therefore opens JARVIS first, which requests Spotify from the Watch process.
5. [Apple: openSystemURL](https://developer.apple.com/documentation/watchkit/wkapplication/opensystemurl(_:)): the method reference describes system schemes; the separate universal-link article documents HTTPS app links. It is not permission to open arbitrary app bundle IDs.
6. [Apple: Shortcuts URL schemes](https://support.apple.com/guide/shortcuts/intro-to-url-schemes-apd621a1ad7a/ios): iPhone/iPad documentation, not proof of Watch support.

Read-only inspection of the installed **watchOS26.5 simulator** Shortcuts Info.plist found `shortcuts`, `shortcuts-production`, and `workflow` URL schemes. However, an isolated SwiftUI Watch probe calling the public `WKApplication.shared().openSystemURL(URL(string: "shortcuts://")!)` stayed on its own screen. A second controlled run logged:

> URL with scheme "shortcuts" not supported

A direct simulator launch control opened the Shortcuts UI successfully, demonstrating that the app itself was available. Scheme registration does not override WatchKit's outgoing URL policy. Both temporary, unpaired Watch simulators were shut down and deleted; existing simulators were not booted or altered. This result is bounded to watchOS26.5 simulation, not a proof of every future OS version. No watchOS27-supported alternative was found. No private APIs or device-management launch tools are embedded in the app.

## Spotify implementation

- New **Spotify · JARVIS** Watch complication, kind `JARVISWatchSpotifyWidget.v1`.
- Circular/corner/rectangular families use a music note within segmented monochrome rings. Inline uses a readable music label.
- Eight lightweight decorative timer-mask frames; no playback-state or microphone claim. Permanent static glyph/rings remain if animation freezes. Always On, Reduce Motion, and missing font select the static rendering. Tinted rendering is allowed, as requested for Resonance.
- Animation adds 16 timer masks per displayed icon. Battery cost remains unmeasured; this is smaller than Resonance's 48 masks, not proof of negligible energy cost.
- Exact internal route `jarvis://spotify`; unknown paths, queries, fragments, user info, and ports are rejected. Fixed external destination `https://open.spotify.com/home`.
- Only the Watch host handles the route. No iPhone handler, WatchConnectivity message, remote launch, account access, playback request, shortcut execution, or user-supplied URL.
- One request per opening; no automatic retries when returning to JARVIS. An explanatory Close screen remains if the Watch doesn't leave JARVIS. No success claim is made from the API call.
- Talk input cannot be interrupted by the Spotify route. Accepted prompt/runtime logic and existing complication kinds remain intact.

## Physical deployment acceptance (pending)

After the owner reconnects and authorizes deployment:

1. Fresh signing/product audit and current device/runtime identity checks; no closed deployment driver reuse.
2. Confirm Spotify is installed on Watch. Add **Spotify · JARVIS** to a supported slot.
3. Tap it and verify the **Spotify Watch app** becomes visible. Check the iPhone remains unchanged. No playback should start solely from this request.
4. Test cold and warm JARVIS launches and returning from Spotify; no launch loops.
5. Verify unsupported/missing-app handling remains on Watch and never requests a phone fallback. If physical behavior differs, reject the route rather than substitute a phone launch.
6. Check reduced-motion/Always On/static fallbacks, real-face animation, and battery under normal use without a developer connection.
7. Recheck Talk-to-JARVIS and first-unused-New-session behavior; avoid live test prompts without owner approval.

Until those checks pass, this is **ready for a test deployment**, not a verified end-to-end Watch-only Spotify launcher. Shortcuts remains intentionally unimplemented.
