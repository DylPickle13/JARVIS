# Anthropic subscription extension in JARVIS

Use the original [leohenon/pi-anthropic-oauth](https://github.com/leohenon/pi-anthropic-oauth)
extension, without a prompt-sanitizer fork. The tested upstream revision is
`2e81a0a2a2d869f9fb96f0bae58020a07b775d3d` (package version `0.3.1`).

## Local setup

The current checkout is `~/.pi/local-packages/pi-anthropic-oauth-ios3`; its name
reflects the initial slot-3 test, not a restriction to that slot. The checkout
and its dependencies are local, not included in this repository. The current
`node_modules` symlink targets the installed Pi 1.3.0 dependencies; it must be
reviewed if that release is removed. Do not commit OAuth credentials.

Merge the following into the gitignored `.pi/settings.json`. Retain existing
extension entries, enabled models, defaults, and model-specific thinking levels.
Replace the extension path with the absolute path to the local checkout.

```json
{
  "extensions": ["/absolute/path/to/pi-anthropic-oauth/src/index.ts"],
  "enabledModels": [
    "anthropic/claude-opus-5-5",
    "anthropic/claude-sonnet-5-5",
    "anthropic/claude-haiku-5-5"
  ],
  "modelThinkingLevels": {
    "anthropic/claude-opus-5-5": "medium",
    "anthropic/claude-sonnet-5-5": "high",
    "anthropic/claude-haiku-5-5": "high"
  },
  "warnings": {
    "anthropicExtraUsage": false
  }
}
```

Launch through `.pi/scripts/pi-cli`. It exports
`PI_ANTHROPIC_OAUTH_REWRITE_MODE=technical-safe`, including on normal tmux
restarts. Invoking stock `pi` directly without that environment would leave the
extension using its default aggressive rewrite mode. The launcher does not
change Codex/oMLX model defaults or patch Pi itself.

Authenticate through `/login` → Anthropic. Credentials use normal Pi storage;
the original extension may create `~/.Claude Code` → `~/.pi`.
Use `/model` or model cycling to switch between Claude, Codex, and local models.
Use `/reload` for settings changes; restart through the launcher when its
environment settings change. Resume saved conversations by their session file;
start blank sessions normally, without a nonexistent `--session-id`.

## Verified and limitations

- Original extension with `technical-safe` successfully served a Claude request
  and supported Claude/Codex switching in the user-tested slot-3 session.
- All three Claude 5.5 models were verified in `/model` in the nine other panes
  during the persistent-settings rollout; no billable test requests were sent
  by that rollout. This is not comprehensive tool or provider testing.
- `technical-safe` protects paths and technical names but still removes some
  Pi-related documentation paragraphs. It is not full prompt preservation.
- The earlier blanket pass-through sanitizer was rejected by Anthropic and was
  discarded. No custom sanitizer or Pi version-lock guard is retained.
- The warning setting only hides Pi's generic OAuth notice. It does not change
  billing or guarantee included-plan access. Keep usage credits disabled unless
  separately authorized. Anthropic controls acceptance and billing policy.
- The local settings and credentials remain gitignored. This note records the
  configuration without force-adding machine-specific settings or secrets.

## Removal

Remove the local extension entry and three model IDs/overrides from project
settings, remove the rewrite-mode export from the launcher if no longer needed,
and reload/restart affected sessions. Leave unrelated settings and credentials
untouched.
