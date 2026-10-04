# Pi managed installation

Migrated mac-mini-64 on 2026-10-03 from npm Pi 1.0.2 to managed Pi 1.0.2.
The official installer was downloaded, compared with the reviewed copy, and
executed locally without an interactive TUI or automatic Pi session startup.
Dependencies are installed with `npm ci --ignore-scripts` from the release lock.

## Launch and runtime resolution

- Official launcher: `~/.pi/agent/bin/pi` (already on PATH).
- Managed release: `~/.pi/agent/install/releases/1.0.2`.
- Active version: `~/.pi/agent/install/current-version`.
- Update with **`pi update`**, not `npm install -g`.
- `.pi/scripts/pi-cli` is the stable JARVIS launcher. It uses the managed
  launcher when its marker exists, otherwise the Homebrew-prefix npm CLI.
  It preserves arguments/signals and fails closed on an incomplete managed install.
- `.pi/scripts/pi-runtime.mjs` resolves the current release dynamically and
  finds dependencies using Node's lookup directories, supporting both nested
  npm dependencies and hoisted managed dependencies. Explicit
  `PI_CODEMODE_TEST_RUNTIME` / `PI_TEST_NODE_MODULES` test overrides still win.
- Mobile terminal, maintenance restart script, and room-audio launcher now use
  the stable project launcher. Their session-selection and permission logic
  are unchanged. No live services, Pi sessions, browser windows, or Spaces were
  restarted or manipulated during migration.

## Compatibility and completed cleanup

`/opt/homebrew/bin/pi` -> `~/.pi/agent/bin/pi` remains as an executable alias
for shell command caches and older supervisor code. It always launches the
**managed current release**, not the backup snapshot.

The temporary package link at
`/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent` was removed
after sir restarted the sessions and the standalone pre-migration VS Code
process exited. All ten remaining Pi process IDs matched the `jarvis-ios`
panes launched through `.pi/scripts/pi-cli`; this conversation's tool ancestry
also resolved to one of those managed sessions. Only the verified symlink was
unlinked. The legacy runtime backup was temporarily retained, then deleted
with sir's explicit approval after verification (see below).

After removing the package link, all **183 Node + 40 Python tests passed
again**, all three executable paths returned 1.0.2, and the runtime resolver
selected the managed release. No services or browser windows were restarted
by the cleanup. Future updates use `pi update`.

## Verification and approved backup disposal

The private migration backup at
`~/.pi/backups/pre-managed-migration-20261003-214502/` was deleted with sir's
explicit approval after cleanup passed. This removed the config archive,
legacy runtime snapshot, original source copies, and installer/test records,
reclaiming approximately **203.6 MiB of allocated space**. Fifteen temporary
installer/test files from this work were also deleted. No active release,
session history, browser profile, live configuration, or unrelated file was
removed.

Before disposal, 21 focused runtime/codemode/lazy-tool tests passed again;
managed metadata and active package version were checked, and known launcher
link directories had no references into the backup. All three CLI entrypoints
still returned 1.0.2 afterward. The original archive had been verified by reading
every member, and the runtime snapshot's 15,013 regular files had been checked
by SHA-256. Global agent JSON hashes were unchanged after installation.

Before and after migration: **183 Node tests + 37 terminal Python tests + 3
room-prompt Python tests passed**. No model calls or live home/browser actions
were used. An isolated resource-loader check additionally imported **27 project
and installed web-access extensions with zero errors** on the managed runtime;
no session-start hooks were dispatched. `pi`, `.pi/scripts/pi-cli`, and the
legacy executable path all returned 1.0.2. Managed marker, selected version, and
locked package version were checked.

## Recovery

The migration backup is no longer available. Git retains the launcher/test
source history; it does not back up credentials or conversation files. If the
managed package needs repair, use the official installer after obtaining
approval for affected service/session changes. Preserve live configuration and
session history; do not remove `~/.pi/agent` to reinstall the CLI.
