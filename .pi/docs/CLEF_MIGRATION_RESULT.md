# Clef → oMLX migration: completed

Verified **2026-10-10** after sir approved [the migration plan](CLEF_MIGRATION_PLAN.md).

## Final state

| Host | Installed/running backend | Model deployment |
|---|---|---|
| `mac-mini-64` | Official app-managed oMLX **0.7.1.dev1** | Existing three chat models plus `mlx-community/clef-4bit` |
| `mac-mini-16` | Official app-managed oMLX **0.7.1.dev1** | Existing Qwen3.5-9B model; **no 27B Clef** |

Both servers are healthy on their existing port 8000 and use MLX **0.32.3**. All five bundled native-kernel groups reported available on both hosts. The official macOS 26/27 DMG matched its published SHA256, passed signature verification and was accepted as a notarized Developer ID application. No quarantine/signature/trust bypass was used.

**Clef deployment:**

- Managed directory: `/Users/dylanrapanan/.omlx/models/mlx-community/clef-4bit`.
- API alias: **`clef`**; engine: **`decision`**; context setting: **16,384 tokens**.
- Endpoint: authenticated **`POST http://127.0.0.1:8000/v1/systemone`**.
- Always send **`"truncate": false`**; images use full base64 image data URIs.
- **Unpinned**, idle TTL **300 seconds**, remote-code trust **false**. Intentionally unloaded after testing to leave memory for chat; it loads on demand.
- No standalone replacement service or automatic Pi/JARVIS decision-tool integration was added. Clef remains excluded from the chat-model picker.

## Same-model verification

The old pinned revision was `d004817dc77fc70916d21be82d951d8028ae3a5c`. Upstream HEAD at download start was `b973b6f405d02f8e9b83208c7e82ddf43a742eb6`; its changes were README/evaluation files only.

**All 13 inference-related artifacts matched the old installed files by SHA256**, including all three weight shards, joint head, head configuration, model/tokenizer/processor configuration and tokenizer. The new managed files are regular files independent of the old HF snapshot/global blobs. The oMLX downloader does not expose a revision pin; the verified artifact hashes, not a floating repository name, establish model identity.

## Checks passed

- **16 live Clef HTTP checks**, repeated successfully after deletion and a fresh model load: health, identity, warmup, all typed questions, repeat stability, malformed JSON/schema/type/criteria, invalid video-as-image, context overflow, transport body cap, chat-route rejection, concurrency and a synthetic red image.
- **5-check quick cold-start suite** after the final app restart: health, identity, load/warmup, text parity and image inference.
- Idle unloading observed with a temporary 10-second test TTL; final TTL restored to 300 seconds. Fresh inference reloaded the model successfully.
- Existing Pi chat discovery, thinking off/on, streaming, synthetic tool-call arguments/multi-turn results and image recognition passed on **both upgraded hosts**, including after app restarts. No generated real tool call was executed.
- **18 existing oMLX bridge regression tests** and **6 new offline smoke-client tests** passed; Python compilation, Ruff 0.16.10 lint/format and Git whitespace checks passed.
- All 11 checked endpoint/authentication/model-root/memory/concurrency/autostart settings were preserved on both hosts. Existing local per-model values were preserved; serialization added only the new `embedding_audio_enabled:false` default. Remote per-model settings were unchanged.

Small synthetic text fixture: 307 tokens; post-cleanup median **2.410 seconds**, versus the historical standalone ~2.51 seconds. Top choices matched. Maximum probability difference was **0.0095** (0.95 percentage points), within the predeclared 0.01 tolerance; outputs are **not bit-identical** across engines. The synthetic image remained red with confidence **0.9968**. These are smoke observations, not a general speed/calibration guarantee.

Clef and Qwen3.6-35B coexisted with aggregate reported MLX/process allocation ~**34.9 GiB** and pressure level **`ok`**. Swap usage rose from ~907 MB to ~4,024 MB during staging/reloads and was stable in the final coexistence check; this is system-wide, not process-attributed. Clef was explicitly unloaded after final verification. No memory safeguards were weakened, and no claim of a swap-free migration is made.

## Retirement and cleanup

- Deleted `/Users/dylanrapanan/JARVIS/projects/clef-server` (~638 MB, mostly its virtualenv).
- Removed the old `mlx-community/clef-4bit` HF repository/cache/unused weights with the repository-scoped supported cache tool, which reported **16.3 GB removed**. No other model cache or global HF/Xet cache was purged.
- The oMLX download had created a dangling old-cache `refs/main` pointing to a HEAD snapshot that existed only in the managed download. This made the old HF CLI skip that cache entry. Backed up and removed just that dangling ref, repeated the scoped deletion preview, and verified no outside symlink references to the old large artifacts before deletion.
- Rechecked new artifact hashes after cache deletion; rescanned oMLX, removing the duplicate old cached-model catalog entry, and reran the full live suite successfully. No listener remains on 8091.
- Removed temporary DMGs/staging and redundant retired-app copies on both hosts.
- Preserved `/opt/homebrew/bin/omlx` → `~/.omlx/bin/omlx` compatibility links. The new app's CLI-link reminder can be hidden by a non-activating launch and block startup; saved its ordinary non-destructive `suppressShellPathPrompt:true` preference in `~/Library/Application Support/oMLX/cli-path-prefs.json`, then verified background app startup on both hosts. No shell path, authentication or macOS security policy was changed.

Replacing the model means there is still one ~16.3 GB managed copy. The old cache removal is **not a net 16.3 GB model-storage saving**.

## Evidence and rollback cleanup

Reusable test client: `.pi/scripts/smoke-clef-omlx.py`; offline tests: `.pi/scripts/tests/test_smoke_clef_omlx.py`; synthetic fixtures/old manifest: `.pi/tests/fixtures/clef/`.

Ignored synthetic reports: `.pi/runtime/clef-migration-20261010/` (`live-smoke.json`, `post-cleanup-live-smoke.json`, cold/reload reports and final two-host chat log).

At sir's explicit follow-up request, removed `~/.omlx/backups/clef-migration-20261010T2110Z/` on **both hosts** (~1.6 GB each), including the old 0.7.0 apps, original settings and temporary helper/source archives. **No migration rollback bundle remains.** Current apps, models and configuration were not changed; both servers remained healthy after removal.

Only non-sensitive artifact-hash and TTL-verification JSON was retained in the ignored `.pi/runtime/clef-migration-20261010/` evidence directory. No private settings, credentials, app bundles or rollback archives are included in the repository changes. A future downgrade would require fresh installation and deliberate configuration reconstruction, not restoration from these deleted backups.

## Remaining limitations

- The installed oMLX version is a **development release**, not 0.7.1 stable.
- Server default truncation is still true; clients must explicitly disable it.
- Unknown extra JSON fields may be ignored; clients must reject unsupported video fields themselves. Invalid video data supplied as an image was rejected in testing.
- The transport body cap is oMLX-wide (default 512 MB), not the former wrapper's 16 MiB cap. It was verified without sending a large body; global upload limits were not changed.
- 27B Clef is intentionally not deployed on the 16 GiB host. No classification/tool/device authorization path was added.
