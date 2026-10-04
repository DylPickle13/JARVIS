# Pi session names on iPhone cards

## Deployed — build 248

The nine Pi cards on the iPhone **JARVIS** tab now use the actual saved Pi session
name instead of the written lifecycle label. The session number, 22-point glyph,
80 ms motion, colours, tap route and normal card/grid dimensions are unchanged.
Long titles use a trailing ellipsis at normal text sizes; accessibility sizes
may wrap, and VoiceOver receives the full validated name **and lifecycle**.

An unnamed New session says **New session**. Other unnamed/unavailable titles
say **Unnamed session**: missing name data must not imply that a running or
restored conversation is New. No topic is guessed from prompts or tmux names.
Room Audio keeps its existing meaningful label and controls; the additive data
contract also supports its fixed slot 10 without changing its UI.

Owner-approved iPhone build **248** was installed once and independently
version/launch/process verified on **2026-10-04 at 12:58 EDT**. The backend was
activated and verified at **12:55 EDT**; its documented watchdog-coordinated
cutover restarted the daemon in **0.557 s**, then resumed the watchdog. All
**16 unrelated protected service records** and existing Pi pane/window/process
identities were preserved. The subsequent iPhone install preserved all 18 service
records. There was no Pi extension change, `/reload`, session restart, household
device command or direct Watch install/launch. Watch's last independent device
verification remains build 245; iOS may sync the unchanged-source embedded companion.

Live cached state supplies **7 actual saved names**; the other **3 slots are New
and unnamed**, not failed name lookups. Names were verified without logging their
text. Launch selected the JARVIS tab. The owner confirmed the physical appearance
looks good after deployment; physical VoiceOver acceptance remains unconfirmed.

## Verification

**173 iPhone tests, 301 shared tests (3 expected live-test skips), 37 terminal
tests and both simulator builds passed from frozen build-248 source.** The
operational source candidate passed 891 backend tests. The shipped backend was
prepared from the exact installed release, applying only the name projection,
new metadata helper and focused tests; **all 795 frozen installed-baseline tests
passed**. Unrelated installed changes, CLI/vendor SDK files and Python runtime
were preserved rather than replaced by the operational checkout. The pre-existing
plain-Paste pixel assertion remains excluded; no new test exclusion was added. Coverage includes actual-name decoding,
legacy/malformed fields, ID binding, Unicode/control limits, rename/clear/resume,
partial/bounded reads, cache identity and cardinality, fixed card/grid geometry,
accessibility expansion, full spoken names/status and unchanged busy motion.
All tested shipping inputs match the frozen source/hash manifest; backend hashes
were checked before and after its stock runtime-isolated verifier. The validation
simulator returned to its original shutdown state.

A read-only candidate-collector check against the ten existing slots found **7
saved names on the first pass in 17 ms**. No names or conversation content were
logged; this pre-deployment check changed no live backend, Pi process, credential
or physical device. This is data lookup evidence, not an installed-app or physical VoiceOver acceptance claim.
The pre-release helper, frozen inputs, logs, result bundle and summary are
retained privately under `jarvis-session-names.3cdzjb`. Release evidence is retained
in `20261004T162812Z-build248-session-names` and backend deployment
`20261004T162812Z-pi-session-names`. Session-created build caches were removed.

The exact signed candidate and exact iPhone rollback **247** passed all four
bundle/signature/profile/unchanged-entitlement and payload audits. Existing
signing authority and byte-identical profiles were reused; no portal/provisioning
change or rebuild between audit and the sole install. Exact prior backend source
and daemon/watchdog plists are retained as rollback. Its configuration/credential
fingerprints, existing history database identity and 10-second history cadence
were verified unchanged; a consistent read-only history backup is retained.
No uninstall, unpairing, reboot, app-data removal or install retry was issued.

## Additive data contract

`subsystems.pi.mobileSessions[]` gains an optional **name** field, for example:

```json
{"sessionID":3,"lifecycle":"running","active":true,"name":"Dashboard names"}
```

The backend emits this field only for a validated explicit name. Older native
clients ignore it; the new `PiMobileSession` decoder accepts older responses,
null/malformed name fields and unchanged lifecycle/legacy activity fields.
Names are resolved by fixed session ID, never array order or the title itself.

## Provenance, privacy and resource limits

The backend uses the same fresh, source-validated PID descriptor that supplies
lifecycle, and reads only its exact `sessionFile` beneath the Pi history root.
Missing/stale/ambiguous/offline tmux identities never supply a name; competing
same-timestamp conversation descriptors withhold the name without changing the
existing lifecycle selection. Switching or resuming sessions cannot reuse a
previous file's cached name.

`jarvisd_core/pi_session_names.py` reads only explicit `session_info.name`
metadata. It does not enumerate the history directory, synthesize titles, call
models, start a subprocess, write session files or return/log conversation text.
Absolute rooted regular owner files and supported session headers are required;
out-of-root files, symlinks and special files are rejected.

A bounded tail probe usually finds the latest name immediately. Otherwise a
bounded incremental cursor warms the exact file. Each probe/scan reads at most
2 MiB (up to two such reads on initial warmup); cached complete files need no
body re-read. The LRU holds at most 32 file identities and stores only names,
stat identity and cursor state, never partial prompt/tool/message contents.
Incomplete/changing samples have no name until a complete stable sample exists.
Rename/clear metadata supersedes older names; replacement, truncation and
same-size rewrites reset the cache. Metadata lines are bounded at 16 KiB.

Both backend and client accept a trimmed single-line name of at most 256 Unicode
scalars/code points. Controls, bidi overrides, empty or oversized names are not
rendered. This is format validation, not a guarantee that a manually chosen
session name contains no sensitive prose; actual titles are deliberately visible
within the existing authenticated/trusted-network dashboard boundary.

The existing Pi collector cadence, cached state handler, credentials and service
configuration are unchanged. The card renderer performs no additional fetch.
