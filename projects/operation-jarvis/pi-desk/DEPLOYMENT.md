# Viewer tmux memory-leak backport — 2026-10-08, active and verified

Owner approved the investigated fix and a local viewer-only restart. Built pinned
**tmux 3.7c** with the complete upstream reference-counting fix
[`1459c90`](https://github.com/tmux/tmux/commit/1459c90a7fa6a70afd1e8438fa9985141e4002be).
The release's `cmd-display-panes.c` receives the corresponding caller fix because
upstream's newer `window-panes.c` does not exist in 3.7c. No development-version
features, display guards, styling, input behavior or animation cadence changed.

The private build is `~/.local/share/pi-desk/bin/tmux`. A small runtime selector
routes only Pi Desk workspace/attachment/navigation commands to it. **Homebrew
and hosted-agent tmux remain unchanged**, and agent attachments still use
`/opt/homebrew/bin/tmux -L jarvis-mobile` explicitly. Other platforms without a
private build retain their own tmux; an invalid private build fails closed.

**212 source tests, 212 staged-runtime tests and 5 VS Code bridge tests passed.**
The stage used the actual installed backend/restart files, preserving their known
unrelated drift. Across **12,000 guarded updates**, patched memory plateaued at
**8.58 MiB attached / 7.16 MiB detached**; post-warm-up maximum growth was only
**64 KiB / no positive growth**, rather than the original ~5.6 KiB per update.
This is bounded stress-test verification, not a day-long live measurement.

At **15:36 EDT**, atomically installed only `core.py`, `desktop.py`, `navigate.py`,
`install.py`, the runtime selector, private binary and its license/provenance/patch,
plus their manifest entries. All unrelated installed hashes and manifest entries,
including backend/restart drift, launcher, configuration and system tmux hash were
preserved. The full installer was **not** run against the real installation.

At **15:38 EDT**, one PID/parent/socket/client-checked normal detach released the
old display viewer. Its server, CLI wrapper and attach client all exited, removing
a **3334 MiB physical footprint**. The existing VS Code terminal returned to its
original shell; **all ten hosted pane/process identities and the hosted server PID
were unchanged**. No agent signals, remote changes, GUI focus/Space switches or
service/model restarts occurred.

**Activation verified at 15:42 EDT:** the owner reopened Pi Desk in the original
`/dev/ttys002` terminal. New server **95382** runs the private verified binary.
Four bounded live samples over 30 seconds stayed at **9.48–9.64 MiB**, without
monotonic growth, and no warning row was present. All ten hosted pane/process
identities and their server PID still matched the baseline. This is short live
verification backed by the longer accelerated stress test, not a day-long soak.
No automatic terminal input injection or new window was used. Visual acceptance
was not independently observed; current styling/configuration remain unchanged.

Backup/results:
`~/.local/state/pi-desk/backups/tmux-refcount-20261008T193622575729Z/`
contains prior scoped files/manifest, original hashes and deployment/release/activation results.
One-shot helpers/build/test logs are in `/tmp/pi-desk-tmux-refcount-20261008/`;
**never replay the completed deployment or detach helper**. See
[`vendor/README.md`](vendor/README.md) for pinned rebuild/rollback instructions and
[`docs/MEMORY_AUDIT_2026-10-08.md`](docs/MEMORY_AUDIT_2026-10-08.md) for diagnosis.

# Token rollout reversal — 2026-10-06, restored and verified

Owner requested undo. Source and installed `status_stream.py` exactly match the
retained pre-rollout helper; original tests restored and **202 source tests passed**.
The first attempt stopped **before any helper write, manifest change or feed signal**
on an outdated backend baseline. That stop remains retained. Fresh owner approval
and the independently verified newer picture-frame-health baseline allowed a new
scoped attempt, not replay of the failed helper.

Only installed `status_stream.py` and its manifest entry were restored; all other
files/entries, including existing `backend.py`/`restart_status.py` drift, stayed
unchanged. One PID/start/parent-checked SIGTERM ended authenticated child 60359;
unchanged CLI supervisor 78848 started restored child 89601. **Ten fresh sanitized
sessions** and cleared warning verified at **16:39 EDT**. Existing clients, pane/
process identities, agents, all 18 service records, backend/config/authentication,
credentials, Pi/Minecraft identities and three-second cadence were preserved. No
full installer, remote update, daemon/model restart or GUI focus switch occurred.

Original failure/source backups: `~/Library/Application Support/JARVIS/api-auth-rollout/20261006T194627Z-revert/`.
Success/backup of authenticated helper: `~/Library/Application Support/JARVIS/api-auth-rollout/20261006T203825Z-revert-feed-continuation/`.
Authoritative completion: `result.json`, status `pre-rollout-helper-restored-feed-verified`.
**Never replay completed/failed helpers.** Trusted-network mode remains; a future
token-mode request needs fresh approval and consumer verification.

# Selection input-focus follow-up — 2026-10-04

Reproduced the reported input trap in isolated terminals: a rapid transcript click
can enter word-selection copy mode, whose search/navigation bindings then swallow
ordinary typing. Mouse selections now use a dedicated, one-shot client key table.
Typing cancels the snapshot and sends the original key directly to the app, keeping
Unicode, editing keys and the first character in order even in one fast input burst.
Desktop navigation/prefix/restart shortcuts are instead re-dispatched through the
root table. Mouse-up, drag, repeated Cmd+C and word/line selection re-arm the table;
Escape/Enter still dismiss without submitting. Keyboard-entered copy mode keeps
its stock navigation. No VS Code extension or global editor-focus change is needed.

Session-header/divider clicks now explicitly select the mouse-targeted pane after
dismissing selection; the earlier resize action did not focus that pane. Divider
drag resizing is unchanged. Mouse handlers retain the original coordinates rather
than replaying synthetic mouse keys.

**202 Python tests and 5 bridge tests passed**. New regressions cover click/typing,
rapid multi-character input, copy-mode-reserved letters, Unicode, editing keys,
root shortcut replay, stock keyboard copy mode, header-to-prompt focus and two
nested isolated tmux servers matching the live agent's disabled mouse reporting.
Installed only `config/tmux.conf` and its manifest hash locally, then reloaded the
display configuration. Clients, viewer panes and all hosted-agent identities were
unchanged. No agent restart, GUI focus switch, remote change or mobile-config edit.
Sir confirmed the improved input behaviour in the actual VS Code session.

Backup:
`~/.local/state/pi-desk/backups/selection-focus-20261005T030609696595Z/`
contains the preceding config/manifest and before/after identity snapshots.

# Browser-style terminal selection — 2026-10-04

Installed and activated **locally on mac-mini-64 only**. Ordinary drag enters the
outer viewer's copy mode even when the nested terminal requests mouse input.
Release stops extending the selection without copying or cancelling. Cmd+C copies
without clearing the highlight; a pane, divider or header click dismisses it.
Double/triple click selects a word/line; Escape and Enter dismiss without copying.
The mouse selection hides tmux's position overlay. Only the selected pane's display
is held; the attachment and hosted agent continue running. Layout/font changes can
still reshape terminal selections. This is not a DOM transcript viewer.

An optional offline-built VS Code extension, `jarvis-local.pi-desk-selection@0.1.0`,
provides Cmd+C (Ctrl+Shift+C elsewhere), scoped to an active terminal titled exactly
`pi-desk` with no native terminal selection. It rechecks the title at invocation;
normal terminals/editors and native Option-drag copying are untouched. The bridge
reads only terminal names, not output or clipboard contents. It sends a dedicated
User90 key, consumed by the display server and a strict no-op without a selection.
macOS uses `/usr/bin/pbcopy`. A remote Mac shell copies to that remote Mac's clipboard;
remote-client clipboard copying is not implemented. The shared installer ships the
optional bridge without automatically installing it or editing editor settings.

**196 full Python tests and 5 bridge tests passed**, followed by all **8 focused
mouse/packaging tests against the installed runtime**. Tests use isolated PTYs and
unique tmux servers, with a fake clipboard sink; they cover app-requested mouse
input, sticky selection, frozen display with ongoing app output, repeated copy,
no-op copy, both key tables, dismissal/focus, word/line selection, title changes,
stale-context safety and native-copy scope. No private clipboard was read.

Updated the installed `config/tmux.conf`, installer and optional bridge files plus
only their manifest entries. The JARVIS workspace adds `piDesk.copySelection` to
`terminal.integrated.commandsToSkipShell`, supplementing stock defaults. Display
configuration was reloaded in place; Code's extension-host log confirms dynamic
activation. **Attached clients, viewer panes and all ten hosted-agent identities
were unchanged.** No agent/viewer restart, focus switch, remote change or mobile
configuration change was performed. Sir confirmed the selection works in the
actual VS Code window; no reload was required.

Rollback backup:
`~/.local/state/pi-desk/backups/browser-selection-20261005T001948578407Z/`
includes prior runtime files/manifest, workspace settings and identity snapshots.
`ROLLBACK.md` and `rollback-selection.tmux` restore just the overridden selection
keys; reloading the old config alone would not remove the new bindings.

# Compact quota text and hidden unavailable 5h — 2026-10-04

Quota labels no longer include the trailing `left` in either header variant or
click details. Percentages still mean remaining quota; colours and spacing resets
are unchanged. The 5h section now appears only when its normalized percentage is
available and it is not explicitly unenforced. Missing/invalid 5h values omit the
entire section and separator, with no `5h:n/a` or unavailable click-detail line.
Real 0% remains visible; hiding unavailable data does not assert that no limit
exists. The weekly-only header is **`Codex W:68%`**.

**188 full source tests passed locally.** Regressions cover exact label text,
missing 5h data for every enforcement state, valid zero/fractional percentages,
responsive widths, independent percentage colours, neutral nonclickable dividers,
literal `%` rendering and real terminal clicks. Each machine passed **36 focused
quota tests before installation and 36 against its installed runtime**; the one
source-only native-app parity test was skipped in each isolated run and passed
locally.

Installed only `codex_quota.py` and its manifest entry on mac-mini-64, mac-mini-16
and Raspberry Pi. The renderer, all other installed/config hashes and manifest
entries, attached clients and pane identities were preserved, including primary
Mac hosted panes. The Pi display-service PID was unchanged. No viewers, services
or agents restarted; live visual acceptance awaits reopened viewers.

**Activation:** detach all Pi Desk viewers on each machine with Ctrl+A then d,
then reopen `pi-desk`. Agents and conversations stay running; do not use F10.

Rollback backups:
- mac-mini-64: `~/.local/state/pi-desk/backups/quota-compact-labels-20261004T172213637259Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/quota-compact-labels-20261004T172225613761Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/quota-compact-labels-20261004T172242906839Z/`

# Codex percentage-only JARVIS palette — 2026-10-04

Only actual quota percentages (digits and `%`) are coloured. Weekly and 5h values
are evaluated independently using the JARVIS iPhone quota card's policy: dark
accent **`#D183E8`** at 30% or more remaining, critical **`#FF3847`** below 30%
(`JarvisPalette.critical` rounded to RGB8). No amber band or lowest-window colour
spillover. Labels, punctuation, `left`, `n/a`, stale and unavailable text are
neutral **`#8A8A8A`**. The entire quota block remains clickable; section dividers
remain neutral and nonclickable.

An explicitly not-enforced 5h window is omitted from both header choices and the
click-detail message, including its separator, even if old percentage data is
present. Missing data alone is not proof of no limit; unknown windows retain grey
`n/a`. Remaining semantics, freshness, true-zero rounding, reset countdowns,
responsive widths, tab priority and hint shortening are unchanged.

**186 full source tests passed locally**, including source parity with the native
app, per-character foreground/click ranges, hidden 5h data, narrow widths and real
PTY emission of the exact grey/purple/red RGB values. On each machine, **34 quota
tests passed before installation and 34 passed against its installed runtime**;
one source-only sibling-app parity test was intentionally skipped in each isolated
run and passed in the full local source suite.

Installed only `codex_quota.py`, `desktop.py` and their two manifest entries on
mac-mini-64, mac-mini-16 and Raspberry Pi. All unrelated installed/config hashes,
manifest entries, attached display clients and pane identities were preserved,
including hosted panes on the primary Mac; the Pi display-service PID was
unchanged. No viewers, services or agents restarted. Live visual acceptance of
this palette is pending until viewers are reopened.

**Activation:** detach all Pi Desk viewers on each machine with Ctrl+A then d,
then reopen `pi-desk`. Agents and conversations stay running; do not use F10.

Rollback backups:
- mac-mini-64: `~/.local/state/pi-desk/backups/quota-percent-palette-20261004T171240049711Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/quota-percent-palette-20261004T171251777728Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/quota-percent-palette-20261004T171306249697Z/`

# Header section dividers — 2026-10-04, 12:49 EDT

Matching grey **`#8a8a8a`** / heavy **`┃`** dividers now separate the title
from session tabs, Codex quota from Restart, and Restart from Switch. Right-hand
dividers appear only between visible sections, with explicit neutral styling and
no clickable quota range. Their widths participate in responsive hint selection;
quota and session tabs retain priority. The title divider is omitted when adding
it would hide a tab, including sliding-tab layouts. Legacy headers use the same
section renderer and bounded hint choices. No extra rows or pane-layout changes.

**183 full source tests passed locally**, including real terminal rendering,
quota clicks, exact width accounting, all narrow-width navigation cases, neutral
styles and no dangling separators. Each machine also passed **6,600 responsive
render cases before installation and 6,600 against its installed runtime**.

Installed only `desktop.py` and its manifest entry on mac-mini-64, mac-mini-16
and Raspberry Pi. All other installed/config hashes, manifest entries, attached
clients and pane identities were preserved, including hosted panes on the primary
Mac; the Pi display-service PID was unchanged. No viewers, services or agents
restarted. Sir confirmed the updated header looks good; other terminals were not
independently visually checked.

**Activation:** detach all Pi Desk viewers on each machine with Ctrl+A then d,
then reopen `pi-desk`. Agents and conversations stay running; do not use F10.

Rollback backups:
- mac-mini-64: `~/.local/state/pi-desk/backups/header-section-dividers-20261004T164910279401Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/header-section-dividers-20261004T164910690246Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/header-section-dividers-20261004T164923597232Z/`

# Header dividers match pane dividers — 2026-10-04, 11:21 EDT

Status-bar group separators now use exact pane-divider grey **`#8a8a8a`** and
heavy vertical **`┃`**, replacing the darker `colour238` / light `│` in both
legacy and responsive headers. Compact/full spacing, group boundaries, terminal
cell counts, clickable tabs, lifecycle colours/animation and pane styling are
unchanged. One-session and sliding-overflow headers still omit group separators.

**180 full source tests passed locally**, including a real single-pane PTY test
that verifies header-only heavy glyphs and exact grey RGB emission. Each of the
three installed runtimes passed **121 renderer checks** across compact/full
widths, all group sizes and all selected sessions.

Installed only `desktop.py` and its manifest entry on mac-mini-64, mac-mini-16 and
Raspberry Pi. Other installed/config hashes, attached display clients and pane
identities were preserved; the Pi display-service PID was unchanged. No viewers,
services or hosted agents restarted. Existing monitors retain their imported
renderer, so live visual acceptance remains pending until viewers are reopened.

**Activation:** detach all Pi Desk viewers on each machine with Ctrl+A then d,
then reopen `pi-desk`. Agents and conversations remain running; F10 is not needed.

Rollback backups:
- mac-mini-64: `~/.local/state/pi-desk/backups/matching-header-dividers-20261004T152110946107Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/matching-header-dividers-20261004T152111413585Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/matching-header-dividers-20261004T152113198383Z/`

# Pi-speed braille and neutral-grey compaction — 2026-10-04, 09:20 EDT

Running and compacting now use identical forward braille animation every **80 ms**
(0.8-second cycle), matching the installed Pi TUI loader's default interval.
Frame deadlines remain independent of 500 ms metadata/health refreshes; the host
feed remains three seconds. Idle/reduced-motion behaviour and changed-header-only
batching are preserved. Compacting is now exact neutral grey **`#8A8A8A`**, matching
Pi Desk's existing neutral grey; Running remains green and Offline stays static `×`.
Pi's spinner colour is theme-dependent, so this is a neutral-grey choice rather
than a claim that every Pi theme uses that RGB. Other colours, navigation styling,
layouts, pane badges, click targets, warnings and quota behaviour are unchanged.

**179 full source tests passed**, including exact app palette parity, forward
spinner cycles, ASCII/reduced motion, independent snapshot/frame deadlines,
responsive widths and real PTY grey/braille emission. **All three machines passed
48 focused pre-install and 48 installed-runtime tests each.** The cross-project
source-only palette assertion is covered locally, not run from isolated/installed
Pi Desk directories that do not contain the sibling app project. Six shared app
terminal/lifecycle colour tests passed; its verification shell syntax was checked.

Installed only `desktop.py` and its manifest entry on mac-mini-64, mac-mini-16 and
Raspberry Pi. All other installed source/config hashes, existing manifest
mismatches, clients, pane identities and Pi display-service PID were preserved.
No viewers, hosted agents or services restarted. Rollback and verification
artifacts are retained; temporary staging/build caches were removed.

**Native app follow-up:** `PiSessionLifecycle.statusColor`, its colour tests and
the verification assertion mirror grey. Owner-approved build 245 was subsequently
installed once and independently version/launch/process verified on both iPhone
and Watch on 2026-10-04 at 09:43 EDT. Exact signed build 244 is retained for rollback;
no backend/Pi restart. See [native app deployment](../jarvis-app/docs/operations.md#grey-compaction-palette--build-245).

**Activation:** detach all Pi Desk viewers on each machine with Ctrl+A then d,
then reopen `pi-desk`. F10 restarts agents, not the UI. Live visual acceptance
remains pending until reopened.

Rollback backups:
- mac-mini-64: `~/.local/state/pi-desk/backups/pi-loader-cadence-20261004T131843969441Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/pi-loader-cadence-20261004T131844346221Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/pi-loader-cadence-20261004T131845583039Z/`

# Pi-style braille and distinct lifecycle icons — 2026-10-04, 00:52 EDT

Running now uses the ten-frame braille spinner `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`. Compacting
uses the same frames backwards at half the cadence. Existing 250 ms/500 ms frame
intervals, cached snapshots and changed-header-only batching are preserved.
Static states now use idle `●`, new `○`, offline `×`, and unknown `?`; missing or
unrecognised states are explicitly unknown. ASCII mode uses `|/-\\`, `.`, `o`,
`x`, `?`; reduced-motion mode keeps working states as steady dots and retains
static-state distinctions.

Lifecycle colours, flat backgrounds, group/focus digits, pane-title badges,
click targets, responsive widths, quota priority and warnings are unchanged.
**No jarvis-app source, build or device deployment was needed.**

**178 full source tests passed locally. All three machines passed 46 focused
pre-install tests and 46 installed-runtime tests each.** Coverage includes full
spinner cycles/wrap-around, reverse half-cadence, every static/fallback state,
ASCII/reduced motion, native single-cell widths, real tmux/PTY icon emission and
orange RGB, responsive layouts and mouse ranges. Menlo/CoreText and the Pi's
configured Foot/Fontconfig fallback glyph coverage were checked. Live visual
acceptance remains pending after reopening viewers.

Installed only `desktop.py` and its manifest entry on mac-mini-64, mac-mini-16
and Raspberry Pi. Existing manifest mismatches, configs, attached clients,
hosted/display pane identities and the Pi display-service PID were preserved.
No viewers, agents or services restarted. Rollback files and verification logs
are retained; temporary staging was removed.

**Activation:** detach all Pi Desk viewers on each machine with Ctrl+A then d,
then reopen `pi-desk`. Existing elected monitors keep their previously imported
renderer until reopened. F10 restarts agents, not the UI.

Rollback backups:
- mac-mini-64: `~/.local/state/pi-desk/backups/braille-state-icons-20261004T044423179719Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/braille-state-icons-20261004T044423428683Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/braille-state-icons-20261004T044424538414Z/`

# Flat number-only header — 2026-10-04, 00:16 EDT

Removed the header's purple tab backgrounds and contrasting indicator cut-outs.
All tabs, lifecycle glyphs, gaps and controls now share dark `#1e1e1e`. Visible
session-group numbers use soft purple `#B28CBD`; the focused number uses accent
purple `#D183E8`, bold and underlined. Focus decoration is scoped to digits only,
with explicit bold/underline resets before spaces, indicators and neighbouring
controls. No rows, cells, click targets or responsive-layout policy changed.

The pane's white-on-`#8D4CA3` **Session X** title badge and neutral heavy dividers
are unchanged. Lifecycle colours, spinner directions/cadence, snapshot batching,
quota priority and warning-row behaviour are unchanged. Both number purples clear
VS Code's default 4.5:1 contrast threshold. This is navigation chrome only:
**no jarvis-app source, build or phone/Watch deployment was needed**.

**175 source tests passed locally**, with **39 focused pre-install tests on each
remote machine** and **35 focused installed-runtime tests on all three machines**.
Coverage includes all session/group/width combinations, tiny/sliding tabs, real
PTY purple foreground/underline and orange/spinner emission, unchanged pane badges,
real mouse clicks and quota ranges, uniform header backgrounds, contrast, and
animation-only batching. Terminal/user visual acceptance remains pending after
reopening the live viewer.

Installed only `desktop.py` and its manifest entry on mac-mini-64, mac-mini-16
and Raspberry Pi. Pre-existing unrelated manifest mismatches were left intact.
Local **9 display/10 hosted-pane identities** and attached clients were preserved;
remote machines had no display panes/clients. The Pi display-service PID and
protected config hashes were preserved. No viewers, services or agents restarted.
Temporary staging was removed after preserving test/deployment evidence in the
private rollback backups below.

**Activation:** detach all Pi Desk viewers on each machine with Ctrl+A then d,
then reopen `pi-desk` so the elected monitor imports the flat renderer. Existing
monitors retain the boxed header until reopened. F10 restarts agents, not the UI.

Rollback backups:
- mac-mini-64: `~/.local/state/pi-desk/backups/flat-session-header-20261004T041424242964Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/flat-session-header-20261004T041424604895Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/flat-session-header-20261004T041425591787Z/`

# Session groups, activity motion and orange compaction — 2026-10-03, 23:11 EDT

The visible group now has a continuous muted-purple `#4B2D59` band, with the
focused number in the same bold white-on-`#8D4CA3` badge as its pane title.
One-/two-/three-session groups, session 10, narrow sliding tabs, click targets,
quota priority and warning-row behaviour are preserved. Each lifecycle glyph
has a neutral dark cell to keep its colour readable within the navigation badge.

Running uses a bright single-cell spinner at 250 ms/frame; Compacting rotates
backwards at 500 ms/frame in exact vivid orange **`#FF7A00`**, replacing blue.
Other states keep steady dots. `PI_DESK_SPINNER=ascii` provides an ASCII fallback;
`PI_DESK_SPINNER=off` disables motion. Settings apply to the elected machine-wide
monitor. Intermediate animation frames reuse cached metadata/status, leaving
500 ms bookkeeping and the three-second host stream unchanged. Only changed
header rows are written, batched across viewers; no warning/row-count writes on
animation-only ticks and no animation wakeups when all sessions are non-busy.

The app's shared `PiSessionLifecycle.statusColor`, its tests and verification
assertion mirror the exact orange across Home and phone/Watch terminal indicators.
Native app motion, other colours, networking and accessibility are unchanged.
An offscreen palette preview was reviewed, but physical visual acceptance remains
pending. The app source is verified, **not installed on physical devices**; signed
phone/Watch deployment remains a separate owner approval.

**173 tests passed on each Mac and on the Pi** (two platform-specific skips on
Linux). A pre-existing test's one-cell layout-rounding assumption was made
portable after isolated tmux 3.5a demonstrated widths `60/60/62` for its native
184-column even-horizontal layout; newer tmux spreads remainder cells instead.
No layout algorithm was changed. **34 focused installed-runtime tests passed on
each machine**, including real PTY orange/spinner/badge emission, all focus/group
combinations, ASCII/static fallbacks, stale status and cached animation snapshots.
The app package completed **290 tests, three expected skips, zero failures** in
an isolated checkout. No physical-device install or full signed archive is claimed.

Installed `desktop.py` only on mac-mini-64. The two old remote installs were
advanced to the compatible current runtime plus `config/tmux.conf`; private
client config, launchers, services, foot/labwc adapters and unrelated files were
preserved. All source hashes verify against the deployed changes. Existing
manifest mismatches remain untouched: local `backend.py`/`restart_status.py`, and
Pi `config/foot.ini`. Local **10 display/10 hosted-pane identities** and attached
clients were preserved; remote machines had no display panes/clients to replace.
The Pi service PID and protected adapter/config hashes were preserved. No viewers,
services or hosted agents were restarted.

**Activation:** detach all Pi Desk viewers on a machine with Ctrl+A then d and
reopen `pi-desk` so its elected monitor imports the new renderer. Existing monitors
retain old code. The Pi display service was not restarted automatically; request
that separately if it owns the viewer. Do not use F10: that restarts agents, not
the renderer.

Rollback backups (private deployment/identity/hash evidence included):
- mac-mini-64: `~/.local/state/pi-desk/backups/session-indicators-20261004T030939521855Z/`
- mac-mini-16: `~/.local/state/pi-desk/backups/session-indicators-20261004T030939701711Z/`
- Raspberry Pi: `~/.local/state/pi-desk/backups/session-indicators-20261004T030940880961Z/`

# Codex quota header — 2026-10-03, 21:37 EDT

Added a clickable, account-wide **remaining quota** block to the existing top
row: `Codex W:68% · 5h:91% left` (example values). It shrinks to weekly-only when
needed, gives way to session navigation on tiny terminals, and never creates a
second row. Shortcut hints yield first. Purple/amber/red indicate the lowest
available enforced quota window, with critical red below 30% matching JARVIS.
Paused five-hour windows do not trigger low-quota colours; missing/stale values
are explicit, never fabricated as 0% or renewed by streaming an old sample.

`codex_quota.py` whitelists percentages, timestamps, enforcement and limit state
from jarvisd's existing quota cache. `status_stream.py` adds a backwards-compatible
`codexQuota` field beside the original numeric session keys. No credentials,
account details, provider errors or conversations are emitted, and no additional
provider requests/model probes are made. Quota uses its own 15-minute freshness
limit, independent of session freshness. Reset timestamps remain anchored to the
sample, and a passed reset does not invent replenished quota.

Clicking displays eight-second reset-countdown details only in the invoking
client's status message, without changing focus, injecting input, opening a pane,
or leaking run-shell failures into view-mode. The quota cache and changed headers
share the existing batched tmux write; reset-only sample changes do not rewrite
headers. Literal percentages survive tmux's strftime handling, including nested
legacy header formats.

**167 source tests and 167 installed-runtime tests passed**, including 30 new
quota tests, every responsive width from 1–220 columns, real PTY rendering and
mouse clicking, malformed/stale data, old streams, and unchanged pane identities.
Installed only `codex_quota.py`, `core.py`, `status_stream.py`, `desktop.py`, and
`install.py` locally after verifying existing target bytes against their source
baseline. Their manifest entries verify; the two pre-existing unrelated
`backend.py`/`restart_status.py` manifest mismatches remain untouched.

All **9 display pane and 10 hosted-agent identities**, and attached clients, were
preserved during atomic installation. No live configuration, viewer, agent,
service or remote install restart was initiated by this deployment. Subsequent
verification found a separate client-invoked agent restart already in progress:
hosted PIDs changed and parked display window IDs moved, while display pane
IDs/PIDs and attached clients remained unchanged. That worker was not started,
cancelled or retried by this update; its progress was `7/10 ready`, waiting for
sessions #3, #7 and #8. Before/final identity metadata is retained in the backup.

Existing imported monitors retain the old renderer: after current maintenance
completes, detach **all local viewers** with Ctrl+A then d and reopen `pi-desk`
to activate it. F10 restarts agents, not the Pi Desk renderer. Detaching/reopening
normally leaves hosted agents and conversations running. Remote installs require
the same source update separately. A live, read-only collector check confirmed
ten sessions and an available weekly reading; the provider did not supply a
five-hour reading.

Rollback backup:
`~/.local/state/pi-desk/backups/codex-header-20261004T013648706204Z/`.

# Heavy session borders — 2026-10-03, 12:29 EDT

Switched `pane-border-lines` from `single` to `heavy`: horizontal lines,
vertical dividers and junctions now use thicker single-stroke UTF-8 glyphs
(`━`, `┃`, `┳`) rather than double lines. The shared `#8a8a8a` grey, white session
labels, purple active badge, layout and shortcuts are unchanged. Each border
still occupies one terminal cell; non-UTF-8 terminals retain tmux's ACS fallback.

**137 source tests passed**, including an isolated PTY check for the actual heavy
horizontal/vertical/junction glyphs and focus/layout checks in all three widths.
Applied only the line-type option live, with a local config/manifest/cache update.
Verified heavy lines, unchanged grey and white labels in every display pane;
**9 display/10 hosted-agent identities** and attached clients were preserved.
No viewers, agents, services or remote installs restarted. Existing unrelated
manifest mismatches and unrelated working-tree files were left untouched.

Rollback backup: `~/.local/state/pi-desk/backups/heavy-session-borders-20261003T162947796627Z/`.

# Uniform session border grey — 2026-10-03, 12:23 EDT

Horizontal title-row lines, vertical dividers and shared junctions now all use
explicit true-colour grey **`#8a8a8a`** on `#1e1e1e`, in both focus states. The
previous configuration emitted the same `colour240` for all three orientations;
an isolated PTY capture confirmed this, so the reported visible mismatch was not
separate tmux colour settings. Terminal contrast/glyph rendering is the likely
explanation, not a confirmed visual diagnosis. The new grey provides **4.83:1**
contrast (previously 2.34:1), clearing VS Code's default 4.5:1 adjustment threshold.
Terminal-wide settings and the white-title/purple-badge styling are unchanged.

**136 source tests passed**, including shared-grey and contrast regression checks.
An isolated PTY using the installed config verified that horizontal, vertical and
junction glyphs emitted identical RGB foreground/background and no bold/dim
attributes across three focus states. Live verification confirmed the shared
style in every display window and pane, preserving **9 display/10 hosted-agent
identities** and attached clients. Only the local config, its manifest entry and
matching config-cache marker were updated. The two unrelated existing manifest
mismatches were preserved. No viewers, agents, services or remote installs were
restarted.

Rollback backup: `~/.local/state/pi-desk/backups/uniform-border-grey-20261003T162334502978Z/`.

# Selected white title contrast — 2026-10-03, 10:14 EDT

The selected title already requested white, but the original bright purple badge
has only **2.59:1** contrast with white. The active local viewer is in VS Code,
which defaults to **4.5:1** minimum terminal contrast and can darken that white.
Changed only the active badge background to deeper purple `#8D4CA3`, giving white
**5.68:1** contrast. Inactive titles, bright brand/tab accents and terminal-wide
settings are unchanged.

**135 source tests passed**, including a new contrast-threshold regression test
and active/inactive title checks in all layouts. Installed only `config/tmux.conf`
and its manifest entry locally, then applied only the title format live. Verified
all **9 display titles** and preserved **9 display/10 hosted-agent identities**
and the attached viewer client. No viewers, agents, services or remote installs
restarted. The two pre-existing unrelated manifest mismatches were left untouched.

Rollback backup: `~/.local/state/pi-desk/backups/selected-title-contrast-20261003T141412838064Z/`.

# White session titles — 2026-10-02, 23:35 EDT

Every `Session N` pane title now uses true white (`#ffffff`). The active title
retains its bold purple badge; inactive titles keep the dark background. Borders,
status tabs, layout, shortcuts and lifecycle dots are unchanged.

**134 source tests passed**, including isolated one-, two- and three-pane layout
checks. Installed only `config/tmux.conf` locally and updated its manifest entry;
applied only the title format live, with a configuration-cache update only when
the previous cache matched. All **9 display pane and 10 hosted-agent identities**
and the attached viewer client were preserved. Verified white formatting on every
display pane. No viewer, agent, service or remote installation restarted.

Two pre-existing manifest mismatches (`backend.py`, `restart_status.py`) were
recorded and left untouched; their runtime bytes were preserved. The title config's
manifest hash verifies successfully.

Rollback backup: `~/.local/state/pi-desk/backups/white-session-titles-20261003T033526992636Z/`.

# Explicit restart session labels — 2026-10-02, 12:49 EDT

Restart progress now says `Waiting for idle: session #1`,
`Restarting: sessions #2, #10`, and `Restart failed: session #3`.
The ready fraction remains a count; all other numbers explicitly identify sessions.
Hash marks are escaped for tmux rendering, and plural labels retain numeric order.

**132 source tests passed**, plus **10 installed-runtime restart-status tests**.
Installed only `restart_status.py` locally and updated its manifest hash; all
**22 manifest hashes** verified. New restart requests use the labels without
restarting any viewers or agents. Already-running workers retain their old labels.
No remote installations, services, restart state, or logs were changed.

Rollback backup: `~/.local/state/pi-desk/backups/restart-labels-20261002T164945963651Z/`.

# Viewer orphan cleanup — 2026-10-01, 23:00 EDT

Found six abandoned local viewer workspaces with 45 reconnecting display clients,
plus one active viewer with nine cached attachments. All 54 connections mapped to
Pi Desk display panes, not extra hosted agents. The abandoned viewers had no
attached display or surviving controller; some had persisted over three days.

Each new private viewer now records its controller PID and installs a
session-scoped `client-attached` hook that enables `destroy-unattached` only after
the first attachment. The last display's exit destroys its cached display panes
even when the Python wrapper cannot clean up. The hook preserves attachment-time
layout equalization; no global destruction option or hosted socket is changed.

A startup sweep under the selection lock removes only tagged, unattached viewers
older than two minutes with a confirmed-dead owner PID. It atomically rechecks the
session name, creation timestamp, ownership, and attachment state inside tmux.
Live owners, PID reuse, permission/probe errors, young workspaces, and untagged
legacy viewers are retained. Mutation timeouts are not retried.

**131 source tests passed**, plus **11 installed-runtime lifecycle tests** using
isolated tmux sockets and dummy panes. Coverage includes first-attachment safety,
multiple clients/last-detach cleanup, SIGKILL without Python cleanup, live legacy
viewer arming, owner ambiguity, grace periods, and a concurrent-attachment race.
All **22 installed manifest hashes** verified.

Installed only `workspace.py` and `desktop.py` locally by atomic replacement and
updated their manifest entries; unrelated concurrent changes were not deployed.
Armed the existing active viewer without replacing any of its pane/client IDs or
PIDs. Explicitly removed only the six revalidated legacy orphan workspaces,
reducing host attachments **54 → 9**. All ten hosted-agent IDs/PIDs were unchanged;
no active viewer, agent, server, service, or remote installation was restarted.
Post-cleanup tmux samples were roughly 5% (host) and 6–9% (display) of one CPU core,
down from roughly 20–25% each; macOS thermal pressure remained normal.

Rollback backup: `~/.local/state/pi-desk/backups/viewer-cleanup-20261002T025104Z/`
(previous runtime, source snapshots, and before/after identity metadata).

# Non-modal restart requests — 2026-10-01, 22:49 EDT

A second restart request now returns success as a no-op and shows **Restart already
in progress** in only the invoking client's status message. It does not spawn a
helper, overwrite the active worker's status/log, or report an artificial failure.
The confirmed CLI passes its invoking client through to the restart dispatcher.

Reproduced the apparent pane takeover with an isolated tmux shortcut: a nonzero
`run-shell -b` exit opens `view-mode` while the pane process continues underneath.
Both F10 and prefix-R now capture launcher stdout/stderr in
`~/.local/state/pi-desk/restart-dispatch.log` and guard the UI job's exit so neither
command output nor failures can open that pane viewer. Actual helper failures still
appear in restart progress/logs and retain their nonzero direct-CLI exit codes.
The background helper also receives `/dev/null` as stdin, never pane input.

**120 source tests passed**, plus **12 installed-runtime regression tests**. Real
isolated PTY/key tests exercise both confirmation shortcuts with stub exits 0, 1
and 127, checking diagnostics, client targeting, unchanged pane IDs/PIDs and focus,
and no pane modes. Duplicate-request tests preserve the original progress/log;
real launch failures remain errors.

Installed only `restart_status.py`, `cli.py` and `config/tmux.conf`, updating and
verifying all **22 manifest hashes**. Reloaded only the two restart bindings, not
navigation/hooks/layouts. All **54 display IDs/PIDs**, **10 hosted-agent IDs/PIDs**
and the viewer client/selection were preserved. Concurrent presentation changes
are recorded in before/after metadata. No restart request or agent/service restart
was launched by this deployment; no remote install changed. The user's earlier
restart completed successfully on its own.

Rollback backup: `~/.local/state/pi-desk/backups/20261002T024924555406Z/`
(previous runtime files/manifest, `bindings.before.tmux` and identity metadata).

# Terminal tab title — 2026-10-01, 22:31 EDT

Pi Desk's dedicated tmux viewer now sends the constant outer terminal title
`pi-desk`, independent of Python's process name, coding-pane titles and focus.
Enabled app-supplied terminal tab titles with `${sequence}` in this local
workspace's `.vscode/settings.json`; global VS Code settings remain untouched.
This ignored/local workspace preference also applies to other terminals in this
workspace and is documented in README for other workspaces/clones.

**114 source tests passed**. New isolated PTY coverage verifies the emitted OSC
title, stable naming through focus/pane-title changes, unchanged pane IDs/PIDs,
and tmux's title-stack save/restore sequences on attach/detach. Installed only
`config/tmux.conf`, updated and verified all **22 manifest hashes**, and applied
only `set-titles-string` and `set-titles` live without a full config reload.

All **54 display panes**, **10 hosted-agent panes**, viewer client, focus and
geometry were unchanged. No viewer, agent or service restarted; no remote install
changed. Previous title returns on detach in supported terminals; explicitly
renamed VS Code tabs still retain their user-assigned name.

Rollback backup: `~/.local/state/pi-desk/backups/20261002T023129447392Z/`
(previous config/manifest, workspace settings with only the new line reversed,
old live options and identity metadata).

# Active-session title badge — 2026-10-01, 22:12 EDT

Replaced the heavy purple active border with thin grey dividers and a bold purple
`Session N` title badge with dark text. Inactive titles remain muted and the
selected top-bar number retains its purple accent. Shared tmux top junctions are
neutral rather than emphasized as protruding corners of an incomplete outline.
No additional rows/columns, layout changes or navigation changes.

**112 source tests passed**, including real isolated tmux focus changes in one-,
two- and three-pane layouts, badge format expansion for every visible pane, and
attachment PID preservation. Installed only `config/tmux.conf` locally by atomic
replacement, updating and verifying all **22 manifest hashes**. Applied only the
three changed live styling options, not the full config/navigation/hooks. Removed
10 legacy per-window overrides only after verifying each exactly matched the old
global style, so those windows now inherit the new style.

All **54 display pane IDs/PIDs**, **10 hosted-agent pane IDs/PIDs**, viewer client,
focus and display geometry were unchanged. No viewer, server, service or agent
restarted; no remote installation changed. Local viewers show the new style
immediately, with no reopen required.

Rollback backup: `~/.local/state/pi-desk/backups/20261002T021238568848Z/`
(previous config and manifest, old global/window options and before/after identity
metadata).

# Automatic blocked-terminal recovery — 2026-09-29, 20:13 EDT

User requested close/kill/reopen without requiring graceful detachment. The live
incident was a `pi-desk` server blocked in `tty_write_callback → writev` on a
still-present VS Code terminal, with no surviving display attach client. Flushing
that display's output restored responsiveness without restarting anything.

- `desktop.main()` now calls `core.prepare_workspace()` before creating panes.
  Existing hung-up-client recovery remains, now also recognizing VS Code's
  `-T hyperlinks` attach command.
- A macOS-only, two-second read-only startup probe gates the new fallback.
  Recovery discovers the server through the exact current-user Pi Desk UNIX
  socket, revalidates UID/command/socket/tty ownership, and flushes only its
  tty-slave output. It covers a terminal that still appears live and a vanished
  display client. PTY masters and the hosted agent socket are excluded.
- Large blocked writes may require several flushes. Up to 20 short probe/flush
  passes stop at the first responsive read-only query. No signals, server kills,
  terminal-setting changes, agent restarts, or mutation retries are used.
  Unrecoverable stalls still report the normal bounded error. A hard kill may
  leave orphan display panes; the fallback does not indiscriminately destroy
  unattached workspaces, which could belong to a concurrently starting viewer.

**106 source tests passed**, followed by **45 tests against installed modules**
(13 recovery tests plus 32 responsive tests). A real macOS PTY/private tmux test
reproduces a blocked write by removing the shared descriptor's `O_NONBLOCK` while
the emulator stops reading, kills the attach client while keeping the terminal
open, invokes startup recovery, and creates a new display session. Server and
original pane IDs/PIDs remain unchanged. That regression also passed three
additional consecutive runs. Tests use private sockets and dummy processes,
never hosted agents. Healthy installed startup probe measured 0.099 seconds.

Installed only `core.py` and `desktop.py` locally by atomic replacement, with
full manifest verification and baseline-content checks. All **35 display pane
IDs/PIDs and 10 hosted-agent pane IDs/PIDs** were unchanged during deployment.
No viewer, server, service, agent, or remote installation restarted/changed.
New `pi-desk` launches use the fix immediately; existing imported viewers need
not be restarted for next-launch recovery to work.

Rollback backup: `~/.local/state/pi-desk/backups/20260930T001330141279Z/`
(previous core, desktop, manifest, and before/after identity metadata).

# Ready-group selection and batched status — 2026-09-29, 17:14 EDT

Implemented the user's requested optimizations in `desktop.py` only:

- Ready visible-group clicks/F12 validate actual pane indices, tags, liveness,
  sizing policy and reconciliation gate, then change focus and publish selection
  in one queue. They no longer trigger layout reconciliation. Stale/dead/missing
  panes, group boundaries and changed capacity retain the recovery fallback.
- The shared monitor combines selection/viewer metadata reads into one tmux
  client and writes changed global/per-viewer headers through at most one further
  client. Private temporary command files bypass the argv message-size limit;
  writes guard viewer existence. Unchanged rows and saved selections are not
  rewritten. Intervals, pulse, warning rows and monitor election are unchanged.

**92 source tests and 32 installed-module responsive tests passed**. New coverage
includes focus-only click/F12 dispatch, stale/dead/missing/order/capacity fallback,
actual pane-loop ordering, hysteresis, selection persistence, empty selection
snapshots, >8192-byte/private/deleted command files, literal quoted warnings,
closed viewers, pulse/idle tick client counts and failure retry. An existing
wall-clock debounce unit test was made deterministic after load-induced timing
flakiness; no production resize behaviour was modified.

Isolated synchronous software comparison, three dummy viewers:

| Operation | Previous → updated median | tmux clients |
| --- | --- | --- |
| In-group selection, 36 samples each | 39.00 → 15.48 ms | 8 → 3 |
| Idle unchanged tick, 15 warm samples each | 8.86 → 5.07 ms | 2 → 1 |
| Pulsing tick, 15 warm samples each | 30.33 → 11.49 ms | 6 → 2 |

Not physical screen/click latency or measured CPU usage. Methodology and scope:
`docs/focus-status-optimization.md`.

Installed only `desktop.py` locally by atomic replacement, updating and verifying
the full manifest. Every other runtime file was preserved. All **31 display pane
IDs/PIDs and 10 hosted-agent pane IDs/PIDs** were unchanged across deployment.
No viewer, service or hosted agent restarted; no remote rollout.

Click/F12 helper invocations pick up the update immediately. Reopen local viewers
to activate the lighter status monitor. With multiple old viewers open, close all
of them so monitor election cannot pass to another old imported implementation;
hosted agents keep running.

Rollback backup: `~/.local/state/pi-desk/backups/20260929T211439672325Z/`
(previous desktop, manifest, deployment metadata and identity verification).

# Batched group switching — 2026-09-29, 16:57 EDT

At user request, chose batching rather than cached whole-group windows.
`workspace.reconcile()` plans pane moves/order against a snapshot and submits
respawns, titles, moves, final equalization, focus and readiness metadata in one
tmux mutation queue. Existing attachments, lazy creation, layout capacity and
per-viewer isolation are retained. There is only one final even-horizontal layout
operation and no pane-index queries between mutations. Failed batches leave
native navigation gated until recovery. This reduces unnecessary redraws; it does
not eliminate tmux's resize notifications or guarantee zero visible flicker.

**84 source tests passed**, plus **16 isolated workspace tests against the actual
installed module**. Coverage includes all sessions/modes and native keys,
identities, responsive sizing, independent viewers, dead/missing pane recovery,
missing window recovery with existing parked attachments, failed batches,
scrambled order and small custom panes.

An isolated synthetic comparison (12 warm three-pane switches per version) found
median command duration **140.30 → 46.32 ms**, resize notifications across six dummy
apps **10 → 6**, and terminal bytes **101,935 → 28,585** (about 72% less output).
These are software/terminal-stream measurements, not real screen latency.
See `docs/navigation-flicker-research.md` for methodology and limits.

Installed **only `workspace.py` locally**, with an atomic file replacement and
verified manifest. Three pre-existing stale manifest entries (`status_stream.py`,
`desktop.py`, `config/tmux.conf`) were reconciled only after confirming their
installed contents exactly matched reviewed source. No contents of those files
were changed; all other runtime files, including machine-specific Foot settings,
were preserved. All **22 display pane IDs/PIDs and 10 hosted-agent pane IDs/PIDs**
were unchanged across deployment. No viewer, service, or agent was restarted;
no remote machine was changed.

Existing cross-group helpers import the updated module on their next invocation.
A running viewer's imported resize watcher retains its old code until that viewer
is reopened; detach with Ctrl+A then d and run `pi-desk` to activate the update
throughout. Hosted agents remain running.

Rollback backup:
`~/.local/state/pi-desk/backups/20260929T205756332805Z/` (previous workspace and
manifest, deployment metadata and identity verification).

# Full-colour two-pane divider — 2026-09-27, 14:12 EDT

Disabled tmux's default `pane-border-indicators colour` behaviour with
`pane-border-indicators off`. The default intentionally colours only half of a
shared border when there are exactly two panes; the shared active divider now
uses the full purple border style. Focus remains indicated by the selected number
and pane label. The four top-bar separators still mark the five pairs of session
numbers; they are not extra pane dividers.

**77 tests passed**, including both focus positions in two-pane mode. Installed
locally with manifest verification and applied only this live display option.
Viewer focus and all display/agent pane identities were unchanged; no restart and
no remote rollout. Backup: `~/.local/state/pi-desk/backups/20260927T181242893478Z/`.

# Smaller responsive width target — 2026-09-27, 14:09 EDT

Reduced the default target from 60 to **52 columns per pane**, calibrated against
the user's open 110×45 terminal. Initial thresholds are now 105 columns for two
sessions and 158 for three; the four-column growth buffer remains (109/162).
Updated documentation and threshold tests, including an isolated live-preference
change and shrink/grow regression at 110 columns. **76 tests passed**.

Installed locally with a verified manifest and applied the preference to the
existing viewer without restarting it. Live verification: session 1 is 55 columns,
session 2 is 54 columns and remains selected; the header has four two-session-group
dividers. All ten hosted-agent pane identities and all pre-existing display pane
identities were preserved. Remote installations were not touched.

Rollback backup: `~/.local/state/pi-desk/backups/20260927T180931405080Z/`.

# Responsive viewer layouts — 2026-09-27, 14:04 EDT

Implemented and installed on mac-mini-64 using the local backend. All installed
source files and manifest hashes verified. Existing viewers were not reconfigured,
restarted, or detached: six display pane identities and all ten hosted-agent pane
identities were unchanged across installation. Close and reopen all local viewers
to activate the new workspace/renderer and replace the old elected status monitor.
No remote machine or long-running service was changed.

- Initial width thresholds: one session below 121 columns, two at 121–181, three
  at 182+. The observed 184×45 viewer retains three approximately 60-column panes.
- 180 ms resize debounce, four-column growth buffer, and configurable per-viewer
  `PI_DESK_MIN_COLUMNS` (default 60). A direct terminal-size watcher avoids idle
  subprocess polling and waits for tmux to observe the new dimensions.
- Viewer-private workspaces preserve focus and reuse attachment processes by
  parking off-screen panes; simultaneous viewers can use different group sizes.
  Normal exit/hangup removes only the owned display workspace.
- Header group dividers, group tint, density and shortcut hints adapt to width;
  narrow headers keep the selected tab visible and clickable. Warning rows are
  explicitly included in session-local status arrays. Escaped conditional purple
  values prevent tmux interpreting `#D` as its pane-ID shorthand.
- Native in-group navigation validates live window/pane order and liveness.
  Cross-group navigation and recovery serialize pane reconciliation. Legacy
  fixed-group navigation remains supported until old viewers are closed.

Validation: **75 tests passed** on mac-mini-64, plus shell syntax and whitespace
checks. New coverage uses isolated tmux sockets, real PTYs and dummy sleep
processes: all ten selections in all modes, actual native arrow keys and bounds,
independent viewers, pane PID preservation, missing/dead/parked-pane recovery,
missing visible-window recovery, warning-row height changes, narrow header format
expansion, debounce, delayed SIGWINCH handling, and the full viewer's automatic
resizing and SIGHUP cleanup. No hosted agents were restarted during tests.

Rollback backup:
`~/.local/state/pi-desk/backups/20260927T180407187615Z/`.
Raspberry Pi/mac-mini-16 rollout and physical-screen acceptance remain pending;
this does not remove the documented nested-tmux host reflow caveat.

# Heavy pane dividers — 2026-09-25, 00:32 EDT

Set `pane-border-lines heavy` in source and the Mac runtime, retaining purple for
active borders and grey for inactive borders. Updated the Mac manifest and applied
only the live border option; no viewers or agents restarted and all display/agent
pane identities are unchanged. Mac suite: 56 passed.

Partial completion: full left/right/bottom outer framing is not implemented; it
requires viewer-layout/renderer work beyond the current tiled tmux configuration.
Pi deployment is pending because SSH to raspberrypi timed out.

# Purple selected-session outline — 2026-09-25, 00:25 EDT

At user request, changed the selected session number, pane-border label, and active
pane outline from cyan to the JARVIS dark accent `#D183E8`. Updated only the desktop
selector and tmux border settings in the Mac/Pi runtimes; both manifests validate.
Mac suite: 55 passed. Live tmux options and status output confirm the purple on both
hosts. Refreshed only the viewers; Mac/Pi display pane IDs/PIDs and Mac hosted-agent
pane IDs/PIDs are unchanged.

# JARVIS purple title — 2026-09-25, 00:21 EDT

Matched `PI-DESK` to the JARVIS app's dark accent, `#D183E8` (24-bit RGB).
Both Mac and Pi tmux clients advertise RGB; the installed desktop manifests were
updated and verified. Mac suite: 54 passed. Live status output showed the exact
RGB title on both hosts. Refreshed only the viewers; display pane identities and
Mac hosted-agent pane identities were unchanged.

# Faster header pulse — 2026-09-24, 23:38 EDT

At user request, shortened each bright/dim phase from 1.5s to 0.75s (1.5s full
cycle). The running/compacting palette and all other header behavior are unchanged.
Mac suite: 54 passed. Pi focused pulse-phase checks passed. Patched only the pulse
phase constant/helper in the installed runtimes and updated/verified the desktop
manifest. Refreshed only the display viewers; live dot alternation and unchanged
pane identities were verified.

# Header contrast follow-up — 2026-09-24, 23:35 EDT

At user request, changed the header title to `PI-DESK` and increased the working-dot
contrast: running alternates 77/22 and compacting 75/24 (xterm palette), retaining
1.5-second phases. Patched only those literals and title detection in both installed
runtimes; updated and verified desktop manifests. Mac suite: 53 passed; Pi focused
selector checks passed. Reopened the Mac viewer and refreshed the Pi display service
with its tmux server outside the display scope. Title and running-dot alternation
verified live via status output; all display and hosted-agent pane identities unchanged.

# Quiet grouped header — 2026-09-24, 23:30 EDT

Deployed only `selector()`, `watch_status()`, and the `time` import to the existing
Mac and Pi runtimes. All other installed functions were verified unchanged; this
was not a reliability rollout. Desktop manifest hashes were updated and verified.

- Two-digit session numbers, muted separators after 03/06/09, no group labels.
- Running/compacting dots alternate brightness every 1.5 seconds through the
  existing shared monitor. Text, focus, shortcuts, and warning behavior unchanged.
- Mac suite: 53 passed. Pi suite: 53 run, one zsh-only skip.
- Reopened the Mac viewer and detached the old client. Restarted only the Pi's
  `pi-desk.service` fullscreen display after verifying its tmux server was outside
  the display's process scope. Both headers and live running-dot palette changes
  were verified through tmux status output (not a rendered-screen inspection).
- All Mac/Pi display pane IDs/PIDs and all hosted-agent pane IDs/PIDs were unchanged.
  No tmux servers or agents restarted. mac-mini-16 and unrelated services untouched.
- Temporary transfer/test files and rollback copies were removed after validation.

# Startup optimization — 2026-09-24, 22:40 EDT

Deployed startup-only changes to Mac and Pi without restarting any viewer, service,
or hosted agent. Installed desktop code was patched by function so the separate
`attach_viewer()` reliability changes remain source-only. Session 2's already-installed
Mac timeout handling was preserved; its two stale manifest entries were reconciled
after confirming exact source hashes. All installed manifest entries now verify.

- Configuration cache: server-local `@pi-desk-config` fingerprints desktop.py,
  native_navigation.py, tmux.conf and install path. A new server or changed file
  triggers configuration. Pane readiness is NEVER cached: choose() still validates
  live tags/order/liveness and retains recovery. Use `configure(force=True)` to
  restore bindings changed manually without modifying configuration files.
- Initial setup loads all six native bindings from a private temporary tmux config
  in one client call (then deletes the file). A direct argv batch exceeded tmux's
  message-size limit in isolation and was rejected before deployment.
- Status rows and row count are applied in one command queue.
- Added real-server coverage for cache reuse/invalidation, forced binding repair,
  both warning-row states, all six native bindings, and unchanged dummy pane
  identities. Fixed an older state-restoration test that inadvertently read the
  live server. These focused tests passed on both platforms. The full working-tree
  suite (including the separate reliability/timeout changes) passed 51 tests on
  Mac; Pi ran 51 with one zsh-only skip.

Installed CLI -> first PTY output, healthy dummy workspace, five openings/platform:

| Platform | Previous median | Updated repeat-open median | First open, uncached config |
| --- | --- | --- | --- |
| Mac | 116.44 ms | 65.73 ms (65.19–67.89) | 95.66 ms |
| Pi | 854.67 ms | 557.79 ms (541.16–562.06) | 807.37 ms |

Repeat-open samples exclude the first configuration-building run. Approximately
44% faster on Mac and 35% on Pi. These are isolated software timings, not physical
screen latency or fresh SSH/session startup. The real installed status monitor ran,
with its election lock/state isolated. The local harness remains at
`/tmp/pi-desk-full-startup.py`; the temporary Pi candidate stage was removed after
validation and deployment. No claim that cold agent connections or the original
blocked-write fault are improved.

The deployment backups were subsequently removed after validation; no rollback
copies remain in the runtime backup directories. Live pane identities
were unchanged at deployment. Optimizations apply on the next open; existing viewers
were left alone. If rollback is needed, restore the prior source files and regenerate
the install manifest; never kill the hosted server. mac-mini-16 was untouched.

# Multiple-viewer acceptance — 2026-09-24, 22:05 EDT

Isolated synthetic-output tests passed on Mac and Pi for two independent viewer
terminals, two seconds with both readers paused, closing one while retaining the
other, attaching a replacement, closing all clients, and overlapping two clients
on the same terminal then closing them separately. The dummy pane PID was preserved
throughout; no live display or agent sockets were used. Two viewers alone did not
reproduce the original stall. This does not rule out a timing-dependent interaction.

`probe_viewers.py` records the reusable test. On Mac it additionally exercised the
new source wrapper with actual SIGTERM, SIGHUP, and a SIGSTOP-stopped tmux child;
the owned child was reaped in every case. 14 checks passed, followed by all 46 unit
tests at that point (including status-monitor election/failover). The Pi ran the
eight raw tmux multi-viewer checks, not wrapper acceptance at that point. Subsequent
updated full-suite validation passed 51 tests on Mac and ran 51 on Pi with one
zsh-only skip. The actual signal/stopped-child wrapper acceptance remains Mac-only.
A probe-cleanup exception on macOS was fixed and its unique leftover test socket
removed; the full Mac probe then passed including cleanup.

Hardening remains source-only. Actual-signal wrapper acceptance on Pi and deployment
verification remain outstanding. No claim of a root-cause fix or deployment.

# Viewer reliability investigation — 2026-09-24, 22:01 EDT

Session 2 recovered the Mac display server by flushing the stale terminal's output
queue. A process sample showed the tmux server blocked in `writev` from its terminal
write callback. This identifies the blocking location, not the initiating cause.

Isolated controlling-PTY tests on Mac and Raspberry Pi exercised a continuously
printing dummy pane, fresh attach, two seconds without reading output, resumed
reading, terminal hangup, and reattach. Neither reproduced a stall. Each server
remained responsive (Mac queries 19.6–33.5 ms; Pi 20.6–33.6 ms), and the dummy
pane identity was preserved. These are command response times, not display latency.
Live viewers and hosted agents were not changed by these probes.

Source-only hardening in `desktop.attach_viewer`: own/reap the display client on
HUP, TERM or interruption; bounded TERM then KILL for an unresponsive/stopped client;
restore prior signal handlers. Never signal a server or process group. Three new
mocked cleanup tests brought the Mac suite to 46 passing tests at that point.
Subsequent full-suite runs passed 51 tests on Mac and ran 51 on Pi with one zsh-only
skip. Actual signal/PTY wrapper acceptance was run on Mac, not Pi. Session 2's timeout
handling is preserved. This patch is NOT deployed and does not establish prevention
of the original blocked-write fault. Validate the wrapper on Pi and verify installed
manifests if deployment is ever authorized.

# Cross-platform software latency — 2026-09-24, 21:53 EDT

Isolated Pi-local PTY input injection to first readable terminal output, using
installed native bindings, selector and ten dummy panes: 36 switches, median
31.081 ms, range 23.945–56.810 ms. Within-group median 30.869 ms; cross-group
31.223 ms. Mac source benchmark: 36 switches, median 5.931 ms, range
3.397–13.059 ms; within-group 6.146 ms, cross-group 5.060 ms.

These exclude physical keyboard, Foot/VS Code rendering, TV processing and scanout.
Dummy panes also exclude live agent output load. Focus was verified after each
timed interval. The Pi output is 1920×1080 at 60 Hz. No camera measurement exists.
`benchmark_navigation.py` provides the isolated cross-platform reproduction;
periodic status redraws are disabled to avoid false first-output measurements.

Mac native navigation files now installed with manifest updates; active Pi Desk
bindings refreshed without disconnecting viewers. Hosted pane identities unchanged.
41 Mac tests passed. Existing viewer monitor code updates on reopening Pi Desk;
native bindings are active immediately. Pi installation was already native and was
not changed. mac-mini-16 untouched. The historical Mac rollback snapshot was later
removed; no runtime rollback copy remains. Never restart agents.

# Native tmux navigation — 2026-09-24, 18:18 EDT

Deployed to Raspberry Pi only. Healthy Ctrl + arrow navigation now runs directly
inside tmux, validating live workspace pane order/tags/window/liveness before
switching. Missing/unhealthy groups fall back to the existing Python recovery.
No Python or shell launch for a normal keypress. tmux records the last selection
synchronously; the elected status monitor atomically persists it in the background.
Reopening a viewer also reads the live tmux selection to avoid persistence lag.

41 tests passed on Mac and Pi (one zsh test skipped on Pi). Isolated tests exercise
actual key bindings, both directions/all groups, clamping, persistence, unchanged
pane PIDs and refusal of the fast path for a missing pane. Live Pi traversed 1–10
and back, including recovery of previously uncreated groups, then restored and
persisted the original selection. Key dispatch plus verification measured 78–96 ms
(median 90 ms); this is not a physical keyboard-to-screen latency measurement.
Only the Pi display service was refreshed; hosted agents were not restarted.

Pi backup: `~/.local/state/pi-desk/backups/20260924T221807712278Z-native-navigation/`.
Rollback restores backed-up desktop/navigation/installer/manifest files, removes
new `native_navigation.py`, then restarts the Pi display service. Mac installations
remain on the prior lightweight helper; source/installer include the native path.

# Navigation latency and shortcut labels — 2026-09-24, 18:08 EDT

Measured full display imports at 362–375 ms on Raspberry Pi for every arrow press.
Added `navigate.py`: lightweight imports, two batched tmux calls, existing selection
lock and atomic selection persistence. Missing/dead/mistagged groups retain the
full recovery path. Direct arrow bindings and prefix fallbacks use the new helper.
Displayed navigation hints now say `Ctrl + ←/→`; the user configured the Mac to
accept those keys directly. No macOS keyboard settings changed by this patch.

41 tests pass on Mac and Pi (Pi skips the Mac/zsh-specific test). Isolated tmux
coverage traverses all groups in both directions, checks endpoint clamping,
selection persistence, invalid-client rejection and unchanged pane identities.
Live Pi end-to-end navigation measurements: old path 610–735 ms, new 321–403 ms.
This reduces delay but does not establish zero-latency navigation.

Deployed navigation, desktop, tmux config and installer to Mac/Pi; refreshed only
viewers. mac-mini-16 untouched. Backups under `~/.local/state/pi-desk/backups/`:
Mac `20260924T220816052394Z-navigation`; Pi `20260924T220759345425Z-navigation`.
Rollback restores backed-up files/manifest and removes newly added `navigate.py`.

# SSH attachment quoting fix — 2026-09-24, 17:58 EDT

User reported persistent pane errors despite an active display and healthy status
projection. Capturing the Pi panes revealed `zsh:1: jarvis-ios not found`: Python's
`shlex.join()` leaves `=jarvis-ios` unquoted, triggering zsh command-path expansion
before tmux receives the exact-session target. `Backend.run_on_host()` now quotes
every argument, including equals-prefixed targets and embedded apostrophes.

40 tests passed on Mac, including execution through real zsh for all ten target
names. Deployed `backend.py` to Raspberry Pi with manifest update and rollback:
`~/.local/state/pi-desk/backups/20260924T215819930853Z-ssh-quote/`.
Respawned only its six existing `pi-desk` display connectors (not hosted agents).
All six SSH viewers subsequently appeared as attached clients on the host and
rendered session content. No Mac installation or mac-mini-16 changes in this fix.
The healthy status projection does not currently prove successful pane attachment;
service-active/status-row checks alone must not be treated as viewer acceptance.

# Warning-only health row — 2026-09-24, 17:19 EDT

Updated `desktop.py` and `config/tmux.conf` on mac-mini-64 and Raspberry Pi;
mac-mini-16 deliberately left unchanged because it is no longer used for Pi Desk.
Healthy displays now use one status row; warnings add a second row only while
needed. Only unhealthy fields are shown. Selector shortcuts are right-aligned,
with compact hints below 120 columns; session click ranges are unchanged.

**39 tests passed on each updated machine**, including isolated live-tmux tests
verifying the warning row removes/restores exactly one line of pane height without
changing pane PIDs. Tests never attach real agents. Live Mac and Pi displays both
confirmed one-row healthy mode; Mac shortcuts confirmed right-aligned in the live
format. Only viewers were refreshed (VS Code integrated terminal on Mac; display
service on Pi). All ten hosted session/pane/PIDs unchanged. Rollbacks:

- Mac: `~/.local/state/pi-desk/backups/20260924T211619003272Z-warnings/`
- Pi: `~/.local/state/pi-desk/backups/20260924T211719038733Z-warnings/`

These focused backups contain only `desktop.py`, `config/tmux.conf`, and
`manifest.json`; restore those to the installed app, then reopen the viewer.
No reboot or prolonged network-outage test performed for this revision.

# Enter-only restart confirmation — 2026-09-24, 17:02 EDT

Updated `cli.py` on all three machines with per-machine rollback copies and
refreshed manifests. F10 / `pi-desk restart` now requires only Enter at an
interactive prompt. Ctrl+C, EOF, nonempty input and noninteractive execution
cancel without invoking the host helper. Existing host preflight checks remain
unchanged. **37 tests passed on each machine**; no real agents were restarted.
An already-open confirmation popup must be closed and reopened to load the change.
SSH to both remote hosts succeeded again during this update; the earlier network
failure's cause remains unconfirmed, and the older extended acceptance checks
below were not rerun as part of this focused patch.

# Portable deployment — 2026-09-24

Installed the same shared app on all three machines. mac-mini-64 is explicitly
`local`; mac-mini-16 and Raspberry Pi are explicitly `ssh` viewers of its ten
existing sessions. `pi-desk` opens the current terminal; Mac app shortcuts open
Terminal using a dedicated `.terminal` profile without AppleScript/Automation
permission. The Pi's fullscreen service is retained separately.

## Acceptance

- **36 tests passed on each of the three machines.** The existing host restart
  helper's **17 tests** also passed; that helper and VS Code tasks were not edited.
- All three interactive viewers were observed running. Both Macs reported live
  status and the correct local/SSH mode. The Pi's first portable deployment
  reported live status; the final launcher-only update was observed active and
  connecting before subsequent LAN access was blocked.
- Primary Mac: all ten display panes, focus selection, group-boundary navigation,
  source manifest and F10 popup tested. Popup closed without confirming restart.
- All ten original host session names, pane IDs and **agent PIDs stayed unchanged**.
  No real agent restart was attempted while work was running.
- Observed tmux caveat: with every host client marked `ignore-size`, attaching
  another viewer can still reflow host pane dimensions. No host resize/layout
  commands were issued. See README; do not describe this flag as an absolute
  geometry guarantee.
- Multiple-viewer monitor election/failover covered by tests; repeated installation
  preserves profiles, retains backups and adds the PATH marker only once.
- mac-mini-16 required tmux 3.7c via Homebrew. Its dependency installation also
  upgraded ca-certificates/OpenSSL; no REAPER/oMLX service restart was requested.
- Latest backups: primary Mac `20260924T204203879898Z`, secondary Mac
  `20260924T204335426464Z`, Pi `20260924T204342822825Z`, each under that machine's
  `~/.local/state/pi-desk/backups/`. Earlier backups retained.

## Remaining acceptance / blocker

After installation and successful Mac GUI checks, new LAN requests from the
primary Mac began returning **No route to host** for both trusted remote hosts.
The local interface and routes remained present. macOS Local Network permission
is a possibility, **not a confirmed diagnosis**; no permission, firewall, route or
network-service settings were changed to bypass it. Final remote all-ten-pane /
F10 checks and cross-host manifest comparison remain pending reconnection.

Only allowlisted release staging remains remotely at
`mac-mini-16:/tmp/pi-desk-portable.e6JLkp` and
`raspberrypi:/tmp/pi-desk-portable.PQumK1`; remove those after reconnection, not the
rollback backups. No full reboot or prolonged-disconnection test was performed.
The existing VS Code workflow remains an untouched fallback.

---

# Initial deployment — 2026-09-22

## Implemented

- Consolidated trial UI units into persistent `pi-desk.service`, **enabled at boot**.
- Kept `multi-user.target` and the existing pi account; no new account or sudo policy.
- Retired `mac-graphical-terminal.service`, `mac-sessions-trial.service` and the
  transient `mac-session-grid-live` user service; stopped the old local
  `mac-session-panels` tmux server. Mac sessions were not killed or recreated.
- New local socket: `pi-desk`. New manual command: `~/.local/bin/pi-desk`.
- Legacy `mac-sessions` is a compatibility wrapper; obsolete connect/grid/display
  scripts were archived before removal.
- Added per-pane reconnect, pane reconciliation/order recovery, read-only live
  lifecycle feed reconnect and strict freshness handling.
- Retained fullscreen, black background, emoji support, 24/12 pt menu/workspace
  fonts, US keyboard and persistent Wi-Fi power-save disablement.

## Backup

Pi pre-migration snapshot: `~/.local/state/pi-desk/backups/20260922T150937Z/`.
A secret-free archive of that allowlisted snapshot is retained in this project's
`backups/` directory. It excludes SSH configuration/keys, known_hosts, presence
identity files, backend state, session transcripts, and environment files with
credentials. Labwc's keyboard-only environment file is included.

The Mac's previous read-only status helper was separately retained under
`~/.local/state/pi-desk/backups/` before replacement.

## Verified

- **13 tests passed on both Mac and Raspberry Pi**, including fresh/stale/future
  status, invalid telemetry, source projection, retry after failed SSH start,
  group idempotency, missing-middle-pane repair with numeric ordering,
  dead-pane respawn, and session 10 remaining solo.
- `systemd-analyze verify` accepted the installed service.
- `systemctl is-enabled pi-desk.service` → enabled; active, with zero restarts.
- Terminated only the UI's read-only status SSH client: it automatically obtained
  a new PID and resumed its stream.
- Terminated only session 1's Pi-side SSH display client: its wrapper automatically
  reconnected with a new SSH PID; the remote Mac session stayed running.
- Opened group 1 through the graphical menu: all three tagged panes were alive.
  F12 returned to the menu and closed only the workspace display client.
- Old trial units no longer running.
- Presence/audio user services and system Bluetooth/SSH remained active.
- Approximately 658 MiB available memory, 56°C, no active thermal throttle;
  `0x20000` was a historical soft-temperature-limit flag only.

## Reboot acceptance — passed 2026-09-22, 11:19 EDT

Owner-authorized reboot confirmed by a changed boot ID. Pi Desk automatically
started on tty3 at 1080p/60 Hz, enabled and active with zero restarts. The live
status SSH stream resumed. Opened group 1 after boot: sessions 1–3 were alive;
F12 returned to the grid. Presence, audio proxy, Bluetooth and SSH recovered;
the backend reported fresh presence data from both zones. Wi-Fi power saving
remained off. No failed system or user units. Left the display at the menu.

## Connection feedback and health strip — 2026-09-22, 11:30 EDT

Added explicit SSH connection/retry and backend-data availability messages, plus
Wi-Fi association signal, Mac ping latency, CPU temperature and presence-service
active state. Read-only checks run off the UI thread every 10 seconds, with
bounded command timeouts and 25-second reading expiry. No radio scans or
household actions. Service state is explicitly not sensor freshness or occupancy.

- **21 tests passed on Mac and Pi**, including message transitions, watchdog,
  missing commands/data, ping failure, timeouts, single-worker bounds, expired
  readings, worker failure, and the grid layout with its new health strip.
- Live diagnostic stream went from connected → SSH disconnected/retry → connected
  after terminating only its own diagnostic SSH client.
- Live health sampling returned Wi-Fi signal, ping latency, temperature and active
  presence service. Group 1 opened with three live panes; F12 returned to the menu.
- Pi Desk remains boot-enabled, active, with zero restarts; presence and audio
  proxy services remained active throughout this display-only update.
- Pre-update Pi rollback: `~/.local/state/pi-desk/backups/20260922T153003Z/`.

## Visual refinement — 2026-09-22, 15:05 EDT

Session text increased to 14 pt; menu remains 24 pt. Cards now use subtle grey
borders, bright bold numbers and coloured lifecycle dots instead of full-card
colour. Normal diagnostics are muted grey; uncertainty is amber and explicit
service failure red. Active local panes have bold cyan titles and cyan borders;
inactive titles/status chrome are muted. Pure-black backgrounds retained.

All 23 tests passed on Mac and Pi, including diagnostic colours and narrow-card
label fit. Applied the configuration to the existing local `pi-desk` tmux server;
verified expanded active/inactive title styles, 14 pt workspace launch and F12.
Presence and audio services stayed active. Pre-update rollback:
`~/.local/state/pi-desk/backups/20260922T190534Z/`.

## Direct session selection — 2026-09-22, 15:10 EDT

Menu now accepts session numbers 1–10 followed by Enter, opens the corresponding
three-session workspace (10 alone), and focuses the requested session. Removed
row-number shortcuts from the cards; added a visible input prompt, Backspace
editing and Escape clearing. Explicit Enter disambiguates 1 from 10.

All 26 tests passed on Mac and Pi. Live checks: `5` + Enter opened 4/5/6 with
session 5 focused; `10` + Enter opened session 10 alone; F12 returned to the menu.
Presence/audio remained active. Pre-update rollback:
`~/.local/state/pi-desk/backups/20260922T191052Z/`.

## Persistent selector and cross-group navigation — 2026-09-22, 15:25 EDT

Replaced the fullscreen menu with **two native tmux status rows at the top**:
clickable numbered session/status dots, then compact connection/health readings.
The bar is not a pane, so navigation cannot get stuck in it. One fullscreen 14 pt
Foot window keeps coding sessions visible at all times. The current 173×46 display
retains 43 content rows per coding pane plus its title/border row.

F12 opens numeric session selection without hiding the workspace. Ctrl+Left/Right
moves through sessions 1–10, switching groups and focusing the requested session;
it stops at the endpoints. The last selected session is persisted as a number.
Existing healthy groups switch without rebuilding layouts; damaged groups retain
pane-repair behaviour. A lock serializes selection and another prevents duplicate
persistent displays. Status/health collection continues while coding.

- **32 tests passed on both Mac and Pi**, including selector ranges, status styles,
  state restoration, group focus, and cross-group/end-point navigation.
- Live F12 selection of 4, Ctrl+Left → group 1/session 3, Ctrl+Right → group 2/session 4.
- Live 10 → Left → 9 and Right → 10; another Right stayed at 10.
- Actual tmux SGR mouse-input test on session 10's range selected group 4/session 10.
  Used a temporary ignore-size local client; terminal contents were discarded,
  not logged. The temporary client was closed afterwards.
- Restarted the display service and verified automatic restoration of group 2,
  focused on session 4. Two-row bar/live health returned; zero service restarts.
- Presence/audio proxy, Bluetooth and SSH remained active; boot enablement retained.
- Pre-update rollback: `~/.local/state/pi-desk/backups/20260922T192538Z/`.

This supersedes the earlier F12-to-fullscreen-menu and 24 pt menu behaviour.
The existing service's boot acceptance was tested earlier; this version was
service-restart tested, not subjected to another full Pi reboot.

## Cleanup — 2026-09-22, 15:38 EDT

Removed the retired curses/fullscreen-menu implementation and its obsolete UI
and keyboard-buffer tests. Shared transport/workspace code now lives in `core.py`;
`desktop.py` is the sole display entry point. The installer backs up the old app
before removing `terminal.py` and stale Python caches. Blank/health-bar clicks
are ignored rather than displaying an invalid-selection message. Attachment
failures now propagate their exit status to the display service.

- **25 current tests passed on Mac and Pi.** Retired-menu tests were removed and
  overlapping tests consolidated; recovery, status freshness, diagnostics,
  all-ten-session focus, group-boundary navigation, click routing and migration
  cleanup remain covered.
- Live F12 selection and 4 → Left → 3 → Right → 4 verified after deployment.
- Installed SHA-256 manifest verified; no `terminal.py` remains in the installed app.
- Removed six explicitly identified temporary deployment/staging directories.
  All nine Pi rollback backups, saved selection and active lock files retained.
- Pi Desk, presence/audio, Bluetooth and SSH remained healthy; zero display restarts.
- Pre-cleanup rollback: `~/.local/state/pi-desk/backups/20260922T193852Z/`.

## Still untested deliberately

- Prolonged Wi-Fi loss, Mac reboot, and TV hotplug. Retry behaviour is tested
  without deliberately taking the household's network or services offline.

No new public ports, HTTP listeners, household automations, browser installations,
Mac session-layout changes, or credential copies were introduced.
