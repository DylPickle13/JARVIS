# Pi Desk navigation flicker: findings and recommended fix

## Chosen implementation: batching

The user selected the simpler batching approach instead of whole-group caching.
`workspace.reconcile()` now plans against a pane snapshot, uses stable pane IDs
and explicit join targets to track order, and submits pane mutations, focus and
readiness publication in one queue with one final equalization. Existing lazy
attachment creation and per-viewer layout isolation are retained. Readiness is
still published last; a failed batch leaves native navigation gated for recovery.

All **84 tests passed**, including new command-batching, partial-failure recovery,
scrambled-order, missing-window and narrow custom-pane regressions. A fresh isolated comparison
of the previous installed implementation and the actual candidate (12 warm
three-pane switches each) found:

| Metric, median | Previous | Implemented batching |
| --- | ---: | ---: |
| Command duration | 140.30 ms | 46.32 ms |
| Resize notifications across all six dummy apps | 10 | 6 |
| Terminal-output bytes | 101,935 | 28,585 |
| Last observed PTY output | 403.75 ms | 47.61 ms |

These are synthetic stream measurements, not real screen latency. Approximately
72% less terminal output does not mean 72% less perceptual flicker.

Comparison harness: `/tmp/pi-desk-flicker-research/compare-implementation.py`.
Raw results: `/tmp/pi-desk-flicker-research/implementation-results.json`.
The earlier prototype measurements and cache recommendation below remain research
context; cached group windows and synchronized-output changes were not implemented.

## Research conclusion

Prefer **viewer-private cached group windows**, retaining each group's complete
pane layout and its existing attachment processes. For an already prepared group
at unchanged geometry, switch the whole window instead of dismantling/reassembling
its panes. Batch cache construction/regrouping commands as a secondary improvement.
Use terminal synchronized updates only as a capability-gated rendering enhancement,
not as a substitute for preventing unnecessary resize events.

This is a researched recommendation and an isolated prototype result, **not a
production implementation or a guarantee of zero visible flicker**.

## What the installed code does

The installed `workspace.py`, `native_navigation.py` and `config/tmux.conf` matched
the repository versions during inspection. The local tmux version was 3.7c.

- `native_navigation.binding()` changes focus directly within a ready group.
  Crossing a group boundary invokes the Python reconciliation fallback.
- `workspace.reconcile()` swaps the selected incoming pane into window 0, breaks
  outgoing panes into individual hidden windows, joins incoming panes, repeatedly
  selects an even layout, and restores numeric pane order.
- Each `core.tmux()` call starts a separate tmux command client. Redraws and resize
  processing can happen between these calls.
- Parking individual panes does not preserve their tiled dimensions. The live
  viewer's visible panes were about 56–57 columns wide while several hidden
  one-pane windows were 172 columns wide.
- `backend.attachment()` uses nested hosted tmux attachment with `ignore-size`.
  That flag does not eliminate every host-side reflow: tmux can consider flagged
  clients when no eligible unflagged clients exist. No live agent was resized,
  restarted or manipulated for these experiments.

This supports a concrete mechanism: group-boundary navigation changes display
pane geometry repeatedly, triggering terminal/app redraws. It does not prove that
all flicker observed in every viewer has this single cause.

## Isolated comparison

Probe: `/tmp/pi-desk-flicker-research/probe.py`
Raw measurements: `/tmp/pi-desk-flicker-research/results.json`

Three independent runs per approach, four warm transitions each (1/2/3 ↔ 4/5/6),
using a 184×45 PTY, tmux 3.7c, synthetic full-screen applications that log
SIGWINCH and redraw their screen. Unique `pi-desk-research-*` sockets were created
and destroyed. No live Pi Desk or `jarvis-mobile` mutation commands were issued.

| Approach | Median resize signals across six dummy apps per switch | Median terminal-output bytes | Median command duration |
| --- | ---: | ---: | ---: |
| Current `workspace.reconcile()` | 10 | 101,903 | 130.41 ms |
| Batched pane operations, one final layout | 6 | 18,481.5 | 25.87 ms |
| Intact cached group-window swap | 0 | 10,079 | 24.98 ms |

All measured transitions ended with the correct numeric pane order. The batched
prototype retains an initial pane-ID discovery query, then submits mutations in
one command list. The cached prototype likewise discovers the selected pane,
then uses `swap-window -d` and `select-pane` in one command list.

Median last PTY-output times after beginning the transition were 418.21 ms for
the current path, 27.09 ms for the batch prototype and 24.73 ms for the cached
prototype. These are **synthetic terminal-stream observations**, not screen
presentation times, native-key latency, SSH latency or a production benchmark.
Output is monitored for 600 ms after mutation commands return.

The comparison covers warm three-pane transitions only. It does not validate
cold group creation, one/two-pane groups, session 10, resizing, multiple viewers,
dead-pane recovery, real agent output or renderer-specific visual flicker.
Those remain implementation acceptance requirements.

## Why batching alone is not the strongest fix

Upstream tmux queues pane resize requests. Its resize processor uses a 250 ms
rate-limit timer in ordinary cases. When multiple queued resizes return to the
original size, tmux deliberately emits an intermediate resize and then the final
resize, with a shortened 10 ms timer, to force the application to redraw.

Thus, one command list is useful for reducing process overhead/intermediate
visible layouts, but it is not a layout transaction that promises zero SIGWINCH.
The experiment directly confirmed remaining resize notifications after batching.

An intact window swap preserves the layout and pane geometry at fixed terminal
size. The prototype produced no resize signals for warm group switches and about
90% fewer terminal bytes than the current path in this synthetic workload.

## Implementation direction

1. Cache complete group windows within each existing private `viewer-*` session.
   Do not return to shared legacy group sessions, which would compromise
   independent viewer sizing.
2. Keep one attachment process per numbered session per viewer. Reuse those
   processes on cache misses and responsive regrouping; never duplicate or
   restart hosted agents merely to populate layouts.
3. Keep window 0 as the visible slot if preserving current invariants is desired.
   A ready hidden group window can be swapped into slot 0 with `swap-window -d`;
   select its desired pane and publish session readiness/group metadata in the
   same native command list.
4. Extend the native navigation fast path to discover and validate a ready cached
   group by actual pane tags/order/liveness and geometry, then perform the swap
   without Python. Stale or dead cached groups must fall back to reconciliation.
5. On an uncached group or changed capacity, prepare the target layout off-screen,
   batch the necessary moves and apply one final even-horizontal layout. Preserve
   the outgoing whole group where possible. Wait for actual readiness rather than
   relying on a fixed sleep to conceal redraws.
6. Terminal width/height or status-row changes can invalidate geometry. Reconcile
   cached groups safely under the existing selection lock and readiness protocol;
   only resize/regroup when actually necessary. Preserve selected session and
   hysteresis behaviour.
7. As an optional final layer, advertise/use tmux's `sync` terminal feature only
   when the outer terminal supports it. The inspected live client's advertised
   features did not include `sync`. VS Code added DEC mode 2026 support in 1.108.
   Do not globally assume every `xterm-256color` terminal supports it.

The layout cache reuses processes that the current implementation already parks;
it need not require eager attachment to all ten sessions or additional agents.
Cold group creation and actual terminal resizes still entail legitimate redraws.
Renderer tearing and redraws originating in the agents themselves may remain.

## Acceptance tests before deployment

- All transitions and numeric focus at capacities 1, 2 and 3, including 9↔10.
- Warm fixed-geometry group changes produce zero attachment-pane SIGWINCH.
- Click/F12/native arrows agree; rapid input does not expose stale metadata.
- Resize and font changes preserve focus, capacity hysteresis and pane identity.
- Cold creation, dead/missing pane recovery and deleted windows remain safe.
- Two differently sized viewers cannot alter each other's display layouts.
- Local and SSH clients on the three supported machines; tmux 3.3 compatibility.
- Visual verification in VS Code, macOS Terminal and the Raspberry Pi's Foot.
- No hosted process/identity changes, extra connections per slot or transcript logs.

## Primary sources

- [tmux 3.7 pane resize queue](https://github.com/tmux/tmux/blob/3.7/server-client.c),
  `server_client_check_pane_resize()`.
- [Pane resize and TIOCSWINSZ](https://github.com/tmux/tmux/blob/3.7/window.c),
  `window_pane_resize()` and `window_pane_send_resize()`.
- [join-pane](https://github.com/tmux/tmux/blob/3.7/cmd-join-pane.c) and
  [break-pane](https://github.com/tmux/tmux/blob/3.7/cmd-break-pane.c).
- [swap-window implementation](https://github.com/tmux/tmux/blob/3.7/cmd-swap-window.c).
- [Client size selection](https://github.com/tmux/tmux/blob/3.7/resize.c),
  `ignore_client_size()`.
- [tmux manual: terminal features and Sync](https://github.com/tmux/tmux/blob/3.7/tmux.1).
- [VS Code 1.108: New VT features](https://code.visualstudio.com/updates/v1_108#_new-vt-features).
