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

## Compatibility for existing processes

Two explicit compatibility links remain on the deployed host:

1. `/opt/homebrew/bin/pi` -> `~/.pi/agent/bin/pi`.
   Keep this for shell command caches and the already-running room-audio
   supervisor, whose in-memory code still references the old CLI path. It
   always launches the **managed current release**, not the snapshot.
2. `/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent` ->
   `~/.pi/backups/pre-managed-migration-20261003-214502/npm-runtime-1.0.2`.
   This preserves on-disk code/assets for already-running npm-era Pi sessions.
   New project helpers prefer the managed runtime; this is not their default.
   Do not delete this snapshot while older sessions may still use it. Remove
   the package link only during a separately approved cleanup after old
   processes have exited. Do not run npm install/uninstall against this bridge.

Existing sessions retain their running code. For maintenance now, invoke
`pi update` from a shell using the managed launcher rather than relying on an
old session's in-process update implementation.

Follow-up verification: sir restarted all ten pi-desk-backed `jarvis-ios`
sessions at approximately 21:59 EDT. All ten pane start commands use
`.pi/scripts/pi-cli`, which selects the managed launcher. The only remaining
pre-migration Pi process is the standalone VS Code session carrying this
migration conversation (started at 21:41 EDT). Its ancestry was verified from
the tool subprocess. Keep the legacy package link until that session also
exits/restarts, then recheck for old processes before removing **only that
symlink**. The `/opt/homebrew/bin/pi` executable alias already selects managed
Pi and can remain for compatibility. Do not remove the backup.

## Backup and verification

Private backup directory (mode 0700):
`~/.pi/backups/pre-managed-migration-20261003-214502/`.

- `pi-config-extensions.tar.gz`: project Pi config/extensions/dependencies and
  global settings/credentials; verified by reading every archive member;
  SHA-256 recorded in `SHA256SUMS`. Sessions, browser profiles, generated runtime,
  and caches are excluded and left in place.
- `npm-runtime-1.0.2`: full legacy package snapshot; 15,013 regular files verified
  against the source by SHA-256 before migration; symlink targets also verified.
- `original-source/`: pre-change launcher/test files outside `.pi`.
- `agent-before-install/`: current global agent JSON immediately before install.
- `installer-executed.sh` / `installer.log`: installer copy and successful log.
- `agent-before-install-hashes.json`: global agent JSON hashes; all unchanged
  immediately after installation.

Before and after migration: **183 Node tests + 37 terminal Python tests + 3
room-prompt Python tests passed**. No model calls or live home/browser actions
were used. An isolated resource-loader check additionally imported **27 project
and installed web-access extensions with zero errors** on the managed runtime;
no session-start hooks were dispatched. `pi`, `.pi/scripts/pi-cli`, and the
legacy executable path all returned 1.0.2. Managed marker, selected version, and
locked package version were checked.

## Recovery

Do not restore the entire backup over live sessions or credentials. The original
runtime can be smoke-tested directly via
`node ~/.pi/backups/pre-managed-migration-20261003-214502/npm-runtime-1.0.2/dist/bundle/cli.js --version`.
For an actual rollback, stop and obtain approval for affected service/session
changes first. Preserve the managed installation and current conversation files;
restore only the necessary launch/config files from the private backup, using
its archive member prefixes. Do not delete the backup while the compatibility
package link points into it.
