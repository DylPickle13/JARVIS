# Key mappings

Part of the unified [Operation JARVIS keyboard project](../README.md). Mappings live here; the legacy `projects/key-mappings` compatibility symlink has been removed.

Mac-side keyboard and mouse remapping using [Karabiner-Elements](https://karabiner-elements.pqrs.org/).

## Setup status

- Karabiner-Elements 16.3.0 is installed and running.
- Required permissions are granted; the virtual HID driver is activated and enabled.
- Core service recognizes the AK820 and loaded the active profile update.
- Active mapping: AJAZZ AK820 mute media key → Play/Pause, scoped to vendor ID `12815` / product ID `20571`.
- Rule passes Karabiner's complex-modification linter. An authorized knob-press inspection confirmed `consumer_key_code: mute`; EventViewer was then closed.
- Initial mapping still muted. Enabled Modify events (`ignore: false`) for the AK820 combined keyboard/pointing interface only; core-service logs confirm both AK820 interfaces are now grabbed. Sir confirmed the knob press now triggers Play/Pause.

To disable the mapping, remove or disable its rule in Karabiner-Elements **Complex Modifications**. [Official installation and permissions guide](https://karabiner-elements.pqrs.org/docs/getting-started/installation/).

## Devices planned

| Device | Input | Planned action |
| --- | --- | --- |
| AJAZZ AK820 | Knob press (`mute` media key) | Play/Pause (active; user confirmed working) |
| AJAZZ AK820 | Knob rotation | Keep volume control |
| Razer DeathAdder Essential 2021 (`1532:0098`) | Two side buttons (`button4`/`button5`) | Disabled via Karabiner; loaded, physical verification pending |

AJAZZ vendor/product identifiers were obtained from Karabiner's connected-device inventory. An authorized knob-press inspection confirmed `mute`. The rule matches only this vendor/product pair. The combined keyboard/pointing interface requires Modify events enabled as well as the keyboard-only interface. Any other mute key emitting the same event on this device would also be remapped.

External mice require **Devices → Modify events** before Karabiner can remap them. This is now enabled for the Razer pointing interface. `razer-side-buttons-disabled.json` suppresses buttons 4/5, including with modifiers; normal clicks, scrolling and movement are unchanged by the rule. The live configuration was backed up before the rule was added. See [Razer lighting status and limitations](../docs/RAZER.md).

[Mouse-button documentation](https://karabiner-elements.pqrs.org/docs/help/how-to/mouse-button/)

## Configuration policy

- Keep reviewed, portable rule files in this project when mappings are chosen.
- Karabiner's live configuration lives in `~/.config/karabiner/`; do not replace it wholesale or commit device-specific live state.
- Back up existing configuration before applying rules.
- Mapping rules do not perform firmware changes or vendor HID writes. The separately reviewed AK820 lighting bridge is deployed; its implementation is tracked in [the bridge plan](../docs/KARABINER-BRIDGE.md). The Razer owned-handle extension is also installed; lighting acknowledgements and setting readbacks are verified. The owner confirmed breathing lights and normal clicking/scrolling; lifecycle acceptance remains pending. See [Razer status](../docs/RAZER.md).
- Remapping is Mac-side and requires Karabiner to be running with approved permissions.
- Disable a rule or disable **Modify events** for the device to stop remapping it.
