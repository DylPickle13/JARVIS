# JARVIS, Home and Terminal navigation

Matching swipe animations installed as **build 241** on both iPhone and Watch, with
version/process verification on **2026-10-02 at 13:23 EDT**. Build 240's page grouping
is unchanged. See [deployment checks](operations.md#matching-swipe-animation--build-241)
and [preserved recovery fixes](terminal-recovery-and-notification-taps.md).
Physical gesture, Crown and notification acceptance remains pending owner review.
Inline iPhone Settings shipped as build 242, then the balanced summary-card grid
superseded it in **build 243**, independently version/launch/process verified at
**2026-10-02 16:06 EDT**. Neither release issued a direct Watch install.

## iPhone

Tabs remain in their existing positions: **JARVIS → Home → Terminal → Jobs → Settings**.

- **JARVIS** contains Pi session cards, Room Audio, Codex quota and oMLX telemetry.
- **Home** contains the unchanged health/history card, followed by smart plugs and
  purifier cards. Purifier details, command confirmation, explicit recovery,
  stale-state handling and errors move with the controls.
- **Terminal** and Jobs retain their existing functionality. Settings uses the
  balanced summary-card grid and separate editors shipped in build 243.
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

## Balanced Settings grid — build 243

Owner review rejected build 242's uneven card sizes. The replacement keeps Liquid
Glass but returns text/password entry to pushed detail pages:

- **Four equally sized summary cards** in a 2 × 2 grid: Connection, iPhone
  Terminal, Watch Terminal and Notifications. A custom measured layout gives every
  card the same width and height, including when one summary is longer. Large
  accessibility text uses one column; text is not shrunk to force a fit.
- Connection shows state and active endpoint; iPhone Terminal shows configuration,
  resolved SSH host/port and username; Watch shows provisioning state and bridge
  host/port (not URL credentials, path or query). Full values remain on detail pages.
- Notifications keeps a directly usable Alerts toggle and independent iPhone/Watch
  registration summaries. The toggle is outside the card's navigation link so
  toggling cannot also push a page. Provider, queue and retry controls live in details.
- **One full-width Diagnostics & Maintenance card** below shows daemon version,
  uptime and LAN/Tailscale addresses, plus confirmation-protected Restart all 10
  Pi sessions and operation/retry status. The version footer follows it.
- Connection editing/reset, SSH credentials/save/forget-trust and private Watch
  setup-code entry use full-width glass sections on separate pages. Those pages
  have their own page-level scrolling and visible back navigation; no card scrolls.

The overview contains no text fields and does not load the SSH password. Existing
credential/provisioning models remain directly observed, and save, reconnect,
Watch publication, secure registration and maintenance recovery APIs are unchanged.
Safety confirmations remain. Main-page overflow is retained for accessibility,
long summaries and exceptional operation messages, not normal portrait use.

Implementation: `JARVIS/Views/SettingsView.swift` and
`JARVIS/Views/SettingsDetailView.swift`. **163 iPhone tests passed** from an isolated
source snapshot, with only the previously documented plain-Paste pixel test excluded.
The populated 414 × 896 iPhone 11 fixture measured **685.5 pt** within the **765 pt**
viewport above the tab bar. Tests verify identical bounds for all four cards even
with long content, zero overview text fields, navigation/back for all four editors,
visible invalid-save errors, accessibility expansion and toggle-without-navigation.
The frozen build-243 release source passed the same 163-test regression. Private
release evidence: `20261002T200255Z-build243-balanced-settings`, including
`ios-tests.xcresult`, `ios-verified.log`, signed archive audit and deployment readbacks.

The audited archive was installed once on the approved iPhone and independently
version/launch/process verified at **2026-10-02 16:06 EDT**. Launch requested Settings.
All 18 protected service PIDs and existing Pi panes were preserved. Exact signed
build 242 is retained for rollback. No backend/Pi restart or direct Watch install;
iOS may automatically transfer the embedded unchanged-source companion. Watch's
last independent device version verification remains build 241. Physical layout,
keyboard and VoiceOver acceptance awaits owner review.

## Inline iPhone Settings — build 242

Historical build 242 used six always-expanded Liquid Glass cards, not navigation
cards. Owner review rejected the uneven sizes; build 243 supersedes this layout:

1. **Connection + Diagnostics** share a row: endpoint/status/override/Connect/Reset
   alongside daemon version, uptime and LAN/Tailscale addresses.
2. **iPhone Terminal** spans the width: host/port, username/password and Save login.
3. **Watch Terminal + Maintenance** share a row: provisioning state, full bridge
   address, private setup code/Send and provisioning-script guidance alongside
   Forget trusted host, Restart all 10 Pi sessions and operation/retry status.
4. **Notifications** spans the width: toggle, independent registrations, APNs and
   dispatch status, queue counts, secure retry, refresh and preview-privacy guidance.

The initial mostly full-width proposal measured too tall. Pairing related cards
keeps normal portrait settings on one screen without reducing the 44-point action
areas. There are no internal scroll views, disclosures, inspector sheets or hidden
technical details. Long values wrap; passwords/setup codes remain secure fields.
Only the outer page can scroll for smaller screens, large text, long errors or the
keyboard. Accessibility sizes stack paired cards and field/action rows vertically.

Reset, forgetting SSH trust and session restarts still require confirmation.
Existing SSH/Keychain save, Watch provisioning, notification registration, secure
retry and maintenance operation-ID/recovery APIs are unchanged. Merely opening
Settings does not save credentials, provision Watch, reconnect Terminal or restart
sessions. It refreshes read-only notification status, as the previous notification
screen did. Credential/provisioning models are directly observed so failures remain
visible even when a save does not change the successful/configured state.

Implementation: `JARVIS/Views/SettingsView.swift`. The four obsolete destination
views have been removed. `SettingsLayoutTests` covers the six-card/no-hidden-detail
contract, natural portrait fit, native text fields, full-tab-bar fit, long details
and accessibility expansion, plus visible invalid-save errors without credential
changes. Simulator regression: **160 iPhone tests passed**, excluding only the
previously documented plain-Paste pixel test. On the 414 × 896 iPhone 11 fixture,
unconfigured content measured **661.5 pt** and populated content (including a long
Watch bridge URL and APNs queue details) **726.5 pt**, within the measured **765 pt**
viewport above the five-tab bar. All six native text fields were mounted without
navigation. The frozen build-242 source passed the same 160-test regression.
Private release evidence: `20261002T193649Z-build242-inline-settings`, including
`ios-tests.xcresult`, `ios-verified.log`, signed archive audit and deployment readbacks.

The exact audited archive was installed once on the approved iPhone; final version
and running process were independently verified at **2026-10-02 15:40 EDT**. The
launch requested the Settings tab. All 18 protected service PIDs and existing Pi
panes were preserved. Exact signed build 241 is retained for rollback. No direct
Watch installation was issued; iOS may transfer the embedded companion automatically,
so Watch's last independent version verification remains build 241.

Physical layout/keyboard/VoiceOver acceptance remains pending owner review. Watch,
backend and credential-store implementations, entitlements and the pinned dependency
lock are unchanged. Shared/backend test evidence is retained from previous releases,
not presented as a new run; the broad all-subsystem verifier is not claimed here.

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
