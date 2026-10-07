# iPhone terminal links

**Build 260 installed once on each approved iPhone and Watch, 2026-10-07.**
Both installed versions are independently verified. iPhone is verified running;
Watch launch remains unconfirmed. Physical gesture/VoiceOver acceptance is owner
review, not established by installation or simulator tests.

## Interaction

- Tap a formatted Pi link or a plain HTTP/HTTPS URL to open its destination using
  iOS's normal URL routing. This does not open the terminal keyboard or emit SSH
  input. Tapping other text retains the existing keyboard-focus behavior.
- Long-press a link for **Copy**, **Open Link** and **Copy Link**. Copy remains
  ordinary selected-text copying; Copy Link copies the destination URL rather
  than the visible label. Ordinary text retains Copy only.
- A tap while text is selected dismisses selection without opening a link.
  Editing selection handles removes link actions and returns to text selection.
- Selection actions are invalidated on dismissal, reselection, handle editing,
  resize and connection/session transitions. The held destination stays tied to
  the long-pressed content while incoming terminal output continues parsing.
- Only HTTP/HTTPS URLs with a host are eligible. File, mail, custom app and
  script schemes are not opened; raw whitespace/control characters are rejected.
  Receiving output alone never opens a URL or reads the clipboard.

## Implementation

`JARVIS/Terminal/PiSSHTransport.swift` installs one custom single-tap recognizer
instead of SwiftTerm's focus/hover-dependent tap. It waits for inline selection
and long-press arbitration and uses SwiftTerm 1.20.0's public cell-aware link
lookup: OSC 8 metadata first, then plain URL detection. Wide graphemes, logical
line wraps and viewport coordinates are respected. Incomplete synchronized
output frames cannot activate links.

A long-press resolves the URL before cropping to visible rows, so a plain URL
starting above the viewport remains usable. The bounded held presentation
re-interns hyperlink payloads using terminal-managed atoms, as it already does
for graphemes. Each distinct payload is allocated once per held viewport and is
released with that terminal, independently of resets in the live terminal.

`config/jarvis-mobile.tmux.conf` advertises `hyperlinks` for the iPhone SSH PTY's
`xterm-256color` capability, retaining RGB and extended keys. Without this flag,
tmux can display Pi's formatted label while stripping its hidden destination.
The existing launcher reapplies this profile on attachment; no manual live tmux
reload, Pi restart, backend restart or Watch behavior change is part of this update.
Links whose metadata was already stripped cannot be recovered from labels alone;
new output or Pi's normal redraw is needed after the profile takes effect.

## Verification and limits

Native fixtures cover formatted/ordinary links, URL semicolons, punctuation,
wraps, off-viewport URL starts, Unicode/wide cells, incomplete synchronized
frames, keyboard-proxy focus, no terminal input/clipboard reads, link menus,
held metadata through live reset, selection editing and stale action rejection.
Existing clipboard, scrolling and keyboard-viewport regressions remain intact.

`terminald/tests/test_terminal_hyperlinks.py` uses disposable tmux sockets and a
synthetic xterm-256color PTY. It verifies actual OSC 8 forwarding with the profile
capability and reproduces the lost-destination behavior without it. It imports
only capability declarations, never the live maintenance hooks.

Frozen revision 2 (269 inputs) passed **202 iPhone tests**, including 17 new
link/profile cases; **347 shared cases** (3 expected live-test skips); **39 terminal
cases**, including both real tmux-forwarding fixtures; and both simulator builds.
The dedicated iPhone simulator returned to Shutdown. Evidence and frozen-source
hashes are retained in private `jarvis-terminal-links.S46PPv/revision2` evidence;
the initial candidate and an incorrect-working-directory Python invocation are
also retained separately. That invocation's import errors were corrected by
running from the app directory, without changing or excluding Python tests.
The final frozen inputs were checked against the repository before this
results-only documentation update.

The previously documented `testPlainPasteButtonRendersWithoutBlackPlatter` pixel
assertion remains excluded from native validation.

## Deployment and remaining acceptance

Owner approved installation and supplied fresh readiness. Two initial read-only
checks stopped before any installation: Watch identity timed out first; the next
reached compatible DDI/unlock but app inventory reported no mounted DDI information.
A fresh owner **“watch is ready still”** check passed all original gates with a
bounded resource-unwind pause before inventory; neither failed helper was replayed.

Build **260** repeated the same test counts/both simulator builds against **269
frozen inputs**, archived using existing paid-team signing without portal changes,
and passed eight candidate/rollback signatures, byte-identical profiles, unchanged
entitlements/dependency locks and source/payload seals. The first offline builder
stopped after passing native tests because the simulator was already Shutdown;
a new continuation retained that evidence and completed the remaining checks.

The exact sealed products were installed **once per device**. Both versions and
the iPhone's current process were independently verified at **11:30 EDT**. The
Watch launch returned a PID, but that process was absent at the ten-second
follow-up; the installer stopped and its receipt remains intact. A separate
read-only verification reconfirmed both installed versions, iPhone running and
Watch not currently running. No install or launch was replayed. Open JARVIS on the
Watch manually; physical Watch launch acceptance remains unconfirmed.

Final read-only checks preserved **18 service records** (17 continuous), existing
Pi/Minecraft/gateway identities, backend/configuration/authentication and ten-second
history cadence. The current verified network-only frame backend explicitly
retains its preceding device registry; preservation checks verify its exact
declared path/hash and immutable deployment receipt, without changing any backend.
No service restart, Pi input, manual tmux reload, credential/profile/dependency
change, reset, rebuild of sealed products or pruning occurred. Exact signed
installed **259** is retained rollback. Private signed/deployment evidence:
`20261007T150514Z-build260-terminal-links`.

Test tap-to-open and long-press **Open Link / Copy Link** on the iPhone, then return
from the browser and verify normal scrolling, ordinary Copy and keyboard focus.
Already-stripped old link labels need new output/a normal Pi redraw after the
profile is applied on attachment. No live terminal input or physical link opening
was performed by this deployment.
