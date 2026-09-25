# CLI operating limits

This folder retains the previously tested lighting CLI plus an explicitly authorized three-second presence watcher. The watcher invokes the existing CLI, not a new protocol. A fresh away report triggers purple ripples once; fresh nearby resumes minute-spaced liked-effect rotation. The collector's 10-second nearby hold is unchanged. Unknown/stale leaves lighting unchanged; see AUTOMATION.md. Its transport and presets were not changed by research cleanup. Visual confirmation establishes the tested effects and controls, not a zero-risk guarantee or complete protocol validation.

## Allowed behavior

- `effects`, `options`, `presets`, `preview`, and `--dry-run` operate offline.
- `discover` and `status` enumerate metadata; they do not open a HID device or send settings. `status` cannot read live lighting settings.
- Explicit `set`/`apply` requests send one validated 65-byte output buffer, then close the connection. Defaults fill omitted lighting values.
- Exact AK820 identity/interface checks, shared non-exclusive access, and a nonblocking local lock limit accidental device selection and overlapping CLI invocations. Other RGB applications are not covered by this lock.

## Limits

No firmware updates, bootloader/reset commands, raw-report access, configuration readback, custom per-key commands, macro/remapping writes, feature-report requests, keystroke reads, immediate failure retries, unconditional startup writes or frame-by-frame animation are exposed. The watcher may retry known pre-write failures only after a full minute; uncertain outcomes block further attempts pending explicit acknowledgment. Owner-authorized presence transitions can add writes between minute-spaced rotations, with a three-second minimum spacing. Radio flapping may increase write frequency and unknown storage-wear risk.

The unit's 17 effects and representative colour/brightness/speed/direction controls were visually confirmed. Some effects may ignore controls. Static/dedicated off opcodes remain unavailable, and lowest brightness is not a confirmed off state. Separately, one `breath` / `#000000` / `highest` / `fastest` / `left_to_right` trial was visually confirmed completely dark on this unit; that historical away setting has since been superseded by the owner's request for purple ripples. This does not certify firmware internals or USB power-off.

Persistence, write frequency and complete configuration semantics remain uncertain. The archived vendor analysis found framing/whole-block discrepancies that were not resolved or silently merged. Continue treating this as a constrained experimental controller; don't extend it by guessing commands or rapidly stream settings. No assertion is made that prior tests damaged the keyboard.

A failed or short write might have been partially accepted. Stop and inspect rather than retrying, seizing another interface, running an updater or guessing a recovery shortcut.

## Future research

The user has no spare keyboard. Research was archived to [Drive / Temp](https://drive.google.com/drive/folders/1_pUP8xbU7WhMEDNwIIuJAL_9MLCycoil); see the README for the archive and manifest links. It does not authorize future device tests. Any new protocol feature requires separate evidence review and explicit approval. Do not interpret an archived script or vendor executable as approved for execution.
