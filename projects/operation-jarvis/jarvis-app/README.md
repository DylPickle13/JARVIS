# jarvis-app

Native iOS + watchOS app for Operation JARVIS — phone and Apple Watch control
surface for the JARVIS stack on `mac-mini-64` (plugs, air purifier,
status/telemetry, service control), over LAN or Tailscale.

**Status:** Build `0.3.0 (132)` is the exact audited physical deployment on the
allowlisted iPhone and Watch. It adds private native iPhone Photos/Files staging,
bounded foreground stale-state convergence, and job-centric Discord-style output
channels with safe inline links. The owner accepted the deployed Jobs presentation
after exact-artifact installation. Checked-in `project.yml` intentionally remains
Build 127 and keeps `JARVIS_NATIVE_ATTACHMENTS` disabled by default; Build 132's
number and iPhone-only flag exist only in its owner-private audited artifact.

A three-conversation Apple terminal candidate is being verified only in the
isolated `feat/apple-multi-terminal-sessions` worktree. It fixes Slot 1 to
`jarvis-ios`, adds only `jarvis-ios-2` and `jarvis-ios-3`, remembers selection
independently on iPhone and Watch, routes Siri and iPhone attachments to the
invoking/active device slot, and retains v1/no-session host compatibility as
Slot 1. It has not been installed or activated against production; see the
[canonical implementation contract](docs/README.md#three-fixed-mobile-pi-conversations).

`jarvisd` retains explicit trusted-network/token auth,
bounded APIs, single-flight state caching, guarded controls, and bounded event
persistence. The app retains one scene-aware connection/polling coordinator,
idempotent desired-state writes, and honest stale/unavailable UI. Build 37 retains
build 36's fixed-editor fullscreen
Pi renderer, one-line wheel behavior, cursor correction, full-screen Watch
shell, 11-point readable transcript, 9-point pannable Raw grid, pinned input
rail, and on-demand six-key palette. Its dock is now **Keys / Input / Send**:
Input opens watchOS system keyboard/dictation and inserts reviewed text at Pi's
cursor without Return; only Send emits Return. Build 38 replaces the legacy
WatchKit input controller—which could default directly to dictation—with public
watchOS `TextFieldLink`, opening the keyboard surface first while retaining its
microphone option and the same no-Return staging semantics. Build 40 adds a
**JARVIS** terminal-face header matching the titled Plugs and System pages, then
replaces the resumable input link with an inline native `TextField`, so one Input tap
opens the QWERTY keyboard directly rather than restoring dictation. It also adds
a small `0x7f` Backspace button at the right edge of the live prompt rail.
Build 40 also reverses the shared iPhone/Watch purifier gauge: lower PM2.5 now
fills more of the ring, with a reading of 1 shown as completely full. Build 41
removes the duplicate Watch prompt rail because Pi already mirrors its editor,
centers **JARVIS**, and moves FIT/GRID inward from the curved right edge. The
compact dock is now **Keys / Input / “/” / DEL / Return-symbol**; `/` leaves the
expandable palette, Return remains exact `0x0d`, and rapid Backspace taps issue
independent exact `0x7f` attempts without a spinner or Backspace lockout.
Build 41 also keeps the frontmost Watch lifecycle alive through Always On's
inactive scene phase, uses a supported low-frequency `TimelineView`, preserves
the latest interface instead of declaring it offline, and forces immediate
status/terminal reconnection on wrist raise. watchOS may still throttle redraws
and suspend live networking while dimmed. Codex quota now refreshes read-only
every minute and receives one immediate authenticated refresh request whenever
the Watch System page comes into view. Build 42 lifts dark ANSI foregrounds for
the Watch OLED, raises dim text opacity, and moves the entire terminal face and
dock inward from the rounded display edges. Codex stays electric blue at 30% or
higher and changes to a red ring, progress, badge, glow/panel, and percentage on
both hosts below 30%. Build 43 corrects build 42's iPhone Siri handoff: the phone
host no longer foregrounds underneath Siri before delivery, and a confirmed
`.sent` result instead opens `jarvis://terminal` through `OpenURLIntent` so the
result sheet can hand off directly to the JARVIS tab. Watch retains its
physically passing foreground behavior and still switches pages only after
`.sent`; failure paths never request the terminal. Build 44 carries that Siri
correction forward and makes the iPhone Home and Settings roots fit the iPhone
11 viewport without required scrolling. Home uses a slim connection strip,
compact plug controls, one purifier card, direct Pi-session and full Codex cards,
and a two-row System summary whose service/job details remain one tap away.
Settings removes duplicated branding and presents daemon, Pi terminal, Watch,
diagnostics, and About summaries while retaining every field and action in
focused subpages. Build 51 stops rebuilding a healthy Watch terminal session on
every wrist raise or tap: the in-flight pinned long poll resumes in place, keeps
the green live state, and receives one bounded recovery restart only if it fails
to complete after wake. Background exit still cancels immediately, and watchOS
may still suspend arbitrary networking while the display is dimmed. Build 51
also removes the authored rectangular outline from the iPhone Neural Core widget.
Build 52 removes that authored outer frame from the Watch Neural Core as well,
leaving the internal procedural Cathedral geometry unchanged. Build 53 resets
only the iPhone's local SwiftTerm emulator before each fresh SSH PTY stream.
Physical acceptance showed a second startup race: the keyboard-hidden layout
could resize SwiftTerm while SSH was authenticating, and that authoritative
size was dropped before the child channel existed. The remote tmux pane then
painted its shorter initial grid into a taller local viewport until opening the
keyboard caused another resize. Build 54 retains every valid layout size and
publishes the newest one as soon as the authenticated SSH session channel is
ready, so the first keyboard-hidden frame and tmux agree without synthetic
input or a pane restart. Build 54 also adds an explicit Watch speaker button
that becomes available only after the current Pi turn settles. A PID-and-tmux-bound Pi extension publishes only the
latest final assistant text blocks; thinking, tool calls, tool results, and
intermediate tool-use messages never enter speech state. terminald sends that
private text only to the loopback room-audio Piper service and relays the WAV to
the Watch over its existing authenticated, certificate-pinned TLS route. Build
55 bounds the non-continuous Crown at position zero so returning to the live edge
cannot rebound to a synthetic `↑1` offset. Build 57 keeps an already-open iPhone
SSH client attached through foreground Siri overlays and explicitly redraws every
attached tmux client after confirmed out-of-band Watch/Siri input. Final-response
speech now converts readable table rows before lossless word-boundary chunking;
no long section is shortened to one TTS segment. Its downloaded local WAV may
finish through wrist-down or app switching using watchOS's supported audio
background mode, while terminal polling/networking still stops immediately in
the true background. Build 58 prepares and downloads that same complete WAV as
soon as a final response becomes available while the Terminal face is
foregrounded; playback remains explicit and begins only from the fully local
file. It replaces the tiny speaker plus top-right FIT/GRID controls with one
44-by-35-point dock-styled voice/Stop control and moves FIT/GRID into the spare
Keys-palette slot. Build 59 adopts watchOS's required long-form audio route
policy and asynchronous route activation so explicit local playback survives
wrist-down and app switching. Active playback is retained through Terminal-face
exit and response replacement until natural completion or explicit Stop; system
interruptions resume when watchOS authorizes it. True-background terminal
networking remains system-suspended, but the last confirmed frame and persistent
tmux session are retained, and every new foreground route requests an immediate
fresh frame rather than waiting on a stale long poll. Build 60 keeps that retained
session visually live across expected Watch view/background rebinding instead of
flashing orange, while a separate fail-closed confirmation flag disables all
terminal input until the recreated authenticated route returns its first frame.
Build 61 fixes the parent lifecycle handoff so every active-to-inactive wrist-down
transition reaches the terminal controller; expected Always-On long-poll
suspension therefore retains the last-confirmed frame instead of being
misclassified as an active-scene disconnect. Build 62 gives reduced-luminance
Always-On snapshots separate truthful semantics: a monochrome checkmark means
the persistent session/frame is retained while live transport resumes on wrist
raise, and a neutral dotted circle means no frame has ever been confirmed. AOD
never reuses orange/green transport colors that a stale snapshot can misstate.
Build 63 gives foreground speech preparation its own authenticated pinned client
and cancellation identity, so terminal long-poll recovery cannot directly cancel
that client. Active transport failures retain the last confirmed presentation
for a bounded 12-second handoff grace while input fails closed immediately.
Build 64 closes the remaining physical route-loss race at both boundaries:
terminald coalesces duplicate requests and atomically caches one complete WAV per
opaque response ID, while the Watch uses bounded retry, seeds polling and speech
clients with the last allowlisted authenticated route, and retains a verified
complete local WAV independently of terminal transport status. A cached response
can therefore be played while the terminal route is reconnecting; true background
still cancels unfinished networking, never queues terminal input, and never
claims unsupported continuous background transport. Builds 65–68 investigated an
unmasked iPhone Cathedral fallback while retaining the 60-frame/two-second cadence.
Physical logs proved that the extra tree first exceeded WidgetKit's 30 MB extension
limit; consolidating it with frame zero removed the memory kill but retained a
static selector state. Build 69 moved each phase to a lightweight Canvas and exposed
the next explicit rejection: the otherwise healthy serialized timeline was
12,016,600 bytes and exceeded the archive-size ceiling. Build 70 preserves all 60
phases, paths, particles, and filaments while sampling curves only as finely as the
173-point phone surface can resolve. It achieved zero memory kills, zero archive
rejections, and successful one-entry reloads, but its opaque Canvas background was
remapped into a solid white Clear-mode tint. Build 71's attempted replacement blend
required duplicate masks and again reached the 30 MB hard limit. At the owner's
request, build 72 removes the unmasked Cathedral fallback and all live frame
backgrounds: the live phone path is exactly 60 transparent, accentable Canvas phases
with one system-timer mask each and one shared wordmark. Its physical archive was
still rejected at 11,169,064 bytes because the newly masked frame zero consumed the
remaining size headroom. Build 73 retains that no-fallback structure and reduces
only subpixel phone curve sampling further; all 60 phases and all path, filament,
particle, ray, column, and ring counts remain unchanged. Build 74 restores the
shared wordmark's approved top-leading placement without adding another frame or
mask. Reduced Motion, stale
telemetry, luminance reduction, and unavailable-font contexts still use the normal
accessible static state rather than claiming unsupported motion. A real timeline
replacement receives a fresh identity, and launching the host requests a
WidgetKit-controlled reload; neither path runs a process timer or claims iOS must
animate continuously. Build 75 restores the Watch-only live rendering tree to the
previously accepted 32 complete masked Cathedral views, while retaining build 74's
phone-only lightweight 60-phase path. Build 76 keeps Pi in regular mode and makes
Watch output and its unwrapped cursor-following editor 12-point monospaced text,
removes FIT/GRID and horizontal panning, fixes Input's doubled system chrome, and
pages read-only Crown history across all rows retained by tmux. Physical review
found that typography too large; build 77 restores the original fitted font for
both output and editor while retaining every other build-76 change. Build 79
restores the pre-build-78 compact iPhone Home presentation, palette, navigation,
and system appearance behavior without changing build 77's Watch terminal work.
Build 81 replaced remote wheel delivery with SwiftTerm's native `UIScrollView`,
but physical testing exposed that tmux's outer DECSET 1049 envelope had placed
SwiftTerm in its intentionally history-free alternate buffer. Build 82 suppresses
only that client-local envelope before terminal parsing and retains up to 100,000
local rows. Physical testing then found that its second simultaneous keyboard-
dismissal pan and output-time `contentOffset` writes could still compete with the
native scroll view. Build 83 removed both, but physical testing still produced only
live-edge rubber-banding. Build 84 retains the same one-pan, zero-input behavior and
records content-free physical metrics—normal-buffer row count, terminal geometry,
scroll-view geometry, offset, gesture state, and received byte counts—to the app's
Caches directory. The physical trace received 266,930 bytes while the normal buffer
remained exactly one 42-row screen, proving terminal repaint operations were being
applied only in place. Build 85 recognizes fragmented full-screen `CSI Ps S` from tmux,
but its physical trace received 1.22 MB of visibly line-by-line output while detecting
zero `CSI Ps S` operations and retaining exactly 42 rows. Build 86's content-free
classifier then measured 13,023 line feeds, 12,972 line erases, and 13,714 absolute
cursor positions, while SwiftTerm still retained exactly 42 rows. This proves Pi's
synchronized updates let tmux keep real history while reducing the phone stream to
cursor-addressed redraws with no scroll operation. Build 87 opens one read-only SSH
metadata channel that samples only tmux `history_size`; it never captures pane text.
Each positive post-attach delta promotes the corresponding current SwiftTerm rows
before the pending redraw is applied. A 150 ms fail-open bound preserves live output
if metadata is unavailable. Terminal input, the persistent pane, tmux configuration,
and the single native scrolling surface remain unchanged. Rejected build 93 added a
separate read-only `/resume` transcript stream, but physical diagnostics proved that
Pi command-palette expansion bypassed its exact input trigger; the ordinary metadata
path consequently promoted 15,799 blank rows while no resume transaction armed.
Build 94 keyed the transaction to Pi's generated session-start reason/generation (or
the protected runtime's bounded recent-access proof), and physical testing confirmed
that saved `/resume` history became scrollable. The reconstructed transcript did not
match Pi's native presentation, however, so the owner rejected that visual result and
requested the earlier fixed-step interaction. Build 95 removes the native-history
promotion/replay channels and disables SwiftTerm momentum, bounce, and local pan.
Each vertical threshold now emits at most one immediate SGR wheel event to Pi's own
viewport, restoring exact Pi-rendered rows and discrete movement. Wheel input is never
queued, paced, retried, replayed, or retained across mouse-mode loss/disconnection; no
snapshot, pane capture, tmux copy mode, or tmux/session mutation is used. Build 102 keeps
the accepted Terminal → Plugs → System Watch order and makes the existing System-page
air-purifier card interactive. Power, Auto/Manual/Sleep/Pet mode, and manual fan levels
1–4 use a closed WatchConnectivity command schema, fail closed on stale state, suppress
duplicate desired-state writes, and report success only after the phone or Watch confirms
the requested purifier state. At that stage, the read-only purifier widget remained isolated.
The exact audited `0.3.0 (102)` archive was installed and launched on the allowlisted
iPhone and Apple Watch without issuing a purifier write. Physical testing confirmed a
Sleep → Auto change after VeSync's expected propagation delay. Build 103 exposes that
bounded verification state explicitly: iPhone shows **Switching to Auto… Waiting for
confirmation**, Watch shows **Switching to Auto…**, both retain progress feedback and
block duplicate writes, and the iPhone connection strip says **confirming purifier**
instead of mislabeling an accepted change as generic stale data. A true timeout or
unrelated stale subsystem still uses the existing fail-closed stale warning. The exact
audited `0.3.0 (103)` archive was installed and launched on the allowlisted iPhone and
Apple Watch after a status-only jarvisd restart; the purifier remained on in Auto mode.
Build 104 adds iPhone **Settings → Developer Signing** with an earliest-profile expiry
countdown and an explicit **Renew for 7 Days** confirmation. Its authenticated jarvisd
endpoint starts only the fixed argument-free renewal script; the Mac obtains and audits
all four Personal Team profiles, builds clean `main`, and upgrades only the private
allowlisted iPhone and Watch while exposing bounded progress back to the app.
Build 105 turns that status into a seven-step visual timeline: device checks,
four-profile creation, clean build, archive audit, iPhone installation, Watch
installation, and final verification/relaunch. Completed, active, pending, and
failed steps remain explicit after relaunch; all four embedded profiles show their
own validity, elapsed progress stays bounded, and jarvisd exposes only an allowlisted
failed-step identifier rather than logs, device identifiers, or local paths.
Build 106 reduces only the iPhone Neural Core selector from 60 to 48 complete
procedural scenes per two-second loop (30 FPS to 24 FPS), eliminating 12 scenes
and 24 system timer-mask views from each live widget composition. The canonical
artwork, telemetry, two-second choreography, full luminance, and Watch cadence
remain unchanged.
Build 107 streamlines iPhone Settings into four destinations: Connection, Pi
Terminal, Watch Terminal, and Developer Signing. Connection absorbs diagnostics
behind Technical Details, the app version moves to the root footer, redundant
About and Diagnostics destinations are removed, and terminal security/recovery
controls remain available in focused sections with destructive confirmation.
Developer Signing keeps all four profile details and the complete seven-step
explanation in disclosures, expands operational progress only while running or
failed, and summarizes a completed renewal in one compact verified result.
Build 110 fully removes the unsuccessful Build 108–109 Watch launcher experiment
and restores the exact pre-experiment Watch Neural Core source and widget bundle.
The rectangular complication again contains only the accepted animated Cathedral
with its original single Pi Terminal tap; no probe, side controls, external launch
routes, Quick Actions sheet, or Now Playing surface remains. Build 107's iPhone
Settings redesign and every unrelated Watch feature remain unchanged.
Build 111 replaces JARVIS-owned blue interface chrome with Pi's official `xhigh`
purple: exact `#D183E8` in dark mode and on Watch, plus Pi's accessible light
variant `#8B008B` on iPhone. The theme covers native navigation, active controls,
status accents, terminal controls, background glows, and widget pending accents
while preserving semantic warning/error/live/air-quality colors and raw terminal
ANSI output. Every JARVIS app, Watch, in-app mark, and widget icon remains
byte-for-byte unchanged, and the restored Neural Core artwork and cadence remain
untouched. Build 112 completes the purifier treatment: the clean/Excellent ring
and quality text use `xhigh` purple on iPhone and Watch, while the iPhone power
toggle, mode picker—including the tappable **Auto** label—and manual fan slider
explicitly inherit the adaptive purple accent. Green/yellow/red air-quality
severity, stale warnings, failures, and pending-confirmation colors remain semantic.
Build 113 reduces Watch dashboard network work without changing its accepted
15-second active/Always-On cadence: each ordinary refresh first requests state
from the last known-good endpoint, and only runs bounded health discovery after
that route fails. Discovery recovery proceeds directly to state without a second
redundant health request; relay/cache fallback and stale-state behavior are unchanged.
The subsequent terminald optimization preserves the accepted 100-millisecond frame
cadence and complete legacy/ANSI response schema while replacing each HTTP handler's
capture loop with one shared, lazy sampler. Metadata and the bounded ANSI grid now
come from one batched read-only tmux invocation per sample; concurrent long polls
share that result, confirmed input wakes the sampler immediately, and sampling stops
after the bounded active-request lease expires. No attach, resize, copy-mode, or
additional terminal input is introduced. The subsequent jarvisd optimization
replaces its 250-millisecond scheduler spin with deadline-based condition waits and
uses the existing 15-second state requests as a 45-second active-client lease.
Active collector cadence is unchanged; after the lease expires, bounded idle
intervals reduce plug, purifier, service, Pi, network, and quota work. Returning
from idle marks over-age plug/purifier data stale, triggers immediate collection,
and waits up to three seconds for one completion before returning; timeout or
failure remains stale and cannot authorize a control. Pending purifier verification
and command-triggered refreshes retain active cadence. Build 114 makes every
interactive Watch-to-iPhone plug and purifier relay immediate-only: correlated
continuations replace the 100-millisecond response-dictionary polling loop, neither
commands nor replies use durable `transferUserInfo`, and an ambiguous delivery or
response timeout is never retried. The Watch requests authoritative state instead.
The iPhone also rejects missing, malformed, future-dated, or more-than-25-second-old
command envelopes, protecting mixed-version rollout from commands queued by an older
Watch build. Read-only latest-value application context remains unchanged. Build 115
removes both plug-widget kinds from the iPhone and Watch extensions, along with their
widget-only App Intents, configurable providers, command feedback store, and retired
source files. Plug control remains fully available inside both native apps. At that
stage, each extension published Neural Core, Open JARVIS, and read-only Air Purifier;
no widget could issue a hardware write. Build 116 removes duplicate Watch
state publication: routine iPhone snapshots now use only coalesced latest-value
application context, while immediate `sendMessage` state delivery is reserved for
explicit request-ID replies. Both hosts reject exact duplicates and older generated
snapshots; the Watch therefore cannot let delayed application context overwrite a
newer direct response or refresh an old cache timestamp. Untimestamped legacy
snapshots remain compatible when no timestamped state would be displaced. The
following jarvisd hardening moves daemon stderr into an owner-only rotating log:
the active file is one MiB with three backups by default, and every emitted line
is capped at 4,096 characters. Repetitive successful plain `GET /health` and
`GET /api/v1/state` records are coalesced per client into a once-per-minute sample
plus a suppressed-count summary. Non-success responses, writes, service/signing
actions, explicit state-refresh queries, and connection failures remain fully
logged. The size, backup-count, and sampling-interval limits are locally
configurable through clamped `JARVISD_LOG_*` environment values. Build 117
bounds Watch speech storage across process termination: startup removes only
regular top-level temporary files whose names exactly match
`jarvis-watch-speech-<UUID>.wav`, leaving unrelated files, symlinks, and nested
content untouched. The single backup-excluded `jarvis-watch-last-response.wav`
cache remains available across wrist-down/app switching, while a missing,
malformed, oversized, symlinked, or metadata-orphaned cache now clears both the
file and response identifier together. Playback, retries, certificate pinning,
and terminal routing are unchanged. Build 118 removes both read-only Air Purifier
widget kinds and their widget-only presentation source from iPhone and Watch.
Each extension now publishes exactly Neural Core and Open JARVIS. Native iPhone
and Watch purifier status and guarded controls remain unchanged. Build 119 adds
one shared fail-closed jarvisd endpoint policy across iPhone input, persistence,
Watch synchronization, discovery, and final request construction. Existing LAN
and Tailscale HTTP endpoints plus HTTPS remain supported and normalized; missing
hosts, invalid ports, credentials, non-root paths, queries, fragments, and every
other explicit scheme are rejected before a token-bearing request can be built.
Build 120 replaces iPhone event/quota parsing's shared mutable ISO-8601 formatter
instances with one immutable value-semantic format strategy while preserving
plain, fractional-second, and offset timestamps. It also makes the Watch
Dashboard container occupy the complete status-bar-free canvas and removes the
Plugs/System top-right header summaries. Build 121 corrects the remaining visible
Plugs-page gap by measuring the space below that header and expanding every plug
row's tile surface to consume it through the bottom edge. Build 122 restores
WidgetKit's explicit `@Sendable` snapshot and timeline completion contracts on
both platforms, removing their Swift 6 task-transfer diagnostics without changing
network refresh, cached fallback, entries, timeline policy, or widget cadence.
Build 123 isolates the pinned SwiftTerm `TerminalViewDelegate` conformance to
UIKit's main actor. Its callbacks remain synchronous, so terminal bytes and PTY
resizes are neither queued nor reordered, while unexpected off-main delegate use
can no longer silently race UI, clipboard, link, or feedback state. Native status,
guarded controls, page order, polling, and semantic colors remain unchanged.
Build 124 configures SSH child-channel half-closure synchronously inside NIOSSH's
child event-loop initializer before pipeline activation. This removes the
`ChannelHandlerContext` capture from the `@Sendable` future callback while
preserving half-closure, setup ordering, and fail-closed channel initialization;
no unsafe isolation, task hop, queue, or terminal transport behavior was added.
Build 125 creates NIOSSH's mutable one-shot `SimplePasswordDelegate` inside the
channel event-loop initializer and hands it directly to that connection's SSH
handler. Credentials remain local values, each connection retains one password
offer, and no delegate crosses an `@Sendable` boundary. The complete iOS build
now compiles with strict concurrency enabled without warnings or errors.
Build 126 applies a behavior-preserving Watch efficiency pass. Endpoint and
terminal-route defaults now write only when their normalized values change;
widgets try their saved authenticated route before bounded discovery fallback;
the Watch dashboard caches its first successful Keychain token read per model
lifetime without caching a locked/unavailable result; and terminal rendering
reuses a bounded three-entry exact ANSI parse cache while suppressing unchanged
frame, status, error, and empty-history publications. The
static launcher requests one WidgetKit reload per installed build, while Neural
Core launch recovery remains unchanged. Quota timestamps now use an immutable
value-semantic parser. Polling and Always-On cadence, terminal byte/input order,
speech preparation, stale-state semantics, Neural Core motion, and guarded
hardware controls are unchanged.
Build 127 retires the former external chat transport and moves all four schedules
to the owner-only generic scheduler. The iPhone adds a fourth **Jobs** tab with a
bounded protected result cache, unread baseline, safe result deep links, and a
read-only job list with per-job output channels. Jobs refreshes every 15 seconds while the app is
active; Home-only hardware/service polling remains confined to Home. `jarvisd`
exposes only sanitized bounded job/result projections. A dormant fail-closed
Watch-only APNs provider and pure route parser remain inactive and push-free
until paid enrollment; no notification prompt, registration, token collection,
entitlement, outbox enqueue, or Apple request is active.
Build 92 removes every
host Siri plug shortcut and restores the supported shared iPhone/Watch two-turn
prompt: say **“Hey JARVIS”**, then answer Siri's **“What would you like me to send
to JARVIS?”** question. The required free-form `String` is normalized and attempted
once with one Return. The value question is the only app-provided dialogue; completion
and failure results are silent. Host metadata contains no plug entities, plug queries,
or turn-on/turn-off intents. Native app plug controls remain unchanged; Build 115
later removes the two widget-only plug-control kinds.
The rejected greeting playback code and bundled JARVIS greeting WAV are absent from
every target. Build 39 mirrors
tmux's exact ANSI-styled grid—including Pi thinking, tool-call backgrounds,
assistant output, dividers, cursor inversion, and token/footer colors—rather
than inferring Pi features. Codex quota accents now use a consistent electric-
blue healthy-state theme on iPhone and Watch. Its focused Digital Crown moves a local read-only
viewport that never sends terminal input. Build 76 retains the 160-row live tail
but fetches bounded 256-row pages on demand across tmux's full 100,000-row regular-
mode history, retaining at most three pages on the Watch. Build 40 reserves
vertical history scrolling exclusively for the Crown; terminal touch drags no
longer change the viewport, while an upward swipe still advances to Plugs.
Build 39 also adds the host-only bare **“Hey JARVIS”** conversational App Intent:
Siri requests one prompt, target-local Keychain configuration preflights the
shared authenticated and certificate-pinned terminal client, then one normalized
prompt is attempted with `appendReturn=true` and no POST retry. Build 40 makes
that accepted prompt and its carriage return one ordered tmux-buffer/PTY write,
so Siri starts Pi immediately without a later manual Send. Build 37 also adds sanitized,
read-only Codex weekly quota, reset, plan, five-hour status, and credit telemetry
from `projects/operation-jarvis/quotas` to iPhone Home and the Watch System page. Build 34 adds Watch terminal failover from the saved LAN endpoint to
stable Tailscale MagicDNS and the current Tailscale address, fits every tmux row
onto one clipped Watch display row, and restores held-Backspace repeat for the
iPhone SwiftTerm keyboard. Build 33 makes the Watch terminal the first of
exactly three vertical pages, followed by Plugs and System, with no launcher
button. Build 32 introduced the native Watch JARVIS terminal backed by a
separate certificate-pinned HTTPS bridge on TCP `8792`. It renders and controls
the same persistent `jarvis-ios` tmux pane, accepts Watch keyboard/Scribble/
dictation input, and remains separate from `jarvisd`. Build 39 makes terminal
history scrolling local/read-only instead of injecting remote mouse bytes;
build 40 removes touch-history scrolling entirely and leaves it Crown-only. Build 31 retains build 30's scroll speed while pacing
wheel input on 60 Hz display frames for burst-free movement, and renames the Pi
tab to JARVIS. Build 30 ends the compact key deck at the Down arrow and slows
touch scrolling by 60%. Build 29 maps vertical touch drags to Pi's fullscreen
wheel scrolling instead of text selection and replaces the dedicated Control-C
key with a slash key. Build 28 performs a one-time migration to an 18-point
starting zoom, then preserves later pinch changes. Build 27 removed the explicit
Pi session display name while retaining SwiftTerm, SwiftNIO SSH, and the
persistent isolated tmux session on this Mac. It preserves build 18's Events
cleanup, build 19's foreground refresh, and build 23's exact “Hey JARVIS” plug
phrases. Physical Watch validation confirms authenticated pinned-HTTPS frames,
one shared Pi pane during simultaneous iPhone attachment, and automatic bridge-
restart recovery without recreating tmux. Owner typing, dictation, key-deck,
Crown and build-34 off-LAN acceptance remain open. Build-37 staged-input/
explicit-Send behavior and physical Codex quota rendering remain owner
acceptance gates. Build-40 physical Crown-only scrolling, keyboard-first Input,
Backspace, ANSI rendering, and immediate bare-phrase Siri routing remain
acceptance gates. Build 42 is physically installed; owner review passed its
brightness, safe-inset, compact-control, and live 11% red-quota presentation.
Its iPhone Siri send succeeded but foregrounded JARVIS underneath Siri's result
sheet, requiring manual dismissal. Build 44 includes build 43's success-only
iPhone Siri handoff, which remains the physical acceptance gate. The three-slot Smart
Stack launcher artwork now passes physical review. Physical consoles
reached `reachable=true` and acknowledged repeated iPhone-to-Watch state
delivery. Cellular/Tailscale cold launch and relaunch also pass. Build 9 removed
weather, reordered Home, and removed the System tab. Build 10 added read-only legacy service status plus a sanitized dynamic scheduled-job inventory. Build 11 replaced the widget catalogue; all four widgets appeared in
the signed physical iPhone gallery and the launcher deep link passed. That gate
exposed a completed-result cache bug after a plug interaction. Build 12 removes
that stale replay, applies confirmed command state immediately, renders pending
feedback, and suppresses repeated same-state taps. Its signed iPhone round trip
passed with exactly one event pair in each direction and the initial state
restored. The Watch gallery then exposed four selected-plug presets and a
two-item grid. Build 13 is the local correction: one editable selected-plug
entry and an all-four 2×2 Watch grid. The physical Watch gallery, editing,
launcher, grid, read-only purifier, and plug-control feedback now pass. Four
intentional alternating Watch widget writes each produced one POST/event pair
and left the lamp restored off. Watch-originated app relay, offline, remaining
accessory-family, live path-change, and accessibility rows remain open. Build 14
is installed on the Watch and adds the branded full-colour launcher widget.
Build 15 is the installed aesthetic candidate: the Watch app now uses a
three-page holographic overview, 2×2 plug control deck, and system/air-quality
page; the iPhone app adds the matching system-pulse header, device-specific plug
cards, air-quality gauge, collapsed runtime sections, event cards, and branded
Settings presentation. Physical review found a blank Open JARVIS Watch launcher
image. Build 16 gives the circular image an explicit proposed frame, forces the
asset to original/full-colour rendering, resolves it from the extension bundle,
and reloads its static timeline whenever the Watch host launches. Physical
review showed that the three-slot Combination widget can use a non-full-colour
rendering mode. Build 17 now branches on `widgetRenderingMode`, uses exact
100×100 Watch-scale full-colour and high-contrast accented assets, explicitly
sizes the circular slot with `GeometryReader`, and advances the launcher kind to
clear the old cached rendition. The re-added physical widget displays the
JARVIS logo successfully. Build 18 deletes `EventsView`, removes its tab and
deep-link route, and strips its AppState UI/polling state. The backend event
audit contract remains intact. Build 19 refreshes both hosts immediately on
activation and every 15 seconds while visible, cancels polling when inactive,
and replaces normal refresh buttons with automatic status plus failure-only
retry on Watch. Build 20 added Turn On JARVIS Plug and Turn Off JARVIS Plug
to Siri/Shortcuts; build 39 adds the separate conversational prompt intent. Build 23 makes their sole spoken form “Hey JARVIS, turn
on/off [the] [plug]” and keeps upgrade-time parameter publication reliable.
Build 24 changes iPhone navigation to Home, Pi, and Settings. The terminal tab opens
an authentic 24-bit terminal and connects directly to macOS SSH. Build 25 moves
first-create/reconnect into `scripts/jarvis-mobile-terminal.sh`, which creates
`jarvis-ios` detached before attaching and supplies Homebrew's path to Pi's Node
launcher under macOS's minimal remote-command environment. Build 26 starts with
the keyboard closed, pins an always-visible keyboard toggle beside the
scrolling key deck, supports tap-to-open and down-swipe dismissal, and prevents
shortcut keys from reopening a deliberately hidden keyboard. Build 27 launches
plain `pi` without a `--name` display-label override. Build 28 recognizes the
legacy saved zoom that masked build 27's fresh default, migrates it once to 18
points, and preserves later pinch zoom within the 9–20-point range. Build 29
disables touch-selection gestures, converts vertical drags to SGR wheel events
for Pi's application-owned viewport, and changes the dedicated Control-C key to
`/`; Ctrl-C remains available through latched Ctrl or a hardware keyboard.
Build 30 removes Left, Right, Shift-Return, Option-Return, Pi-menu, and Paste
buttons so the key deck ends at Down, while retaining the fixed keyboard toggle.
It raises the wheel threshold from 18 to 45 points at default zoom for a 60%
scroll-speed reduction. Build 31 preserves that distance mapping, caps pending
steps, and emits at most one wheel step per 60 Hz display frame instead of
bursting multiple terminal redraws together. The terminal tab is now labeled
JARVIS. Siri's plug parameter is populated from current `jarvisd` state rather
than a compiled list; the generic widget action is not discoverable.

Installed and audited build-44 iPhone artifact:
`/tmp/JARVIS-build44-minimal-home-settings.xcarchive` and
`/tmp/JARVIS-build44-minimal-home-settings-export/JARVIS.ipa`
(SHA-256 `18d9a83f1c4753fe9820664323424c2371eb671077630b570b7614c6fc4a0e78`).
All four archived products report `0.3.0 (44)`, are Personal-Team signed, and
preserve the required nested Watch hierarchy. The exact IPA was upgraded onto
the allowlisted iPhone with `ideviceinstaller -w upgrade`; CoreDevice inventory
reports build 44 and the host launched successfully. The exact archived Watch
product was attempted only on Dylan's allowlisted Watch, but transient tunnel
negotiation remained unavailable; the Watch was left paired, untouched, and on
build 42.

Superseded signed build-43 candidate:
`/tmp/JARVIS-build43-siri-success-handoff.xcarchive` and
`/tmp/JARVIS-build43-siri-success-handoff-export/JARVIS.ipa`
(SHA-256 `ad2abf0b7d9a36b466d3e2dabf8bd309706c043972b8736f6add292042457632`).
All four products report `0.3.0 (43)`, are Personal-Team signed, and preserve the
required nested Watch hierarchy. Build 43 was not physically installed; build
44 carries its Siri handoff unchanged.

Installed and audited build-42 artifacts:
`/tmp/JARVIS-build42-bright-safe-red-siri.xcarchive` and
`/tmp/JARVIS-build42-bright-safe-red-siri-export/JARVIS.ipa`
(SHA-256 `d0724f25933242236f44efb15d659826d9e6fd9e70e3f153fbaa642172a9e771`).
The exact IPA was upgraded onto the allowlisted iPhone with
`ideviceinstaller -w upgrade`, and the exact archived Watch product was
installed directly through CoreDevice. Both inventories report `0.3.0 (42)`.
Physical brightness, rounded-edge safety, compact controls, and live 11% red
quota passed; the phone Siri result-sheet handoff is superseded by build 43.

Superseded installed build-41 artifacts:
`/tmp/JARVIS-build41-watch-dock-always-on-codex.xcarchive` and
`/tmp/JARVIS-build41-watch-dock-always-on-codex-export/JARVIS.ipa`
(SHA-256 `efd9be1c4c87d617b26bc7f90784a1d9e994377dc3b790c0db858a3c89fb8125`).
The exact IPA was upgraded onto the allowlisted iPhone with
`ideviceinstaller -w upgrade`; the exact archived Watch product was installed
through CoreDevice after one non-destructive retry for a transient tunnel
timeout. Both inventories report `0.3.0 (41)`, and both host/widget process pairs
were confirmed running.

Superseded installed build-40 artifacts:
`/tmp/JARVIS-build40-crown-keyboard-backspace-siri.xcarchive` and
`/tmp/JARVIS-build40-crown-keyboard-backspace-siri-export/JARVIS.ipa`
(SHA-256 `d46801ac0e417da247af4295cdeaf57770bef45243612e20fa95540160f83697`).
The exact IPA was upgraded onto the allowlisted iPhone with
`ideviceinstaller -w upgrade`; the exact archived Watch product was installed
through CoreDevice. Both inventories report `0.3.0 (40)`, and both host/widget
process pairs were confirmed running.

Superseded installed build-39 artifacts:
`/tmp/JARVIS-build39-ansi-mirror-crown-siri.xcarchive` and
`/tmp/JARVIS-build39-ansi-mirror-crown-siri-export/JARVIS.ipa` (SHA-256
`355b2c524d3e9e285873dab919b9d89e999bf4178fb028d1a5782651e53a05b5`).

Superseded build-38 artifacts: `/tmp/JARVIS-build38-keyboard-first-watch-input.xcarchive`
and `/tmp/JARVIS-build38-keyboard-first-watch-input-export/JARVIS.ipa`
(SHA-256 `c38d6e7bbc53a2708230a4107e0d25c946b76fb51d70e7e2740d9468c05d4350`).

Superseded installed build-37 artifacts: `/tmp/JARVIS-build37-staged-input-codex-quota.xcarchive`
and `/tmp/JARVIS-build37-staged-input-codex-quota-export/JARVIS.ipa`
(SHA-256 `769d78d519303e6e11c312596f2fb8d26f4a66bb91713059e5aec3af79a19fa6`).

Superseded installed build-36 artifacts: `/tmp/JARVIS-build36-readable-watch-dictation.xcarchive`
and `/tmp/JARVIS-build36-readable-watch-dictation-export/JARVIS.ipa`
(SHA-256 `3430df1569a1befa3acc58f430a344235490e1c7ad4fbc49a4303889ff66b9d6`).

Superseded build-35 artifacts: `/tmp/JARVIS-build35-terminal-scroll-watch-fullscreen.xcarchive`
and `/tmp/JARVIS-build35-terminal-scroll-watch-fullscreen-export/JARVIS.ipa`
(SHA-256 `6c8d733ae1e9dfa3049e19f72fd1c34809be65aadf326e3eef68d7160763711a`).
Build 35 was not physically deployed; build 36 supersedes it.

Build-32 artifacts: `/tmp/JARVIS-build32-watch-terminal.xcarchive` and
`/tmp/JARVIS-build32-watch-terminal-export/JARVIS.ipa` (SHA-256
`26037a06fdb67f751cbbcb7c10e0d3389dbe5e32e901cffc86d53ae4c521f477`).

**v5 note:** the app is the native Apple client for Operation JARVIS. Its
backend is the small `jarvisd` daemon in this folder, which remains the only
hardware/status/service API control plane. The iPhone JARVIS tab uses a separate
SSH terminal data plane; the Watch reaches that same tmux pane through the
independent token- and certificate-protected `jarvis-terminald` HTTPS bridge.
APNs push + Live Activities are out (free Apple ID can't do
APNs); oMLX is out of app scope entirely. The widget catalogue is Neural Core
and Open JARVIS.

**Everything lives in this folder** — the Swift app targets, shared
`JARVISKit` package, `jarvisd`, and `jarvis-terminald` are all under
`jarvis-app/` so the whole project is self-contained.

## Read first

This README is the primary architecture, security, packaging, deployment, widget,
physical-validation, recovery, and release reference for the app. Historical
plans retired from `docs/` are consolidated below. The current native iPhone
keyboard-avoidance and Photos/Files attachment architecture, implementation
sequence, and physical gates are consolidated in the
[`docs/README.md` implementation documentation](docs/README.md#iphone-terminal-keyboard-avoidance-and-native-attach-implementation-plan).

## Scope (v5, approved)

- **In:** smart plugs, air purifier, status and telemetry (Pi session count,
  network, uptime, room audio, scheduler, scheduled jobs, and retained results),
  service start/stop/restart (room-audio server), Neural Core and Open JARVIS
  read-only widgets on iPhone and Watch, the two-turn “Hey JARVIS” App Intent,
  the iPhone SSH-backed Pi terminal with private native Photos/Files attachment
  staging in enabled signed candidates, and the foreground-only Watch view of
  that same persistent terminal over the private HTTPS bridge, with LAN and
  Tailscale remote access.
- **Out:** Cast (all TV/speaker control), Spotify, camera, in-app voice/wake
  word, Raspberry Pi room endpoint, scheduler process mutation and scheduled-
  job mutation in the read-only first release, active **APNs push + Live
  Activities** (paid-account only), **oMLX** (nothing), room-display HUD, and
  phone-voice PWA.

## Devices & distribution

- iPhone 11 (iOS 26) + Apple Watch Series 11 46 mm (watchOS 26).
- Free Apple ID (no $99 yet): 7-day provisioning expiry. Build 104 exposes the
  earliest iPhone/Watch component expiry and a user-confirmed Mac-side renewal
  under **Settings → Developer Signing**; `scripts/renew-free-signing.sh` is its
  fixed allowlisted action. `scripts/redeploy-jarvis-app.sh` remains available
  for iPhone-only development.
- Simulator validation is restricted to exactly one iPhone 11 and one Apple
  Watch Series 11 (46mm) device; physical devices remain the release gate.

## Branding

- App name: **JARVIS**
- Accent: Pi **`xhigh` purple** — `#D183E8` in dark mode/Watch and accessible `#8B008B` in iPhone light mode
- Icon: generated from `../jarvis-icon.png` for both opaque iOS and watchOS
  app-icon catalogs

## What's working now

- **`jarvisd` daemon** — running under launchd (`com.operation-jarvis.jarvisd`)
  with a resurrector watchdog. Explicit `JARVISD_AUTH_MODE=trusted-network`
  (default, configured LAN/Tailscale CIDRs) or `token` mode protects the API;
  `JARVISD_EVENT_TOKEN` is scoped to event ingestion. Verified: `/health`,
  `/api/v1/state` (plugs, purifier, Pi count, network, uptime),
  `/api/v1/command` (allowlisted, rejects cast), `/api/jarvis/events` ingest,
  `/api/v1/events`, `/api/v1/services` (server-allowlisted lifecycle actions),
  `/api/v1/scheduled-jobs`, `/api/v1/scheduled-job-results`, and the fixed
  signing status/renewal endpoints.
- **iOS app — navigation** — 4-tab shell (Home / JARVIS / Jobs / Settings).
  Home shows the connection header (LAN vs Tailscale + IP), Pi session count, a
  **2-column plug grid**, then the **air purifier** (power switch +
  Auto/Manual/Sleep/Pet segmented control + fan 1–4 slider). Weather and its
  external data collection are removed. Home lists room audio, the scheduler,
  and protected `jarvisd` information. Jobs provides a bounded, durable,
  read-only job list and Discord-style per-job output channels with inline safe
  links. Only server-allowlisted service actions
  are rendered; the scheduler card is read-only. Plug controls send
  desired-state `plug-on`/`plug-off`
  commands, serialize per resource, and show busy/error/unavailable states.
- **Event audit backend** — the bounded `/api/v1/events` API and single
  `/api/jarvis/events` ingest sink remain available to operational tooling, but
  the native iPhone client no longer displays or polls an Events feed.
- **iOS app — lifecycle** — health-first discovery is owned by the scene
  lifecycle, retries with backoff after transport failures, and observes network
  path changes. Home hardware/service state refreshes immediately and every 15
  seconds only while Home is selected. Jobs schedules/results refresh every 15
  seconds while any app tab is active; backgrounding cancels polling. Pull-to-
  refresh remains optional, and warm `jarvisd` state reads return from cache.
- **iOS app — Pi terminal** — SwiftTerm renders Pi's regular TUI while SwiftNIO
  SSH carries a password-authenticated PTY to this Mac. First use confirms and
  remembers the SSH host key; the password stays in target-local Keychain. The
  isolated `jarvis-mobile` tmux server creates or attaches `jarvis-ios`, so Pi
  survives tab changes, backgrounding, termination, and reconnection. The
  accepted Build 95 viewport disables native pan momentum/bounce and emits at
  most one immediate SGR wheel event per drag threshold, leaving transcript
  rendering to Pi. Wheel input is never queued, paced, retried, or replayed.
  Escape, Ctrl, Tab, slash, Up, Down, the keyboard toggle, tap-to-open,
  downward-swipe dismissal, persisted 9–20-point zoom, and landscape remain.
  Build 129 confirmed that the accepted SwiftUI composition behaves correctly
  when tmux retains `window-size latest`; the bootstrap reasserts that policy
  without forcing pane geometry or replacing the protected Pi process. Build
  132's isolated iPhone candidate enables a paperclip that stages reviewed
  Photos/Files over a separately typed SSH child. It never injects `/attach`,
  Return, filenames, or protocol bytes into the PTY. Commits are bounded,
  generation/revision checked, exact-byte and SHA-256 verified, and never
  automatically retried after ambiguous delivery. Watch remains attachment-
  isolated.
- **watchOS app** — the embedded Watch app opens directly on Terminal, followed
  by Plugs and System. Dashboard state refreshes every 15 seconds while visible,
  uses direct `jarvisd` first with immediate-only correlated iPhone relay and
  stale cache fallback, and provides guarded native plug plus purifier
  power/mode/fan controls. The terminal uses bearer-authenticated,
  certificate-pinned HTTPS to `terminald`, a fitted one-row-per-tmux-row ANSI
  mirror, Crown-only paged read-only history, keyboard/dictation staging, and
  exact slash/DEL/Return controls. Input fails closed until a fresh route is
  confirmed and is never queued or replayed. Always-On presentation retains the
  last truthful frame without promising continuous networking. Final-response
  speech is explicitly requested and plays only from a verified local WAV.
  Codex quota refresh remains read-only, one-minute, and non-critical to
  hardware freshness.
- **Two-turn Siri prompt** — the iPhone and Watch hosts advertise exactly one
  App Shortcut: “Hey JARVIS.” Siri then asks for the required free-form prompt.
  Host metadata contains no Siri plug entities, queries, or on/off intents. The
  answer is normalized to one logical line and submitted through the authenticated,
  certificate-pinned terminal client as one immediate, non-retried request with
  `appendReturn=true`. The question is the only app-provided dialogue; completion
  and failure results are silent. No greeting playback intent or bundled JARVIS WAV
  is present. Plug control remains available inside the iPhone and Watch apps.
- **Widget catalogue** — each embedded WidgetKit extension publishes exactly
  two non-control widgets: Neural Core and Open JARVIS. All plug and purifier
  widget source, App Intents, and built kinds are removed. Fifteen-minute Neural
  Core timelines use a short single-flight direct-daemon refresh; launchers are
  static. Personal Team provisioning provides no App Groups or shared widget
  credentials, so widgets do not claim shared cache/token or phone relay.
- **`JARVISKit`** — shared package with `JarvisClient` (incl. `discover`),
  `StateSnapshot` models, `EndpointStore` (Keychain), `WatchBridge`; mocked
  networking tests pass, while live integration tests are explicit opt-in.
- **`scripts/redeploy-jarvis-app.sh`** — deterministic one-command build +
  CoreDevice install for iPhone-only development (free Apple ID, 7-day
  auto-provisioning), with current-build output and embedded-watch
  verification. CoreDevice sets a skip-Watch-install flag; use the companion
  runbook's IPA/`ideviceinstaller` flow when registration or transfer is under
  test.
- **`scripts/redeploy-jarvis-watch.sh`** — deterministic watchOS device build +
  install for an available paired physical Watch, with a clear CoreDevice
  availability check.
- **`scripts/verify-jarvis-app.sh`** — daemon tests, package tests, plist/shell
  checks, and iOS/watchOS simulator builds; live tests are opt-in.

## Layout (current)

```text
jarvis-app/
├── README.md                   # this file
├── project.yml                 # xcodegen spec (regenerates JARVIS.xcodeproj)
├── JARVIS.xcodeproj            # generated (do not hand-edit)
├── docs/
│   ├── README.md               # terminal + native attachment implementation plans
│   └── third-party/            # retained third-party license text
├── scripts/                    # verify, deploy, signing, terminald, provisioning
├── jarvisd/                    # Python hardware/status/service daemon (port 8790)
│   ├── jarvisd.py              #   HTTP server + cached state coordinator
│   ├── tests/                  #   auth, input, cache, event, service tests
│   ├── services.json           #   launchctl service registry
│   ├── resurrector.sh          #   watchdog (keeps jarvisd alive)
│   └── launchd/                #   LaunchAgent plists (jarvisd + resurrector)
├── terminald/                  # authenticated Watch terminal bridge (port 8792)
│   ├── jarvis_terminald.py     #   tmux snapshots + bounded byte input
│   ├── tests/                  #   auth/frame/input/provisioning unit tests
│   └── launchd/                #   separate LaunchAgent
├── JARVISKit/                  # shared Swift package (client, models, watch bridge)
│   ├── Package.swift
│   ├── Sources/JARVISKit/      #   Models, JarvisClient, EndpointStore, WatchBridge
│   └── Tests/JARVISKitTests/   #   unit + live integration tests
├── JARVIS/                     # iOS app target (SwiftUI)
│   ├── JARVISApp.swift         #   @main + Home/JARVIS/Jobs/Settings tab shell
│   ├── AppState.swift          #   connection + state + command model
│   ├── AppStateWatchBridge.swift
│   ├── Info.plist              #   scoped local/Tailscale ATS policy
│   ├── PrivacyInfo.xcprivacy
│   ├── Assets.xcassets/        #   icon + accent color
│   ├── Terminal/               #   SwiftTerm + SwiftNIO SSH + Pi key deck
│   └── Views/
│       ├── HomeView.swift      #   Pi telemetry, plugs, purifier, services + daemon info
│       ├── JobsView.swift      #   read-only retained results and schedules
│       ├── SettingsView.swift  #   connection, terminals, signing + app info
│       └── Components.swift    #   badge, card, formatting helpers
├── JARVISWatch/                # watchOS app target
│   ├── JARVISWatchApp.swift
│   ├── Info.plist              #   ATS exception
│   └── Views/WatchConnectView.swift
├── JARVISWidget/               # Neural Core + Open JARVIS
└── JARVISWatchWidget/          # Neural Core + Open JARVIS complications
```

## Backend dependency

`jarvisd` — Python daemon in `jarvis-app/jarvisd/` (port 8790, LaunchAgent +
resurrector): auth, cached `/api/v1/state`, `/api/v1/command` (allowlisted →
`jarvis-cli`), `/api/v1/events`, `/api/jarvis/events` ingest, `/api/v1/services`
(start/stop/restart), sanitized `/api/v1/scheduled-jobs` and
`/api/v1/scheduled-job-results`, plus fixed signing status/renewal endpoints.
The full contract and operating procedure are consolidated later in this
README. Tailscale on the Mac is transport-only.

### Security configuration

The default `JARVISD_AUTH_MODE=trusted-network` accepts only the configured
LAN/Tailscale CIDRs and preserves zero-tap app access. For strict token mode,
set `JARVISD_AUTH_MODE=token` and provide `JARVIS_API_TOKEN`; missing/wrong
app tokens are rejected. `JARVISD_EVENT_TOKEN` is scoped to
`POST /api/jarvis/events` and cannot control
commands or services. Configure `JARVISD_TRUSTED_CIDRS` when the home subnet
changes. Do not put tokens in the repository.

---

# Consolidated architecture, operations, and implementation plans

Historical Markdown documents retired from `docs/` before the current terminal
work are preserved below in full. This README remains canonical for that legacy
architecture and operational material; the current terminal and native
attachment plans are in [`docs/README.md`](docs/README.md). The
`docs/third-party/` license text remains separate because it is not Markdown.

<!-- Previously folded from the retired pre-consolidation docs index -->

# JARVIS native Apple app — unified documentation

**Last updated:** 2026-08-30 EDT

**Applies to:** Xcode 26, iOS 26, watchOS 26, XcodeGen 2.46, Personal Team/free provisioning

**App root:** `/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app`

**Current physical release:** `0.3.0 (126)`

**Current source candidate:** `0.3.0 (127)`; archive and physical acceptance pending

**Physical installation:** iPhone `0.3.0 (126)` and Apple Watch `0.3.0 (126)` on Dylan's allowlisted devices, installed from the exact audited archive products

**Implemented feature record:** [Siri conversational prompt-to-Pi](#siri-conversational-prompt-to-pi-plan)

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
- iPhone navigation is Home, JARVIS, Jobs, and Settings. Build 18's Events
  removal and backend audit retention remain unchanged.
- Home order is Pi sessions, plugs, air purifier, then services and protected
  `jarvisd` information; scheduled-job history and schedules live in Jobs.
- Room audio, scheduler, and sanitized scheduled-job telemetry are integrated.
  The scheduler card is read-only; room-audio actions remain server-allowlisted.
- Desired-state plug commands, authoritative cache revisions, stale-state UI,
  per-resource busy locks, and duplicate-write protection are implemented.
- The corrected Xcode 26 Watch companion hierarchy, `Watch/` embedding, signing,
  parent registration, developer installation, icons, and installed flags pass.
- Physical iPhone and Watch widget galleries expose the final two kinds per platform: Neural Core and Open JARVIS.
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
  Build 51 no longer tears down a healthy terminal long poll on every wrist
  raise or tap. It resumes the pinned session in place, preserves the green live
  state, and performs one bounded recovery restart only when the poll does not
  complete after wake. `WKSupportsAlwaysOnDisplay` remains explicitly enabled.
  This avoids JARVIS deliberately disconnecting, but watchOS can still suspend
  arbitrary networking while dimmed, so continuous terminal streaming in
  Always On is not promised.
- Build 41 reduces the background Codex quota collector interval from five
  minutes to one minute. Every transition into the Watch System page also sends
  one authenticated `GET /api/v1/state?refresh=codexQuota`, then briefly polls
  ordinary state for completion. The collector remains the fixed read-only
  `quotas.py codex --json` command with no probe/save flag and remains
  non-critical to plug/purifier freshness.
- Build 51 removes the iPhone Neural Core widget's authored rounded-rectangle
  outline so only the system-owned widget edge remains. Build 52 removes the
  authored outer frame from the Watch Neural Core too while preserving all
  internal procedural Cathedral geometry.
- Build 53 clears SwiftTerm's local parser, buffers, character-set modes, and
  repeat-character state before consuming each newly authenticated iPhone SSH
  PTY stream. That removes stale client state but does not by itself close the
  startup resize race found during physical acceptance. It does not clear,
  restart, resize, or send input to the persistent `jarvis-ios` pane.
- Build 54 retains the latest valid SwiftTerm columns and rows even if UIKit
  finishes the keyboard-hidden layout before the authenticated SSH child
  channel exists. Session readiness publishes that retained viewport instead
  of replaying the stale PTY creation dimensions; normal later layout and
  keyboard changes still use standard SSH window-change requests. No terminal
  bytes are synthesized, and the persistent pane and Pi process are preserved.
  Build 54 also adds a top-bar Watch speaker/stop control. It is fail-closed while
  there is no completed conversation, while Pi is generating, or until a complete
  local WAV is available. Once verified locally, playback no longer depends on
  the terminal route remaining live. The current Pi process publishes a
  private, atomic final-text marker on `agent_settled`; only `text` blocks from
  the latest final `stop`/`length` assistant message are eligible. terminald
  exposes only readiness plus an opaque response ID in frames, accepts no text
  from the Watch, and forwards the matching private text to the loopback-only
  room-audio `/synthesize` endpoint. The endpoint reuses the canonical Piper
  JARVIS voice and returns a bounded WAV. The Watch downloads it through the
  existing bearer-authenticated, certificate-pinned route and plays it with
  public `AVAudioPlayer`; prepared stale audio is replaced, while an active local
  file is retained until natural completion or explicit Stop. Build 57 preserves
  an already-started local WAV through wrist-down or app switching with the
  supported watchOS `audio` background mode; terminal polling and network
  sessions still stop immediately in true background.
  It also converts readable table rows and splits long prose at bounded word
  boundaries without shortening final text. Build 58 foreground-prefetches one
  complete latest-response WAV through that existing route, but never starts
  playback without a button tap. The 44-by-35-point voice/Stop control takes the
  former top-right FIT/GRID position and matches the lower dock; FIT/GRID remains
  available in the Keys palette. Backgrounding cancels unfinished preparation,
  while an already-started fully local WAV continues unchanged. Build 59 uses
  `.playback`/`.spokenAudio` with `.longFormAudio` and watchOS asynchronous route
  activation, preserves active playback through page exit and response changes,
  and resumes authorized system interruptions from the saved position. It also
  retains the last confirmed terminal frame across expected background
  suspension and requests sequence zero on every recreated route for immediate
  foreground confirmation; it does not claim unsupported permanent background
  networking. Build 60 separates retained-session presentation from live-route
  input readiness: expected background or SwiftUI view rebinding preserves the
  last confirmed green terminal state, but every input control remains disabled
  until a newly created pinned client receives an authenticated frame. No input
  is queued, retried, or replayed. Build 61 always forwards the parent scene's
  `.inactive` transition to the terminal controller, even when the model already
  considers JARVIS foregrounded, while avoiding duplicate refresh-loop creation.
  Build 62 uses SwiftUI's supported `isLuminanceReduced` environment value to
  render a monochrome retained-session checkmark in Always-On state instead of a
  potentially stale transport color; active mode still reports verified
  connecting/live/offline state. Build 63 decouples the foreground speech
  download from the terminal polling client's generation and preserves prepared
  speech across foreground route recovery. Build 64 makes response synthesis
  idempotent at terminald: concurrent requests for one opaque response ID share
  one render, and the complete WAV is written atomically to a private mode-0600
  one-response cache before delivery. This is a non-archival cache: terminald
  deletes every older WAV whenever it publishes the current response, so the Mac
  can retain at most one WAV rather than accumulating speech history. The Watch
  likewise uses one fixed, backup-excluded cache filename; replacement reuses
  that slot, while stale-response cleanup, explicit Stop, natural completion,
  and unrecoverable errors delete it. The Watch remembers only an allowlisted
  selected route, uses bounded 1/2/4/8/12-second speech recovery, and stops the
  loading state after six failed retries until a newly authenticated route is
  confirmed. A validated complete local WAV is retained across terminal route
  failure, process restoration, true background, and app switching, and can be
  started while the terminal reconnects; unfinished network preparation is still
  cancelled in true background. A stale response, page exit before playback,
  explicit Stop, completion, or unrecoverable validation/trust error clears it.
  Physical build-64 acceptance passed on both allowlisted devices: a fresh short
  response produced exactly one synthesis, two forced cache retries returned
  byte-identical WAVs with zero additional synthesis, and a 52.895-second response
  remained audible through wrist-down, page changes, app switching, and natural
  completion without incorrect orange status. OSLog lifecycle/route/speech events
  are included for physical diagnostics. No
  automatic speech, new credential, new port, workout, extended runtime session,
  or terminal input path is added.
- Build 65 adds an iPhone-only animation fail-safe under the existing 60
  procedural Cathedral frames. If WidgetKit suspends the timer masks in an
  all-transparent state, the fail-safe remains a complete fixed-phase composition
  with full authored layer density, luminance, and the JARVIS wordmark. Each
  selected animation frame first paints the same dark background, so the fail-safe
  adds no ghost trails during normal 30 FPS motion. A new timeline entry changes
  the animated view identity, and host launch requests a Neural Core timeline
  reload, giving WidgetKit supported opportunities to rebuild a suspended selector
  without a process timer, private API, or animation claim. The non-sensitive
  JARVIS brand label is explicitly unredacted; telemetry remains fail-closed and is
  never exempted from WidgetKit privacy treatment.
- Build 66 removes build 65's iPhone `widgetRenderingMode == .fullColor` motion
  gate. Physical iOS 26 can classify a full-sized Home Screen widget as accented
  or clear; the gate therefore selected the static branch even though the system
  timer selector was available. Full-density fail-safe artwork remains beneath
  all rendering modes, while reduced-motion, stale telemetry, luminance reduction,
  and unavailable-font conditions continue to select a complete static frame.
- Build 67 performs the first physical memory reduction after device logs proved
  `JARVISWidget` was killed at 30,721 KB for exceeding iOS's 30 MB active hard
  limit while producing its replacement timeline; WidgetKit then retained the old
  static archive. Continuous artwork now omits the phase-independent wordmark from
  the fallback and every masked frame and draws one unredacted wordmark above the
  complete stack. Physical build-67 logging showed that removing those Text
  subtrees alone was insufficient: the process still reached the same hard limit.
- Build 68 removes the actual extra complete tree. Phone frame zero is both the
  unmasked, always-present fail-safe and the normal first phase; masked frames
  1–59 replace it during their slots. The phone therefore serializes exactly
  60 complete Cathedral frames rather than 61 while retaining all 60 phases per
  two seconds. Watch keeps its existing 32 masked frames with no added fallback.
  Physical build-68 logging confirmed zero 30 MB kills, but generation still took
  about 2.3 seconds across WidgetKit's rendering variants and the replacement file
  missed the system archive window.
- Build 69 replaces every internal full `JARVISNeuralCoreArtwork` subtree with a
  lightweight Canvas-only frame. Geometry, animation transactions, clipping, and
  accessibility remain on the outer continuous view once. Static contexts retain
  the complete accessible artwork path. Clean physical logging then showed the
  healthy 12,016,600-byte archive being explicitly rejected as too large.
- Build 70 reduces only phone curve tessellation to the physical widget's resolvable
  precision. It preserves 60 phases per two seconds and every path, filament,
  particle, ray, column, and ring; Watch sampling is unchanged. Physical logs
  confirmed successful timeline reloads with no memory or archive-size kill.
- Build 71 removes the Canvas-internal phone background after physical Clear mode
  remapped it into a solid white accented layer, but its duplicate replacement masks
  again exceeded the 30 MB extension limit and the timeline was rejected.
- Build 72 removes the unmasked live fallback and every per-frame background. Its
  best-effort live path consists only of 60 transparent accentable Canvas phases,
  one timer mask per phase, and one shared wordmark. Physical logs showed healthy
  memory but rejected its 11,169,064-byte timeline archive as too large.
- Build 73 reduces only subpixel phone curve sampling to recover archive headroom
  for frame zero's timer mask. It retains all 60 phases and every artwork element;
  Watch tessellation remains unchanged. Physical logs confirmed three successful
  timeline reloads with no memory or archive rejection, and captured motion resumed.
- Build 74 restores the once-shared wordmark to its approved top-leading alignment
  without adding any frame, mask, background, or fallback. The exact signed iPhone
  product produced two successful physical timeline reloads with zero memory kills,
  archive rejections, or reload failures; a 7.17-second capture sampled 17 distinct
  Cathedral frames with no static run.
- Build 75 isolates those iPhone-only archive optimizations from watchOS. The Watch
  live path is restored to its previously accepted 32 complete Cathedral views,
  each with its original system-timer mask; phone build-74 rendering is unchanged.
- Build 76 removes FIT/GRID and horizontal panning. Its first physical candidate
  used 12-point output and editor text. The direct keyboard-first Input field keeps
  exactly one dock surface. Authenticated read-only 256-row history pages let the
  Crown traverse every row retained by tmux while only three pages remain in Watch
  memory. The authoritative 48-column pane and regular-mode Pi process are never
  resized, restarted, or sent history-navigation input.
- Build 77 restores the original accepted FIT font size to both output and Pi's
  unwrapped cursor-following editor after physical review found 12 points too large.
  FIT/GRID remains removed, horizontal gestures remain absent, and build 76's Input
  surface and full paged history remain intact.
- Build 79 restores the accepted compact iPhone Home source after build 78's dashboard
  redesign was physically rejected.
- Build 81 delegated iPhone transcript movement to SwiftTerm's existing native
  `UIScrollView`, but physical testing found no accessible history because the
  outer `tmux attach-session` client enters DECSET 1049 and SwiftTerm correctly
  gives that alternate buffer no scrollback.
- Build 82 filters only that fragmented outer-client `1049h`/`1049l` envelope
  before SwiftTerm parsing, without altering the persistent pane or requesting a
  server snapshot. Its normal buffer retains the same bounded 100,000 rows as tmux.
  Physical testing nevertheless found history inaccessible.
- Build 83 removes build 82's second simultaneous keyboard-dismissal pan recognizer
  and its output-callback `contentOffset` writes. Physical testing still produced
  only live-edge rubber-banding, so build 83 is rejected.
- Build 84 preserves build 83's one native pan and zero-byte scrolling path while
  writing content-free physical diagnostics to
  `Library/Caches/JARVIS-terminal-scroll-diagnostics.log`. A physical long-response
  reproduction received 266,930 bytes, but `normalLines` stayed exactly equal to
  the 42-row terminal and `contentSize` stayed equal to the viewport. This rules out
  gesture ownership and stale `contentSize`: tmux's batched multi-line `CSI Ps S`
  updates were only shifting SwiftTerm's screen in place.
- Build 85 parses fragmented CSI boundaries locally. When tmux scrolls its complete
  client region with `CSI Ps S`, the app invokes SwiftTerm's equivalent normal-buffer
  scroll primitive once per displaced row. Restricted-region and non-SU ANSI remain
  untouched. Physical testing rejected build 85: after 1.22 MB of visibly line-by-line
  output, diagnostics reported `promoted=0`, `normalLines=42`, and one-viewport content.
- Build 86 leaves build 85's rendering behavior unchanged and adds a fragmented ANSI
  diagnostic state machine. Its physical trace measured 13,023 C0 line feeds, 12,972
  EL commands, 13,714 CUP commands, zero SU/DL/IL/IND, and no local history growth.
  Combined with tmux history growing to 283 rows, this identifies synchronized
  cursor-addressed redraw as the lost-scroll path.
- Build 87 adds one companion SSH exec channel that reads only tmux `history_size` at
  25 ms intervals. The first count is a baseline, so old tmux history is never fetched
  or synthesized. Positive deltas received after attachment invoke SwiftTerm's normal-
  buffer scroll before the associated cursor-addressed redraw; the visible final screen
  remains tmux-authored while displaced local rows enter native scrollback. It requests
  no pane text, sends no terminal input, and makes no tmux/session/configuration mutation.
  If no fresh metadata arrives within 150 ms, output renders immediately and the next
  count is rebaselined instead of being applied late to the wrong screen. CSI-S remains
  a reconciled fallback, and snapshots, overlays, offset writes, and redraw rebasing
  remain absent.
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
- Build 44 keeps that Siri contract unchanged and compresses the iPhone Home
  and Settings roots to fit the iPhone 11 viewport without required scrolling.
  Pi sessions and the full Codex card remain directly visible; plugs and the
  purifier use compact controls; service/job details and Settings configuration
  move behind summary rows without removing any action or telemetry.
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

### Installed build 44 on iPhone

```text
Archive: /tmp/JARVIS-build44-minimal-home-settings.xcarchive
IPA:     /tmp/JARVIS-build44-minimal-home-settings-export/JARVIS.ipa
SHA-256: 18d9a83f1c4753fe9820664323424c2371eb671077630b570b7614c6fc4a0e78
```

All four Personal-Team-signed products report `0.3.0 (44)`. Deep and individual
signatures, required Watch hierarchy, iPhone `openAppWhenRun=false`, Watch
`openAppWhenRun=true`, widget prompt exclusion, and Watch dependency isolation
pass. Validation passes 26 `jarvisd`, nine terminal-daemon, 43 JARVISKit tests
with three expected live skips, 19 iPhone tests, repository smoke
`PASS=104 WARN=0 FAIL=0`, and warning-free signed archive/export logs. The exact
IPA was upgraded with `ideviceinstaller -w upgrade`; CoreDevice inventory reports
build 44 and the iPhone host launched successfully. Simulator evidence:

- `/tmp/JARVIS-build44-home-direct-pi-codex.png` — the complete Home root with
  direct Pi/Codex cards, plugs, purifier, and System visible without scrolling.
- `/tmp/JARVIS-build44-home-direct-codex-critical-red.png` — direct 29% Codex
  card in the strict critical-red theme.
- `/tmp/JARVIS-build44-minimal-settings-final.png` — the complete compact
  Settings index visible without scrolling.

The exact archived Watch product was attempted only on Dylan's allowlisted
Watch. CoreDevice tunnel negotiation remained unavailable, so no destructive
recovery was attempted and the Watch remains installed on build 42. Build 44's
system-level iPhone Siri sheet handoff and compact physical layout remain owner
acceptance gates.

### Superseded signed build 43 candidate

```text
Archive: /tmp/JARVIS-build43-siri-success-handoff.xcarchive
IPA:     /tmp/JARVIS-build43-siri-success-handoff-export/JARVIS.ipa
SHA-256: ad2abf0b7d9a36b466d3e2dabf8bd309706c043972b8736f6add292042457632
```

All four Personal-Team-signed products report `0.3.0 (43)`. Its security,
signing, hierarchy, and validation gates passed, but it was not physically
installed. Build 44 carries its success-only Siri handoff unchanged.

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
actual SGR cell attributes and a bounded 160-row live history tail. Build 40 allows
only the focused Digital Crown to move the local read-only history viewport;
vertical touch no longer scrolls terminal output and cannot become terminal
input during a network loss. Build 76 removes FIT/GRID and every horizontal
scroll gesture. Build 77 uses the original fitted font for both complete output
rows and Pi's unwrapped cursor-following editor. Authenticated 256-row GET pages
extend Crown navigation through tmux's full retained regular-mode
history without adding terminal input or unbounded Watch memory. Thinking, tool
calls, assistant text, dividers, and usage/footer rows retain Pi's own styling
without semantic reconstruction.
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
creation races, launches `pi --tui-mode regular` without assigning a special
Pi display name, and then attaches the phone PTY. The regular main-screen layout
keeps the editor and newly streamed response together near the top until output
grows, so the Watch mirror sees the first response rows immediately instead of
cropping them above a fullscreen bottom editor. The presentation override is
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
parameter-query burst. At that historical checkpoint, widget configuration
choices remained separate; Build 115 removes those plug-widget choices entirely.

Every intent obtains fresh state and validates the exact daemon identifier before
writing. Already-satisfied requests return without a POST. Other writes use only
`plug-on` or `plug-off`, and Siri reports success only after the command response
or a follow-up authoritative read confirms the desired state. Stale, unknown,
removed, rejected, and unconfirmed requests fail closed. The then-present raw
widget `SetPlugIntent` was non-discoverable and is removed in Build 115. Watch execution tries direct
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

### Build 132 release result

- Source commit `b7e0eb444c62c30bada257f7f4b09cbc86d4310f` is preserved on
  `feat/iphone-terminal-attach`; its isolated candidate enabled native iPhone
  attachments and set build 132 without changing checked-in defaults.
- The exact four-product archive passed signature, provisioning, entitlement,
  background-mode, APNs-isolation, Watch-isolation, source-contract, and
  62-file manifest audits with zero compiler diagnostics.
- Exact archive products were installed without rebuilding. Both allowlisted
  inventories report `0.3.0 (132)`, and the iPhone Jobs route plus Watch app
  launched successfully.
- Files/Photos staging, cancellation, clear, hashing, size/mode, cleanup,
  pane-survival, no-model-turn, and flat attachment storage passed physically.
  The owner also accepted the deployed job-centric Jobs presentation and safe
  inline-link behavior.
- The protected `jarvis-mobile` / `jarvis-ios` / `%0` runtime and
  `window-size latest` policy survived deployment. APNs remains dormant and
  Watch remains attachment-isolated.

Additional attachment stress cases and a repeated forced-idle stale-start probe
remain optional follow-up validation, not Build 132 release blockers.

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
- Read-only scheduler status.
- Sanitized, dynamic, read-only scheduled-job inventory.
- Direct Watch operation on LAN, iPhone relay when direct access fails, and
  cached stale fallback.
- Neural Core and Open JARVIS widgets on iPhone and Watch; plug and purifier
  control remains inside the apps.
- The host-only two-turn “Hey JARVIS” App Intent and `jarvis://home`,
  `jarvis://pi`, `jarvis://jobs[/result/<sequence>]`, and `jarvis://settings`
  deep linking.
- iPhone-only authentic Pi TUI over SSH with persistent tmux reattachment.
- LAN and Tailscale access.

### Excluded

- The retired dashboard, room-display HUD, phone-voice PWA, camera/browser APIs,
  Pi/ADB tiles, and port `8787`.
- Weather and Open-Meteo.
- Cast, Spotify, camera, in-app voice/wake word, Raspberry Pi room control, and
  oMLX.
- APNs, Live Activities, and TestFlight while using free provisioning.
- Scheduler mutations and scheduled-job add/remove/edit/setup in the current
  read-only rollout.
- Service, scheduled-job, plug, or purifier widgets and widget controls.

Cast, room audio, Pi telemetry, smart plugs, purifier tooling, and other
Operation JARVIS subsystems continue to exist outside the native app.
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
├── README.md                   # app reference + consolidated historical docs
├── docs/
│   ├── README.md               # current terminal + attachment implementation plans
│   └── third-party/            # retained third-party license text
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
└── JARVISWatchWidget/          # watchOS WidgetKit extension
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
| `GET /api/v1/scheduled-jobs` | Sanitized read-only private-scheduler inventory. |
| `GET /api/v1/scheduled-job-results` | Bounded sanitized retained results with `after`, `limit`, and optional `jobId`. |
| `GET /api/v1/signing/status` | Bounded fixed signing-renewal status and profile projection. |
| `POST /api/v1/signing/renew` | Starts only the fixed argument-free allowlisted renewal action; accepts no body. |

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

1. Room Audio Server — existing allowlisted lifecycle controls.
2. Scheduled Jobs Runner — read-only.
3. Protected `jarvisd` status card.

Scheduled jobs remain canonical `.pi/scheduler/runner.py` records, not fake
LaunchAgents. Public output is sanitized again at the daemon boundary. The app
may receive only bounded fields such as ID, name, description, schedule, enabled
state, next/last run, last status, run count, and retained result summaries.
Prompts, model names, context identifiers, paths, environment values, command
lines, database details, and unsanitized output must never reach the native
response.

Any future scheduler or job mutation requires a separate warning, explicit
authorization, a fixed backend allowlist, confirmation UI, duplicate protection,
and an audit event. Do not stop the scheduler across an understood due boundary.

---

## 5. Native app behavior

### iPhone

- **Home:** Pi sessions → plugs → air purifier → System summaries for services,
  schedules, and protected `jarvisd` state.
- **JARVIS:** the persistent SSH/tmux Pi terminal; Home hardware polling rests
  while this tab is selected.
- **Jobs:** read-only retained Inbox and Schedules views, unread baseline, safe
  HTTP(S) links, and `jarvis://jobs/result/<sequence>` result routing.
- **Settings:** focused Connection, Pi Terminal, Watch Terminal, and Developer
  Signing destinations plus app version information.
- Health establishes connectivity before slower resources load. Scene lifecycle
  owns connection and polling; backgrounding cancels work, foregrounding
  reconnects, and network-path changes trigger rediscovery.
- Home state/services refresh immediately and every 15 seconds only on Home.
  Jobs schedules/results refresh every 15 seconds while any tab is active.
  Pull-to-refresh remains available but is not required.
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
repeated relay request executes once. Interactive plug/purifier messages and their
correlated replies use only immediate `sendMessage` delivery and are never queued
for later execution. The iPhone rejects command timestamps outside the bounded
25-second delivery window. The Watch remains pending until a result, error, or
timeout; an ambiguous delivery is never retried and instead requests authoritative
state.

The iPhone sends the latest endpoint and state through application context.
The Watch refreshes immediately whenever it becomes active and every 15 seconds
while visible, using a single coalesced refresh task. It cancels that task when
inactive. Normal refresh buttons are absent; passive freshness is always shown
and Retry now appears only after an automatic failure. The Watch cannot join the
iPhone's Tailscale client directly, so away-from-home operation relies on the
iPhone relay. Inventory, installed flags, reachability, state delivery, and
command correlation are separate assertions.

### Siri and Shortcuts

The iPhone and Watch hosts advertise exactly one App Shortcut: bare **“Hey
JARVIS.”** Siri asks **“What would you like me to send to JARVIS?”**, normalizes
the required free-form answer to one bounded logical line, preflights the saved
authenticated/certificate-pinned terminal route, and attempts one immediate
`appendReturn=true` request. Input is never queued, replayed, or retried after
ambiguous delivery. iPhone uses a success-only `OpenURLIntent` handoff to the
JARVIS tab; Watch foregrounds/selects Terminal only after confirmed delivery.

Host metadata contains no plug entities, plug queries, or turn-on/off intents;
plug and purifier control remains inside the native apps. Widgets contain no
Siri prompt intent, and no purifier, service, scheduler, status, or launcher
shortcut is published.

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

Each platform publishes exactly two current widget kinds. All plug and purifier
widget kinds are removed; plug and purifier status/control remain inside the
native apps.

### iPhone families

| Widget | Families | Behavior |
|---|---|---|
| Neural Core | system medium | Read-only synchronized artwork and cached telemetry; opens JARVIS Home. |
| Open JARVIS | system small; accessory circular, rectangular, inline | Static `jarvis://home` launcher. |

### Watch families

| Widget | Families | Behavior |
|---|---|---|
| Neural Core | accessory rectangular | Read-only synchronized artwork and cached telemetry; opens the terminal. |
| Open JARVIS | accessory circular, corner, rectangular, inline | Opens the Watch app; full-colour canonical art except inline system fallback. |

### Data and interaction rules

- Launcher timelines use `.never`; Neural Core timelines request refresh about
  every 15 minutes, subject to WidgetKit scheduling.
- State becomes stale after 15 minutes or when `jarvisd` marks it stale.
- Only concurrent timeline reads are coalesced; completed attempts are not
  retained as a process-level refresh cache.
- No remaining widget contains an App Intent button or hardware-write path.
- Widget links retain their documented Home, Watch-app, or terminal destination.

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
- Build 118 removal of every plug/purifier widget and widget write path.
- Build 126 physical iPhone/Watch installation, terminal behavior, native
  plug/purifier controls, and two-kind widget catalogues.

### Historical Build 127 matrix (completed and superseded by Build 132)

| Owner | Test | Pass condition |
|---|---|---|
| Build 127 packaging | Archive/export clean `main` once | All four exact products report `0.3.0 (127)` and pass profile, signature, entitlement, and Watch-hierarchy audits. |
| Exact deployment | Install the audited iPhone IPA and nested Watch product | Both allowlisted inventories report Build 127; Build 126 is replaced only after verification. |
| Jobs | Inspect Inbox, Schedules, unread state, details, and safe links | Sanitized results render, active refresh works, and no scheduler/job mutation route exists. |
| Widgets | Inspect both galleries | Each platform exposes only Neural Core and Open JARVIS; no plug, purifier, or control widget appears. |
| Siri/terminal | Run one harmless owner prompt | Bare “Hey JARVIS” sends once, success hands off correctly, and no host plug intent returns. |
| Watch routing | Exercise read-only direct/relay/offline recovery | State and terminal routes recover honestly; no input or hardware write is queued/replayed. |
| iPhone networking | Wi-Fi/cellular switch and Local Network deny/re-enable | Automatic recovery and truthful path/error state. |
| Accessibility | Physical VoiceOver, large text, contrast, Reduce Motion | Core iPhone/Watch controls remain usable. |

Use underlying canonical CLI/hardware state as truth once per test. Do not
re-prove every surface after every action. Warn before any physical hardware
change, use desired-state actions, and restore the original state. Real bot,
scheduler, scheduled-job, or purifier mutations require separate explicit
permission.

### Historical Build 127 release checklist (completed and superseded)

1. Finish the remaining Build 127 matrix.
2. Run `./.pi/smoke-test.sh` once.
3. Run `JARVIS_RUN_IOS_TESTS=1 ./scripts/verify-jarvis-app.sh` once.
4. Run the opt-in live JARVISKit suite once.
5. Verify `jarvis-cli --json help` and one safe read-only status path.
6. Run `git diff --check`, inspect repository status, and audit for forbidden
   artifacts or identities.
7. Build from fresh DerivedData and deploy one exact archive to both allowlisted
   devices.
8. Confirm both inventories report `0.3.0 (127)` and run read-only Jobs,
   widget, terminal-route, and Siri handoff acceptance.
9. Record Build 127 as the physical release only after every required row passes;
   do not change the marketing version unless separately approved.

All commits remain local unless Dylan separately requests a push.

---

## 12. Condensed early implementation history (through Build 24)

| Milestone/build | Result |
|---|---|
| M0 | Added `jarvisd`, launchd watchdog, JARVISKit, discovery, iOS/watch shells, and free-team deployment. Physical iPhone LAN auto-discovery passed. |
| M1 | Added Home plug/purifier/Pi controls. |
| M2 | Added Events and service lifecycle UI; later consolidated services into Home. |
| M2.1 | Added explicit auth modes, bounded HTTP/event storage, cached single-flight state, reversible services, lifecycle-aware polling, honest stale UI, deterministic deployment, tests, and real WCSession callbacks. |
| Build 8 | Corrected packaging/reliability baseline, companion registration, physical state delivery, and cellular/Tailscale validation. |
| Build 9 | Removed weather/Open-Meteo, reordered Home, removed System tab. |
| Build 10 | Added read-only legacy service/scheduler status and sanitized dynamic scheduled jobs. |
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

<!-- Folded from `docs/animated-monochrome-cathedral-plan-2026-08-23.md` -->

# Animated Monochrome Cathedral Plan

Date: 2026-08-23 EDT
Status: Historical implementation plan; deployed and physically accepted through the later Build 75/126 widget path, with WidgetKit/Always-On timing still system-controlled

## Decision summary

The Monochrome Cathedral can be recreated entirely as native SwiftUI vector/procedural artwork. It does not need to be a PNG, GIF, video, or other static asset.

A continuously animated third-party iPhone Home Screen widget or Apple Watch complication is **not possible with WidgetKit**. Widget views are archived and rendered by the system; the extension's view code is not continuously running while the widget is visible. WidgetKit supports animations when transitioning between timeline entries or other system-driven content changes, not an indefinite display-link animation loop.

Apple also explicitly disables widget and complication animations on Always-On displays to preserve battery life.

The recommended product is therefore:

1. A native-vector Monochrome Cathedral widget and complication with **short, system-supported motion when a real timeline entry changes**.
2. A balanced hero frame that remains attractive when WidgetKit freezes it between updates and in Always On.
3. Optionally, the same rendering engine presented inside the foreground iPhone and Watch apps, where it can animate continuously while active. In Always On, motion stops but the artwork does not apply an additional authored luminance reduction; the system remains responsible for actual display luminance.

## Feasibility matrix

| Surface | Procedural/vector artwork | Continuous animation | Short update transition | Always On |
| --- | --- | --- | --- | --- |
| iPhone Home Screen widget | Yes | No | Yes, when WidgetKit changes entries | System suppresses animation on AOD-capable devices |
| Watch complication / accessory widget | Yes | No, even while the face is active | Yes, when WidgetKit changes entries | Static; animation is system-disabled |
| Foreground iPhone app | Yes | Yes | Yes | Not applicable to Dylan's iPhone 11 |
| Foreground Watch app | Yes | Yes while active | Yes | Static with no additional authored dimming; the system controls display luminance |

Smart Stack widgets and Live Activities do not remove the continuous-animation restriction. A custom Watch face is also not available to third-party apps.

## Apple platform basis

- WidgetKit archives timeline-entry views and the system renders those archived representations. The widget extension's view code is not running continuously on screen.
- Widget animations communicate changes between timeline entries. They are not a persistent render loop, and Apple limits widget/Live Activity animations to a maximum duration of two seconds.
- Widgets do not support continuous, real-time updates, and timeline reloads are system-budgeted.
- On Always-On displays, the system does not perform widget animations.
- A foreground watchOS app is different: `TimelineView(.animation)` can drive high-frequency rendering while active. Its cadence drops when the app becomes inactive or enters Always On.

References:

- [Animating data updates in widgets and Live Activities](https://developer.apple.com/documentation/widgetkit/animating-data-updates-in-widgets-and-live-activities)
- [Bring widgets to life — WWDC23](https://developer.apple.com/videos/play/wwdc2023/10028/)
- [Widgets — Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/widgets)
- [Updating watchOS apps with timelines](https://developer.apple.com/documentation/watchos-apps/updating-watchos-apps-with-timelines)
- [WidgetKit foundations — WWDC26](https://developer.apple.com/videos/play/wwdc2026/277/)

## Visual contract

The production design retains only the `JARVIS` wordmark. There are no visible metric labels, status sentences, or explanatory text.

The cathedral remains state-reactive through geometry rather than copy:

- Pi sessions control illuminated filament channels and radial density.
- The four approved plugs control four architectural anchor nodes.
- Codex remaining controls the outer orbital arc while preserving the strict critical threshold: below 30% is critical; exactly 30% is not critical.
- PM2.5 controls central-core intensity.
- Fresh connectivity permits the energized composition.
- Missing or stale telemetry freezes, dims, and fractures the projection instead of inventing activity.
- Gallery placeholders are the only state allowed to use illustrative values.

Accessibility continues to expose a useful spoken state even though the visual presentation contains no metric text.

## Procedural animation design

Build the image as deterministic vector layers, not a raster sequence:

1. **Core reactor** — pronounced rhythmic breathing and concentric discharge waves.
2. **Inner filament sphere** — deterministic curved links carrying bright synaptic impulses, visible tails, and destination-node flashes.
3. **Particle crown** — seeded particles that brighten, orbit, and drift along constrained paths; no random jitter between renders.
4. **Cathedral arches** — symmetric upper and lower structures with very slow counter-rotation or phase offset.
5. **Orbital equator** — a restrained white/silver sweep around the center.
6. **Telemetry anchors** — four fixed nodes whose intensity reflects real plug state.
7. **Wordmark** — stable `JARVIS` text; it does not orbit, pulse, or compete with the image.

Motion must be energetic but ordered and architectural. Frequent neuron-like firings should make the projection feel alive without turning it into random noise or a loading spinner.

### Motion modes

- `liveApp`: continuous time-driven animation for a foreground app.
- `widgetTransition`: a restrained morph between two equally valid hero frames when WidgetKit presents a new entry.
- `reducedMotion`: no rotation or travel; at most a subtle opacity transition on a real update.
- `alwaysOn`: static full-designed-luminance hero frame; the system may apply its own display treatment.
- `stale`: static fractured frame with no energized motion.

Every endpoint must be a finished composition because WidgetKit may stop showing motion at any time.

## Proposed architecture

### Shared rendering engine

Create a shared source group compiled into the iPhone app, Watch app, iPhone widget, and Watch widget without adding SwiftTerm, NIO, or SSH to widget targets.

Suggested types:

- `MonochromeCathedralArtwork`: public SwiftUI composition.
- `MonochromeCathedralCanvas`: procedural `Canvas` renderer.
- `MonochromeCathedralGeometry`: deterministic points, arcs, filaments, and seeded particles.
- `MonochromeCathedralPhase`: normalized phase values for core, orbit, crown, and highlights.
- `MonochromeCathedralMotionMode`: live app, widget transition, reduced motion, Always On, or stale.
- `MonochromeCathedralStyle`: phone/watch density and rendering-mode adaptations.

Inputs remain explicit: telemetry, layout, motion mode, phase, rendering mode, and luminance state. Rendering must never perform networking or generate fake telemetry.

### Widget behavior

The current providers request a reload every 15 minutes, but WidgetKit controls actual timing. Do not increase reload frequency to simulate animation.

When a fresh entry replaces an old entry:

- Alternate between two compositionally balanced deterministic phases.
- Animate small layer transforms and opacity changes for approximately 1–2 seconds.
- Let the resulting frame remain static until the next real update.
- Suppress motion under Reduce Motion, stale telemetry, nonanimated system contexts, or reduced luminance, without intentionally dimming the static hero frame.

This produces occasional "awakening" motion, not continuous animation. It must be described honestly in the widget description and acceptance criteria.

Preserve existing deep links:

- iPhone Neural Core opens Home.
- Watch Neural Core opens Terminal.

### Optional foreground app behavior

Use `TimelineView(.animation)` to derive phase from the supplied timeline date rather than timers or mutable random state.

- iPhone: animate while the relevant JARVIS view is visible.
- Watch: animate only when the app is active and cadence is live.
- Watch Always On: immediately freeze on the full-designed-luminance static hero phase and rely on the system for actual display luminance.
- Respect Reduce Motion on both platforms.

This is the only supported route to genuinely continuous Monochrome Cathedral motion.

## Performance boundaries

- Keep a single primary `Canvas` and a small number of independently transformed SwiftUI layers.
- Use deterministic seeded geometry so entry updates do not scramble the sphere.
- Reduce filament and particle counts on Watch.
- Keep Always-On artwork at the designed luminance; simplify only effects the system cannot render legibly or efficiently.
- Avoid Metal, video, animated GIF/APNG, timers, display-link workarounds, timer/custom-font frame encoding, and private clock-hand effects in widget extensions.
- Treat the actual `GeometryReader` size as authoritative; do not hardcode mockup pixels.

Initial density targets for physical profiling, not hard requirements:

- iPhone medium: 80–140 visible filament segments and 40–64 particles.
- Watch rectangular: 36–72 visible filament segments and 18–32 particles.
- Always On: no animation and no intentional luminance reduction; detail may change only if physical legibility or performance requires it.

## Implementation gates

### Gate 0 — motion study (complete)

Produce a short native-vector motion study at the exact iPhone medium and Watch rectangular aspect ratios. Show:

- normal active loop,
- WidgetKit-compatible one-shot transition,
- Watch Always-On frame,
- stale/frozen frame,
- Reduce Motion frame.

Approval here prevents committing to unsuitable motion language.

Neural-firing revision 2 motion-study artifacts:

- `/tmp/JARVIS-monochrome-cathedral-neural-firing-study.mp4`
- `/tmp/JARVIS-monochrome-cathedral-neural-firing-iphone.mp4`
- `/tmp/JARVIS-monochrome-cathedral-neural-firing-watch.mp4`
- `/tmp/JARVIS-monochrome-cathedral-full-luminance-static.png`

### Gate 1 — renderer replacement (complete)

Replace the current Neural Core ring/trace with the static Monochrome Cathedral renderer while preserving telemetry semantics, `JARVIS`, accessibility, rendering modes, and deep links.

### Gate 2 — physical WidgetKit transition proof (installed; visual acceptance pending)

Before building the entire animation system, prove on both allowlisted physical devices that the chosen layer transforms interpolate acceptably between timeline entries. If `Canvas` contents crossfade rather than interpolate cleanly, keep geometry inside Canvas and animate only stable containing layers such as orbit rotation, scale, and opacity.

This gate is important because widget animation behavior is system-rendered and physical evidence is authoritative.

### Gate 3 — optional live app renderer (not implemented)

Add date-driven continuous motion to an approved app destination without changing the iPhone Home or Watch Terminal deep-link contracts.

### Gate 4 — hardening and deployment (complete for widget scope)

- Unit-test deterministic geometry and phase generation.
- Preserve stale/fail-closed telemetry tests.
- Preserve the exactly-30%-noncritical Codex test.
- Snapshot live, stale, placeholder, full-color, accented, reduced-motion, and Always-On states for both layouts.
- Profile CPU/GPU and memory on the physical iPhone and Watch.
- Build and audit all four products; verify widgets remain free of SwiftTerm/NIO/SSH.
- Archive and deploy only after explicit approval, using the exact audited iPhone IPA and archived Watch product.

## Acceptance criteria

1. No raster cathedral image is used in production artwork.
2. The `JARVIS` wordmark is the only visible text.
3. The artwork dominates both widget footprints and stays ordered at Watch size.
4. Widget motion occurs only on genuine WidgetKit entry changes and is never advertised as continuous.
5. The foreground app version, if approved, animates smoothly while active.
6. Watch Always On is static, legible, accent-aware, and not intentionally dimmed by JARVIS; system luminance treatment is accepted.
7. Reduce Motion removes rotation, travel, and pulsing.
8. Stale or unavailable telemetry cannot illuminate activity.
9. Existing platform-specific deep links remain unchanged.
10. No hardware control, daemon mutation, terminal input, or persistent pane restart is involved.

## Build 47 implementation record

Production implementation:

- `WidgetShared/NeuralCoreArtwork.swift` — shared procedural Cathedral, neural impulses, reactor waves, accent/AOD/Reduce Motion handling, stale-state fracture, and accessibility.
- `JARVISKit/Sources/JARVISKit/NeuralCoreMotion.swift` — deterministic timeline-entry phase and 1.8-second transition duration.
- `JARVISWidget/NeuralCoreWidget.swift` — iPhone medium phase input, near-black background, and Home deep link.
- `JARVISWatchWidget/NeuralCoreWidget.swift` — Watch rectangular phase input, transparent background, and Terminal deep link.

Verification completed:

- 26 `jarvisd` tests.
- 9 `terminald` tests.
- 48 JARVISKit tests with 3 expected live-test skips.
- 19 iPhone host tests.
- Warning-free iOS and watchOS simulator builds.
- Warning-free signed archive and export.
- All four products report `0.3.0 (47)`, team `5GB5BU49Q8`, valid signatures, and the required bundle hierarchy.
- Watch host and widget remain free of SwiftTerm, NIO, and SSH linkage.

Artifacts:

- Archive: `/tmp/JARVIS-build47-monochrome-cathedral.xcarchive`
- IPA: `/tmp/JARVIS-build47-monochrome-cathedral-export/JARVIS.ipa`
- IPA SHA-256: `2602cc2b4955002c77b84823fcbcf9461690534dd591fd3759fbbb9cfb165ebd`
- Archive log: `/tmp/JARVIS-build47-archive.log`
- Export log: `/tmp/JARVIS-build47-export.log`
- iPhone install log: `/tmp/JARVIS-build47-iphone-install.log`
- Watch install log: `/tmp/JARVIS-build47-watch-install.log`

Deployment:

- Exact exported IPA installed with explicit `ideviceinstaller -w upgrade` on Dylan's allowlisted iPhone only.
- Exact archived `JARVISWatch.app` installed through CoreDevice on Dylan's allowlisted Apple Watch only.
- Both device inventories report `0.3.0 (47)`.
- Both host apps launched and both widget extension processes remained active after installation.
- No plug, purifier, daemon, scheduler, service, terminal-input, or persistent-pane mutation occurred.

## Physical acceptance update — builds 49–52

- The allowlisted physical iPhone accepted the 30 FPS Cathedral presentation and
  the authored outer widget frame is absent.
- The allowlisted physical Watch accepted the Cathedral presentation, build-51
  terminal wake recovery, and build-52 removal of the authored outer Neural Core
  frame. Internal procedural geometry remains unchanged.
- WidgetKit and Always-On timing remain system-controlled; no unsupported
  keep-awake or process-driven widget API was introduced.

Remaining broad accessibility and system-throttling checks are release-matrix
items rather than blockers for the accepted frame-removal correction.

<!-- Folded from `docs/siri-conversational-pi-terminal-plan-2026-08-23.md` -->

# Siri conversational prompt-to-Pi plan

**Date:** 2026-08-23 EDT

**Proposed release:** `0.3.0 (39)`
**Status:** Historical Build 39–44 implementation record. The prompt intent remains current; Build 92 removed the host plug intents referenced by the original test plan, and Build 126 was the installed checkpoint when this history was consolidated.

> Historical note: references below to “two existing plug shortcuts” or plug-phrase regression tests describe the pre-Build-92 host surface. Current host metadata exposes only the bare two-turn “Hey JARVIS” prompt shortcut.

## Implementation result

Build 39 implements the approved architecture in host-only App Intents on both
iPhone and Watch. `SendPromptToJARVISIntent` advertises exactly bare
**“Hey JARVIS”**, uses the prompted required `String`, reads only target-local
Keychain configuration, normalizes one logical line with a 3,500-byte UTF-8
cap, performs an authenticated pinned frame preflight, and then attempts exactly
one `appendReturn=true` POST. The foreground Watch terminal now consumes the
same extracted `WatchTerminalClient`. Build 40 keeps the network request
unchanged but makes terminald load the normalized prompt bytes and trailing
`0x0d` into one exact tmux paste buffer, eliminating the separate `send-keys`
step so Pi begins the prompt immediately.

Xcode accepted and trained the exact bare phrase in both host metadata products.
Unit tests cover normalization, controls, bounds, preflight, one-buffer atomic
prompt/Return delivery, ambiguous POST non-retry, and dialog outcome mapping. A
disposable TLS server and isolated tmux socket verified one prompt plus one Return with duplicate
request suppression; no automated test writes to the production Pi pane.
Physical iPhone/Watch Siri routing, lock-state, and cellular acceptance remain
pending because the devices were intentionally disconnected during implementation.

## 1. Objective

After Siri is already listening, support this public-API flow on iPhone and Apple Watch:

1. Owner: **“Hey JARVIS.”**
2. Siri: **“What would you like me to send to JARVIS?”**
3. Owner speaks an arbitrary prompt.
4. JARVIS inserts that resolved text into the existing `jarvis-ios` Pi/tmux editor and emits one Return.
5. Siri: **“Sent to JARVIS.”**

This is a parameter-prompting App Intent, not a custom wake word. The system wake remains “Hey Siri” or a hardware gesture; JARVIS never runs an always-listening microphone.

## 2. Feasibility and platform boundary

The existing public App Intents stack already supports the required conversation:

- An `AppShortcut` can advertise the literal phrase `"Hey \(.applicationName)"`.
- A missing `String` `@Parameter` can use `requestValueDialog` so Siri asks for the prompt.
- `perform()` can submit the resolved text and return a spoken `IntentDialog` acknowledgement.
- iPhone can keep `openAppWhenRun=false` and return a success-only
  `OpenURLIntent` on current OS releases; Watch can retain its host foreground
  behavior and switch pages only after confirmed delivery.

The exact bare phrase must still pass Xcode metadata validation and physical Siri routing. If Siri reserves or misroutes it, retain **“Hey JARVIS”** as the acceptance target and test **“Ask JARVIS”** only as a diagnostic fallback—not as a silent product substitution.

## 3. MVP behavior decisions

- **Two-turn requested flow:** no extra Yes/No confirmation in the MVP. The deliberate answer to Siri’s prompt authorizes submission.
- **One logical terminal line:** normalize CR/LF and disallowed control characters so speech cannot create multiple terminal submissions.
- **Atomic execution:** send UTF-8 prompt bytes plus one server-appended Return in one authenticated request.
- **Current cursor:** input goes to the same Pi editor/cursor used by iPhone and Watch terminal controls.
- **No queue:** if the bridge is unavailable, nothing is saved for later.
- **No replay:** do not fail over or retry after a POST begins. An ambiguous timeout returns “Send was not confirmed; check JARVIS.”
- **No Pi-answer speech in MVP:** Siri acknowledges delivery only. Capturing and speaking the asynchronous Pi response is a separate feature.
- **Idle-editor precondition:** MVP acceptance assumes no other client has unsent text at the Pi cursor. The current tmux frame does not expose a reliable semantic “editor empty” flag; silently clearing or replacing another client’s draft is prohibited.

## 4. Architecture

```text
Siri on iPhone or Watch
        │
        ▼
SendPromptToJARVISIntent
  @Parameter prompt: String
        │
        ├─ target-local terminal configuration
        │  (endpoint + pinned certificate + Keychain token)
        │
        ▼
Shared pinned TerminalBridgeClient
  1. authenticated frame preflight
  2. exactly one POST /v1/terminal/input
        │
        ▼
jarvis-terminald :8792
  bounded bytes + request-ID dedupe
        │
        ▼
jarvis-mobile / jarvis-ios tmux pane
        │
        ▼
Pi fixed editor receives prompt + Return
```

`jarvisd` remains the hardware/status/service control plane and receives no terminal prompt route. `jarvis-terminald` remains unable to call plugs, purifier, services, or scheduler logic.

## 5. Implementation workstreams

### A. Add the conversational App Intent

Implemented as a host-only intent beside the existing plug intents:

```swift
struct SendPromptToJARVISIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to JARVIS"
    static let description = IntentDescription("Send a spoken prompt to the active JARVIS Pi session.")
    #if os(watchOS)
    static var openAppWhenRun: Bool { true }
    #else
    static var openAppWhenRun: Bool { false }
    #endif

    @Parameter(
        title: "Prompt",
        requestValueDialog: IntentDialog("What would you like me to send to JARVIS?")
    )
    var prompt: String
}
```

Add a third `AppShortcut`:

```swift
AppShortcut(
    intent: SendPromptToJARVISIntent(),
    phrases: ["Hey \(.applicationName)"],
    shortTitle: "Talk to JARVIS",
    systemImageName: "waveform"
)
```

Bump `JARVISSiriParameterRegistrar`’s phrase schema version so upgrade-time shortcut metadata republishes even when the plug catalogue is unchanged.

### B. Extract a shared pinned terminal bridge client

Implemented by moving the reusable HTTPS behavior out of the private Watch view implementation into a JARVISKit client that:

- accepts a `WatchTerminalConfiguration` but never persists or logs it;
- preserves SHA-256 leaf-certificate pinning;
- uses bearer authentication;
- probes saved endpoint, LAN, MagicDNS, and current Tailscale candidates with an authenticated frame GET;
- selects one confirmed route before enabling submission;
- performs one `WatchTerminalInput` POST with a fresh request ID;
- has bounded preflight and submit timeouts;
- never retries an input POST on another route;
- exposes no SwiftTerm, SwiftNIO, or SSH dependency.

The foreground Watch terminal should consume this same client after extraction so Siri and UI networking cannot drift.

### C. Read target-local credentials safely

Because free provisioning prevents a shared Keychain/App Group:

- **iPhone intent:** read the existing iPhone terminal provisioning token, endpoint, and fingerprint from `WatchTerminalProvisioningSettings` storage.
- **Watch intent:** read the existing Watch-local token, endpoint, and fingerprint from the Watch terminal settings storage.
- Keep `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`.
- If Keychain is unavailable while locked, Siri says **“Unlock this device and try again.”** Nothing is sent.
- Do not copy credentials into App Intent parameters, defaults, widgets, logs, or WatchConnectivity messages.

### D. Normalize and bound the spoken prompt

Before network access:

1. Trim surrounding whitespace.
2. Replace CR/LF runs with a single space.
3. Reject NUL, escape, and remaining C0/C1 control characters.
4. Preserve ordinary Unicode and punctuation.
5. Reject empty text.
6. Cap normalized UTF-8 to at most 3,500 bytes, below the bridge’s 4,096-byte limit.

Submit:

```swift
WatchTerminalInput(data: Data(normalized.utf8), appendReturn: true)
```

This uses terminald’s byte-safe tmux paste path and appends exactly one Return without shell interpolation.

### E. Define Siri dialogs and failures

| Condition | Siri response | Terminal effect |
|---|---|---|
| Success | “Sent to JARVIS.” | Prompt + one Return |
| Empty prompt | “I didn’t hear a prompt.” | None |
| Too long | “That prompt is too long for JARVIS.” | None |
| Not provisioned | “Open JARVIS Settings and set up the terminal first.” | None |
| Device locked / Keychain denied | “Unlock this device and try again.” | None |
| No authenticated frame route | “The JARVIS terminal is offline.” | None |
| Certificate mismatch | “The JARVIS terminal identity could not be verified.” | None |
| POST rejected | “JARVIS did not accept the prompt.” | None or server-confirmed rejection |
| POST timeout after transmission begins | “Send was not confirmed; check JARVIS.” | Never retried automatically |

Do not include the prompt, token, endpoint, certificate details, or local paths in dialogs or logs.

### F. Keep target and control-plane isolation

- Compile the new intent only into iPhone and Watch host apps, not either widget.
- Continue verifying that Watch and Watch widget binaries have no SwiftTerm/NIO/SSH linkage.
- Do not add a prompt endpoint to `jarvisd`.
- Do not use WatchConnectivity as a delayed queue.
- Do not add background microphone capture, Speech framework recording, or a custom wake-word engine.

## 6. Test plan

### Unit and protocol tests

- Phrase metadata contains exactly the new parameterless **“Hey JARVIS”** shortcut plus the two existing plug shortcuts.
- Upgrade schema republishes shortcut parameters once.
- Prompt normalization preserves Unicode and punctuation.
- Newline/control-character input cannot create a second command.
- Empty and oversized prompts fail before network access.
- Successful payload has prompt bytes and `appendReturn=true`.
- Request IDs are unique and duplicate server receipt produces only one tmux write.
- Disconnected, unprovisioned, locked-Keychain, certificate-mismatch, and timeout paths never queue or replay.
- No test writes to the production tmux pane; use a disposable terminald/tmux fixture.

### Build and static checks

- iOS and watchOS Debug/Release builds are warning-free.
- App Intents metadata extraction accepts the bare phrase.
- Release binaries contain the new intent metadata.
- Watch dependency isolation remains clean.
- Existing plug-only Siri intent behavior remains unchanged.
- Repository smoke remains `WARN=0 FAIL=0`.

### Physical iPhone acceptance

1. With iPhone unlocked and JARVIS terminal provisioned, activate Siri.
2. Say **“Hey JARVIS.”**
3. Confirm Siri asks the configured prompt question.
4. Speak a unique harmless fixture prompt against a disposable tmux session.
5. Confirm exactly one normalized prompt and one Return arrive.
6. Repeat over LAN and cellular/Tailscale.
7. Verify offline, certificate-mismatch fixture, locked-device, and force-quit behavior produce no delayed input.

### Physical Watch acceptance

Repeat the same flow with Siri initiated on the Watch:

- foreground and wrist-raised;
- iPhone nearby and then unavailable where practical;
- Wi-Fi/LAN and supported off-LAN path;
- no duplicate send if Siri dismisses or the wrist drops;
- simultaneous iPhone terminal attachment still targets one tmux pane.

### Regression acceptance

- “Hey JARVIS, turn on/off …” continues routing only to plug intents.
- Bare “Hey JARVIS” routes only to the prompt intent.
- No contact-directed “Tell JARVIS” phrasing returns.
- Watch manual input remains explicit: Input stages without Return, `/` and DEL
  emit exact bytes, and only the Return-symbol button emits `0x0d`.
- Build 42 consumed one terminal-page request after `.sent`, but physical iPhone
  testing showed its unconditional host foreground remained beneath Siri's
  result sheet until manual dismissal.
- Build 43 keeps iPhone background-capable during delivery and returns a
  success-only `OpenURLIntent` for `jarvis://terminal` on iOS 18.2 or newer.
  Watch retains its passing foreground behavior and still selects Terminal only
  after `.sent`. Widget metadata still excludes the prompt intent.
- No plug, purifier, service, scheduler, or production terminal mutation occurs during automated tests.

## 7. Rollout sequence

1. **Done:** implement as build 39 behind the existing Personal Team configuration.
2. **Done:** validate with disposable HTTPS/tmux fixtures and simulator Siri metadata.
3. **Done:** archive/export and audit the exact signed build-39 artifacts.
4. Install on the allowlisted iPhone and Watch only after the owner reconnects them.
5. Perform owner-driven physical Siri routing with a harmless disposable prompt.
6. Keep build 38 available for rollback.
7. Do not restart the persistent Pi pane unless separately approved.

## 8. Explicit non-goals

- No independently always-listening “Hey JARVIS” wake word.
- No replacement for Siri’s system speech recognition.
- No automatic reading of Pi’s eventual response.
- No prompt history, cloud sync, widget action, or offline queue.
- No terminal access through `jarvisd`.
- No automatic clearing or replacement of another client’s staged editor text.
