# JARVIS, Home and Terminal navigation

Matching swipe animations installed as **build 241** on both iPhone and Watch, with
version/process verification on **2026-10-02 at 13:23 EDT**. Build 240's page grouping
is unchanged. See [deployment checks](operations.md#matching-swipe-animation--build-241)
and [preserved recovery fixes](terminal-recovery-and-notification-taps.md).
Physical gesture, Crown and notification acceptance remains pending owner review.

## iPhone

Tabs remain in their existing positions: **JARVIS → Home → Terminal → Jobs → Settings**.

- **JARVIS** contains Pi session cards, Room Audio, Codex quota and oMLX telemetry.
- **Home** contains the unchanged health/history card, followed by smart plugs and
  purifier cards. Purifier details, command confirmation, explicit recovery,
  stale-state handling and errors move with the controls.
- **Terminal**, Jobs and Settings retain their existing functionality.
- The initial iPhone destination remains the first tab, now labelled JARVIS.

Swipe left for the next tab and right for the previous tab, without wrapping.
A gesture must travel at least 64 points and be predominantly horizontal.
The tab recognizer is **detached on Terminal**: horizontal gestures there only
select Pi sessions. Home and Jobs may swipe into Terminal; use the tab bar to leave.

Vertical scrolling, native controls, horizontal scroll views, explicit SwiftUI
horizontal-control exclusions, presented sheets/dialogs, pushed navigation details,
and VoiceOver are protected from tab gestures. Tab selection uses the same binding
as tab taps. Accepted swipes use the matching page motion below; Reduce Motion
keeps selection immediate and unanimated.

Internal route IDs remain `.home` (JARVIS), `.system` (Home), and `.pi` (Terminal).
Existing URLs, launch arguments, session notifications and widget destinations
keep their meaning. In particular, legacy `jarvis://home` still opens the first
JARVIS dashboard, while `jarvis://system` opens the new Home page.

## Watch

The restored non-wrapping vertical pager follows **Home → Terminal → Plugs →
JARVIS → Jobs**. The Watch still opens to Terminal. This Watch-only arrangement
restores the former card grouping without reverting the iPhone layout or fixes.

- **Home** contains only the health card.
- **Plugs** has its own two-column grid; large text uses single-column Crown scrolling.
- **JARVIS** contains purifier above Codex and oMLX, in its Crown viewport.
- Home uses Crown overflow only for accessibility text sizes.
- From Terminal, swipe down to Home and up to Plugs. Jobs returns to JARVIS.
  Horizontal session gestures are unchanged. Purifier detail sheets suspend
  the underlying pager/Crown input.
- Five page indicators follow the restored order without wrapping.
- Legacy simulator System/Overview arguments remain aliases for Home/JARVIS.

The iPhone grouping stays unchanged; selection is not forcibly mirrored.

## Matching swipe motion — build 241

Accepted swipes use a **300 ms ease-out slide and fade**, travelling 14% of the
viewport: horizontally on iPhone, vertically on Watch. Forward/backward movement
follows each device's existing page order. Swipes commit on release, rather than
tracking the finger interactively. The iPhone tab bar and Watch indicators stay put.

The phone keeps its native `TabView`, delegate, navigation stacks and live controllers.
Temporary page snapshots provide the motion without multiplying UIKit's own tab
crossfade or changing live page opacity/transforms. They stay in memory only and
are removed at completion or cancellation. Content taps are briefly shielded while
the snapshots move; the native tab bar stays usable. New routes, backgrounding,
rotation and Reduce Motion changes cancel the phone animation immediately.
Repeated swipes cannot stack overlays.

Watch uses the same timing and proportional travel through a SwiftUI visual transition.
Reduce Motion, inactive scenes, Always On and modal coverage disable that motion.
Deep links and notification routes remain immediate; no backend work or selection
waits for an animation. Terminal's horizontal session gestures are unchanged.
Tab taps retain their native behavior; this effect belongs to page swipes.

## Refresh ownership and compatibility

- JARVIS owns the existing Pi/Room Audio and visible Codex/oMLX refresh policies.
- Home owns foreground device-state refresh and visible health-history reads.
- iPhone Home foreground entry or explicit device refresh requests purifier cloud
  readings; recurring polling does not. Watch requests purifier readings on JARVIS
  entry, alongside its purifier card, not on Home or Plugs entry.
- Home does not request Codex quota refresh. Passive tabs remain cache readers.
- History pauses when purifier controls cover iPhone Home; Watch history remains Home-only. Existing command locks,
  freshness checks, cooldowns, unknown-outcome handling and no-write-retry rules
  are unchanged.
- Backend endpoints, WatchConnectivity messages, widgets' snapshot publication,
  signing, entitlements and stored data formats do not change.

## Source and verification

- `JARVIS/JARVISApp.swift`: tab labels and shared selection binding.
- `JARVIS/Views/TabSwipeNavigation.swift`: gesture installation and input exclusions.
- `JARVIS/Views/TabPageAnimator.swift`: cancellable native phone-page presentation.
- `JARVISKit/Sources/JARVISKit/PageNavigationMotion.swift`: shared timing, travel and Watch transition.
- `JARVIS/Views/HomeView.swift`: JARVIS dashboard (legacy source name).
- `JARVIS/Views/SystemView.swift`: Home shell (legacy source name).
- `JARVIS/Views/HomeDeviceControls.swift`: extracted plug/purifier UI.
- `JARVIS/AppState.swift`: stable routes, swipe policy and refresh ownership.
- `JARVISWatch/Views/WatchDashboardContent.swift`: regrouped Watch content.
- `JARVISKit/Sources/JARVISKit/WatchDashboardPage.swift`: pager order/bounds.
- `JARVISWatch/Views/WatchTerminalView.swift`: updated vertical destinations only.

Regression coverage includes `TabNavigationTests`, `TabPageAnimationTests`,
`PageNavigationMotionTests`, `AppStateTests`, `WatchDashboardPageTests` and
`OMLXSummaryTests`. Hosted unit tests suppress the
app shell's live networking/notification activation; models use injected fixtures.
Build in an isolated checkout with the pinned package lock. Signing, installation
and physical gesture/Crown/VoiceOver acceptance remain separate steps.

### Watch restoration validation — build 240

149 iPhone tests passed; 285 shared tests completed with 3 expected skips.
Both simulator builds and the signed four-bundle archive passed. The same previously
documented plain Paste pixel test remains excluded. All 37 unchanged terminal tests
passed in the fresh frozen release source; earlier temporary-workspace runs hit
the sampler timing assertion and are retained as diagnostic evidence.

The affected Watch source contracts passed; the unrelated broad verifier was not
claimed as passing. Production iPhone source, notification routing, terminald,
entitlements and pinned dependencies match build 239. No device-control commands
were issued. Both physical installs and version/process readbacks passed. Eighteen
protected service PIDs were unchanged; the installer flagged a Pi 4 process change
during its post-check. All ten tmux slots still exist. The owner acknowledged a
possible concurrent restart and closed the follow-up; the original check is retained.
See the operations record; physical swipe/Crown acceptance remains pending.

### Original navigation validation — build 239, 2026-10-02

- Shared package: **285 tests, 3 expected live-test skips, no failures**, including the completion-tap correction.
- iPhone simulator: **149 tests passed**, including 10 navigation/layout tests.
- iPhone and Watch simulator builds succeeded with the unchanged pinned dependency lock.
- Synthetic 320-point Home renders were reviewed in dark mode at normal and
  accessibility text sizes; light-mode renders are also retained in test attachments.
- The initial full iOS run reproduced the previously documented
  `testPlainPasteButtonRendersWithoutBlackPlatter` pixel test failure. It is unchanged
  by this work and was excluded from the final successful run.
- The broad backend/terminal integration verifier was not run; it includes unrelated
  historical source assertions. Its affected device-location/pager assertions were
  updated, and shell syntax plus `git diff --check` passed.
- Build 239 was subsequently signed, audited and installed once on each physical
  device, with independent final version/process checks. The separately approved
  terminald TLS fix was deployed with credentials and Pi identities preserved.
  The terminal service's 37 isolated tests passed; no live hardware command or
  synthetic notification was sent. Real gestures, Crown and VoiceOver still
  require physical acceptance.
