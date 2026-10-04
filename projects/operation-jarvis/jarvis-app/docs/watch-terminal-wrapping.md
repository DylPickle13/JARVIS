# Watch terminal wide-pane wrapping

## Status

Owner-approved build **249** was installed once on both allowlisted devices and
independently version/launch/process verified on **2026-10-04 at 16:39 EDT**.
Both devices authoritatively reported build 248 before installation; that exact
sealed signed archive remains the immediate rollback. All 18 protected service
records and existing Pi session identities were preserved. No service or Pi
restart, credential change, uninstall, unpairing or installation retry occurred.
The owner confirmed Session 10 wrapping works after installation. Broader
oldest-history, long-editor and VoiceOver acceptance remains unconfirmed.

## Diagnosis

A read-only tmux capture of Session 10 showed a **172 × 43** pane and the complete
answer after the reported last visible word, “Ontario”. The Watch's FIT font is
clamped to a 5.5-point minimum, but its wrap width was still the authoritative
pane's full column count. Desktop-width lines consequently extended past the
Watch's clipped output surface rather than wrapping at its actual capacity.

## Source change

- `WatchTerminalLayout.mirrorDisplayColumns` calculates the cell capacity from
  the available Watch width and the existing FIT font, bounded by the pane width.
- Output uses that capacity for local ANSI-preserving wrapping. Already-fitting
  panes keep the same columns and typography; there is no new mode or larger font.
- The pinned editor uses the same capacity for its unwrapped cursor-following
  viewport. No horizontal gesture or duplicate prompt rail is added.
- When wrapping is required, the Crown's source-row clamp permits scrolling to
  the first source row. The former full-source-page clamp could permanently hide
  leading wrapped lines at the oldest history edge.
- Crown scrolling remains source-row-based and read-only. The bounded history
  endpoint, cache limits, terminal input, polling and speech behavior are unchanged.

The authoritative PTY is never resized. No Pi input, reset or restart is required.

## Verification

An isolated source copy passed:

- **33 WatchTerminal tests**, including the Session 10 sentence through “tip.”,
  preserved ANSI styles, cell capacity at 140–190-point widths with 48–200-column
  panes, and Crown coverage of wrapped history through its oldest row.
- **304 shared tests**, with 3 expected live-integration skips and no failures.
- The unsigned **watchOS simulator build**; only existing deprecation warnings.
- Shell syntax and `git diff --check`.

The frozen build-249 release subsequently passed **173 iPhone tests, 304 shared
tests (3 expected skips), 37 terminal tests and both simulator builds**, plus the
signed archive build. The pre-existing plain-Paste pixel assertion remains the
only native test exclusion. All four candidate and exact rollback-248 bundles
passed signature, byte-identical profile, unchanged-entitlement and payload-seal
audits; existing signing authority and dependency locks were reused without
portal/provisioning changes. No rebuild occurred between audit and installation.

The verification script's source contract now requires Watch-capacity wrapping
instead of full-pane-width overflow. The entire repository verifier and the
remaining physical acceptance checks were not run. Frozen source, logs, result bundle, exact signed
archive, audit and one-shot installation evidence are retained privately in
`20261004T202531Z-build249-watch-wrapping`.

After owner acceptance and the fix's commit/push, authorized cleanup removed
superseded build-244/245/247 binaries and deduplicated the initial verification
checkout, reclaiming **340.43 MiB net allocated space**. Signed builds **249 and
248** remain, with seals/signatures/frozen inputs reverified; every historical
source, audit, deployment log and test result is retained. No service or Pi
identity changed. See [current recovery retention](operations.md#current-recovery-retention-and-cleanup).

## Physical acceptance (installed build 249)

1. Open Session 10 with its existing wide pane. Confirm the complete final answer
   is visible, including words after “Ontario”, without horizontal panning.
2. Use the Crown through wrapped output and the oldest available history.
3. Check a normally fitting narrow pane for unchanged typography and layout.
4. With explicit permission for a test input, check that a long editor line still
   follows the cursor and that normal terminal input is unchanged.
