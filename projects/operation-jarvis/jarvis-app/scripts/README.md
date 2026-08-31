# scripts/

Build and deployment helpers. The iPhone SwiftTerm renderer requires Xcode's
optional Metal component; install it once with
`xcodebuild -downloadComponent MetalToolchain` if needed.

- `redeploy-jarvis-app.sh` — builds and installs the free-provisioned iPhone
  app through CoreDevice. This is appropriate for iPhone-only iteration, but
  iOS records a `skip watch app install` flag for this route. Do not use it as
  evidence of companion registration or transfer.
- `redeploy-jarvis-watch.sh` — builds and directly installs the Watch product
  against the paired physical Watch. This is the permitted Personal Team
  developer-install route. A direct install is authoritative only after the
  corrected parent package is registered on the iPhone and both installed
  flags are checked.
- `renew-free-signing.sh` — the fixed, argument-free action behind iPhone
  **Settings → Developer Signing**. It reads a private mode-600 allowlist from
  `$HOME/Library/Application Support/JARVIS/signing-renewal/config.env`, asks
  Xcode for four fresh Personal Team profiles, archives clean `main` in an
  isolated worktree, audits team/device/profile/signature/hierarchy rules, and
  installs the exact archived host through Apple's paired CoreDevice tunnel and
  then the exact nested Watch app on only the configured devices. Its fixed
  seven-step progress includes a final installed-build verification/relaunch
  phase and retains only the allowlisted phase that failed. Progress is written
  atomically to `status.json`; a duplicate run is locked out. The
  script never uninstalls, unpairs, reboots, or accepts a client command/path.
- `patch-watch-embedding.sh` — keeps XcodeGen's `Embed Watch Content` phase at
  `JARVIS.app/Watch/` (`dstSubfolderSpec = 16`), the Xcode 26 layout accepted by
  the corrected iPhone/Watch target relationship.
- `jarvis-mobile-terminal.sh` — macOS SSH bootstrap for the phone terminal. It
  supplies Homebrew's PATH, creates the exact `jarvis-ios` tmux session while
  detached when absent, tolerates concurrent reconnect creation, launches Pi's
  regular main-screen TUI without a display-name override so Watch captures see
  response output immediately, re-sources the checked-in one-line wheel fallback
  bindings, and then attaches the phone PTY. Its
  `--ensure-only` mode lets the Watch bridge recreate the same session without
  attaching another tmux client or changing terminal dimensions.
- `install-jarvis-terminald.sh` — installs and starts the separate authenticated
  HTTPS Watch/Siri terminal bridge on TCP `8792`. Build 39 captures a bounded
  ANSI-styled tmux-history grid for local Crown scrolling; build 40 atomically
  pastes a Siri prompt and its Return in one ordered buffer. Build 54 adds a
  response-ID-matched `/v1/terminal/speech` relay: terminald reads only the
  current PID/tmux-bound extension marker, sends its private final text to the
  loopback room-audio Piper endpoint, and returns the WAV without exposing text
  in terminal frames. Its lazy shared frame sampler preserves the 100-millisecond
  cadence while batching metadata and ANSI capture into one read-only tmux
  invocation; concurrent long polls share samples, and confirmed input triggers
  an immediate refresh. It does not infer Pi concepts from ANSI, accept arbitrary
  speech text, control hardware, or route through `jarvisd`.
- `jarvis-terminal-provisioning.sh` — prints the private, certificate-pinned
  setup code that is pasted once into iPhone Settings and transferred to the
  paired Watch through WatchConnectivity. Existing LAN setup codes also derive
  stable MagicDNS and current Tailscale bridge fallbacks in build 34; no secret
  retransmission is required. Never commit or post the code's output.
- `verify-jarvis-app.sh` — runs project-contained daemon and package tests,
  plist/shell checks, opaque icon validation, combined iOS/embedded-Watch
  simulator verification, and the standalone watchOS simulator build. Its Watch
  contracts require the exact ANSI mirror, Crown-only read-only viewport, direct
  native keyboard Input, removed prompt rail, centered/safe-inset header and dock,
  brightened Watch foregrounds, compact equal `/`/DEL/Return-symbol keys,
  spinner-free repeatable Backspace, Always On foreground lifecycle, on-view
  Codex refresh, shared sub-30% critical quota threshold, atomic Siri Return,
  and final-text-only authenticated Watch speech playback.
  It also audits the sole host-only bare “Hey JARVIS” two-turn prompt shortcut,
  iPhone's success-only hidden `OpenIntent` handoff, Watch foreground behavior,
  complete removal of host Siri plug intents and greeting audio, immediate-only
  correlated Watch plug/purifier relay writes, bounded command-envelope age,
  removal of queued WatchConnectivity command delivery and response polling, and
  the exact two-kind non-control widget catalogues with all retired plug/purifier
  widget source, App Intents, and built kinds absent. The iPhone terminal
  contract additionally verifies the restored
  fixed-step Pi viewport: native momentum/bounce is disabled, each threshold
  emits at most one immediate SGR wheel event, and no event is queued, paced,
  retried, replayed, or delivered after mouse mode/disconnection. iOS and live
  integration tests remain opt-in.

For initial companion registration under free provisioning:

1. archive/export a signed debugging IPA with Xcode;
2. install the parent IPA through `ideviceinstaller` so CoreDevice's skip-Watch
   option is not used;
3. do **not** rely on **My Watch → Available Apps → Install** — watchOS rejects
   free-profile apps from that source with `MIInstallerErrorDomain Code=111`;
4. install the exact `JARVIS.app/Watch/JARVISWatch.app` from the same archive
   through Xcode/CoreDevice's Watch developer service;
5. verify both installed flags and then test reachability.

Follow the complete procedure, trust step, identity rules, diagnostics, and
non-destructive recovery order in:

[`../README.md`](../README.md)
