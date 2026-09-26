# Basement presence keyboard/mouse lighting watcher

## Active components

- Local user LaunchAgent **`com.jarvis.ajazz-keyboard-watch`** runs `watch.py --watch` for both the AK820 and Razer, using one age-adjusted presence snapshot per poll.
- Private JARVIS scheduler job **`Keyboard lights`**, ID **`job_41fb6dd73fce`**, runs `watch.py --alerts` every minute using `__direct_stdout__`. It only relays keyboard/mouse alerts and checks watcher health; it never sends lighting commands. Its name, ID and one-minute cadence are unchanged.
- The previous minute-based lighting job (`job_bf8f4ff68cb5`) was disabled and removed. No duplicate lighting scheduler remains.
- The watcher was explicitly authorized by the owner. No collector/backend service or global scheduler cadence was changed; no new BLE scan or keyboard backend route was added.

## Behavior

The watcher calls the existing authenticated `presence/status.py` client, sleeps three seconds after each bounded check, and repeats. Slow requests extend the interval; there is no catch-up loop. No model calls are involved.

- **Either device nearby:** first fresh basement `nearby` report resumes randomly selected liked effects, white `#FFFFFF`, highest brightness, fastest speed. Ordinary effect changes remain at least 60 seconds apart, excluding presence transitions. Do not repeat the last successful coloured rotation effect.
- **Both away:** first fresh basement `away` report applies **`ripples`, `#FFFFFF`, `highest`, `fastest`, `left_to_right`** once. Repeated away checks and watcher restarts do not resend a successful away profile. Black RGB is no longer the requested away behavior.
- The collector's **10-second nearby hold remains unchanged**, plus up to roughly three seconds publishing latency. The watcher reacts within a few seconds of a fresh backend transition under normal conditions. This is not literally instant departure detection.
- The old extra two-check keyboard debounce is bypassed by the watcher. Arrival/away transitions can send a report between minute-spaced rotations; a three-second minimum spacing still prevents overlapping/catch-up bursts.
- Unknown, stale, invalid, missing or failed presence leaves lighting unchanged. A valid sample must have `stale: false`, age 0–15 seconds; age is rechecked immediately before sending after state persistence. Other-room estimates never override basement.
- BLE proximity is an estimate, not proof of human location. Devices left behind can retain nearby; radio dropouts can cause false departures.
- `away_applied` and `last_effect` are last successful requests, **not lighting readback**. Manual/external changes are not detected.
- Keyboard `breath` remains one of the nine liked effects, per the owner's clarification.
- **Mouse nearby → steady; away → off. Never breathing.** `mouse_cycle.py` allowlists only these two effects. The owner's default mouse brightness is **20%**, applied and acknowledged via the bridge. Presence transitions preserve that brightness; they leave DPI and polling untouched. Brightness is not reasserted on every poll or verified across power loss. No repeated command for unchanged presence or a watcher restart; a fresh presence transition can send one command after the three-second cooldown. Unknown/stale presence leaves the mouse unchanged.
- Mouse and keyboard use separate persisted state/faults and separate daemon journals. A keyboard command failure does not prevent a fresh, safe mouse update. The snapshot's age includes fetch latency and time spent commanding the first device; the mouse refuses a snapshot that has aged out.

## Safety and failures

The keyboard uses the existing signed Karabiner owned-handle bridge: one validated 65-byte output report and exact model/interface checks. The mouse uses its installed signed bridge with one validated feature exchange per command. No new driver, daemon, input capture, firmware operation, USB cutoff or automatic recovery write.

- Persist a pending marker before every command. A timeout, short/unrecognized result or crash after reservation blocks later writes until explicit owner acknowledgment. Restarts and state migrations never clear this block.
- Known pre-write failures may be attempted again only after at least **60 seconds**, even if presence flips. Never retry them at the three-second polling rate.
- No unconditional startup write. Startup requires fresh presence, valid state/preferences and all write gates. A persisted successful away profile is not replayed on startup.
- A singleton `watcher.lock`, shared `cycle.lock`, and the CLI's `.lighting.lock` prevent duplicate watcher processes and overlapping local operations.
- The owner authorized responsive transitions; these add writes beyond normal once-per-minute rotation. Firmware persistence/storage wear remains unknown. Flapping presence can therefore increase wear risk; no zero-risk claim is made.

## Notifications

Healthy checks and successful ordinary transitions are silent. The existing durable fault latch emits one error when entering failure, stays silent during continuing failure, and emits one recovery once confirmed. A keyboard fault requires a successful lighting command to recover, not just healthy presence.

The watcher queues these messages privately; the minute-based alert relay delivers them to the existing bounded JARVIS job history. Thus lighting transitions are responsive, but notification delivery can take about a minute. The relay also reports a missing/stale watcher heartbeat once and recovers once when the watcher responds; this is explicitly not device readback.

The private alert queue retains at most 64 messages. An extreme prolonged relay outage can discard oldest messages. Queue/latch persistence is not an exactly-once transaction across process crashes and scheduler delivery. Storage inaccessibility uses the existing bootstrap error marker; if both storage locations are inaccessible, durable deduplication is impossible.

## Files and controls

Project: `/Users/dylanrapanan/JARVIS/projects/operation-jarvis/keyboard`.

Runtime: `~/Library/Application Support/JARVIS/ajazz-keyboard/`, owner-only directory/files:

- `state.json` version 4: timestamps, counters, last effect, `away_applied`, pending marker and mode. Versions 1–3 migrate without clearing pending. Previously applied black/purple is not treated as already-applied white ripples.
- `mouse-state.json` version 1: last tick/attempt, last acknowledged `steady`/`off`, succeeded and pending markers. `mouse-alerts.json` stores a separate fault latch. The mouse daemon journal also survives restarts.
- `alerts.json`: persistent device/presence/preferences/state fault latch.
- `watcher.json`: heartbeat and bounded alert outbox; `watcher-health.json`: relay health latch.
- `last-command-error.json`: latest sanitized error class, never raw child stderr. May be historical after recovery.
- `watcher.log`: bounded 64 KiB log with one backup for watcher storage failures.
- `black-colour-test.json`: historical authorized black trial, visual/typing confirmation and normal-lighting restoration. Not current away configuration.

LaunchAgent plist: `~/Library/LaunchAgents/com.jarvis.ajazz-keyboard-watch.plist`.

```sh
cd /Users/dylanrapanan/JARVIS/projects/operation-jarvis/keyboard
.venv/bin/python cycle.py --status  # local cached state, not device readback
.venv/bin/python mouse_cycle.py --status
./ajazz status                     # connection metadata only
launchctl print gui/$(id -u)/com.jarvis.ajazz-keyboard-watch
```

To explicitly stop lighting automation, unload the watcher (disabling the alert job alone does NOT stop it):

```sh
launchctl bootout gui/$(id -u)/com.jarvis.ajazz-keyboard-watch
```

After confirming it has exited, restart only when intended:

```sh
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.jarvis.ajazz-keyboard-watch.plist"
```

Do not immediately bootstrap while bootout is still completing. Do not use privileged/root recovery or automatically retry failed lifecycle operations. `install_watch.py --install` is first-install only and refuses an existing service/plist. The watcher runs in the logged-in user's launchd domain, not as a system/root service.

`cycle.py --once` retains the legacy bounded/two-check behavior for explicit manual use; it is no longer scheduled. Do not manually run it alongside the watcher. `cycle.py --acknowledge-uncertain` remains an explicit owner-only recovery decision: it sends nothing, clears the pending block and resets the away latch; a later fresh watcher check may then send a command. Never invoke acknowledgment automatically. Mouse recovery uses `.venv/bin/python mouse_cycle.py --acknowledge-uncertain`, which coordinates the daemon and local marker, sends no device report, and requires fresh presence after a full-minute cooldown. Do not use only the manual CLI's daemon acknowledgement to clear an automation fault.

## Validation

113 offline tests pass, including the keyboard/bridge suite and new mouse transition, shared-snapshot freshness, never-breathing allowlist, restart suppression, independent faults, state migration and uncertainty tests. Tests use mocks and send no device reports.

Live deployment: keyboard switched to white immediately, mouse acknowledged steady mode, and the restarted watcher reports keyboard cycling plus mouse steady, no faults and no pending writes. Mouse steady/off follows fresh backend basement state; physical departure/return acceptance remains pending.

During activation the watcher encountered a known pre-write failure, then successfully applied the requested away profile on a later permitted check. The successful request is recorded as `mode: away`, `away_applied: true`, `pending: false`, with no faults. This confirms transport acceptance, not visual output or firmware persistence. The underlying raw cause of the initial transient failure was not retained; sanitized diagnostics are now retained for future failures.
