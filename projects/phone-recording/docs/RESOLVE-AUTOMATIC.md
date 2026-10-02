# Automatic Resolve timeline drop

## Normal workflow

**Stop & prepare** now runs:

1. Stop and verify managed collection on mac-mini-16.
2. Copy/verify the exact take on mac-mini-64 (reuse an existing verified copy safely).
3. Run confidence-gated cue-free audio alignment.
4. Use the native Resolve API to create/save **Phone Sync <take-id>** in **Phone Recordings Auto Sync**.

Every camera gets its **own named video track, with one full-length source clip**, placed at its synchronized offset. Each gets an audio track too, but only the chosen reference (currently Dyl Cam/Samsung) is enabled. There are **no automatic six-second cuts** in this normal workflow. The earlier rough-cut generator is a separate technical demo.

The highest enabled video track covers lower ones in the viewer. Toggle upper video tracks off to inspect lower angles, then make your cuts normally. These are ordinary editable tracks, not a native multicam clip.

Use the root launcher or shared CLI:

```sh
./phone-recording stop
./phone-recording prepare <take-id> # existing verified take through preparation
./phone-recording import <take-id>  # import only from approved sync report
```

## Implementation and scope

- `resolve_native.py`: verifies original hashes against `_verified-export.json`, validates the declared camera paths/offsets, generates a guarded finite Lua job, invokes it once through Workspace → Scripts and reads its completion receipt.
- `resolve_import.import_timeline` now routes to this native path. `import_timeline_external` preserves the legacy external/OTIO diagnostic, not the default.
- `prepare_resolve.py` already invokes import after successful synchronization; dashboard Stop/collect/prepare therefore share this integration.
- `dashboard_jobs.preparation_status` marks failed Resolve import as `resolve_import_needs_review`, rather than treating successful audio sync as a successful editor import.
- Roles/labels come from the report and camera registry. Four-track generation is covered synthetically; Overhead is still disabled and four-camera live validation is outstanding.
- Resolve must be available and permit the local Automation/menu action. The app may be brought forward; no GUI timeline cutting or simulated Console typing is involved.
- A missing dedicated project can be created. A saved/populated unrelated project blocks the import. The empty, unsaved `Untitled Project` placeholder exposed after project deletion is recognized only after checking its name, zero timelines, empty media/subfolders and absence from the saved project list.

## Privacy-prompt fix

The App Store build's script location is inside its protected container. Repeated reads/writes there were a likely cause of macOS asking whether Visual Studio Code could access other apps' data.

There is now **one fixed installed launcher**:

`~/Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data/Library/Application Support/Fusion/Scripts/Utility/JARVIS Approved Edit.lua`

It only loads:

`~/Movies/Phone Recordings/.resolve-automation/dispatch.lua`

All per-take job scripts, plans, submission records, completion receipts and locks live under **`~/Movies/Phone Recordings/.resolve-automation/`**, an owner-only shared workspace. Normal pipeline operation does not inspect or write the protected app container. Old evidence was retained; receipts and rebuild generation were migrated to the shared folder.

The fixed loader and shared read/write path were tested in the live app. macOS still controls permission prompts; their absence cannot be guaranteed. No Full Disk Access, TCC database modification, privacy reset, new network listener or security bypass was used. If a prompt recurs, identify the triggering operation rather than granting broad access by default. New installations may require one-time launcher setup/permissions and a safe Resolve restart so its menu enumerates the script.

## Replay and human-edit protection

- Completed plan receipts prevent duplicate imports; re-preparing the same take does not rerun Resolve mutations or overwrite your cuts. A cached receipt attests past completion, not a fresh inspection after you manually rename/delete a timeline.
- Existing timeline names without a matching completion receipt block, never overwrite.
- Persisted submission with no result is ambiguous and blocks replay. Another unresolved import blocks launching a new one. A reported pre-edit block can be retried deliberately after fixing the condition.
- Lua intent guards prevent manual menu replay from rewriting completed timelines or their receipts.
- Partial failures retain their timelines for inspection. No automatic timeline deletion.
- Deleting a Resolve project intentionally requires an explicit rebuild-generation change in `generation.json`, after verified backup/deletion. Ordinary retries never rotate this value. Retain old receipts/evidence.

## Clean rebuild test — September 9, 2026

User authorized deleting only the test project. Saved and verified backup:

`~/Movies/Phone Recordings/20260909-160821-021d734f/Resolve Sync/Phone Recordings Auto Sync - before-rebuild.drp`

Then closed/deleted **Phone Recordings Auto Sync** through the API, rotated the explicit generation, and ran the shared `prepare` command on the already verified take. The initial unrelated-placeholder block led to the narrow guard described above; the subsequent full preparation succeeded.

Verified live:
- Dedicated project recreated, exactly one timeline.
- V1 **Wide Angle**, V2 **Dyl Cam**, V3 **Bass Pedals**, one full source each.
- Three named audio tracks; only Dyl Cam enabled.
- Source starts 74/45/0 frames on the 30fps timeline; saved native timeline ID `d3fb8b78-12b6-4d49-924d-068ef3cccbb8`.
- Repeated preparation returned the same completed receipt/timeline ID without another import.
- Fixed launcher can read/write the shared workspace outside the protected container.
- **146 automated tests pass**, including retry ambiguity, blocked-project retry, duplicate protection, verified-file rejection, four-track script generation, explicit rebuild generation and no normal launcher-file access.

No new recording or phone deletion was performed during this clean rebuild test. Previously validated phone collection was not repeated. REAPER and original media were untouched. VFR/picture-audio sync still requires human review; timeline placement and duration checks do not replace it.

Evidence: `validation/resolve-automatic-pipeline-validation.json`, `resolve-automatic-track-probe.txt`, `resolve-clean-rebuild-deletion.json`.
