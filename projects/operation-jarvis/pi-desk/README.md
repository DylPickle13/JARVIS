# Pi Desk

One lightweight terminal workspace for the same ten Mac-hosted Pi Coding Agent
sessions, on **mac-mini-64, mac-mini-16 and Raspberry Pi**. No browser, desktop
streaming, or VS Code dependency. The agents always run on mac-mini-64.

## Token rollout reversal — 2026-10-06

At owner request, source and installed status helper/tests are restored to exact
pre-rollout behavior; 202 tests passed. The initial rollback stopped before writes/
signals because a newer backend changed its inherited baseline; failure retained.
Fresh owner approval and verified newer baseline allowed a new helper/manifest-only
rollback and one scoped status-child reconnect. Ten fresh sanitized sessions and
unchanged supervisor/viewers/agents, unrelated installed files and all 18 service
records were verified. No backend credentials/policy or remote hosts were changed.
See [deployment status](DEPLOYMENT.md).

## Open it

```sh
pi-desk
```

This opens the shared workspace **in the current terminal**, just as `pi` opens
its TUI. Open a new terminal after installation for the PATH update, or run
`~/.local/bin/pi-desk`. On Macs, `~/Applications/Pi Desk.app` opens a dedicated
black Terminal window with 14 pt Menlo. Existing terminal profiles are untouched.
The app sets its own profile, not Terminal's default profile.

On the Raspberry Pi, the existing Foot/labwc fullscreen service still starts at
boot. `pi-desk-display` (or legacy `mac-sessions`) switches to that display;
`pi-desk` itself is now the portable terminal command. Multiple terminal viewers
are supported, with one elected status monitor per machine and failover on exit.

## Interface

The persistent `PI-DESK` top row uses the JARVIS app's dark accent purple
(`#D183E8`). The header has a uniform dark (`#1e1e1e`) background, with no boxes
around session indicators. Numbers in the visible group use soft purple (`#B28CBD`);
the focused number uses bright accent purple (`#D183E8`), bold and underlined.
Only the digits receive focus decoration—not spaces, lifecycle glyphs or controls.
The active pane's `Session N` title retains its bold deeper-purple (`#8D4CA3`)
badge with white text. This keeps white
above VS Code's default 4.5:1 contrast threshold, preventing automatic darkening
of selected labels without changing terminal-wide settings. Inactive titles also
use white text on the dark background. Horizontal title-row lines, shared junctions
and vertical dividers use thicker, single-stroke heavy-line glyphs in the same
true-colour grey (`#8a8a8a`) in every focus state. Its 4.83:1 contrast on the dark
background also clears VS Code's default adjustment threshold. tmux's half-border focus indicator is disabled;
the title badge and selected number identify focus even in one- and two-pane
layouts. No extra rows or columns are used. The top row contains
ten clickable session numbers and lifecycle icons, with shortcut hints aligned at
the right. A matching grey `┃` separates `PI-DESK` from the session tabs, and
separates Codex quota, Restart and Switch on the right. Control dividers appear
only between visible sections; their cell widths count toward hint shortening.
The title divider is omitted if it would hide a session tab, including sliding-tab
layouts. Hints shorten or disappear as space runs out; below 100 columns the
tabs tighten. Extremely narrow terminals show a sliding subset with hidden-tab
indicators, always keeping the focused session clickable; Ctrl + ←/→ still reaches all
ten sessions. Numbers use two digits, with heavy `┃` separators in the same true-colour grey
(`#8a8a8a`) and line weight as the pane dividers, matching the current one-, two-,
or three-session groups; there are no group labels. Running
sessions use the ten-frame Pi-style braille spinner (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) every
80 ms (0.8-second cycle), matching Pi TUI's default loader. Compacting uses the
same speed and direction; colour distinguishes the busy states. The palette is: running green, compacting neutral grey
`#8A8A8A`, idle purple, new cyan, offline grey, unknown amber. Static icons are
idle `●`, new `○`, offline `×`, and unknown `?` (including missing/unrecognised
states). All icons/spinners and padding share the same dark
header background, with number-only bold/underline explicitly reset. This uses the existing
shared monitor, not terminal blink support. Animation frames reuse cached status
and viewer metadata; metadata/health checks retain their 500 ms cadence and the
host feed retains its three-second cadence. Frame deadlines stay independent of
snapshot refreshes, so metadata checks do not shift the spinner cadence.
Frames update only changed headers,
not the warning row or pane layout. With no busy sessions there are no animation
wakeups. Set `PI_DESK_SPINNER=ascii` before starting the elected monitor for a
single-cell ASCII fallback (`|/-\\`, idle `.`, new `o`, offline `x`, unknown `?`),
or `PI_DESK_SPINNER=off` for reduced motion: running/compacting become steady `●`
while static states retain their distinct icons.
These settings belong to that machine's shared monitor, not individual viewers. A second row appears only for
connection/diagnostic warnings and disappears when healthy, returning its terminal
row to the coding panes. Healthy diagnostic values are hidden.
Coding workspaces adapt automatically to the terminal width, keeping the selected
session visible and focused. No extra menu pane. Last selected session is restored
independently on each machine.

### Codex quota in the header

The right-hand header shows **remaining** account-wide Codex quota, using the
same sanitized jarvisd cache as the JARVIS app:

```text
Codex W:68% · 5h:91%
```

`W` means weekly, `5h` means the five-hour window. Percentages still mean quota
remaining, without a trailing word in the header. Click the block to show available
reset countdowns in an eight-second, client-only status message; this never opens
a pane or changes focus. Only actual percentages (including `%`) are coloured,
independently for each window: JARVIS iPhone's dark accent purple (`#D183E8`) at
30% or more remaining, and its critical red (`#FF3847`) below 30%. There is no
amber band. All other quota text, punctuation and placeholders use neutral grey
(`#8A8A8A`). A five-hour window is shown only when a valid percentage is available
and the window is not explicitly unenforced. Otherwise its entire section,
separator and click-detail line are omitted; the header becomes `Codex W:68%`.
There is no `5h:n/a` placeholder. Missing weekly values remain grey `n/a`, not 0%;
hiding an unavailable 5h reading does not imply there is no limit. Only real
exhaustion displays 0%.

Shortcut hints shorten/disappear before quota does. When necessary the block
shrinks to `Codex W:68%`, then disappears if there is no room. Quota never
hides a session tab or takes a second row. A missing weekly value uses the
five-hour value in the compact form instead.

Unavailable and stale readings show muted `Codex unavailable` / `Codex stale`,
without old percentages. Quota freshness is independent of session status: the
sample retains its original checked timestamp and expires after 15 minutes,
matching jarvisd's quota cache. Reset countdowns use the absolute reset timestamp;
a passed reset never invents a replenished quota. No credentials, account details,
provider errors, or conversation contents leave the host. The existing three-second
state stream carries one extra allowlisted field; there are no additional provider
requests or model probes. Older viewers ignore that field and retain session status.

After updating Python files, detach **all viewers on the updated machine** with
Ctrl+A then d, and reopen `pi-desk` so the elected monitor loads the new renderer.
Hosted agents and their conversations keep running. Remote installs require the
same source update separately.

### Responsive layout

| Terminal columns (initial open) | Maximum visible sessions | Groups |
| --- | --- | --- |
| 1–104 | 1 | Selected session only |
| 105–157 | 2 | 1/2, 3/4, 5/6, 7/8, 9/10 |
| 158+ | 3 | 1/2/3, 4/5/6, 7/8/9, 10 alone |

The default target is 52 columns per pane plus one column per divider. A 110×45
terminal shows two panes; a 184×45 terminal retains three panes. Panes remain horizontal; terminal height
controls content height, not the group size. Resizing or changing terminal font
size automatically regroups after approximately 180 ms without further size
changes. Shrinking uses the table boundaries; growing requires four extra columns
(109 for two, 162 for three) to avoid oscillation at a boundary.

Focus is preserved: session 5 stays selected through `4/5/6` → `5/6` → `5`.
The session-group separators follow the group size and disappear in one-session
mode; title/control dividers remain when space permits.
The final group is not padded with empty panes. Each viewer has a private local
display workspace, so a narrow window cannot rearrange another wider window.
Existing display attachment processes are parked in hidden windows and reused
when groups change; opening additional groups creates their attachments lazily.
Group changes batch pane moves, ordering, focus and readiness updates into one
tmux command queue, with one final layout equalization, to reduce intermediate
redraws. tmux can still deliver resize notifications; this is not a guarantee of
flicker-free rendering. Closing a viewer removes only that viewer's display
workspace, never the agents. Each private viewer enables session-scoped tmux
`destroy-unattached` after its first display attaches, so the last display's exit
also cleans up parked connections when Python shutdown handlers cannot run.
Newly starting, still-unattached viewers are not auto-destroyed. On startup, a
serialized orphan sweep removes only tagged viewers older than two minutes with
no display attached and a positively dead owner PID; attachment and identity are
rechecked inside tmux before deletion. Live, ambiguous, and untagged legacy
workspaces are retained for explicit inspection. You may close or kill the terminal
and run `pi-desk` again; graceful detachment is not required. On macOS, startup probes
only the display server. If terminal output is wedged after a close/kill, it
verifies the current user's exact Pi Desk socket and server, then clears only
that server's terminal-output queues until the read-only probe responds. This
also covers a VS Code terminal that still appears live after its display client
has disappeared. Recovery may take a few seconds and discard pending display
bytes; it never signals/restarts agents, kills a server, changes terminal
settings, or retries a potentially partially executed workspace mutation. Healthy
live displays are not flushed by this fallback. A hard kill before the first
attachment can leave display panes until the next guarded startup sweep; it does
not end the hosted conversations. Unrecoverable stalls
still produce a bounded error instead of restarting agents.

To tune the target pane width, set `PI_DESK_MIN_COLUMNS` before opening a viewer:

```sh
PI_DESK_MIN_COLUMNS=60 pi-desk  # prefer wider panes (the original thresholds)
```

Accepted values are 20–300; invalid values use 52. Each viewer retains its own
setting until it closes.

| Control | Action |
| --- | --- |
| Click a number | Open its current-size group and focus that session |
| Ctrl+A, then g | Selection alternative for Mac function/media keys |
| Ctrl + ←/→ | Previous/next session, crossing group boundaries |
| Click a pane | Focus that pane |
| F10 or Ctrl+A, then Shift+R | Confirm in the top bar, then restart in the background |
| Ctrl+A, then d | Leave this viewer; agents keep running |

Clicks and numbered selections within a ready visible group use a focus-only path,
validating current pane indices, session tags, liveness and responsive capacity
before switching focus. Stale, dead, missing or out-of-group panes still use the
normal recovery/regrouping path; healthy selections do not equalize the layout.

Navigation stops at 1 and 10. Plain arrows are unchanged. Font/fullscreen controls
belong to the terminal: Cmd+Plus/Minus and Ctrl+Cmd+F on macOS; Ctrl+Plus/Minus and
Alt+F11 in the Pi desktop. The Pi retains 1080p, 14 pt DejaVu/Noto Emoji and a black
background. The Mac app requests a 173×47 terminal; ordinary CLI usage preserves
the user's terminal size/profile.

### Selecting and copying text

Drag normally to select text; releasing the mouse keeps the highlight. Selection
snapshots only the outer viewer pane, even when the nested agent terminal requests
mouse input. That pane's display stays steady while selected; agents and other
panes continue running. Click a pane, divider or header to dismiss and resume the
live view. A session-header click also focuses that pane's prompt. Typing while a
mouse selection is active dismisses it and sends the full input to the prompt,
including the first character. Escape or Enter dismisses without copying or
submitting. Double-click selects a word; triple-click selects a line. Ordinary
keyboard-entered tmux copy mode keeps its original controls. Layout/font changes
can still invalidate or reshape terminal selections; this is not a browser DOM
transcript.

For **Cmd+C in local macOS VS Code**, install the optional
[vscode-selection bridge](vscode-selection/README.md). Cmd+C copies without clearing
the highlight, and native Option-drag selections retain VS Code's built-in copying.
The bridge applies only to a terminal titled exactly `pi-desk`; normal terminals
and editors are unchanged. No hosted-session configuration or restarts are needed.
Without the bridge, use tmux's ordinary copy-mode keyboard controls. On macOS the
Pi Desk display uses `pbcopy`; other terminals/platforms retain tmux's normal
clipboard transport. Remote-shell clipboard behaviour is described in the bridge
README. The shared installer ships the bridge but never installs it automatically
or rewrites VS Code settings.

### Terminal tab title

Pi Desk sets the outer terminal title to `pi-desk` while its tmux viewer is attached,
independent of coding-pane titles or the selected session. tmux saves/restores the
previous title on attach/detach in supported terminals, including VS Code.

VS Code normally labels tabs by process name, which shows `Python` for the launcher.
Set `"terminal.integrated.tabs.title": "${sequence}"` in the workspace's
`.vscode/settings.json` so terminals display app-supplied titles instead (with a
process-name fallback if no title is supplied). This is workspace-only, not a
global VS Code setting; other terminals also use their normal shell/app titles.
Manually renamed tabs retain their explicit names. `.vscode/` is local/ignored in
this repository, so apply the setting separately in other workspaces or clones.

### Links in VS Code's terminal

Pi Desk advertises OSC 8 hyperlink support to VS Code (`TERM_PROGRAM=vscode`)
without assuming every `xterm-256color` terminal supports embedded links. After
updating, detach with Ctrl+A then d and run `pi-desk` again to apply the viewer
capability; agents keep running. To enable embedded Markdown links in an already
running Pi session, set **Terminal → Hyperlinks** to **true** with Pi's `/settings`,
then run `/reload` in that session. Pi caches terminal capability detection, so
reopening the viewer alone may not update a running agent. Use VS Code's normal
link gesture (Cmd-click on macOS). Plain URL detection is provided by VS Code.

## Start/restart agents without VS Code

```sh
pi-desk restart            # press Enter to confirm; Ctrl+C to cancel
pi-desk restart --dry-run  # preflight only, no changes
```

F10 asks for confirmation in the top bar, then runs in the background with
progress in the top status area; session navigation and input remain available.
Labels identify sessions explicitly, e.g. **Waiting for idle: session #1** and
**Restart failed: session #3** (session IDs, not counts); **8/10 ready** is a count.
Completion/failure stays visible for 60 seconds. Full helper output is saved locally
to `~/.local/state/pi-desk/restart.log`; shortcut/launcher diagnostics are appended
to `~/.local/state/pi-desk/restart-dispatch.log`. Shortcuts never print command output
into a coding pane or open tmux's error-output viewer. Real failures still appear in
the progress status/logs and retain nonzero exit codes for direct CLI callers.
Repeated confirmed F10 requests requeue sessions already marked ready, without
launching another helper or resetting waiting/restarting sessions. Requeued sessions
get their own 30-minute idle wait and the same identity/status safety checks; failed
slots are not retried. Rapid duplicate requests coalesce while a slot is queued or
starting. The original worker keeps its progress/log. A worker started before this
feature was installed cannot accept requests; let it finish first. The terminal
command above remains interactive (and does not provide this F10 control channel).
Both delegate to the host's existing
`jarvis-mobile-vscode-restart.py --all` helper rather than duplicating its safety
logic. All ten identities and status records must pass preflight. Stale, unknown,
or ambiguous status blocks the operation. Each busy session waits until idle
(up to 30 minutes); idle sessions restart immediately and startups overlap.
Each slot's identity, conversation path and fresh status are rechecked before
respawn. A changed conversation or PID fails that slot rather than guessing.
This is polling, not an input lock: avoid sending new work during the restart.
Existing conversations resume by explicit session path; initially missing/dead
slots start fresh. This affects **every** viewer. Progress counts verified ready
sessions, regardless of completion order. Partial failures are reported, other
slots continue, and failures are never automatically retried. In the interactive
terminal command only, Ctrl+C cancels remaining work, but does not undo
already-started restarts.

Opening Pi Desk, switching groups, recovering SSH, and closing a viewer **never
restart agents**. If hosted slots are absent, explicitly use start/restart after
reviewing the confirmation. Existing VS Code tasks remain available as fallback;
they have not been removed or changed.

## Shared app, explicit transport

Installed source: `~/.local/share/pi-desk/` on every machine.
Private machine configuration: `~/.config/pi-desk/client.json`.

| Machine | Backend | Hosted sessions |
| --- | --- | --- |
| mac-mini-64 | `local` | Its existing `jarvis-mobile` socket |
| mac-mini-16 | `ssh` | mac-mini-64's same socket |
| Raspberry Pi | `ssh` | mac-mini-64's same socket |

There is no hostname guessing. A missing config retains the original SSH default;
invalid configuration fails closed. SSH uses the existing alias/keys, strict host
verification, no agent/X11/port forwarding, bounded connect/keepalive timeouts,
and automatic attachment/status reconnection. No keys or credentials are copied.

The separate **local `pi-desk` tmux socket** holds only display panes. Hosted
attachments use `-E -f ignore-size`: they do not update the host's tmux environment
or detach existing clients. No host resize/layout commands are issued by the
viewer. **tmux sizing caveat:** when *all* attached clients have `ignore-size`,
tmux can fall back to the latest client's dimensions and reflow a hosted pane.
The flag is not an absolute guarantee against reflow; this was observed during
Mac acceptance. Agent identities/conversations are unaffected. Only local display
panes are regrouped and equalized on terminal resize. Display panes remain stable
through regrouping, but different viewers still attach to the same underlying
agents and can encounter that host-side reflow caveat.

## Status and diagnostics

Running green, Idle purple, New cyan, Compacting vivid orange (`#FF7A00`), Offline
grey, Unknown muted amber. Compaction's exact RGB is mirrored by the JARVIS app's
shared phone/Watch/Home palette; the app's native animation is unchanged.
The host projects numbered lifecycle labels from the existing trusted-loopback
jarvisd endpoint every 3 seconds. Local viewing uses a local subprocess; remote
viewing streams the same installed helper over SSH. No transcript data is sent
by the status stream. Samples older than 15 seconds become Unknown; a stream
silent for 12 seconds is retried. Failures never imply that the host is off.
The shared monitor fetches selection and viewer metadata in one tmux client call
per tick. Changed global and viewer headers are written with at most one further
client call through a short-lived private command file, avoiding tmux's argv-size
limit. Unchanged headers and saved selections are not rewritten; closed viewers
are skipped at execution time. Polling intervals and warning-row behaviour are
unchanged.

Mac diagnostics show local/SSH mode and local load, without Linux-only commands.
Pi diagnostics retain Wi-Fi association signal, host ping, CPU temperature and
presence-service state: 10-second sampling, bounded commands, 25-second expiry.
**Presence active means only that the service is running**, not fresh sensing or
human presence. No radio scans, new ports, privileged health commands or logs.

## Install/update

Python 3.9+ and tmux 3.3+ are required. Macs can install tmux with Homebrew. Both
remote clients must already have a working, trusted `mac-mini-64` SSH alias.
From a reviewed source/staging directory:

```sh
# Primary Mac only:
python3 install.py --backend local

# Secondary Mac:
python3 install.py --backend ssh

# Pi with its existing fullscreen adapter/account/permissions:
sudo systemctl stop pi-desk.service
python3 install.py --backend ssh --pi-desktop
sudo systemctl daemon-reload
sudo systemctl enable --now pi-desk.service
```

`install_pi.py` remains a compatibility entry point for the last option. The Pi
adapter alone depends on labwc, Foot, wlr-randr, HDMI-A-1, tty3 and the existing
pi account/sudo policy. No installer starts/restarts hosted agents. Mac installation
does not touch system services, Terminal defaults, VS Code tasks or other apps.
Only an explicit PATH line is appended to `.zshrc` (Mac) or `.bashrc` (Pi).
The host repository path for maintenance can be set with `--project-root`.

Close and reopen **all local viewers** after updating Python code so the elected
status monitor also uses the new renderer. Existing fixed-group viewers are not
live-migrated or forcibly detached. Remote installations must be updated separately. If resetting display panes is needed,
stop only the dedicated `pi-desk` socket, **never `jarvis-mobile`**. The Pi service
owns only its compositor/display and does not control presence/audio/Bluetooth/SSH.

## Implementation

- `cli.py`: common `pi-desk` entry point and confirmed maintenance.
- `backend.py`: validated local/SSH commands and cleaned nesting environment.
- `connect.py`: reconnecting attachment; `connect.sh` is a compatibility shim.
- `desktop.py`, `core.py`: UI, selection, shared status stream and pane recovery.
  Each viewer watches its terminal dimensions without idle subprocess polling.
- `layout.py`: width policy, hysteresis, group mapping and navigation shapes.
- `workspace.py`: private viewer workspaces, focus-preserving pane parking/reuse,
  and display-only cleanup. Legacy fixed-group helpers remain for old viewers.
- `native_navigation.py`: in-tmux, in-group arrow switching with live pane validation;
  the status monitor saves selection in the background. Cross-group keys reconcile
  the display through Python, as do missing/dead-pane repairs.
- `navigate.py`: fallback for adaptive and legacy workspaces.
- `health.py`, `status_stream.py`: bounded diagnostics and host lifecycle/quota projection.
- `codex_quota.py`: sanitized quota wire contract, independent freshness, colours,
  responsive labels and reset-countdown details.
- `install.py`: common deployment, manifest and allowlisted rollback copies.
- `launch.sh`, `config/`: optional Pi fullscreen adapter, shared tmux configuration,
  and Mac Terminal launcher.

## Backups, rollback and verification

Private rollback copies: `~/.local/state/pi-desk/backups/<UTC timestamp>/` on each
machine. All earlier backups remain intact. Shell profiles are **not** copied
because they may contain secrets; undo only the exact line marked `# Pi Desk CLI`
if removing the command. No credentials, IRKs, SSH configuration or transcripts
belong in Git or project backups. Historical source archive: [`backups/`](backups/).

To roll back, close Pi Desk viewers (stop its Pi service when applicable), restore
reviewed app/config/launcher files from that machine's backup or install a known-good
source revision with the correct backend. Do not blindly extract over `$HOME`.
An initial Mac install can be removed by deleting its dedicated app, launcher and
configuration, and removing the exact added PATH line; leave hosted sessions alone.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_pi_desk test_responsive
sh -n connect.sh && sh -n launch.sh
pi-desk --help
tmux -L pi-desk list-clients -F '#{session_name} focus=#{@pi-desk-session}'
```

Tests use isolated sockets, temporary state and sleep processes, never real agent
restarts. Deployment results and acceptance limits: [DEPLOYMENT.md](DEPLOYMENT.md).
