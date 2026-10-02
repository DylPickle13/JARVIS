# Review pauses and Delete take

The dashboard now pauses twice instead of automatically proceeding from Stop to Resolve.

## Everyday flow

1. **Start recording**; wait for confirmation.
2. **Stop & review** stops cameras once and fingerprints the exact new clips. No footage copy is saved at this point. The iPhone fingerprint check reads its clip over the existing Network connection into memory, so this step can take time for large recordings. No file connection is held during recording.
3. **Before transfer:** choose **Transfer recording** or **Delete take…**. Deleting here discards the exact phone originals. The confirmation explicitly says there is **no saved Mac copy**.
4. Transfer collects and verifies the take on mac-mini-16, deleting managed phone originals only after the existing checks. It then **pauses**, without copying to mac-mini-64 or synchronizing.
5. **Before verified copy:** choose **Verify copy & prepare** or **Delete take…**. Deleting here removes the verified mac-mini-16 take; it has not been copied to this Mac.
6. Preparation verifies the second-Mac copy, aligns audio and imports the guarded Resolve timeline. **Delete take…** remains available afterward, for the take folder on both Macs and its sole dedicated Resolve project.

The latest take and Take library both expose these actions. Histories remain in overlays; the main page retains its no-scroll tested layout.

## Destructive confirmation and limits

- Permanent deletion: **no backup and no Trash**. Type `DELETE <exact-take-id> PHONES`, `REMOTE`, or `BOTH` according to the displayed scope. The backend independently checks the current stage; a stage change invalidates an old confirmation.
- No deletion while another job is running/queued/uncertain. Known recording or unresolved pending collection also blocks incompatible deletion. Start cannot proceed until a pending take is collected or explicitly discarded.
- Phone-only discard is offered only for a successfully stopped, fingerprinted review take, before any collection began. Exactly one new clip per enabled phone is required; ambiguous/additional clips block discard.
- Frozen phone file inventories and fingerprints are rechecked before deletion. All enabled cameras must be observed idle. No camera toggles are issued by discard. A durable per-file intent precedes each one-time deletion.
- Stage-two and completed-take deletion check exact archive identities, matching source hashes, and recorded successful phone-original deletion. Symlink/path traversal and changed sources block deletion. An incomplete/unverified local copy requires inspection, not a broad cleanup sweep.
- Resolve cleanup uses the existing finite menu launcher and shared Movies runtime. It requires the exact recorded timeline UID/name, exactly one timeline, and no media belonging to another take. An unrelated open project is not switched away from; only the existing narrow empty/unsaved Untitled Project exception is allowed. Mixed projects, renamed/replaced timelines, or ambiguous imports require manual inspection. No direct database/container deletion or `.drp` export occurs.
- Jobs hold the existing sync/import/controller locks. Immutable deletion IDs, durable intents and receipts prevent blind replay. Reconcile reads completed receipts; it does not resume interrupted media removal. Partial deletion remains blocked for manual inspection. Success rotates the Resolve import generation when the dedicated project was deleted, clears exact-take dashboard pointers, and retains non-media audit metadata.
- Legacy CLI `stop` retains its old automatic behavior; dashboard Stop and the Advanced safe-stop button use `stop_review`. Shared `collect` now pauses before local preparation. `prepare <take-id>` performs the remaining guarded work. Preparation/import are blocked while a managed recording/collection is pending.

## Validation and deployment

186 automated tests pass. New checks cover exact scope confirmation, CSRF, both review pauses, active/uncertain job exclusion, path and symlink rejection, changed hashes, remote single-shot receipts, stopped inventory rules, Resolve cleanup guards, and observation-only recovery. The real isolated Chrome fixture checks the new actions, phone-only warning, active-transfer disablement and no-scroll layout at four viewport sizes with four synthetic cameras.

Remote review/controller modules are deployed on mac-mini-16 under the controller lock; imports and syntax passed. Local dashboard was restarted only while idle. **No live recording or phone deletion was performed for this rollout.** A user-authorized real test of the new review/discard paths is still needed; the previous successful recording/Resolve playback test predates these changes.
