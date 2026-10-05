# Pi Desk Selection (optional VS Code bridge)

Ordinary dragging in Pi Desk snapshots only that viewer's pane. Release keeps the
highlight; Cmd+C copies without dismissing it; the next pane/status click resumes
the display. Double-click selects a word, triple-click a line, and Escape cancels.
The hosted agents continue running. Native Option-drag selections still use
VS Code's built-in copy command. This is terminal copy mode, not a DOM transcript.

The extension uses stable APIs and reads only the active terminal name. It never
reads session output or the clipboard. The app-supplied tab title must be exactly
`pi-desk` (a manually renamed tab is not detected). Other terminals and editors
retain their native copying. The dedicated User90 binding is a no-op without a selection.

Build/install locally, without npm or marketplace dependencies:

```sh
python3 build_vsix.py /tmp/pi-desk-selection.vsix
"/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" --install-extension /tmp/pi-desk-selection.vsix
```

In the workspace's `.vscode/settings.json`, add `piDesk.copySelection` to
`terminal.integrated.commandsToSkipShell` (preserving existing entries). This
supplements VS Code's built-in skipped commands; it does not replace them. Also
set `terminal.integrated.tabs.title` to `${sequence}`. No keybindings/user-profile
settings are rewritten by the Pi Desk installer. The extension is optional;
Pi Desk itself does not depend on VS Code.

On macOS, the Pi Desk display server uses `/usr/bin/pbcopy` for copying. This
integration is intended for a locally running VS Code terminal. A terminal on a
remote Mac copies to that Mac's clipboard, not the VS Code client's clipboard.
On other platforms tmux retains its normal clipboard transport; Ctrl+Shift+C is
the bridge shortcut, but successful OS clipboard integration is terminal-specific.

After uninstalling the extension, remove its commandsToSkipShell entry. To undo
the selection configuration, restore the previous Pi Desk tmux config **and** its
mouse/copy bindings: sourcing an old config alone does not remove new overrides.
The local deployment backup includes a selection-only `rollback-selection.tmux`
and `ROLLBACK.md`. Reload only the display configuration; do not restart agents.
