# Pi Desk memory investigation — 2026-10-08

## Resolution update — active and verified at 15:42 EDT

With owner approval, a private tmux 3.7c backport was built, stress-tested and
installed locally for Pi Desk only. **212 source + 212 staged-runtime tests and
5 bridge tests passed.** Patched guarded updates plateaued at 7–9 MiB across
12,000 frames. One graceful display detach released the old server's 3334 MiB
footprint; all ten hosted-agent process identities remained unchanged.

The owner reopened the fixed viewer in the original terminal. Its verified new
server stayed at **9.48–9.64 MiB** across four live samples over 30 seconds, with
no warning row. All ten hosted-agent identities remained unchanged. No automatic
terminal input or new window was used. Full deployment/rollback record:
[`../DEPLOYMENT.md`](../DEPLOYMENT.md).

## Finding

Pi Desk's installed **tmux 3.7c** has an upstream command-list reference-counting
leak triggered by the per-viewer `if-shell -F` guard in
`desktop.py:render_viewers`. The guard is useful: a viewer can disappear after
its metadata snapshot, and its disappearance must not abort another viewer's
updates. Do not simply remove this safety behavior.

The status monitor rewrites animated headers every 80 ms while any session is
running or compacting. Each successful guarded update retains its parsed command
list, including the several-kilobyte header. The accumulation is unrelated to
agent conversation history, Python buffers, or rendering a visible terminal.

Upstream fix, dated 2026-08-25:
https://github.com/tmux/tmux/commit/1459c90a7fa6a70afd1e8438fa9985141e4002be

It corrects ownership in `arguments.c` and releases the returned command lists
in `cmd-if-shell.c` and related callers. The installed 3.7c source predates the
fix. A complete backport must preserve the ownership changes, not copy only an
isolated `cmd_list_free` line.

## Live observations

- The Pi Desk tmux server had a 3.2 GB physical footprint after about 28 hours;
  it continued growing during the investigation.
- About 1 GB was resident; much of the remaining footprint was compressed or
  paged memory. The original report was not confusing RSS with total footprint.
- Ten display panes had **zero history lines**, and their reported grid/history
  storage together was under 0.5 MB.
- One actual viewer was attached. It was not an orphan, and no zombie processes
  were found.
- The Python wrapper used about 15 MiB. The wrapper plus ten Python attachment
  helpers together used about 117 MiB, not multiple gigabytes.
- Installed `connect.py`, `cli.py`, `core.py`, `status_stream.py`, and
  `config/tmux.conf` matched repository versions.

## Isolated reproduction

A scratch diagnostic at `/tmp/pi-desk-memory-audit-20261008.py` imported only the
header-rendering helpers, redirected **both** tmux socket constants to a fresh
`pd-memory-audit-*` socket, and used a sleeping dummy pane. Status was synthetic;
there was no status feed, backend request, real agent attachment, pane content
capture, or visible terminal window. Attached cases used an offscreen PTY drained
by a local thread. Every diagnostic server and socket was removed on completion.

Measurements are physical footprint bytes converted to MiB:

| Case | Frames | Initial | Final | Behavior |
| --- | ---: | ---: | ---: | --- |
| Actual global + guarded viewer updates, attached | 1,600 | 3.00 MiB | 17.16 MiB | Continued growth after warm-up |
| Actual global + guarded viewer updates, **detached** | 2,400 | 2.70 MiB | 20.00 MiB | Continued growth with no display |
| Direct responsive header updates, attached | 2,400 | 2.98 MiB | 6.86 MiB | Plateau by ~800 frames |
| Direct legacy header updates, attached | 2,400 | 3.00 MiB | 7.92 MiB | Plateau by ~800 frames |
| Plain header updates, attached | 1,600 | 2.98 MiB | 2.95 MiB | Stable |
| RGB + Unicode spinner header, attached | 1,600 | 2.98 MiB | 3.05 MiB | Stable |

After warm-up, the guarded detached case added approximately **5.6 KiB per
update**. At the production maximum of 12.5 updates/second, this corresponds to
roughly **250 MiB/hour per viewer** while animation is active. This is an estimate
from accelerated synthetic updates, not a measured day-long production rate.

The detached result rules out GPU rendering, terminal scrollback, and actual
agent output as necessary causes. Ordinary RGB/Unicode updates and direct large
header writes stabilize, isolating the guarded command path. The corresponding
upstream fix establishes the ownership error in that path.

## Recommended next step

1. Obtain a tmux build containing the complete upstream fix, preferably a narrow
   backport to the current version rather than an unreviewed development upgrade.
2. Run the guarded-update reproducer against that build and confirm the memory
   slope disappears; retain the viewer-disappearance guard and current UI.
3. Run Pi Desk's existing isolated navigation, resizing, cleanup, and selection
   tests before any rollout.
4. With owner approval, deploy the verified build and reopen **only the Pi Desk
   display viewer**. A new binary does not repair an already-running old server,
   and its accumulated memory will not disappear without replacing that server.
5. Preserve the independent `jarvis-mobile` server and all hosted agents.

A viewer-only restart would reclaim the immediate allocation but is temporary
relief, not a fix. Slowing or disabling animation would reduce the trigger rate
but also would not correct the underlying leak.

## Scope

Investigation only: no production files, tmux options, viewer layouts, services,
or agents were changed or restarted. All ten hosted pane identities remained
unchanged. This report is the only repository addition.
