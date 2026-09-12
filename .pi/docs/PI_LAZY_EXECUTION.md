# Lazy tool direct-call execution

## Behavior

Optional tool schemas start hidden. Use `load_tools` to discover and activate a
group. The patched JARVIS runtime can also handle a valid direct call to a
registered optional tool: it loads the group and runs that call once, without a
retry or another model round trip.

- Only tools in `.pi/extensions/99-lazy-tools.ts`'s `TOOL_GROUPS` are opted in.
- Unknown, removed, unlisted inactive, and CLI/SDK-excluded tools do not resolve.
- Arguments are validated before activation. Normal tool-call guards, tool-local
  confirmations, sequential execution, cancellation, streaming, and results remain.
- The original output/details/error are preserved. The result records activated
  tool names and appends the group's playbook (including ordinary blocks/errors).
- A throwing extension guard fails closed. Activation metadata survives, but
  previously returned guidance may be lost when the handler chain throws.
- Groups stay active until reset/restart/reload. `/reset-tools` hides them again;
  another valid direct call can auto-load them again.
- Stock Pi or `JARVIS_PI_LAZY_AUTOCALL=0` retains explicit-loading behavior.
- This cannot force a provider to emit a tool name absent from its advertised
  schemas. Explicit `load_tools` remains the reliable discovery route.

### Cache behavior

This does not advertise all optional schemas or hide provider payloads. Explicit
loading keeps Pi's native deferred-tool markers. A directly called tool may refresh
the prefix once because Pi keeps an already-used tool's schema immediate, rather
than declaring it after first use. Unused tools in the same group can still be
deferred. Providers without native support receive the full active-tool list.
Activating optional tools does not change the system prompt.

## Core changes

The version-pinned source patch is
`.pi/patches/pi-0.85.1-lazy-execution.patch`.

Base: [`earendil-works/pi` v0.85.1](https://github.com/earendil-works/pi/tree/d981de1229ef899957bbe968bc8dcda02a21f477),
commit `d981de1229ef899957bbe968bc8dcda02a21f477`.

1. Agent core adds a pure, opt-in `resolveTool(name)` lookup. Scheduling and
   validation use it only if a name is absent from the active execution snapshot.
   The default remains unchanged: inactive tools are not found.
2. `ExtensionAPI.setLazyTools(names)` replaces an explicit hidden-execution
   allowlist. It resolves only allowed entries in the wrapped session registry;
   it neither registers tools nor activates schemas. Runtime rebuild clears it.
3. JARVIS sets the allowlist in `session_start`. After validation, its `tool_call`
   hook activates the registered group instead of asking the model to load it and retry.
4. AgentSession records additive preflight activations. Agent core carries those
   markers and appended guidance into success, error, block, and cancellation
   results. Existing tool execution wrappers are not bypassed.

`setActiveTools` still controls schema visibility. To deliberately disable hidden
execution for a designated tool, remove it from `setLazyTools` as well, or use a
CLI/SDK exclusion. Do not treat merely hiding a lazy tool as a permission gate.

## Build, test, activate

From the repository root, in a development checkout:

```bash
node .pi/scripts/pi-lazy-runtime.mjs build
node .pi/scripts/pi-lazy-runtime.mjs test
node .pi/scripts/pi-lazy-runtime.mjs install
node .pi/scripts/pi-lazy-runtime.mjs status
```

The build script:

- Clones and verifies the exact upstream commit, then applies the checked-in patch.
- Installs locked dependencies with lifecycle scripts disabled.
- Uses model catalog data from the matching published `pi-ai@0.85.1` package;
  no provider login, API call, or moving catalog regeneration is needed.
- Builds CLI, RPC, and SDK artifacts and runs TypeScript checking and relevant
  upstream tests, including deferred-provider payload tests.
- Packs the patched agent-core and coding-agent packages using upstream's
  consumer-install helper, with local tarball dependency overrides.
- Tests the installed SDK and bundled implementation with inert tool mocks,
  plus a real CLI RPC subprocess using an offline mock provider.

Ignored build artifacts live under
`.pi/runtime/pi-lazy-tools/releases/<patch-hash>/`. A `build.json` identifies the
verified build. Existing completed builds are reused only after regression tests.
An incomplete build is not overwritten automatically: inspect/move its directory
before retrying. Keep release artifacts while their runtime is installed.

Installation atomically points the global npm `bin/pi` symlink at the tested
release. It leaves the stock package untouched and saves the original link in
`.pi/runtime/pi-lazy-tools/installation.json` for rollback. Both `pi` and
`pi --mode rpc` then use the new bundle. SDK imports from the stock package still
use stock Pi; import the release named in `build.json.runtime` for the patched SDK.

**Restart Pi processes to use the new core. `/reload` alone cannot upgrade an
already running Pi core.** Existing sessions are not killed or restarted by the
installer. This installation is local to mac-mini-64, not the remote hosts.

A global npm upgrade can replace `bin/pi`, so check `status` afterward. The
installer will not overwrite an unexpected executable or silently downgrade a
newer stock Pi. Review and rebase the patch when upgrading.

## Rollback

Disable automatic calls for a new process while keeping the custom core:

```bash
JARVIS_PI_LAZY_AUTOCALL=0 pi
```

Or restore the original stock executable:

```bash
node .pi/scripts/pi-lazy-runtime.mjs rollback
```

Restart Pi afterward. The extension feature-detects `setLazyTools` and continues
to work with explicit loading on stock Pi. Rollback refuses to overwrite a link
that has changed since installation. No session/history data is modified.

## Regression coverage

`.pi/scripts/tests/pi-lazy-tools.test.mjs` tests first-call success and real output,
validation, exclusions/unknown names, earlier/later/throwing permission guards,
parallel ordering and per-group anchors, hidden sequential tools, execution errors,
cancellation before/during execution, streaming updates, reset/reload/stale APIs,
explicit deferred loading, allowlist revocation, environment/stock fallback, and
packaged CLI RPC. No actual browser, hardware, account, or LLM is contacted.

`.pi/smoke-test.sh` checks registry/activation wiring and runs this suite for both
SDK and bundled runtime when a verified build exists.
