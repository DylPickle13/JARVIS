# Durable background-browser options

Research: 2026-10-11. Installed Chrome: 154.0.8037.99.
No running-browser, profile, launcher, policy or recovery changes were made by this
research. The owner subsequently declined a separate browser and requested removal
of the occlusion flag. Chrome has been relaunched without it; these options remain
research only, not approved implementation work.

## Evidence and limits

The original site's element screenshot timed out waiting for stability, with an
independently observed Runtime.callFunctionOn pending beyond the drain grace.
After owner-directed visibility, the command acknowledged. A separately approved
Chrome restart with `--disable-backgrounding-occluded-windows` was followed by two
successful out-of-view heading screenshots. The restarted page was signed out and
used a new renderer: this is mitigation evidence, not a controlled proof that every
original application failure has been eliminated.

Pinned Playwright's stability helper requires animation-frame callbacks. Its
local timeout does not cancel an already pending renderer evaluation. A permanent
solution must preserve actionability checks and actual execution receipts, rather
than force clicks, claim cancellation, or simply release recovery fences.

## Source checks against the installed Chrome version

1. `WebContentsImpl::UpdateWebContentsVisibility` maps OCCLUDED to VISIBLE when
   `kDisableBackgroundingOccludedWindowsForTesting` is present. It also trusts
   initial visibility before the first genuine visible transition, explaining why
   never-shown fixture tabs are not adequate controls for previously viewed tabs.
   https://raw.githubusercontent.com/chromium/chromium/154.0.8037.99/content/browser/web_contents/web_contents_impl.cc
2. `WindowOcclusionEnabled` is a persistent policy, but its supported platform is
   `chrome.win:90-`, **not macOS**. Its deprecated predecessor is also Windows-only.
   Writing an identically named macOS preference is not a supported solution.
   https://raw.githubusercontent.com/chromium/chromium/154.0.8037.99/components/policy/resources/templates/policy_definitions/Miscellaneous/WindowOcclusionEnabled.yaml
3. The current `FocusController::SetFocusEmulationEnabled` implementation changes
   emulated active/focused state; it is not a browser-window occlusion override.
   It can also change focus/blur semantics seen by a website. It is not established
   as a fix for this incident.
   https://raw.githubusercontent.com/chromium/chromium/154.0.8037.99/third_party/blink/renderer/core/page/focus_controller.cc
4. `PageHandler::SetWebLifecycleState(active)` calls SetPageFrozen(false), not a
   window visibility override. Unfreezing and removing occlusion are distinct.
   Screenshot/screencast/recording APIs are capture mechanisms, not a documented
   per-tab background-rendering policy. No ongoing capture workaround was enabled.
   https://raw.githubusercontent.com/chromium/chromium/154.0.8037.99/content/browser/devtools/protocol/page_handler.cc
5. No current `MacWebContentsOcclusion` feature entry was found in this version's
   about_flags.cc, content/common/features.cc or content/public/common/content_features.cc.
   Search results showing that older feature name are not sufficient evidence of
   a supported current chrome://flags preference.

These findings do not prove no future Chromium API can solve this. They do rule
out presenting the checked alternatives as a verified macOS per-tab fix today.

## Option A — retain the shared profile, manage startup

Make the approved rendering policy part of a reviewed Chrome launcher and verify
it before browser work begins. This avoids remembering a command-line argument,
retains the current shared cookies/profile, and does not alter action safeguards.

A Dock wrapper **alone is insufficient**: normal app launch, login restoration,
Spotlight or opening a URL can start Chrome first without the argument. A complete
plan must define which startup entry points are managed and detect unsupported
starts. Never silently kill/relaunch a running personal browser to repair flags.
Do not edit Chrome's signed app bundle. No persistent startup mechanism has been
installed. The Chrome-wide background rendering/power trade-off remains.

This is a durable deployment of the workaround, not a different rendering fix.

## Option B — recommended architectural separation, if approved

Use a JARVIS-owned persistent automation profile and managed browser process,
preferably a headless renderer for unattended work. JARVIS controls its lifecycle
and automation launch settings; personal Chrome can be launched, covered, moved
between desktops or closed independently. It removes reliance on remembering how
the personal browser was launched, rather than promising Chromium needs no flags.

Required trade-offs and gates:
- This changes the present shared-profile/visible-window architecture and requires
  explicit owner approval. It is not an automatic backend fallback.
- Separate sign-ins are required. Do not copy personal cookies, credentials or a
  live profile. Persistent storage is not a guarantee that site sessions survive
  restarts; Workday and other sites need acceptance testing.
- Some sites require visible/manual authentication or disallow headless use.
  Stop for CAPTCHA or access restrictions; no bypass. Supervised authentication
  and any visible-browser mode transitions require an explicit design.
- Keep public browser_* schemas, serialized dispatch, per-session ownership,
  unknown-outcome fences and independent journal proof. Do not make headless mode
  a path around unresolved operations in the current bridge.
- Migrate only after a clean journal and completion/preservation of existing work.
  No live form/draft migration or automatic replay is assumed.
- Validate actual target-site read-only stability first, then separately approved
  actions. Test idle rendering, multiple sessions, restart/session expiry and
  negative recovery cases before calling it a production replacement.

## Recommendation

If keeping personal Chrome's live logins is non-negotiable, choose A with honest
startup coverage and explicit fail-closed detection. If eliminating the dependency
on the personal desktop is the priority, choose B and accept separate authentication.
Do not weaken element stability, replace normal clicks with force/DOM clicks, add
indefinite waits, continuously capture pages, or silently adopt another controller.
