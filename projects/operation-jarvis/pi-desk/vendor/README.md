# Viewer-only tmux 3.7c memory-leak backport

Pi Desk can use a private executable at its installed `bin/tmux`. Only display
commands use this build. System/Homebrew tmux, `jarvis-mobile`, hosted-agent
attachments, backend policy, and PATH are unchanged. Without a private binary,
other platforms retain their existing tmux. An invalid private binary fails
closed rather than silently reverting to a leaking build.

## Provenance

- Release: https://github.com/tmux/tmux/releases/tag/3.7c
- Archive: https://github.com/tmux/tmux/releases/download/3.7c/tmux-3.7c.tar.gz
- Archive SHA-256: `7c60cae9a0e25288e2e24750aafc9e8800fc7fd4555e447e1b29ee4201cfb3bf`
- Upstream fix: https://github.com/tmux/tmux/commit/1459c90a7fa6a70afd1e8438fa9985141e4002be
- Backport patch: `tmux-3.7c-refcount.patch`

The patch includes both sides of command-list ownership: `arguments.c` and
its affected callers. Upstream's `window-panes.c` does not exist in 3.7c; the
corresponding release caller is `cmd-display-panes.c`, where both queue insertion
branches receive the same ownership release. This adaptation was reviewed against
all release `args_make_commands` / `args_make_commands_now` callers. No features,
rendering, guards, animation cadence, configuration, or protocol were changed.

The tmux source license remains in the release archive. Distributions containing
the private executable must retain the release `COPYING` license alongside it.
No compiled platform-specific binary is committed to this repository.

## Rebuild on mac-mini-64

Use a **new private build directory** and the pinned release archive. Check the
archive hash before extraction. Do not run `make install` against Homebrew or
replace `/opt/homebrew/bin/tmux`.

```sh
cd "$BUILD/tmux-3.7c"
patch --dry-run --fuzz=0 -p1 < "$SOURCE/vendor/tmux-3.7c-refcount.patch"
patch --fuzz=0 -p1 < "$SOURCE/vendor/tmux-3.7c-refcount.patch"
CC=clang CFLAGS='-O2 -g' \
CPPFLAGS='-I/opt/homebrew/opt/libevent/include -I/opt/homebrew/opt/ncurses/include -I/opt/homebrew/opt/utf8proc/include -I/opt/homebrew/opt/jemalloc/include' \
LDFLAGS='-L/opt/homebrew/opt/libevent/lib -L/opt/homebrew/opt/ncurses/lib -L/opt/homebrew/opt/utf8proc/lib -L/opt/homebrew/opt/jemalloc/lib' \
JEMALLOC_CFLAGS='-I/opt/homebrew/opt/jemalloc/include' \
JEMALLOC_LIBS='-L/opt/homebrew/opt/jemalloc/lib -ljemalloc' \
./configure --prefix="$BUILD/staged" --enable-utf8proc --enable-jemalloc
make -j4
```

Explicit jemalloc flags allow the existing Homebrew dependencies to be used
without installing pkg-config or changing the machine's packages. `otool -L tmux`
should list the same utf8proc, ncurses, libevent, jemalloc and system libraries as
the original Homebrew build.

## Verify before deployment

```sh
python3 probe_memory.py --tmux "$BUILD/tmux-3.7c/tmux" \
  --mode actual --frames 6000 --assert-plateau
python3 probe_memory.py --tmux "$BUILD/tmux-3.7c/tmux" \
  --mode actual --frames 6000 --detached --assert-plateau
PATH="$BUILD/tmux-3.7c:$PATH" python3 -m unittest discover -p 'test_*.py'
```

The memory probe creates only fresh isolated sockets, sleeping dummy panes and
optional offscreen PTYs. It never reads real agent output, uses a real status
feed, connects to hosted sessions, or opens a terminal window. It removes its
own diagnostic servers and sockets in `finally`.

## Deployment and rollback

Deploy only the verified binary, its `COPYING` license/provenance metadata, the
small runtime selector, and the display caller/installer changes. Preserve all
unrelated installed files and manifest entries, including known unrelated drift.
Retain their original hashes and a rollback backup before atomic file replacement.

Replacing the file does not patch an already-running server. Detach the local
Pi Desk viewer normally, confirm its old display server exits, and run `pi-desk`
again in that same terminal. **Do not use F10 or the agent restart command.** No
hosted-agent process needs to restart, and no GUI focus or desktop switch is
required. Verify hosted server/pane/process identities before and afterward.

A rollback restores the scoped caller files and original manifest and removes
only the newly installed private build files; it does not replace system tmux or
restart agents. A viewer reopen is needed to activate either direction.
