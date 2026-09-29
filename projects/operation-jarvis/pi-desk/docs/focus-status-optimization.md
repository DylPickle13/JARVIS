# Focus-only selection and batched status work

## Changes

Both optimizations are in `desktop.py`; workspace layout batching is unchanged.

### Ready-group clicks and F12

`choose()` still serializes selections with the existing selection lock. It checks
the invoking client's live window/pane information in one formatted tmux query:
viewer identity, width, capacity, minimum-width preference, reconciliation gate,
window index, and each visible pane's index/session tag/dead flag.

If the target belongs to the live healthy group and the current sizing policy
still agrees, focus and `@pi-desk-last` publication share one command queue. No
pane moves, respawns or layout equalization occur. The persisted selection is
updated under the same lock, but an unchanged value is not rewritten.

Readiness is not cached: malformed metadata, stale capacity, reconciliation in
progress, wrong pane order, dead/missing panes and group boundaries fall back to
the existing reconciliation path. tmux's pane loop can enumerate by pane ID;
validation compares indexed entries, not the loop's incidental enumeration order.
Legacy groups and native arrow bindings were not changed.

### Shared status monitor

Each tick reads selection and viewer metadata in one tmux command client, with
selection persistence under the existing lock. It computes the same global and
viewer-specific headers and submits changed writes with at most one additional
tmux client. An unchanged tick requires only the combined read.

A private mode-0600 temporary tmux command file avoids the argv IPC message-size
limit when several complete headers are batched. It is deleted after the command
returns, including error paths. Arguments are quoted; warnings containing quotes,
semicolons, dollar signs and hash characters remain literal. Viewer writes check
session existence at execution time so a closed viewer is skipped rather than
aborting surviving viewers' updates. Caches advance only after a successful call.

Status timing, pulse phase, warning-row height behaviour, freshness/retry policy,
shared monitor election and per-viewer headers are unchanged. No transcript data
is captured or put in command files. Only status/header metadata is involved.

## Validation

**92 source tests passed**, plus **32 responsive tests against the installed
modules**, on mac-mini-64/tmux 3.7c. All device/transport effects are mocked or on
unique isolated sockets with dummy applications. An existing wall-clock debounce
unit test was made deterministic after a load-related timing failure; production
resize/debounce code was not changed. New tests cover:

- Click/F12 dispatch in one-, two- and three-pane groups; zero layout mutations.
- Actual index/tag/liveness and hysteresis checks, including unordered pane loops.
- Fallback for stale flags/capacity, scrambled order, dead/missing panes and boundaries.
- Focus, global selection and file persistence, including unchanged file timestamps.
- Combined snapshots with valid, invalid and absent selection options.
- Several full headers exceeding 8192 bytes, command-file privacy and deletion.
- Literal quoted warnings, pulse changes, status-row removal and pane identity preservation.
- Viewer disappearance between snapshot and write.
- One read and at most one write per actual monitor tick.
- Failed batch retry without caching the failed render or retaining temporary files.

## Isolated comparison

Harness: `/tmp/pi-desk-flicker-research/compare-focus-status.py`.
Raw samples: `/tmp/pi-desk-flicker-research/focus-status-results.json`.

Compared the previous installed `desktop.py` with the candidate using unique
sockets, three dummy viewer sessions (184/110/80 columns), and one attached PTY.
Focus measurements include 36 synchronous `choose()` calls per version; each
status measurement uses 15 warm synchronous ticks after an initialization tick.
The final comparison was run without the test suite concurrently executing.

| Operation | Previous median duration | Updated median duration | tmux clients, previous → updated |
| --- | ---: | ---: | ---: |
| Ready-group selection | 39.00 ms | 15.48 ms | 8 → 3 |
| Unchanged idle status tick | 8.86 ms | 5.07 ms | 2 → 1 |
| Pulsing status tick, three viewers | 30.33 ms | 11.49 ms | 6 → 2 |

These are local software timings, not physical presentation latency, click-to-screen
latency, CLI helper process startup time, SSH latency or a measured CPU percentage.
Absolute timings vary with system load; the reduced command-client counts are the
more direct evidence. No Raspberry Pi/mac-mini-16 benchmark or visual acceptance
was performed.

## Activation

External click/F12 helpers import the new `desktop.py` on their next invocation.
The elected monitor in an already-running viewer keeps its imported old code.
Reopen local Pi Desk viewers to activate the lighter monitor; if several are open,
close all old viewers so the election cannot pass to another old monitor. Hosted
agents remain running. No live viewer/service/agent restart is necessary for the
file deployment itself.
