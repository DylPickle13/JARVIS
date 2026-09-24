# AJAZZ AK820 — Mac lighting CLI

Project: `/Users/dylanrapanan/JARVIS/projects/operation-jarvis/ajazz-keyboard`

Manual lighting controls for the **base wired RGB AK820**. This unit's 17 effects, RGB/rainbow, five brightness and speed levels, and both directions were visually confirmed in representative tests. Not every effect/control combination was tested; some effects may ignore some controls. Tested does not mean risk-free or full vendor-protocol certification.

The working CLI and presets are unchanged. This project was moved intact under Operation JARVIS (not copied); its runtime environment was recreated at the new path with the same pinned HID dependency. Experimental Windows-driver research, simulators, binary packages and analysis tools remain archived outside this project.

## Presence-gated rotation

**Enabled:** local LaunchAgent `com.jarvis.ajazz-keyboard-watch` checks authenticated basement proximity approximately every three seconds. Nearby, it cycles liked effects once per minute without immediate repeats. The private `Keyboard lights` job (`job_41fb6dd73fce`) now only relays alerts every minute; it does not control lighting. No model calls or new keyboard backend endpoint are used.

Healthy runs are silent. The first failure produces one error, continuing failures stay silent, and confirmed recovery produces one success result. Private persisted state survives process restarts; uncertain write outcomes block further writes pending acknowledgment.

**Both away → purple ripples:** the first fresh away report applies `ripples`, `#9933FF`, highest brightness and fastest speed once. **Either nearby → rotation resumes** on the first fresh nearby report. The collector's 10-second nearby hold is unchanged; the extra keyboard debounce is removed. Unknown/stale leaves lighting unchanged. The former black-RGB away behavior has been superseded. See [automation behavior, controls and limitations](docs/AUTOMATION.md).

## Usage

```sh
cd /Users/dylanrapanan/JARVIS/projects/operation-jarvis/ajazz-keyboard
./ajazz --help
./ajazz effects
./ajazz options
./ajazz presets

# Metadata only: these do not open the keyboard or send lighting reports.
./ajazz discover
./ajazz status

# Explicitly apply one lighting configuration:
./ajazz apply teal-breath
./ajazz apply rainbow-wave
./ajazz apply purple-ripples
./ajazz set --effect breath --color '#9933FF' --brightness low --speed slow

# Offline previews: no HID access.
./ajazz preview teal-breath
./ajazz set --effect wave --color rainbow --dry-run
./ajazz apply teal-breath --color '#9933FF' --dry-run
```

**Each write supplies a complete set of lighting values:** defaults → optional preset → flags. Omitted values do not preserve the keyboard's current settings. For example, `set --brightness medium` also requests default teal breathing, slow speed and left-to-right direction.

Defaults: `breath`, `#00AACC`, `low`, `slow`, `left_to_right`.

| Option | Values |
| --- | --- |
| `--effect` | `corrugated`, `cloud`, `serpentine`, `spectrum`, `breath`, `reaction`, `ripples`, `traverse`, `stars`, `flowers`, `roll`, `wave`, `cartoon`, `rain`, `scan`, `surmount`, `speed` |
| `--color` | Quoted `'#RRGGBB'` or `rainbow` |
| `--brightness` | `lowest`, `low`, `medium`, `high`, `highest` |
| `--speed` | `fastest`, `fast`, `medium`, `slow`, `slowest` |
| `--direction` | `left_to_right`, `right_to_left` |

`lowest` is not a verified off command. Static and dedicated off opcodes, per-key lighting, macros, remapping and firmware commands are not exposed. A historical black-breathing trial was visually confirmed dark, but the owner now requests purple ripples while away. `status` reports connection metadata, **not current lighting state**; `lighting_state` remains null. A successful write confirms transport, not readback or storage behavior.

## Presets and preferences

Bundled presets live in `presets/`. `apply` also accepts a JSON file with only the five lighting fields above; defaults fill omitted fields. Use `set --preset NAME` for a preset plus overrides.

Your saved preferences are preserved in [liked-effects.md](liked-effects.md).

## Safety

- One allowlisted output report per `set`/`apply`. The authorized watcher uses the same CLI: ordinary rotation once per minute, additional reports on fresh presence transitions, at least three seconds apart. No input reads, immediate failure retries, unconditional startup writes or frame-by-frame animation.
- Exact model/vendor-interface checks and shared/non-exclusive macOS access; never seize the keyboard.
- Avoid rapid repeated writes: nonvolatile storage behavior is unknown.
- Unknown/short-write outcomes block future writes; never reset or immediately retry. Only known pre-write failures may be tried after a full minute. A failed/short write may still have been partially accepted.
- See [operating limits](docs/SAFETY.md). Research-derived framing/storage uncertainties were not resolved by the visual tests; no experimental protocol changes were merged into this CLI.

## Setup and offline tests

The retained `.venv` is the CLI runtime, not the removed analysis environment. To recreate it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

The launcher uses this project's environment regardless of the caller's directory. Tests use mocks, previews and dry-runs; no real keyboard commands are sent. The enabled watcher, in contrast, can apply lighting when its fresh-presence gates pass. Disabling the alert scheduler alone does not stop the watcher; see the automation controls above.

Protocol attribution: [openajazz](https://github.com/not-nullptr/openajazz), inspected commit `800e8fba3ecd04db41c179d765e14867d5b9683f`. No upstream source or Windows binary is vendored here.

## Archived research

[Google Drive / Temp](https://drive.google.com/drive/folders/1_pUP8xbU7WhMEDNwIIuJAL_9MLCycoil):

- [Research archive and pre-cleanup snapshot](https://drive.google.com/file/d/1oZLqfRRGQ3nJFjJLQ3bx5-eI4oSHTVob/view)
- [Contents manifest and file hashes](https://drive.google.com/file/d/15iGZ5UayiC0A9t_rgX-kEIRU_PJ8jyqh/view)

Archive: `ajazz-keyboard-research-20260924T194016Z.tar.gz` (196,086,182 bytes).
SHA-256: `5c2fa212f3ca383eec0af78ff0ae49074ecabf17c98b8b6aa087549494ec8c19`.

Archive contents were checked locally; Drive size, MD5 and SHA-256 matched before local research removal. The archive includes vendor executables as inert evidence, **not software approved to run**. It includes original CLI/docs/tests for reference; runtime `.venv`, `.git`, the lock file and regenerable bytecode caches were excluded.
