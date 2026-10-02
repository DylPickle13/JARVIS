# Pi Desk

One lightweight terminal workspace for the same ten Mac-hosted Pi Coding Agent
sessions, on **mac-mini-64, mac-mini-16 and Raspberry Pi**. No browser, desktop
streaming, or VS Code dependency. The agents always run on mac-mini-64.

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
(`#D183E8`); the selected session number uses it too. The active pane's `Session N`
title is a bold purple badge with dark text; inactive titles stay muted. Pane
dividers use thin grey lines in every focus state, keeping tmux's shared top
junctions understated instead of emphasizing protruding corners or an incomplete
outer frame. tmux's half-border focus indicator is disabled; the title badge and
selected number identify focus even in one- and two-pane layouts. No extra rows or
columns are used. The top row contains
ten clickable session numbers and lifecycle dots, with shortcut hints aligned at
the right. Hints shorten or disappear as space runs out; below 100 columns the
tabs tighten. Extremely narrow terminals show a sliding subset with hidden-tab
indicators, always keeping the focused session clickable; Ctrl + ←/→ still reaches all
ten sessions. Numbers use two digits, with muted separators matching the current
one-, two-, or three-session groups; there are no group labels. Running
and compacting dots alternate between bright and clearly dim shades every 0.75
seconds (a 1.5-second full cycle); other states stay steady. This uses the existing
shared monitor, not terminal blink support. A second row appears only for
connection/diagnostic warnings and disappears when healthy, returning its terminal
row to the coding panes. Healthy diagnostic values are hidden.
Coding workspaces adapt automatically to the terminal width, keeping the selected
session visible and focused. No extra menu pane. Last selected session is restored
independently on each machine.

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
The header separators follow the group size and disappear in one-session mode.
The final group is not padded with empty panes. Each viewer has a private local
display workspace, so a narrow window cannot rearrange another wider window.
Existing display attachment processes are parked in hidden windows and reused
when groups change; opening additional groups creates their attachments lazily.
Group changes batch pane moves, ordering, focus and readiness updates into one
tmux command queue, with one final layout equalization, to reduce intermediate
redraws. tmux can still deliver resize notifications; this is not a guarantee of
flicker-free rendering. Closing a viewer normally removes only that viewer's display
workspace, never the agents. You may close or kill the terminal and run
`pi-desk` again; graceful detachment is not required. On macOS, startup probes
only the display server. If terminal output is wedged after a close/kill, it
verifies the current user's exact Pi Desk socket and server, then clears only
that server's terminal-output queues until the read-only probe responds. This
also covers a VS Code terminal that still appears live after its display client
has disappeared. Recovery may take a few seconds and discard pending display
bytes; it never signals/restarts agents, kills a server, changes terminal
settings, or retries a potentially partially executed workspace mutation. Healthy
live displays are not flushed by this fallback. A hard kill can leave orphaned
display panes, but does not end the hosted conversations. Unrecoverable stalls
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
Completion/failure stays visible for 60 seconds. Full helper output is saved locally
to `~/.local/state/pi-desk/restart.log`; shortcut/launcher diagnostics are appended
to `~/.local/state/pi-desk/restart-dispatch.log`. Shortcuts never print command output
into a coding pane or open tmux's error-output viewer. Real failures still appear in
the progress status/logs and retain nonzero exit codes for direct CLI callers.
Repeated requests succeed as a no-op and show **Restart already in progress** in
only the invoking client's status message, without overwriting the original worker's
progress/log or launching another helper. The terminal command above remains
interactive. Both delegate to the host's existing
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

Running green, Idle purple, New cyan, Compacting blue, Offline grey, Unknown amber.
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
- `health.py`, `status_stream.py`: bounded diagnostics and host lifecycle projection.
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
