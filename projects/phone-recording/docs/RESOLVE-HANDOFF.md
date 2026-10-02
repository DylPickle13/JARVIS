# Editable Resolve handoff — September 9, 2026

**Historical demo:** the user subsequently authorized backing up/deleting this test project and validating a clean automatic rebuild. Current output is one full camera per video track, not the rough cut below. See [RESOLVE-AUTOMATIC.md](RESOLVE-AUTOMATIC.md).

## Open now

Project **Phone Recordings Auto Sync**, timeline **Rough Cut 20260909-160821-021d734f v002**.

- 72 seconds, twelve six-second camera shots, one continuous Samsung audio clip.
- Ordinary editable source-linked clips, not a flattened movie and not a native multicam clip.
- **Synced Sources 20260909-160821-021d734f v002** retains all three aligned camera tracks, with only Samsung audio enabled.
- The camera schedule is a technical demonstration, not an artistic music edit. Adjust cuts in the rough timeline; keep the source timeline intact.
- The `v001` timelines remain as development evidence. The v001 rough cut is incomplete (one shot); use **v002**.
- Project saved; `.drp` backup: `~/Movies/Phone Recordings/20260909-160821-021d734f/Resolve Sync/Phone Recordings Auto Sync - handoff-v002.drp`. This references existing media; it does not embed the videos.

## What worked

The installed application is the sandboxed App Store bundle `com.blackmagic-design.DaVinciResolveLite`, reporting DaVinci Resolve 21.0.4.5. Its actual menu-script folder is:

`~/Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data/Library/Application Support/Fusion/Scripts/Utility`

The normal non-sandbox user script folder was not being enumerated. Scripts appeared after restarting Resolve from the proper location. Lua launched through **Workspace → Scripts** receives the global `resolve` object; `bmd.scriptapp('Resolve')` alone still returned nil. Use `resolve or bmd.scriptapp('Resolve')`.

The native API imported the three original files, created tracks/timelines, placed source ranges, named tracks, set master audio, added review markers, saved the project and exported the backup. No mouse-driven timeline cutting was used; UI interaction was only for script launching/setup/inspection. There is no persistent external bridge, listener or background controller installed.

## Finite guarded jobs

`JARVIS Approved Edit.lua` in the sandbox Utility folder runs a local `Fusion/JARVIS/approved-job.lua` only after checking the exact dedicated project name. Each approved attempt has its own intent file. Existing intent blocks replay, including after failure; inspect evidence before staging another job. Runtime directory is owner-only. The final handoff job has already completed; clicking it again is intentionally blocked.

`JARVIS Read Only Probe.lua` currently writes timeline inventory to `Fusion/JARVIS/timeline-probe.txt`. It does not change the project.

Generator: project-root `resolve_rough_cut.py`. It is currently a **three-camera, 30fps technical proof of concept**, not the everyday dashboard importer. It rejects unapproved sync reports and existing timeline names. New revisions must use a new version number, never overwrite the user's changes.

## Failures and interpretation checks

- Early Console keystrokes were unreliable and opened Project Settings rather than executing code. Settings dialogs were canceled; switched to menu scripts instead.
- OTIO import returned nil after successful media import. No OTIO import success is claimed. Existing generated OTIO/report still describes the original synchronization, while the successful native-edit result is recorded separately.
- First native edit failed its exact duration assertion on one short shot. Direct measurements on this build showed `AppendToTimeline` consuming an end-exclusive source range; v002 corrected this and every six-second video cut measured exactly 180 frames.
- Resolve interprets LG as 28 FPS, Samsung as 29.97 FPS and iPhone as 30 FPS. Native source ranges are converted using those rates. Full source durations are checked with a four-frame tolerance against ffprobe; cuts use strict timeline-duration checks. This is not independent proof of correct VFR picture/audio synchronization.
- iPhone media is displayed portrait according to its orientation metadata. This is not an accidental crop. Current desk/monitor and dark LG views remain test material.

## Verified and remaining

**Verified:** 133 automated tests; actual API-created timelines; 12 consecutive 180-frame cuts; 2160-frame master audio; project save/export; visible Resolve timeline/viewer; original local media hashes unchanged. REAPER untouched.

**Next:** user plays v002, checks sync and adjusts a cut. Playback/lip-sync, advanced effects, native multicam conversion, long-form performance editing and a persistent automation bridge remain unproven. Do not rerun generation over a hand-edited timeline.

Evidence: `validation/resolve-edit-handoff-validation.json` and `validation/resolve-edit-handoff/`.
