# JARVIS native Apple app — unified documentation

**Last updated:** 2026-08-23 EDT

**Applies to:** Xcode 26, iOS 26, watchOS 26, XcodeGen 2.46, Personal Team/free provisioning

**App root:** `/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app`

**Current release:** `0.3.0 (40)`

**Current signed deployment candidate:** `0.3.0 (41)`

**Physical installation:** iPhone `0.3.0 (40)` and Apple Watch `0.3.0 (40)` on Dylan's allowlisted devices, installed from the exact audited artifacts

**Implemented feature record:** [Siri conversational prompt-to-Pi](siri-conversational-pi-terminal-plan-2026-08-23.md)

This is the single architecture, security, packaging, deployment, validation,
and recovery reference for the JARVIS iPhone app, Apple Watch app, widgets, and
`jarvisd`. It replaces the earlier research, milestone, service-integration,
Watch-companion, widget, and post-deployment documents.

Do not commit secrets, device identifiers, signing identities, certificates,
provisioning profiles, device logs, screenshots, archives, exported IPAs,
DerivedData, or other build products. Keep device selectors in private
environment variables. Never unpair or erase the Watch during recovery, and
never deploy to a device outside Dylan's allowlist.

---

## 1. Current checkpoint

### Completed

- `jarvisd` remains the sole hardware/status/service API control plane on TCP
  `8790`; build 24 adds a separate iPhone-only SSH terminal data plane.
- The deprecated Node/PWA dashboard, LaunchAgent, APIs, PWA, and TCP `8787`
  listener are fully removed.
- Weather and Open-Meteo are removed from the daemon and native contract.
- iPhone navigation is Home, JARVIS, and Settings. Build 18's Events removal and
  backend audit retention remain unchanged.
- Home order is Pi sessions, plugs, air purifier, then services/scheduled jobs
  and protected `jarvisd` information.
- Discord bot, room audio, scheduler, and sanitized scheduled-job telemetry are
  integrated. Bot and scheduler cards are read-only; room-audio actions remain
  server-allowlisted.
- Desired-state plug commands, authoritative cache revisions, stale-state UI,
  per-resource busy locks, and duplicate-write protection are implemented.
- The corrected Xcode 26 Watch companion hierarchy, `Watch/` embedding, signing,
  parent registration, developer installation, icons, and installed flags pass.
- Physical iPhone and Watch widget galleries expose the final four widget types.
- Physical plug-control tests restored their initial states and produced one
  command/event pair per intentional desired-state change.
- Build-33 cellular/Tailscale cold launch and relaunch pass without a hardware
  or terminal command. Discovery prefers LAN, stable MagicDNS, then the current
  Tailscale address and replaces obsolete saved endpoint hints.
- Build 14 embeds the canonical JARVIS artwork in the Watch widget and uses it
  for circular, corner, and rectangular Open JARVIS presentations. Inline keeps
  a system glyph.
- Build 15 applies one Apple-native holographic visual system across both host
  apps. Watch uses three vertical pages: branded overview, all-four 2×2 plug
  deck, and read-only system/air-quality status. iPhone adds a system-pulse
  header, device-specific plug cards, air-quality gauge, collapsed runtime/job
  sections, event cards, and branded Settings hero. Command and backend
  contracts are unchanged.
- Build 17 makes the circular Open JARVIS complication rendering-mode aware and
  the physical three-slot Smart Stack Combination widget now displays the
  JARVIS logo.
- Build 18 simplifies the iPhone shell to Home and Settings. `EventsView`, its
  tab/deep-link route, UI state, and five-second event polling are removed.
- Build 19 gives both host apps one shared immediate-then-15-second foreground
  refresh policy and removes normal refresh buttons from the visible UI.
- Build 20 adds exactly two dynamic, plug-only Siri shortcuts to both hosts.
- Build 22 corrects Watch Siri phrase routing and upgrade-time parameter
  publication after the first physical build-20 invocation fell through to
  Contacts without issuing a JARVIS command.
- Build 23 adopts Dylan's requested “Hey JARVIS” command form and removes all
  “with JARVIS”, “Use JARVIS”, and “Tell JARVIS” advertised alternatives.
- Build 24 adds the iPhone-only SSH-backed Pi terminal with persistent tmux
  reattachment while leaving Watch, widgets, and hardware APIs unchanged.
- Build 25 replaces the first-run inline tmux command with a checked-in detached
  create-then-attach bootstrap. It handles `/quit`, simultaneous reconnects,
  and macOS SSH's minimal PATH so Homebrew Node can launch Pi reliably.
- Build 26 starts Pi without covering the tabs, pins an always-visible keyboard
  toggle, adds tap-to-open and down-swipe dismissal, and keeps key-deck
  shortcuts from reopening the keyboard.
- Build 27 removes Pi's explicit `JARVIS iPhone` display-name override. The
  hidden tmux session remains persistent, but every new process launches as
  plain `pi`.
- Build 28 fixes upgraded installations whose persisted legacy zoom masked the
  larger fresh default. It migrates that value once to 18 points, records the
  zoom schema, and preserves every later pinch change.
- Build 29 disables touch text-selection gestures and maps vertical drags to SGR
  wheel events so Pi's fullscreen, application-owned transcript scrolls under
  the finger. The dedicated Control-C key becomes `/`; latched Ctrl and hardware
  keyboards still provide Ctrl-C.
- Build 30 removes every key-deck action after Down while retaining the fixed
  keyboard toggle. It raises the default-zoom wheel threshold from 18 to 45
  points, reducing touch-scroll speed by 60% for finer movement.
- Build 31 retains that speed while pacing queued wheel steps one per 60 Hz
  display frame, eliminating multi-step redraw bursts and cancelling pending
  input on disconnect or mouse-mode exit. It relabels the terminal tab JARVIS.
- After build-31's final simulator-backed validation, all local iPhone/Watch
  simulator devices, both iOS/watchOS runtimes, derived simulator products, and
  CoreSimulator caches were removed. Approximately 30.4 GB was returned to the
  filesystem. Build-32 validation temporarily restored the two runtimes and now
  keeps only an iPhone 11 and paired Apple Watch Series 11 (46mm) simulator.
- Build 32 adds the Watch JARVIS terminal without putting SSH, SwiftTerm, or NIO
  in the Watch product. A separate `jarvis-terminald` HTTPS listener on `8792`
  captures the existing `jarvis-ios` tmux pane and accepts bounded, deduplicated
  byte input. The Watch pins its certificate, requires a private bearer token,
  stores that token in target-local Keychain, and receives provisioning from the
  iPhone through WatchConnectivity. Wrist-down/background cancellation leaves
  tmux and Pi running.
- Build 33 makes Terminal the first face directly, removes the old launcher,
  and retains Plugs and System as pages two and three for exactly three pages.
  It also restores stale-endpoint recovery through stable MagicDNS after the
  Mac's Tailscale address changed.
- Candidate build 34 derives LAN, MagicDNS, and current Tailscale terminal
  bridge candidates from every existing provisioned endpoint. A successful
  frame pins the active route; terminal input remains immediate-only and is
  never retried or replayed across routes. The Watch renderer dynamically fits
  the tmux column count and clips every source row to one display row. The
  iPhone terminal uses a local zero-width marked sentinel so iOS keeps software
  Backspace auto-repeat enabled without sending sentinel bytes over SSH.
- Build 37 retains build 36's mobile Pi launch with
  `--tui-mode fullscreen`, where Pi owns a fixed input editor and scrollable
  transcript. Every SGR wheel event moves one logical line; tmux copy-mode also
  has one-line fallback bindings instead of its five-line defaults. Wheel
  coordinates are fixed to Pi's input cursor, while SwiftTerm suppresses the
  remote hardware cursor so tmux redraw/copy positions cannot flash over the
  transcript. Pi's software cursor remains visible in the editor.
- Build 36 retains build 35's watchOS `._statusBarHidden()` custom
  three-state pager and now ignores the otherwise-unused bottom safe-area inset,
  allowing Terminal, Plugs, and System to use the whole display. The modifier is
  SDK-available on watchOS but underscored, so physical behavior remains an
  acceptance gate and must be rechecked after watchOS or Xcode updates; remove
  it before App Store submission unless Apple exposes a documented equivalent.
- Build 36 replaces the 4.8–6.8-point fit-to-grid Watch renderer. The
  default Read mode uses 11-point monospaced text, wraps plain terminal rows at
  whitespace where possible, preserves Unicode, and collapses full-width divider
  rows. Raw mode uses 9-point text and horizontal panning without changing the
  underlying tmux grid. The cursor row appears separately in a pinned 10.5-point
  input rail that follows long commands.
- Build 37 keeps the on-demand two-row terminal key palette but replaces the
  redundant Type/Speak/Keys dock with **Keys / Input / Send**. Input calls
  WatchKit's public `presentTextInputController` with no suggestions and plain
  input, exposing keyboard and dictation through one system surface. Completed
  text is inserted at the live Pi cursor with `appendReturn=false`; the pinned
  prompt rail provides review, and only the separate Send action emits the exact
  `0x0d` carriage-return byte. Offline input remains disabled and unqueued.
- Build 38 replaces the legacy WatchKit controller, which opened directly in
  dictation on the physical Watch, with watchOS `TextFieldLink`. Tapping Input
  now opens the system keyboard surface directly; its microphone option remains
  available. Completed keyboard or microphone text still stages with no Return,
  and only the dock's Send button submits the Pi editor.
- Build 39 replaces fixed cyan/plain-text Watch output with a direct ANSI grid
  mirror from `tmux capture-pane -e -N`. Pi's own foreground/background colors,
  bold, dim, italic, underline, inverse, and strike styling now carry through to
  thinking text, tool-call blocks, assistant output, dividers, and token/footer
  rows without any Pi-semantic reconstruction. FIT preserves the complete 48-
  column grid at Watch width; GRID retains the larger horizontally pannable
  presentation.
- Build 39 gives the Codex quota card and Watch panel a consistent electric-blue
  accent instead of switching to orange at the current quota level.
- Build 39 fixes Digital Crown scrolling by keeping Watch focus on the terminal
  and moving a local, read-only viewport through the latest 160 tmux history
  rows. It no longer injects SGR mouse bytes, so scrolling works independently
  of Pi mouse mode and can never become delayed terminal input. Simulator
  interaction verified live → 27 rows back → live movement.
- Build 40 adds a **JARVIS** header with a terminal glyph and live status dot to
  the Terminal face, matching the titled Plugs and System pages.
- Build 40 removes vertical touch-history scrolling: only the Digital Crown can
  change the terminal viewport. An upward terminal swipe remains page navigation
  to Plugs. Simulator evidence confirms a downward drag stays live while Crown
  movement reaches 21 rows of history.
- Build 40 replaces `TextFieldLink`, which could restore dictation on the physical
  Watch, with a native inline `TextField`. One Input tap now presents the QWERTY
  keyboard directly; the keyboard's microphone option remains available and Done
  still stages text with `appendReturn=false`. A small Backspace button at the
  right edge of the prompt rail emits exactly `0x7f` without submitting.
- Build 40 reverses the main iPhone and Watch air-quality rings so visual fullness
  represents cleanliness rather than pollution. PM2.5 `1` (or lower) is a full
  circle, the ring drains linearly to empty at `75`, and unavailable remains empty.
- Build 39 implements the host-only Siri prompt intent on iPhone and Watch. Bare
  “Hey JARVIS” asks for a required prompt, normalizes it to one logical line,
  preflights the shared authenticated/certificate-pinned terminal client, and
  makes one non-retried `appendReturn=true` POST. Existing plug shortcuts remain
  unchanged; widgets contain no prompt intent and `jarvisd` gains no route.
- Build 40 makes `appendReturn=true` one exact tmux buffer containing normalized
  prompt bytes followed by `0x0d`, instead of a paste followed by a separate
  `send-keys`. Disposable HTTPS/tmux testing confirms the prompt starts
  immediately, remains deduplicated by request ID, and is never retried.
- Build 41 removes the duplicate native Watch prompt rail because the ANSI Pi
  mirror already displays Pi's editor and cursor. The terminal gains the freed
  vertical space, **JARVIS** is geometrically centered, and FIT/GRID moves 14
  points inward from the curved right edge.
- Build 41 changes the terminal dock to **Keys / Input / “/” / DEL /
  Return-symbol**. Slash leaves the expandable palette. The fixed-size Return
  symbol emits only exact `0x0d`. The fixed-size Backspace emits exact `0x7f`
  through a non-retried immediate POST that does not set the normal loading
  indicator, so repeated taps remain enabled while earlier DEL responses are in
  flight. Other terminal actions wait for those confirmations to preserve order.
- Build 41 treats Watch scene `.inactive` as frontmost Always On instead of
  background. It preserves the selected route, current terminal frame, button
  state, and foreground refresh loops; a 15-second `TimelineView` provides the
  supported UI-redraw schedule, which watchOS may throttle to minute cadence.
  A wrist raise forces immediate status refresh and terminal long-poll restart.
  `WKSupportsAlwaysOnDisplay` is explicitly enabled. This avoids JARVIS
  deliberately disconnecting, but watchOS can still suspend live networking
  while dimmed, so continuous terminal streaming in Always On is not promised.
- Build 41 reduces the background Codex quota collector interval from five
  minutes to one minute. Every transition into the Watch System page also sends
  one authenticated `GET /api/v1/state?refresh=codexQuota`, then briefly polls
  ordinary state for completion. The collector remains the fixed read-only
  `quotas.py codex --json` command with no probe/save flag and remains
  non-critical to plug/purifier freshness.
- Build 42 raises dark Watch ANSI foregrounds to a tested minimum luminance while
  retaining hue relationships, keeps true black for inverse cells, raises dim
  opacity from `0.62` to `0.82`, and uses 8-point horizontal/bottom plus 6-point
  top terminal-face insets. Equal-size slash, DEL, and Return controls narrow to
  28×35 points so Keys and Input remain single-line inside the safer width.
- Build 42 applies one shared strict threshold: weekly Codex remaining below
  `30%` is red themed on iPhone and Watch; exactly `30%` remains electric blue.
  The red theme covers ring, percentage, progress/badge, phone glow, and Watch
  panel/border accents.
- Build 42 records and announces a one-shot terminal presentation request only
  after a confirmed `.sent` outcome. Physical iPhone testing found that its
  unconditional `openAppWhenRun` foregrounded JARVIS underneath Siri's result
  sheet, so the user still had to dismiss Siri before seeing Pi connect.
- Build 43 makes that handoff platform-specific. iPhone now keeps
  `openAppWhenRun=false` and, on iOS 18.2 or later, returns a success-only
  `OpenURLIntent` for `jarvis://terminal`; the URL selects the JARVIS tab. Watch
  retains the already-passing host foreground behavior and consumes the success
  marker to select Terminal. Failure paths return only their existing dialogs.
  Widgets still contain no prompt intent, and terminal input is still attempted
  exactly once.
- Build 37 replaces the Watch System page's connection-source panel with an
  aesthetic Codex quota card and adds a larger counterpart to iPhone Home after
  Pi activity. Build 37 originally scheduled the fixed read-only
  `quotas.py codex --json` command every five minutes; build 41 lowers that to
  one minute and retains no probe or save flag. It publishes only plan,
  weekly/five-hour percentages and reset data, allowance,
  limit state, and credit balance. Model catalog, account data, credentials, and
  raw provider errors never enter the native state contract. A failed quota
  refresh preserves the last good value and cannot make plugs, purifier, or the
  global JARVIS state stale.

### Signed build 43 physical-test candidate

```text
Archive: /tmp/JARVIS-build43-siri-success-handoff.xcarchive
IPA:     /tmp/JARVIS-build43-siri-success-handoff-export/JARVIS.ipa
SHA-256: ad2abf0b7d9a36b466d3e2dabf8bd309706c043972b8736f6add292042457632
```

All four Personal-Team-signed products report `0.3.0 (43)`. Deep and individual
signatures, required Watch hierarchy, iPhone `openAppWhenRun=false`, Watch
`openAppWhenRun=true`, widget prompt exclusion, allowlisted provisioning,
explicit Always On metadata, and Watch dependency isolation pass. Validation
passes 26 `jarvisd`, nine terminal-daemon, 43 JARVISKit tests with three expected
live skips, 19 iPhone tests, repository smoke `PASS=104 WARN=0 FAIL=0`, and
warning-free signed archive/export logs. The iPhone simulator confirms that
`jarvis://terminal` selects the JARVIS tab in
`/tmp/JARVIS-build43-iphone-terminal-openurl.png`. The system-level Siri sheet
handoff remains a physical acceptance gate. Build 43 has not been installed.

### Installed build 42

```text
Archive: /tmp/JARVIS-build42-bright-safe-red-siri.xcarchive
IPA:     /tmp/JARVIS-build42-bright-safe-red-siri-export/JARVIS.ipa
SHA-256: d0724f25933242236f44efb15d659826d9e6fd9e70e3f153fbaa642172a9e771
```

All four Personal-Team-signed products report `0.3.0 (42)`. The exact IPA was
upgraded with explicit `ideviceinstaller -w upgrade`; the exact archived Watch
product installed directly through CoreDevice. Both inventories reported build
42, both host apps launched, and the Watch app/widget pair ran. Physical review
passed brighter terminal text, rounded-edge safety, one-line controls, and the
live 11% critical quota theme. Siri delivered the phone prompt exactly once,
but JARVIS remained beneath the Siri result sheet until manual dismissal; build
43 supersedes that handoff.

Simulator evidence retained from build 42:

- `/tmp/JARVIS-build42-watch-bright-safe-terminal-fit.png` — brighter ANSI text,
  single-line Keys/Input, and the full header/dock inset from rounded edges.
- `/tmp/JARVIS-build42-watch-codex-critical-red.png` — 29% Watch quota panel in
  the red critical theme.
- `/tmp/JARVIS-build42-iphone-codex-critical-red-top.png` — matching 29% iPhone
  quota card theme.

### Superseded installed build 41

```text
Archive: /tmp/JARVIS-build41-watch-dock-always-on-codex.xcarchive
IPA:     /tmp/JARVIS-build41-watch-dock-always-on-codex-export/JARVIS.ipa
SHA-256: efd9be1c4c87d617b26bc7f90784a1d9e994377dc3b790c0db858a3c89fb8125
```

All four Personal-Team-signed products report `0.3.0 (41)`. Deep signatures,
required Watch hierarchy, exact host-only Siri metadata, widget exclusion,
bundle relationships, explicit Always On metadata, and Watch dependency
isolation pass. Validation passed 26 `jarvisd`, nine terminal-daemon, 41
JARVISKit tests with three expected live skips, 17 iPhone tests, repository smoke
`PASS=105 WARN=0 FAIL=0`, and warning-free signed archive/export logs.

Simulator and disposable-bridge evidence:

- `/tmp/JARVIS-build41-watch-final-compact-keys.png` — centered **JARVIS**,
  readable inset GRID, no duplicate prompt rail, and equal-size `/`, DEL, and
  Return-symbol buttons.
- `/tmp/JARVIS-build41-watch-key-palette-no-slash.png` — the expandable palette
  now contains only Esc, Ctrl, Tab, Up, and Down.
- `/tmp/JARVIS-build41-watch-final-rapid-backspace.png` — five Backspaces are
  simultaneously in flight without a loading indicator; the delayed fixture
  received five exact `7f false` requests in under one second.
- `/tmp/JARVIS-build41-watch-system-codex-refresh.png` — the System page renders
  quota and generated exactly one forced refresh request per page entry; leaving
  and returning generated a second request.
- Simulator lock/wake retained the last interface and generated an immediate
  ordinary state request within four seconds of wake.

`jarvisd` was restarted from PID `71713` to `77314` to activate the one-minute
and on-view read-only quota paths; a live forced refresh returned an available,
completed sanitized quota snapshot. `jarvis-terminald` remains PID `45590`.
The production tmux pane remains `%0`, PID `66665`, session `$0`, command `node`;
it was not restarted and received no test input. Physical compact-dock,
rapid-Backspace, Always On, wrist-raise, and quota-refresh acceptance remain
owner-operated. The exact build-41 IPA was upgraded with explicit `ideviceinstaller -w upgrade`;
the exact archived Watch product installed through CoreDevice after one
non-destructive retry for a transient tunnel timeout. CoreDevice inventories
reported build 41, both host/widget process pairs ran, the Watch established its
terminal and state connections, and per-view quota refresh requests arrived.
Owner review found the ANSI text too dark and the edge controls too close to the
rounded display; build 42 is the correction.

### Installed build 40

```text
Archive: /tmp/JARVIS-build40-crown-keyboard-backspace-siri.xcarchive
IPA:     /tmp/JARVIS-build40-crown-keyboard-backspace-siri-export/JARVIS.ipa
SHA-256: d46801ac0e417da247af4295cdeaf57770bef45243612e20fa95540160f83697
```

All four Personal-Team-signed products report `0.3.0 (40)`. Deep signatures,
required Watch hierarchy, exact host-only Siri metadata, widget exclusion,
keyboard-path Release strings, bundle relationships, and Watch dependency
isolation pass. Validation passes 25 `jarvisd`, nine terminal-daemon, 40
JARVISKit tests with three expected live skips, 17 iPhone tests, repository smoke
`PASS=105 WARN=0 FAIL=0`, and warning-free archive/export logs.

Simulator evidence:

- `/tmp/JARVIS-build40-watch-jarvis-title.png` — terminal glyph, **JARVIS**
  title, live status dot, Backspace, and the compact Keys/Input/Send dock.
- `/tmp/JARVIS-build40-watch-clean-keyboard.png` — one Input tap opens the
  native QWERTY keyboard rather than dictation.
- `/tmp/JARVIS-build40-watch-touch-does-not-scroll.png` — a vertical terminal
  drag remains on the live viewport.
- `/tmp/JARVIS-build40-watch-crown-only-scroll.png` — the Crown alone moves 21
  rows into bounded history.
- `/tmp/JARVIS-build40-watch-air-quality-full-at-1.png` — Watch System renders
  PM2.5 `1` as a full cleanliness ring.
- `/tmp/JARVIS-build40-iphone-air-quality-full-at-1.png` — iPhone Home uses the
  same full-at-1 ring semantics.

The nine terminal-daemon tests include both a one-buffer prompt/Return assertion
and a disposable HTTPS/tmux round trip that receives exactly one prompt plus one
newline. `jarvis-terminald` was restarted from PID `19659` to `45590` to activate
that atomic path. The production pane remains `%0`, PID `66665`, session `$0`,
command `node`; it was not restarted and received no test input. The exact IPA
was installed with explicit `ideviceinstaller -w upgrade`, and the exact archived
Watch product was installed through CoreDevice. The known process-scoped Watch
install-coordination conflict cleared with one non-destructive retry. Device
inventories report `0.3.0 (40)` on both allowlisted devices, and the iPhone
app/widget plus Watch app/widget processes were confirmed running. Physical
Crown, keyboard, Backspace, purifier-ring, rendering, Siri-routing, and
failure-path acceptance remain owner-operated.

### Superseded installed build 39

```text
Archive: /tmp/JARVIS-build39-ansi-mirror-crown-siri.xcarchive
IPA:     /tmp/JARVIS-build39-ansi-mirror-crown-siri-export/JARVIS.ipa
SHA-256: 355b2c524d3e9e285873dab919b9d89e999bf4178fb028d1a5782651e53a05b5
```

All four Personal-Team-signed products report `0.3.0 (39)`. Deep signatures,
required Watch hierarchy, host-only Siri metadata, widget exclusion, Release UI
strings, and Watch dependency isolation pass. Xcode accepts and trains exactly
three host shortcuts, including bare **“Hey JARVIS”** with one required prompt.
Validation passes 25 `jarvisd` tests, nine terminal-daemon tests including a
disposable HTTPS/tmux round trip, 39 JARVISKit tests with three expected live
skips, 17 iPhone tests, warning-free iOS/watchOS builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`.

Simulator evidence:

- `/tmp/JARVIS-build39-watch-ansi-mirror-fit2.png` — FIT mirror with Pi-styled
  green tool block, italic thinking, bullets, divider, inverse cursor, and footer.
- `/tmp/JARVIS-build39-watch-after-crown.png` — Crown-focused local viewport 27
  rows into bounded tmux history.
- `/tmp/JARVIS-build39-watch-crown-return-live.png` — reverse Crown movement
  returning toward the live Pi grid.

`jarvis-terminald` was restarted from PID `52929` to `19659` to activate the
additive ANSI/history frame fields. Its legacy `lines` field remains exactly one
live screen for build-38 compatibility. The persistent pane identity remained
`%0`, pane PID `66665`, session `$0`, command `node`; it was not restarted and
received no test input. The exact IPA was installed with an explicit
`ideviceinstaller -w upgrade`, and the exact archived Watch product was installed
through CoreDevice. Device inventories report `0.3.0 (39)` on both allowlisted
devices, and the iPhone app/widget plus Watch app/widget processes were confirmed
running. Physical Crown, rendering, Siri routing, and failure-path acceptance
remain owner-operated.

### Superseded build 38

```text
Archive: /tmp/JARVIS-build38-keyboard-first-watch-input.xcarchive
IPA:     /tmp/JARVIS-build38-keyboard-first-watch-input-export/JARVIS.ipa
SHA-256: c38d6e7bbc53a2708230a4107e0d25c946b76fb51d70e7e2740d9468c05d4350
```

All four signed products report `0.3.0 (38)`. Deep signatures, required Watch
hierarchy, Personal Team provisioning, Release keyboard-first UI, and Watch
dependency isolation pass. Validation passes 25 `jarvisd` tests, six terminal-
daemon tests, 32 JARVISKit tests with three expected live skips, 15 iPhone
tests, warning-free iOS/watchOS builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. Simulator interaction confirms one Input tap opens
the system keyboard directly. The exact IPA and archived Watch product were
installed and launched on the allowlisted devices on 2026-08-23 EDT; a transient
CoreDevice install-coordination conflict recovered with a non-destructive retry.
Physical owner confirmation of keyboard-first behavior remains open.

### Superseded installed build 37

```text
Archive: /tmp/JARVIS-build37-staged-input-codex-quota.xcarchive
IPA:     /tmp/JARVIS-build37-staged-input-codex-quota-export/JARVIS.ipa
SHA-256: 769d78d519303e6e11c312596f2fb8d26f4a66bb91713059e5aec3af79a19fa6
```

All four signed products report `0.3.0 (37)`. Deep archive/export signatures,
required `Watch/` hierarchy, Personal Team provisioning, Release input/quota UI,
and Watch dependency isolation pass. Validation passes 25 `jarvisd` tests, six
terminal-daemon tests, 32 JARVISKit tests with three expected live skips, 15
iPhone tests, warning-free iOS/watchOS builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. Simulator review covers the Keys/Input/Send terminal
dock, staged no-Return protocol bytes, iPhone Codex card, and polished Watch
Codex card without truncation. The exact IPA and archived Watch product were
installed and launched on the allowlisted devices on 2026-08-23 EDT. One
`jarvisd` restart activated the read-only quota collector and a live state check
confirmed fresh Codex telemetry; the persistent Pi/tmux pane was not restarted.

### Superseded installed build 36

```text
Archive: /tmp/JARVIS-build36-readable-watch-dictation.xcarchive
IPA:     /tmp/JARVIS-build36-readable-watch-dictation-export/JARVIS.ipa
SHA-256: 3430df1569a1befa3acc58f430a344235490e1c7ad4fbc49a4303889ff66b9d6
```

All four signed products report `0.3.0 (36)`. Deep archive/export signatures,
required `Watch/` hierarchy, Personal Team provisioning, and Watch dependency
isolation pass. The exact IPA and archived Watch product were installed on the
allowlisted physical devices on 2026-08-23 EDT. Physical review found that Type
and Speak open the same system text-input surface, motivating build 37's unified
Input action and separate terminal Return.

### Superseded build-35 deployment candidate

```text
Archive: /tmp/JARVIS-build35-terminal-scroll-watch-fullscreen.xcarchive
IPA:     /tmp/JARVIS-build35-terminal-scroll-watch-fullscreen-export/JARVIS.ipa
SHA-256: 6c8d733ae1e9dfa3049e19f72fd1c34809be65aadf326e3eef68d7160763711a
```

All four signed products report `0.3.0 (35)`, the required `Watch/` hierarchy
and deep signatures pass, and the Watch products remain free of SwiftTerm/NIO/
SSH linkage. Build 35 was not installed and is superseded by build 36.

### Watch JARVIS terminal (build 32 onward)

```text
Archive: /tmp/JARVIS-build32-watch-terminal.xcarchive
IPA:     /tmp/JARVIS-build32-watch-terminal-export/JARVIS.ipa
SHA-256: 26037a06fdb67f751cbbcb7c10e0d3389dbe5e32e901cffc86d53ae4c521f477
```

The Watch dashboard opens directly on a full-screen, monospaced terminal face,
then vertically pages to Plugs and System. It does not open SSH: watchOS blocks
ordinary low-level TCP networking. Instead, foreground `URLSession` long
polling retrieves tmux frames over pinned HTTPS. Build 34 tries the saved bridge
first, then LAN, stable Tailscale MagicDNS, and the current Tailscale address;
after a frame succeeds it keeps that route active. Build 39 preserves tmux's
actual SGR cell attributes and a bounded 160-row history tail. Build 40 allows
only the focused Digital Crown to move the local read-only history viewport;
vertical touch no longer scrolls terminal output and cannot become terminal
input during a network loss. FIT mirrors all Pi columns at Watch width, while
GRID provides a 9-point
horizontally pannable mirror. Thinking, tool calls, assistant text, dividers,
and usage/footer rows retain Pi's own styling without semantic reconstruction.
Watch keyboard, Scribble, dictation, or Continuity Keyboard still produces
bounded text. Build 40 uses a native inline `TextField` to open the QWERTY
keyboard first and preserves build 37's completed-text staging at the current Pi
cursor with no Return. Build 41 removes the duplicate prompt rail because the Pi
mirror already displays its editor. The dock is now Keys, Input, fixed-size `/`,
fixed-size DEL, and fixed-size Return symbol. Slash emits one `0x2f`; Backspace
emits one immediate `0x7f` without a spinner and remains tappable while earlier
DEL confirmations are in flight; Return emits one `0x0d`. Esc, Ctrl, Tab, Up,
and Down remain in the on-demand palette. Build 42 brightens dark ANSI
foregrounds without changing true black, raises dim-cell opacity, and insets the
whole terminal face from the rounded display. The three byte controls remain
equal at 28×35 points so Keys and Input fit on one line.

`jarvis-terminald` is isolated from `jarvisd` and has no hardware, purifier,
service, scheduler, or command-control routes. It permits only configured
LAN/Tailscale CIDRs, uses a generated 256-bit token and self-signed certificate
stored under `~/Library/Application Support/JARVIS/terminald`, caps input at
4096 bytes, suppresses duplicate request IDs, avoids shell interpolation, and
never queues disconnected input. `scripts/jarvis-mobile-terminal.sh --ensure-only`
recreates Pi after `/quit` without attaching a second tmux client
or changing the iPhone's pane dimensions.

Install the bridge with `scripts/install-jarvis-terminald.sh`. Run
`scripts/jarvis-terminal-provisioning.sh`, privately paste its output into the
Apple Watch JARVIS section in iPhone Settings, and tap **Save and send to Apple
Watch**. Never commit, log, or post that setup code.

Build-39 automated validation passes 39 JARVISKit tests with three expected live
skips, nine terminal-daemon tests, 17 iPhone tests on the exact iPhone 11
simulator, warning-free iOS/watchOS builds, and a live Series 11 simulator HTTPS
check. Its disposable HTTPS server and isolated tmux socket receive one prompt
and one Return even when the request ID is submitted twice; no fixture reaches
the production pane. The
signed archive and exported IPA contain four synchronized build-32 products and
pass signature, hierarchy, entitlement, Release seed-removal, and Watch
dependency-isolation audits.

The exact build-32 parent IPA and archived Watch product are installed on the
two allowlisted physical devices. Physical terminal validation observed a
certificate-pinned, bearer-authenticated HTTPS frame stream for 15 consecutive
samples, with payload sizes matching the live 51×44 `jarvis-ios` frame. The
Watch and an attached iPhone simultaneously used the single `%0` pane and one
plain Pi process. Restarting `jarvis-terminald` preserved its credentials and
the tmux pane PID, and the Watch reconnected automatically for another 15 of 15
samples. Canceled long polls are now closed without traceback noise. No
production terminal input or hardware command was issued; owner acceptance of
physical typing/dictation, key-deck bytes, Crown/touch scrolling, `/quit`, and
wrist-down recovery remains open.

### Build-31 native Pi terminal

```text
Archive: /tmp/JARVIS-build31-smooth-scroll-jarvis-tab.xcarchive
IPA:     /tmp/JARVIS-build31-smooth-scroll-jarvis-tab-export/JARVIS.ipa
SHA-256: 9680cf6a22716d0795062cf9ea3077b18975167d00d90f87b22bcd001246b467
```

The iPhone shell now contains Home, JARVIS, and Settings. The JARVIS tab embeds SwiftTerm
`1.20.0` and Apple SwiftNIO SSH `0.15.0` in only the phone host target. It
connects to TCP 22 using the configured username/password, keeps the password
in target-local Keychain, presents the first SSH host-key fingerprint for trust,
and fails closed if that key later changes. A blank host inherits the host from
the current LAN/Tailscale `jarvisd` endpoint. The direct terminal path is
separate from `jarvisd`; normal hardware/status/service traffic still uses only
the daemon.

After PTY allocation, the client executes
`scripts/jarvis-mobile-terminal.sh`. The bootstrap exports a deterministic
Homebrew-aware PATH, checks for the exact `jarvis-ios` session on the isolated
`jarvis-mobile` socket, creates it detached when absent, handles concurrent
creation races, launches `pi --tui-mode fullscreen` without assigning a special
Pi display name, and then attaches the phone PTY. The presentation override is
mobile-session-local and does not change Pi's global setting. This order lets the phone recreate Pi
after `/quit` instead of losing the session between creation and attachment.
The checked-in tmux profile enables true colour, CSI-u extended
keys, mouse/focus events, one-line copy-mode wheel fallback, a large history,
latest-client sizing, and no status bar. The bootstrap re-sources that profile
on every attachment, including existing persistent sessions. Leaving JARVIS or backgrounding closes only SSH; tmux and Pi continue on
the Mac. Returning reconnects without replaying disconnected input. Home
polling stops while JARVIS is selected.

The authentic terminal occupies the tab above a compact key deck containing only
Escape, latched Ctrl, Tab, slash, Up, and Down. The fixed keyboard toggle remains
at the trailing edge. Ctrl-C and removed navigation shortcuts remain available
through the software or hardware keyboard. Build 28 migrates legacy saved zoom once to an
18-point starting size; subsequent pinch zoom remains persisted and clamped to
9–20 points. A fixed trailing control remains visible beside the scrolling keys and toggles
terminal focus/the software keyboard. Pi connects keyboard-free, tapping the
terminal opens input, a downward terminal swipe dismisses it, shortcut keys do
not reopen it, and leaving JARVIS resigns focus. Hardware keyboard input is passed
through by SwiftTerm. iPhone portrait and both landscape orientations are
enabled.

A disposable password-authenticated SSH fixture validates PTY transport,
24-bit ANSI rendering, initial host trust, reconnect after app termination, and
changed-host-key rejection in the iPhone 11 simulator. Build-26 simulator
interaction validates keyboard-free launch, the fixed toggle, software keyboard
open/hide/reopen, downward-swipe dismissal, shortcut behavior, portrait, and
landscape. Build-28 unit and build gates validate the one-time 18-point zoom
migration, later saved-zoom preservation, and rejection of any bootstrap
`--name` override. Build-29 tests additionally reject SwiftTerm's touch mouse-
drag recognizer, disable long/multi-tap selection, verify exact SGR wheel-up and
wheel-down sequences, and verify the slash key emits only `0x2f`. Build-30 gates
require the deck to end at Down and verify a 45-point wheel threshold at the
18-point default zoom. Build-31 gates verify 60 Hz display-linked delivery,
bounded pending steps, reversal cancellation, and the JARVIS tab label. A
disposable tmux PTY confirms those SGR wheel events
reach the Pi pane. Minimal-PATH host
tests reproduce the original SSH-only launch failure and confirm the corrected bootstrap leaves
Pi alive as `node`. Fresh creation, attach/detach persistence, existing-session
reattachment, and `/quit` recreation pass. Homebrew tmux `3.7c` is installed,
its profile parses, macOS Remote Login is listening on TCP 22, and no
hardware/service command was run.

Verification passes with 28 JARVISKit tests/3 live skips, 15 AppState tests,
warning-free iOS/watchOS simulator builds, target-isolation checks, and all
existing Siri/widget metadata gates. Repository smoke reports `PASS=105 WARN=0
FAIL=0`. The Release archive and IPA contain four synchronized `0.3.0 (31)`
products and pass deep signatures, Personal Team, hierarchy, entitlement, App
Intent, Release-only seed-removal, terminal isolation, and bootstrap audits.
The archive log has no compiler warnings or errors. Build 30 is physically
installed. Physical build-31 smooth-scroll and JARVIS-label review plus `/quit`
recreation, background/foreground, force-quit, and LAN/Tailscale validation
remain; Watch build 23 can remain installed because builds 24–31 change no
Watch behaviour.

### Build-23 “Hey JARVIS” Siri command form

```text
Archive: /tmp/JARVIS-build23-hey-jarvis.xcarchive
IPA:     /tmp/JARVIS-build23-hey-jarvis-export/JARVIS.ipa
SHA-256: 1803e84e78f223d694520360c2bd1aaf868d5aee47bf290cab53e4b7621ce6b2
```

The two plug intents now advertise only “Hey JARVIS, turn on/off [the] [plug]”
and parameterless “Hey JARVIS, turn on/off a plug” forms. A normal voice request
is therefore “Hey Siri, hey JARVIS, turn on the lamp”: the first “Hey Siri” wakes
the system assistant and the remaining phrase is the registered JARVIS command.
There is no “with JARVIS”, “Use JARVIS”, or “Tell JARVIS” fallback in compiled
host metadata. The optional article variants remain explicit because Watch Siri
uses fixed App Shortcut phrase matching. The phrase schema is version 4, forcing
both hosts to republish the unchanged dynamic plug catalogue after upgrading.

All four archived products report `0.2.0 (23)` and pass deep signature, required
bundle hierarchy, Personal Team, entitlement, synchronized-version, and exact
App Intent metadata audits. The archive's App Intents training step accepted all
six phrases. Verification passes with 28 JARVISKit tests/3 live skips, 11
AppState tests, iOS/watchOS simulator builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. The exact parent IPA and archived Watch product are
installed on the two allowlisted devices, and both inventories report build 23.
A physical iPhone console confirmed publication of all four dynamic plug values.
CoreDevice again could not foreground the Watch app because watchOS denied
navigation from the clock during an active system state, so Dylan must manually
open JARVIS on Watch before testing the new phrase. Deployment generated only
read-only state GETs and zero command, service, or event mutation POSTs. No Siri
phrase or physical plug command was exercised automatically.

### Build-22 Watch Siri phrase and registration recovery

```text
Archive: /tmp/JARVIS-build22-siri-phrases.xcarchive
IPA:     /tmp/JARVIS-build22-siri-phrases-export/JARVIS.ipa
SHA-256: 7b363b93fd5669cda01dbebe2cb423a1c0a5e640d5918cc4fc6d789aaa4875c4
```

The iPhone and Watch hosts still expose only Turn On JARVIS Plug and Turn Off
JARVIS Plug through `AppShortcutsProvider`. Siri on the physical Watch routed
“Tell JARVIS to turn on the lamp” as a request for a contact; no JARVIS intent or
hardware write ran. watchOS also lacks Siri's flexible phrase matching. Build 22
therefore removes contact-directed “Tell” phrases and publishes exact verb-first
variants: “Turn on/off [the] [plug] with JARVIS” and “Use JARVIS to turn on/off
[the] [plug].” Each action also has parameterless phrases such as “Turn on a plug
with JARVIS,” so it remains visible before dynamic values are published and can
ask which plug.

`JARVISPlugEntityQuery` builds its catalogue from
`state.subsystems.plugs.plugs`; no production plug identifier is compiled into
the Siri source. Normalization handles case, spaces, hyphens, and underscores.
Exact matches win and ambiguous results remain multiple for Siri disambiguation.
A target-local schema/catalogue signature now calls
`updateAppShortcutParameters()` after the first fresh state following an install
or phrase-schema upgrade even when the pre-upgrade cached plug IDs are unchanged;
it also republishes after add/remove/rename. The catalogue is seeded before the
notification, and a 15-second single-flight coordinator coalesces App Intents'
parameter-query burst. Existing widget configuration choices remain separate.

Every intent obtains fresh state and validates the exact daemon identifier before
writing. Already-satisfied requests return without a POST. Other writes use only
`plug-on` or `plug-off`, and Siri reports success only after the command response
or a follow-up authoritative read confirms the desired state. Stale, unknown,
removed, rejected, and unconfirmed requests fail closed. The raw widget
`SetPlugIntent` is explicitly non-discoverable. Watch execution tries direct
`jarvisd` first and then a fresh, immediate-only, correlated iPhone relay. Siri
writes are never queued for execution after a spoken timeout.

All four archived products report `0.2.0 (22)`, pass deep signature, hierarchy,
entitlement, synchronized-version, and exact App Intent metadata audits.
Automated verification passes with 28 JARVISKit tests/3 live skips, 11 AppState
tests, warning-free iOS and watchOS simulator builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. The exact parent IPA and archived Watch product are
installed on the two allowlisted devices and both inventories report build 22.
A physical iPhone console confirmed publication of all four dynamic plug values.
CoreDevice could install but not foreground the Watch app because watchOS denied
navigation from the clock during an active system state; Dylan must open JARVIS
once on the Watch before direct parameterized phrase retesting. Deployment and
registration emitted zero mutation POSTs. The build-20 failed phrase changed no
plug, and no build-22 Siri phrase or hardware write was exercised automatically.

### Build-19 automatic host refresh

```text
Archive: /tmp/JARVIS-build19-refresh.xcarchive
IPA:     /tmp/JARVIS-build19-refresh-export/JARVIS.ipa
SHA-256: 18ce74f7a5143ecb3912068f9913087980bde87a8706415be64c68f44ad7003e
```

`JARVISRefreshPolicy` now defines one 15-second active cadence for iPhone and
Watch. Both refresh immediately on activation, continue only while visible, and
cancel polling when inactive. iPhone Home refreshes state, services, scheduled
jobs, and health together; Settings performs no polling. Its toolbar button is
removed while pull-to-refresh remains an optional recovery gesture. Watch
refreshes direct-first with automatic iPhone-relay fallback, coalesces concurrent
refreshes, requests a fresh phone snapshot when relaying, and blocks plug writes
while offline. Its normal Refresh status controls are replaced by passive
freshness feedback and a failure-only Retry now action. WidgetKit timelines stay
at approximately 15 minutes.

All four archived products report `0.2.0 (19)`, use the configured Personal
Team, pass deep signature verification, and preserve the required Watch bundle
hierarchy. Verification passes with 21 JARVISKit tests/3 live skips, 8 AppState
tests, warning-free iOS/watchOS simulator builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. The verifier also makes its negative source-contract
checks fail explicitly rather than relying on shell negation under `set -e`.
The exact parent IPA and archived Watch product installed on the two allowlisted
devices; both inventories report build 19 and all four host/widget processes
were active after launch. A 40-second physical observation showed immediate and
approximately 15-second read-only health/state/service/job request cycles. It
emitted no hardware, service, purifier, job, or event mutation POST.

### Build-18 two-tab iPhone cleanup

```text
Archive: /tmp/JARVIS-build18-two-tab.xcarchive
IPA:     /tmp/JARVIS-build18-two-tab-export/JARVIS.ipa
SHA-256: 63f1bcca99ac6773def2739052fe14b51150f2e6d25104c440e2a81403eb6370
```

Build 18 removes only the native Events presentation and polling path. It
deletes `EventsView`, its tab and deep-link route, AppState event UI/cache
fields, and the five-second selected-tab poller. At that checkpoint the verifier
locked the Home/Settings-only navigation contract; build 24 intentionally adds
Pi as the third tab. The bounded `jarvisd` event-ingest and
event-list APIs remain available for operational audit and compatibility;
hardware, service, widget, Watch relay, and command-safety contracts are
unchanged.

All four archived products report `0.2.0 (18)`, use the configured Personal
Team, pass deep signature verification, and preserve the required Watch bundle
hierarchy. Verification passes with 20 JARVISKit tests/3 live skips, 7 AppState
tests, warning-free iOS/watchOS simulator builds, and repository smoke
`PASS=105 WARN=0 FAIL=0`. The exact parent IPA was installed on the allowlisted
iPhone, whose inventory reports build 18; the phone host and widget extension
were active after launch. The Apple Watch intentionally remains on build 17.
Deployment and launch emitted no hardware, service, purifier, job, or event
mutation POST.

### Build-15 aesthetic candidate

```text
Archive: /tmp/JARVIS-build15-aesthetic.xcarchive
IPA:     /tmp/JARVIS-build15-aesthetic-export/JARVIS.ipa
SHA-256: 7247a43441d14f2ebbf7a1a133ef34b41b25217d27c723978b6f96b7d0be6f98
```

All four products report `0.2.0 (15)`. The archive passes deep signature,
bundle hierarchy, synchronized-version, embedded Watch, App Intent, host
`JARVISMark`, and widget `JARVISWidgetIcon` audits. The exported parent IPA and
exact archived Watch product installed successfully on the two allowlisted
physical devices; both inventories report build 15 and both host/extension
processes were observed active. JARVISKit ran 20 tests with
3 physical live tests skipped; AppState ran 7 tests with no failures; iOS and
watchOS simulator builds had no project warnings; repository smoke remains
`PASS=105 WARN=0 FAIL=0`. Light/dark iPhone Home, Events, and Settings plus all
three Watch pages were inspected in simulator. The iPhone accessibility-extra-
large layout remains scrollable without clipped core content; the watchOS 26.5
simulator does not support changing Dynamic Type, so physical Watch text sizing
remains a gate. Deployment and launch produced normal read-only health/state/
service/job requests and no command, service, job, purifier, or event POST.

Physical review then found that the circular Open JARVIS Watch widget reserved
its slot but rendered a blank image. Build 16 makes the resizable image consume
the full proposed accessory frame, resolves it explicitly from the extension
bundle, marks the asset for original rendering, retains watchOS full-colour
accented rendering, and asks WidgetKit to reload the static launcher timeline
whenever the Watch host launches.

### Build-16 Watch launcher correction

```text
Archive: /tmp/JARVIS-build16-watch-launcher-fix.xcarchive
IPA:     /tmp/JARVIS-build16-watch-launcher-fix-export/JARVIS.ipa
SHA-256: 16c05336347365327b64c8c88245e7090a7884e9e2ee8e13c579d9edf8b55f01
```

All four products report `0.2.0 (16)`. Full verification passes with the same
20 JARVISKit tests/3 live skips, 7 AppState tests, warning-free simulator builds,
and `PASS=105 WARN=0 FAIL=0` smoke result. The compiled Watch extension contains
the `JARVISWidgetIcon` rendition without automatic template rendering. The exact
Watch product and parent IPA are installed on the allowlisted devices and both
inventories report build 16. The first parent update waited while the JARVIS
host/widget processes were active; after those processes were terminated
normally, the same explicit upgrade completed. No uninstall, pairing change,
hardware command, or mutation POST occurred. Physical review confirmed that
this remained blank specifically in the three-slot Smart Stack Combination
widget, whose circular complications can use non-full-colour rendering.

### Build-17 three-slot Smart Stack correction

```text
Archive: /tmp/JARVIS-build17-combo-fix.xcarchive
IPA:     /tmp/JARVIS-build17-combo-fix-export/JARVIS.ipa
SHA-256: 8d5c8697a34aff7ef2e91ec521a74d2487095a25c0874b66f8d84517d5f8a234
```

All four archived products report `0.2.0 (17)`, use the configured Personal
Team, and pass deep signature validation. The Watch launcher now branches on
`widgetRenderingMode`: full-colour presentation uses an original-rendering
100×100 Watch `2x` asset, while accented/vibrant presentation uses a separate
high-contrast 100×100 Watch `2x` JARVIS ring rendition marked accentable. The
circular family receives explicit geometry and the launcher kind advances to
`JARVISWatchLauncherWidget.v2` to invalidate the failed cached rendition.
Verification passes with 20 JARVISKit tests/3 live skips, warning-free iOS
and watchOS simulator builds, and repository smoke `PASS=105 WARN=0 FAIL=0`. The exact archived Watch product installed on the
allowlisted Watch, its inventory reports build 17, and both host and widget
extension processes were active. After the old slot was removed and Open JARVIS
was re-added, Dylan physically confirmed the logo appears in the three-slot
Smart Stack Combination widget. No hardware, service, purifier, job, or event
mutation occurred.

### Build-14 physical checkpoint

```text
Archive: /tmp/JARVIS-build14-watch-launcher-icon.xcarchive
IPA:     /tmp/JARVIS-build14-watch-launcher-icon-export/JARVIS.ipa
SHA-256: f9abf05c1b77868c61e841d4d0eca8e33697c4c0e67b372459d1d786d85fcf23
```

All four archived products report `0.2.0 (14)`, use the configured Personal
Team, pass deep signature validation, and include the compiled
`JARVISWidgetIcon` rendition. The exact archived Watch product is installed and
its widget-extension process has been observed active. An automated Watch launch
was once denied because watchOS temporarily prohibited navigation away from the
clock; this was not a signing or installation rejection.

Three build-14 parent-IPA transfers initially did not finish iPhone package
activation, leaving the iPhone on build 13 at that checkpoint; it later activated
build 14 after reconnection. Build 15 and build 16 subsequently installed on both
devices. Do not repeat blind build-14 installs. No plug, purifier, scheduled-job,
or managed-service mutation was emitted during these deployments.

### Remaining release gates

1. Install build 24 on Dylan's iPhone, enter the Mac login password, approve the
   displayed host fingerprint, and validate the live Pi TUI without issuing a
   hardware command.
2. Validate Pi persistence across Home/Pi tab changes, backgrounding, force
   termination, portrait/landscape, software/hardware keyboards, and a live
   LAN/Tailscale path change.
3. Inspect the redesigned physical iPhone Home and Settings screens and all
   three Watch pages in normal and large-text presentation.
4. Inspect the remaining Watch accessory families.
5. Force stale, unknown, and offline widget states and prove writes are blocked.
6. Complete the Watch-originated state request, correlated relay command result,
   timeout, duplicate-request, direct/relay failover, and offline-cache matrix.
7. Complete live Wi-Fi/cellular path switching and Local Network permission
   recovery for daemon traffic.
8. Complete physical VoiceOver, Dynamic Type, contrast, and remaining
   accessibility checks.
9. Run the remaining event audit and disposable-service UI smoke, then one final
   verification/deployment pass before release acceptance.

The purifier physical write gate remains intentionally incomplete after VeSync
cloud lag and timeouts. The purifier may remain off; do not retry a purifier
write without explicit authorization. The former 30-minute reliability
observation is waived and is not a release task.

---

## 2. Product scope and system boundary

JARVIS is a native SwiftUI control surface over the existing Operation JARVIS
adapters; it does not reimplement hardware protocols.

```text
iPhone app / iPhone widgets / Watch app / Watch widgets
                         │
                    JARVISKit
                         │
                  jarvisd :8790
          ┌──────────────┼────────────────┐
          │              │                │
     cached state     commands       services/events
          │              │                │
  Pi/network files   jarvis-cli     launchctl registry
                         │          jarvisd event store
                  plugctl / purifierctl

              iPhone Pi tab only
                         │
               SwiftTerm + SSH :22
                         │
                tmux jarvis-ios
                         │
                         Pi
```

### Included

- Pi-session, network, daemon, plug, purifier, service, scheduler, and scheduled-
  job status.
- Idempotent plug control and guarded purifier controls in the main app.
- Bounded backend event ingestion and audit storage; no native event-feed UI.
- Server-allowlisted room-audio lifecycle control.
- Read-only Discord-bot and scheduler status.
- Sanitized, dynamic, read-only scheduled-job inventory.
- Direct Watch operation on LAN, iPhone relay when direct access fails, and
  cached stale fallback.
- Open JARVIS, configurable JARVIS Plug, JARVIS Plug Grid, and read-only Air
  Purifier widgets on iPhone and Watch.
- Typed App Intents and `jarvis://home`, `jarvis://pi`, and
  `jarvis://settings` deep linking.
- iPhone-only authentic Pi TUI over SSH with persistent tmux reattachment.
- LAN and Tailscale access.

### Excluded

- The retired dashboard, room-display HUD, phone-voice PWA, camera/browser APIs,
  Pi/ADB tiles, and port `8787`.
- Weather and Open-Meteo.
- Cast, Spotify, camera, in-app voice/wake word, Raspberry Pi room control, and
  oMLX.
- APNs, Live Activities, and TestFlight while using free provisioning.
- Discord-bot/scheduler mutations and scheduled-job add/remove/edit/setup in the
  current read-only rollout.
- Service, scheduled-job, or purifier controls in widgets; purifier widgets are
  always read-only.

Cast, room audio, Discord voice, Pi telemetry, smart plugs, purifier tooling,
and other Operation JARVIS subsystems continue to exist outside the native app.
The historically named `~/.ssh/jarvis_dashboard_host` key is shared active
infrastructure and must not be deleted as dashboard cleanup.

### Event ownership

There is one user-action event sink:

```text
jarvis-cli action → POST /api/jarvis/events on jarvisd → bounded audit store/API
```

Read-only collectors set `JARVIS_EMIT_EVENTS=0`; idle status polling must not
create lifecycle events. Accepted user writes produce bounded start/complete or
failure events. Native Apple clients do not poll or display the event feed. No
surviving runtime attempts a second dashboard event post.

---

## 3. Project layout and ownership

```text
jarvis-app/
├── README.md
├── docs/README.md              # this unified document
├── project.yml                 # XcodeGen source of truth
├── JARVIS.xcodeproj            # generated; never hand-edit
├── scripts/
│   ├── verify-jarvis-app.sh
│   ├── redeploy-jarvis-app.sh
│   ├── redeploy-jarvis-watch.sh
│   └── patch-watch-embedding.sh
├── jarvisd/
│   ├── jarvisd.py
│   ├── services.json
│   ├── tests/
│   ├── resurrector.sh
│   └── launchd/
├── config/
│   └── jarvis-mobile.tmux.conf # isolated persistent Pi terminal profile
├── JARVISKit/                  # models, API client, discovery, cache, WCSession
├── JARVIS/                     # iOS host app; Terminal/ owns SwiftTerm + SSH
├── JARVISWidget/               # iOS WidgetKit extension
├── JARVISWatch/                # watchOS host app
├── JARVISWatchWidget/          # watchOS WidgetKit extension
└── SharedAppIntents/           # compiled into all host/extension targets
```

Regenerate the project through XcodeGen and retain the post-generation Watch
embedding patch:

```bash
cd /Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app
xcodegen generate
```

`project.yml` and generated `JARVIS.xcodeproj` must remain synchronized. Never
repair packaging by manually editing `project.pbxproj`.

---

## 4. `jarvisd` contract and security

`jarvisd` is a small stdlib Python HTTP daemon managed by
`com.operation-jarvis.jarvisd`; a separate resurrector LaunchAgent health-checks
it and may restart it. The daemon delegates commands to the canonical
`jarvis-cli` with fixed argv and no shell.

### API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Minimal liveness, version, and uptime. |
| `GET /api/v1/state` | Cached network, Pi, plug, purifier, service, freshness, and stale metadata. |
| `POST /api/v1/command` | Allowlisted typed action and parameters. |
| `GET /api/v1/events` | Bounded event history with `since`/`limit`. |
| `POST /api/jarvis/events` | Scoped event ingestion from canonical JARVIS actions. |
| `GET /api/v1/services` | Registered LaunchAgent status and server metadata. |
| `POST /api/v1/services/{name}` | Server-allowlisted start/stop/restart. |
| `GET /api/v1/scheduled-jobs` | Sanitized read-only cron-runner inventory. |

Unknown paths/methods and malformed, scalar, empty, or oversized request bodies
are rejected with bounded JSON errors. Client responses do not expose local
argv, paths, stdout/stderr, secrets, or private hardware identifiers.

### Authentication modes

- `JARVISD_AUTH_MODE=trusted-network` is the zero-tap default. Only source
  addresses in `JARVISD_TRUSTED_CIDRS` are accepted. Configure loopback, the
  current home LAN, and Tailscale ranges as appropriate.
- `JARVISD_AUTH_MODE=token` requires `JARVIS_API_TOKEN` on protected
  `/api/v1/*` endpoints. Starting token mode without a token is an error.
- `/health` remains minimally public.
- `JARVISD_EVENT_TOKEN` authorizes event ingestion only and can never authorize
  state, command, or service access.
- Browser-originated writes and wildcard CORS are not allowed.
- Secret comparisons use constant-time comparison. Never store tokens in Git.

Trusted-network mode trusts allowed network peers; it is not per-user
authorization. Token mode is available when stricter client authentication is
required, but free-team widget extensions cannot inherit the host app's
Keychain token.

### State coordinator

- Expensive subsystem reads run in background, not per HTTP request.
- At most one refresh per subsystem is active.
- Last-good state survives collector failures and is marked stale/error.
- Warm `/state` reads compose directly from cache.
- Successful plug/purifier command results advance authoritative cache
  revisions immediately; older in-flight reads cannot roll back the UI.
- Plug refreshes are fast; purifier refreshes are deliberately slower to avoid
  VeSync rate limits.
- Disconnects and timeouts are bounded and cleaned up.

### Events

- Retain at most 500 logical events.
- Compact persistence atomically and preserve monotonically increasing sequence
  IDs across restart.
- Ignore individual corrupt persisted lines without losing later valid events.
- Service actions and user commands are audited; collector reads are silent.

### Services and scheduled jobs

`jarvisd/services.json` is the server-side authority for labels, plist paths,
display names, sort order, criticality, and `allowedActions`. Service state
separates configured, loaded, running, and PID values. `jarvisd` and its
resurrector are never controllable through this registry.

Current Home runtime order:

1. JARVIS Discord Bot — read-only.
2. Room Audio Server — existing allowlisted lifecycle controls.
3. Scheduled Jobs Runner — read-only.
4. Dynamic scheduled-job inventory.
5. Protected `jarvisd` status card.

Scheduled jobs remain canonical `.pi/discord-cron/runner.py` records, not fake
LaunchAgents. `list-public` output is sanitized again at the daemon boundary.
The app may receive only bounded fields such as ID, name, description, schedule,
enabled state, next/last run, last status, and run count. Prompts, model names,
Discord identifiers, paths, environment values, command lines, database details,
and raw output must never reach the native response.

Any future bot, scheduler, or job mutation requires a separate warning, explicit
authorization, a fixed backend allowlist, confirmation UI, duplicate protection,
and an audit event. Do not stop the Discord bot while the controlling
conversation depends on it, and do not stop the scheduler across an understood
due boundary.

---

## 5. Native app behavior

### iPhone

- **Home:** Pi sessions → plugs → air purifier → services/jobs/`jarvisd`.
- **Settings:** discovery, endpoint override, connection state, and About.
- Health establishes connectivity before the slower state resource is loaded.
- Scene lifecycle owns connection and polling; backgrounding cancels frequent
  work, foregrounding reconnects, and network-path changes trigger rediscovery.
- State, services, scheduled jobs, and health refresh together immediately and
  every 15 seconds while Home is active. Settings performs no background
  resource polling. Pull-to-refresh remains available but is not required.
- Failure in one resource preserves the last successful values from others.
- Missing data renders Loading, Stale, Unavailable, or Unknown—not plausible
  zero/off/stopped values.
- Plug writes always use `plug-on` or `plug-off`, never `plug-toggle`.
- Purifier writes serialize and remain stale/read-only while verification is
  pending; they are never automatically retried.

### Watch

The Watch chooses paths in this order:

1. Direct `jarvisd` access on the home LAN.
2. A correlated `WCSession` relay through the iPhone when direct access fails.
3. Last cached state marked stale when neither path is available.

The versioned Watch message envelope contains `version`, `type`, `requestID`,
`sentAt`, and a typed payload. Message types cover endpoint context, state,
state request, desired-state plug command, command result, and command error.
The iPhone keeps a bounded in-flight/result cache keyed by request ID so a
repeated relay request executes once. The Watch remains pending until a result,
error, or timeout instead of inferring success from a later snapshot.

The iPhone sends the latest endpoint and state through application context.
The Watch refreshes immediately whenever it becomes active and every 15 seconds
while visible, using a single coalesced refresh task. It cancels that task when
inactive. Normal refresh buttons are absent; passive freshness is always shown
and Retry now appears only after an automatic failure. The Watch cannot join the
iPhone's Tailscale client directly, so away-from-home operation relies on the
iPhone relay. Inventory, installed flags, reachability, state delivery, and
command correlation are separate assertions.

### Siri and Shortcuts

The discoverable host surface is deliberately plug-only:

- Turn On JARVIS Plug.
- Turn Off JARVIS Plug.

The plug parameter is a dynamic `AppEntity` sourced from current daemon state,
not the widget's fixed configuration enum. Cached state may help resolve a
spoken name, but only fresh direct or relayed state may authorize a write. A
persisted target-local phrase-schema/catalogue signature ensures publication on
first fresh state after an install or phrase update as well as after identifiers
are added, removed, or renamed. The only fixed Watch phrases are “Hey JARVIS,
turn on/off [the] [plug]” and parameterless “a plug” forms that prompt for the
entity. “With JARVIS”, “Use JARVIS”, and contact-directed “Tell JARVIS” forms are
not advertised. Matching is normalized but not fuzzy; ambiguity is handed back
to Siri instead of guessing. The widget-only raw intent remains non-discoverable.
No purifier, service, scheduler, status, launcher, or general JARVIS shortcut is
published.

### Accessibility and presentation

- Use semantic colors plus text/icon state, never color alone.
- Controls expose roles, labels, hints, current state, and busy state to
  VoiceOver.
- Layouts adapt to accessibility Dynamic Type instead of clipping or preserving
  a forced multi-column layout.
- Dark mode, increased contrast, Reduce Motion, system margins, and minimum tap
  targets remain supported.

---

## 6. Widget catalogue and safety contract

Each platform publishes exactly four current widget kinds. The legacy JARVIS
Plugs and JARVIS First Plug kinds are removed.

### iPhone families

| Widget | Families | Behavior |
|---|---|---|
| Open JARVIS | system small; accessory circular, rectangular, inline | Static `jarvis://home` launcher. |
| JARVIS Plug | system small; accessory circular, rectangular, inline | Configurable approved plug with explicit ON/OFF/STALE state. |
| JARVIS Plug Grid | system medium and large | Separate desired-state controls; medium shows up to four and large up to eight. |
| Air Purifier | system small/medium; accessory circular, rectangular, inline | Read-only PM2.5, quality, power, mode, fan, filter, and stale status as space permits. |

### Watch families

| Widget | Families | Behavior |
|---|---|---|
| Open JARVIS | accessory circular, corner, rectangular, inline | Opens the Watch app; full-colour canonical art except inline system fallback. |
| JARVIS Plug | accessory circular, corner, rectangular, inline | One configurable approved plug. |
| JARVIS Plug Grid | accessory rectangular | All four approved plugs in a compact 2×2 layout. |
| Air Purifier | accessory circular, corner, rectangular, inline | Read-only glanceable status. |

Approved plug choices are Family Room Light, Lamp, Pedalboard, and TV. The Watch
gallery publishes one default selected-plug recommendation; editing that widget
exposes all four choices.

### Data and interaction rules

- Launcher timelines use `.never`; state timelines request refresh about every
  15 minutes, subject to WidgetKit scheduling.
- State becomes stale after 15 minutes or when `jarvisd` marks it stale.
- Stale or unknown plug controls are disabled.
- Only concurrent timeline reads are coalesced. A completed pre-command result
  is never replayed after a write.
- A plug command shows Updating, disables the control, applies confirmed state
  to the extension-local cache, and selectively reloads plug timelines.
- Repeated requests for the same desired state are suppressed for ten seconds.
- Every plug action is explicit `plug-on`/`plug-off`; no widget uses inversion.
- Purifier widgets have no intent or button.
- Non-button areas deep-link to JARVIS Home.

Personal Team provisioning cannot provide App Groups or shared cross-target
Keychain access. Each extension therefore keeps target-local state and directly
discovers `jarvisd`. Widget token-mode credentials are not inherited, and Watch
widgets do not claim iPhone relay support.

The Watch Open JARVIS circular image is scaled to fit, padded by three points,
and clipped to the system circle. Corner and rectangular variants use bounded
circle-clipped artwork. watchOS 11+ requests full-colour accented rendering;
inline retains a legible system glyph because it has no reliable full-colour
image area.

Simulator static rendering, light/dark/increased-contrast previews, and launcher
deep linking are useful, but unsigned Xcode 26 simulator extensions can be
rejected by `linkd` for App Intent execution. Signed physical execution is the
authoritative intent/configuration gate.

Apple references:

- [Widgets — Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/widgets/)
- [Making a configurable widget](https://developer.apple.com/documentation/widgetkit/making-a-configurable-widget)
- [Accessory widgets and Watch complications](https://developer.apple.com/documentation/widgetkit/creating-accessory-widgets-and-watch-complications)

---

## 7. Companion identity, embedding, and signing

### Exact bundle hierarchy

| Product | Bundle identifier |
|---|---|
| iPhone app | `com.operation-jarvis.jarvis` |
| iPhone widget | `com.operation-jarvis.jarvis.widget` |
| Watch app | `com.operation-jarvis.jarvis.watchkitapp` |
| Watch widget | `com.operation-jarvis.jarvis.watchkitapp.widget` |

Do not restore the obsolete `.watch` suffix. All products derive
`CFBundleShortVersionString` and `CFBundleVersion` from shared
`MARKETING_VERSION` and `CURRENT_PROJECT_VERSION`; keep them synchronized.

The built Watch plist must contain:

```xml
<key>WKApplication</key><true/>
<key>WKCompanionAppBundleIdentifier</key>
<string>com.operation-jarvis.jarvis</string>
<key>WKRunsIndependentlyOfCompanionApp</key><false/>
```

`WKWatchOnly` must be absent.

### Canonical target relationship and bundle layout

The iPhone target embeds the Watch dependency on iOS:

```yaml
- target: JARVISWatch
  platforms: [iOS]
  platformFilter: iOS
  embed: true
```

Accepted archive layout:

```text
JARVIS.app/
├── PlugIns/JARVISWidget.appex
└── Watch/JARVISWatch.app
    └── PlugIns/JARVISWatchWidget.appex
```

The copy phase destination is `$(CONTENTS_FOLDER_PATH)/Watch` with
`dstSubfolderSpec = 16`. `scripts/patch-watch-embedding.sh` enforces this after
XcodeGen. `PlugIns/JARVISWatch.app` must not exist.

Important Watch target settings include:

```yaml
PRODUCT_BUNDLE_IDENTIFIER: com.operation-jarvis.jarvis.watchkitapp
PRODUCT_NAME: JARVISWatch
INFOPLIST_FILE: JARVISWatch/Info.plist
GENERATE_INFOPLIST_FILE: NO
ALWAYS_EMBED_SWIFT_STANDARD_LIBRARIES: YES
ASSETCATALOG_COMPILER_APPICON_NAME: WatchAppIcon
GENERATE_PKGINFO_FILE: YES
SDKROOT: watchos
SKIP_INSTALL: YES
TARGETED_DEVICE_FAMILY: "4"
WRAPPER_EXTENSION: app
WATCHOS_DEPLOYMENT_TARGET: "10.0"
```

Do not set `ALLOW_TARGET_PLATFORM_SPECIALIZATION=YES`; it breaks the combined
simulator dependency graph. The canonical artwork source is
`projects/operation-jarvis/jarvis-icon.png`. App icons must be square and opaque.

### Personal Team limitations

- Provisioning expires after roughly seven days and must be refreshed.
- No TestFlight or APNs.
- No App Groups or shared cross-target Keychain entitlements.
- Apple Watch/Bridge may list the app but cannot install a free-profile build
  from that consumer source.
- A passing signature does not prove parent registration, Watch installation,
  installed flags, or reachability.

---

## 8. Verification, archive, and export

### Comprehensive local verification

SwiftTerm's renderer requires Xcode's optional Metal compiler. Install it once
if `metal` is missing:

```bash
xcodebuild -downloadComponent MetalToolchain
```

Then run:

```bash
cd /Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app
JARVIS_RUN_IOS_TESTS=1 ./scripts/verify-jarvis-app.sh
```

The verifier regenerates the project, runs Python and Swift tests, checks Python,
plist, JSON asset, shell, URL-scheme, icon, widget-kind, App Intent, embedding,
and compiled Watch asset contracts, then builds iOS and watchOS simulators.
Live package tests are opt-in:

```bash
JARVIS_LIVE_TESTS=1 \
JARVISD_TEST_URL=http://127.0.0.1:8790 \
JARVIS_RUN_IOS_TESTS=1 \
./scripts/verify-jarvis-app.sh
```

Before release also run from the repository root:

```bash
./.pi/smoke-test.sh
git diff --check
git status --short
```

Audit the diff for secrets, identifiers, profiles, logs, screenshots, and build
products.

### Signed archive

Use private environment variables such as `TEAM_ID`, `ARCHIVE`,
`DERIVED_DATA`, `EXPORT_PATH`, and `EXPORT_OPTIONS`:

```bash
rm -rf "$ARCHIVE" "$DERIVED_DATA"

xcodebuild \
  -skipPackagePluginValidation \
  -project JARVIS.xcodeproj \
  -scheme JARVIS \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" \
  -derivedDataPath "$DERIVED_DATA" \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  archive
```

Use an uncommitted export-options plist:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>debugging</string>
  <key>destination</key><string>export</string>
  <key>signingStyle</key><string>automatic</string>
  <key>teamID</key><string>YOUR_TEAM_ID</string>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict></plist>
```

```bash
rm -rf "$EXPORT_PATH"
xcodebuild \
  -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -allowProvisioningUpdates
```

### Archive audit

```bash
APP="$ARCHIVE/Products/Applications/JARVIS.app"
WATCH="$APP/Watch/JARVISWatch.app"
PHONE_WIDGET="$APP/PlugIns/JARVISWidget.appex"
WATCH_WIDGET="$WATCH/PlugIns/JARVISWatchWidget.appex"
IPA="$EXPORT_PATH/JARVIS.ipa"

codesign --verify --deep --strict --verbose=4 "$APP"
codesign -d --entitlements :- "$APP" 2>/dev/null
codesign -d --entitlements :- "$PHONE_WIDGET" 2>/dev/null
codesign -d --entitlements :- "$WATCH" 2>/dev/null
codesign -d --entitlements :- "$WATCH_WIDGET" 2>/dev/null
unzip -l "$IPA" | grep 'Payload/JARVIS.app/Watch/JARVISWatch.app/Info.plist'

/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :WKCompanionAppBundleIdentifier' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :WKRunsIndependentlyOfCompanionApp' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIconName' "$WATCH/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$WATCH_WIDGET/Info.plist"
```

Expected Watch values are `.watchkitapp`, companion
`com.operation-jarvis.jarvis`, `false`, `WatchAppIcon`, and the nested
`.watchkitapp.widget` identifier. Confirm all four products use the intended
team, profiles are unexpired and include the required development devices, and
no App Group entitlement is present.

---

## 9. Canonical free-profile deployment

Use four distinct private selectors:

```bash
PHONE_COREDEVICE_ID=...
WATCH_COREDEVICE_ID=...
PHONE_UDID=...
WATCH_UDID=...
```

CoreDevice identifiers are used by `devicectl`; hardware UDIDs are used by
`ideviceinstaller` and `idevicesyslog`.

### Companion registration and installation

1. Verify, archive, export, and audit one exact product set.
2. Install or upgrade the parent IPA through the iPhone service so CoreDevice's
   skip-Watch flag is not requested:

   ```bash
   ideviceinstaller -u "$PHONE_UDID" install "$IPA"
   ```

3. For a clean install, trust the developer on the iPhone under **Settings →
   General → VPN & Device Management → Developer App**, then launch JARVIS once.
4. Do not use **My Watch → Available Apps → Install**. Free-profile installation
   from Bridge is expected to fail with `MIInstallerErrorDomain Code=111` /
   `ApplicationVerificationFailed`.
5. Install the exact Watch product from the same archive through developer
   services:

   ```bash
   xcrun devicectl device install app \
     --device "$WATCH_COREDEVICE_ID" \
     "$WATCH"
   ```

6. Confirm both inventories, both installed flags, then launch both apps and
   validate messaging.

A first inventory query may be empty while registries synchronize; wait and
retry before changing metadata or reinstalling.

### Iteration helpers

For iPhone-only iteration:

```bash
TEAM_ID=... ./scripts/redeploy-jarvis-app.sh --device "$PHONE_COREDEVICE_ID"
```

CoreDevice deliberately records `Setting skip watch app install flag` for this
route, so it does not prove parent companion transfer/registration.

For Watch-only developer iteration after parent registration:

```bash
TEAM_ID=... ./scripts/redeploy-jarvis-watch.sh --device "$WATCH_COREDEVICE_ID"
```

A direct Watch install by itself is not proof of a valid companion relationship.

---

## 10. Device diagnostics and non-destructive recovery

### Tunnel and inventory

```bash
xcrun devicectl list devices --timeout 30
xcrun devicectl device info details \
  --device "$WATCH_COREDEVICE_ID" --timeout 30
```

The Watch should be paired and booted, with Developer Mode enabled,
`ddiServicesAvailable: true`, and `tunnelState: connected`. A transient
`RemotePairingError 1001` often clears on serial retry; never unpair or erase the
Watch for it.

```bash
xcrun devicectl device info apps \
  --device "$PHONE_COREDEVICE_ID" --timeout 45 \
  | grep -E 'com\.operation-jarvis\.jarvis|JARVIS'

xcrun devicectl device info apps \
  --device "$WATCH_COREDEVICE_ID" --timeout 45 \
  | grep -E 'com\.operation-jarvis\.jarvis|JARVIS'
```

The Watch row must use `.watchkitapp` and the expected build number.

### Installation logs

```bash
idevicesyslog -u "$PHONE_UDID" > /tmp/jarvis-companion-install.log 2>&1
```

After the operation:

```bash
grep -Ei \
  'skip watch|operation-jarvis|watchkitapp|ACX|ApplicationVerificationFailed|MIInstallerErrorDomain|failed|error' \
  /tmp/jarvis-companion-install.log
```

Interpretation:

- `Setting skip watch app install flag` means the CoreDevice iPhone-only route.
- `enumerateLocallyAvailableApplications ... .watchkitapp` means parent
  registration found the embedded companion.
- `MIInstallerErrorDomain Code=111` from Bridge is the expected free-profile
  source restriction.
- `ProfileValidated=true` proves profile validation, but a clean iPhone install
  may still need explicit trust.

Never commit captured logs.

### WatchConnectivity consoles

```bash
xcrun devicectl device process launch \
  --device "$PHONE_COREDEVICE_ID" \
  --terminate-existing --console --timeout 60 \
  com.operation-jarvis.jarvis

xcrun devicectl device process launch \
  --device "$WATCH_COREDEVICE_ID" \
  --terminate-existing --console --timeout 60 \
  com.operation-jarvis.jarvis.watchkitapp
```

Relevant debug prefixes are `[JARVIS WatchBridge iPhone]`,
`[JARVIS WatchBridge Watch]`, and `[JARVIS Watch smoke]`.

### Guarded relay smoke

Force the Watch's direct endpoint to fail so it must relay through the iPhone:

```bash
xcrun devicectl device process launch \
  --device "$WATCH_COREDEVICE_ID" \
  --terminate-existing --console --timeout 100 \
  com.operation-jarvis.jarvis.watchkitapp -- \
  -jarvisSeedEndpoint http://127.0.0.1:9 \
  -jarvisForceEndpoint \
  -jarvisRelaySmokePlug lamp \
  -jarvisRelaySmokeState off
```

Before any physical write: warn the user, confirm canonical current state, send
that same desired state first, prove one correlated result/event pair, perform
at most one reversible change, and restore the original state. Never use
`plug-toggle`; do not test purifier writes during Watch recovery.

### Recovery order

Stop as soon as a gate passes:

1. Confirm the exact bundle hierarchy and synchronized versions.
2. Inspect the built Watch plist, not only source metadata.
3. Confirm complete opaque icon catalogs.
4. Confirm target dependency and `JARVIS.app/Watch/` embedding.
5. Deep-verify nested signatures and device coverage.
6. Run the verifier and signed generic-device/archive build.
7. Check pairing, unlock state, Developer Mode, DDI, and tunnel.
8. Use `ideviceinstaller` when parent registration is the goal.
9. Trust and launch the iPhone app if needed.
10. Install the exact archived Watch app through developer services.
11. Recheck inventories and both installed flags.
12. Launch both apps and validate reachability/state messaging.
13. Run an idempotent relay smoke before one reversible physical write.

Do not infer success from a build, icon, signature, direct Watch install,
`isReachable`, or Bridge listing alone. Remove only JARVIS if an explicitly
approved clean reinstall becomes necessary; never alter pairing records.

---

## 11. Physical validation and release procedure

### Already closed unless related code changes

- Cached-state latency and collector single-flight behavior.
- Daemon auth/input/event/service regression tests.
- Deterministic endpoint discovery priority, fallback, cancellation, and dedupe.
- Cold iPhone launch/relaunch and daemon-restart recovery.
- Cellular/Tailscale cold launch and relaunch.
- Xcode 26 Watch identities, icons, embedding, archive/export, and both installed
  flags.
- Paired-simulator bidirectional state delivery with a write-blocking backend.
- Automated duplicate Watch request-ID single execution.
- Disposable LaunchAgent unloaded → start → stop → start → restart/new PID →
  stop and cleanup.
- All four iPhone plug controls with initial-state restoration.
- Representative direct Watch lamp control with restoration.
- Signed iPhone widget launcher and one-command ON/OFF feedback round trip.
- Watch gallery, one editable selected-plug entry, all-four grid, launcher,
  read-only purifier, and four intentional non-duplicated lamp writes with final
  restoration.

### Remaining consolidated matrix

| Owner | Test | Pass condition |
|---|---|---|
| iPhone packaging | Activate existing build-14 IPA | Inventory reaches build 14 without data loss. |
| Watch launcher | Circular Smart Stack and remaining families | Artwork fits, stays full colour where supported, clips cleanly, and launches. |
| Watch app direct | One representative current-state command | Pending, correlated result, and refreshed state. |
| Watch app relay | Disable direct path and repeat guarded command | iPhone relay returns one result; duplicate request executes once. |
| Watch app offline | Remove direct and relay | Cached state is stale and writes fail/block honestly. |
| Widgets | Force stale/unknown/offline | Controls disable; purifier remains read-only. |
| iPhone networking | Wi-Fi/cellular switch and Local Network deny/re-enable | Automatic recovery and truthful path/error state. |
| Events | Inspect after targeted actions | User actions appear once; collector noise is absent. |
| Disposable service UI | One reversible approved smoke | Correct status, confirmation, action, and event. |
| Accessibility | Physical VoiceOver, large text, contrast, Reduce Motion | Core iPhone/Watch controls remain usable. |

Use underlying canonical CLI/hardware state as truth once per test. Do not
re-prove every surface after every action. Warn before any physical hardware
change, use desired-state actions, and restore the original state. Real bot,
scheduler, scheduled-job, or purifier mutations require separate explicit
permission.

### Final pass before `0.3.0`

1. Finish the remaining physical matrix.
2. Run `./.pi/smoke-test.sh` once.
3. Run `JARVIS_RUN_IOS_TESTS=1 ./scripts/verify-jarvis-app.sh` once.
4. Run the opt-in live JARVISKit suite once.
5. Verify `jarvis-cli --json help` and one safe read-only status path.
6. Run `git diff --check`, inspect repository status, and audit for forbidden
   artifacts or identities.
7. Build from fresh DerivedData and deploy one exact archive to both allowlisted
   devices.
8. Confirm versions and run a brief direct/relay smoke.
9. Bump/release `0.3.0` only after every required row passes.

All commits remain local unless Dylan separately requests a push.

---

## 12. Condensed implementation history

| Milestone/build | Result |
|---|---|
| M0 | Added `jarvisd`, launchd watchdog, JARVISKit, discovery, iOS/watch shells, and free-team deployment. Physical iPhone LAN auto-discovery passed. |
| M1 | Added Home plug/purifier/Pi controls. |
| M2 | Added Events and service lifecycle UI; later consolidated services into Home. |
| M2.1 | Added explicit auth modes, bounded HTTP/event storage, cached single-flight state, reversible services, lifecycle-aware polling, honest stale UI, deterministic deployment, tests, and real WCSession callbacks. |
| Build 8 | Corrected packaging/reliability baseline, companion registration, physical state delivery, and cellular/Tailscale validation. |
| Build 9 | Removed weather/Open-Meteo, reordered Home, removed System tab. |
| Build 10 | Added read-only Discord bot/scheduler and sanitized dynamic scheduled jobs. |
| Build 11 | Replaced legacy widgets with the four-type iPhone/Watch catalogue. |
| Build 12 | Removed completed-result replay, applied confirmed widget state, added Updating feedback and ten-second duplicate suppression. |
| Build 13 | Published one editable Watch plug recommendation and complete all-four 2×2 grid; physical widget tests passed. |
| Build 14 | Added canonical full-colour Watch launcher art and compiled-asset verification; Watch installed, iPhone remained build 13. |
| Build 15 | Unified both host apps under the holographic visual system; added the three-page Watch dashboard and refined iPhone Home, Events, and Settings; physical review exposed a blank circular launcher image. |
| Build 16 | Forces the Watch launcher asset to consume its accessory frame and render full-colour, reloads its static timeline on host launch, and is installed on both devices; the three-slot Combination widget remained blank. |
| Build 17 | Adds exact Watch-scale full-colour and accented launcher assets, rendering-mode selection, explicit circular geometry, and a fresh widget kind; the physical three-slot Smart Stack logo passed. |
| Build 18 | Removes the unused iPhone Events tab, view, deep-link route, UI state, and five-second polling while retaining bounded backend event audit APIs. |
| Build 19 | Gives both host apps a shared immediate-then-15-second foreground cadence, lifecycle cancellation, coalesced Watch refresh/relay fallback, passive freshness, and failure-only retry. |
| Build 20 | Adds exactly two dynamic plug-only Siri shortcuts, fresh-state validation, confirmed desired-state results, duplicate suppression, and immediate-only correlated Watch relay fallback. Its first physical Watch phrase fell through to Contacts without a command. |
| Build 21 | Intermediate deployment removes contact-directed phrases, adds parameterless fallbacks, and persists a schema/catalogue publication signature. |
| Build 22 | Adds exact optional-article phrase variants for Watch's fixed matching, revalidates metadata/signatures, and installs the corrected products on both devices; owner phrase retest remains pending. |
| Build 23 | Replaces every advertised phrase with “Hey JARVIS, turn on/off [the] [plug]” or its parameterless prompt, increments the publication schema, and installs the exact signed products on both devices; owner Watch invocation remains pending. |
| Build 24 | Adds the iPhone-only authentic Pi terminal using SwiftTerm, SwiftNIO SSH, Keychain login, first-use host trust, and persistent isolated tmux reattachment; archive and simulator transport tests pass, and physical iPhone validation is pending. |

Notable local commits include dashboard retirement (`590f937`), daemon hardening
(`4e47501`), Apple reliability/packaging (`042fdd4`), deployment operations
(`b36877f`), weather retirement (`713a176`), Home service telemetry (`3151ecd`),
widget replacement (`ed5fd1e`), widget feedback correction (`9cf3eb5`), Watch
catalogue correction (`e6ee1fb`), and Watch launcher artwork (`80ef493`).

Historical plans that suggested weather, a System tab, `plug-toggle`, App Group
cache sharing, a `.watch` bundle suffix, `PlugIns/JARVISWatch.app`, dashboard
coexistence, or Bridge installation are superseded by this document.

---

## 13. External references

- [WatchKit system text input](https://developer.apple.com/documentation/watchkit/wkinterfacecontroller/presenttextinputcontroller(withsuggestions:allowedinputmode:completion:))
- [watchOS low-level networking — TN3135](https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos)
- [Preventing insecure network connections](https://developer.apple.com/documentation/security/preventing-insecure-network-connections)
- [Local network privacy discussion](https://developer.apple.com/forums/thread/663858)
- [Apple Developer membership comparison](https://developer.apple.com/support/compare-memberships/)
- [WidgetKit complications — WWDC22](https://developer.apple.com/videos/play/wwdc2022/10050/)
- [WidgetKit widgets — WWDC22](https://developer.apple.com/videos/play/wwdc2022/10051/)
- [Tailscale](https://tailscale.com/)
