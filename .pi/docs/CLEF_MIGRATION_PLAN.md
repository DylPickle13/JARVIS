# Clef → oMLX migration plan

Status: **completed and verified** (2026-10-10). Sir approved the development release, both host upgrades and scoped retirement after verification. See the [completion report](CLEF_MIGRATION_RESULT.md) for final state, evidence and rollback locations.

## Target state

- Both Macs use the official app-managed **oMLX 0.7.1.dev1** release with bundled native kernels.
- `mac-mini-64` serves **`mlx-community/clef-4bit`** (the existing 27B, 4-bit model) through `POST /v1/systemone` on the existing oMLX endpoint. No substitute quantization or Clef-Flash without approval.
- `mac-mini-16` receives the server upgrade but **does not install or load 27B Clef**. It continues serving its existing models. It can call the 64 GB host's authenticated endpoint if a decision client is added later.
- `/Users/dylanrapanan/JARVIS/projects/clef-server` and its obsolete Hugging Face cache entry/unused weights are removed **after replacement verification**.
- Existing endpoints, authentication, provider IDs, model settings and other model files remain intact. No new standalone service, launchd job or Pi decision tool is part of this migration.

## Verified inventory and constraints

| Item | mac-mini-64 | mac-mini-16 |
|---|---|---|
| RAM | 64 GiB | 16 GiB |
| macOS | 27.0.1 | 27.0.1 |
| Installed app | `/Applications/oMLX.app`, 0.7.0 | Same, 0.7.0 |
| Service | App-managed, listening on port 8000 | Same |
| Model root | `/Users/dylanrapanan/.omlx/models` | Same path on remote host |
| Available data-volume disk | ~654 GiB | ~12 GiB |
| Existing oMLX model storage | ~49 GB | ~5.6 GB |
| Existing SSD KV cache | ~3.7 GB | ~8.3 GB |

Both currently use concurrency 1 and the `aggressive` memory-guard tier; preserve these settings initially. Local hot-cache limit is 4 GB; remote is 1 GB. Both currently have a legacy `/opt/homebrew/bin/omlx` symlink to the app's `~/.omlx/bin/omlx` shim, **not a Homebrew server installation**.

The existing Clef benchmark measured ~16.83 GB of MLX allocation for short synthetic inputs, before allowing for all OS/driver overhead. This makes the 16 GiB Mac an unsuitable deployment target; its free disk also cannot accommodate the ~16.3 GB download with headroom. Do not force it through swap or weaken memory guards. Clef-Flash 9B is an optional, separate future decision, not the same model.

## Release pin

This is a **development release**, despite the GitHub API's prerelease flag. Obtain explicit approval for that risk and a maintenance window before execution.

- Release: https://github.com/jundot/omlx/releases/tag/v0.7.1.dev1
- Matching official DMG for both hosts: https://github.com/jundot/omlx/releases/download/v0.7.1.dev1/oMLX-0.7.1.dev1-macos26-27.dmg
- Asset size observed: 845,293,387 bytes.
- Published asset SHA256 observed: `04fbff0b54bd8656a6684e3051879d7039cb5f4514777527614c54d6d00e0ca2`.

Recheck the release/asset metadata at execution; verify the downloaded hash, app signature and normal macOS trust assessment. Do not remove quarantine or bypass an update-signature/Gatekeeper failure. Do not use `brew upgrade omlx`, a floating source checkout or an independently modified app Python environment.

## 1. Preserve rollback and test evidence

1. Confirm the maintenance window, active requests and any running REAPER/music work before interrupting the remote host. No UI focus/Space changes without approval.
2. Recheck available disk and actual running backend version on both hosts. On the remote host, budget for the ~0.85 GB DMG, unpacked new app and ~1.6 GB old app backup; retain at least 5 GiB free after staging. If insufficient, stop and ask rather than deleting unrelated caches/models.
3. Privately back up each 0.7.0 app and its settings, model settings/profiles and lifecycle configuration, preserving permissions. Keep API keys/tokens out of this repository, terminal output and reports. Record existing catalog, loaded models, aliases and limits using read-only calls.
4. Save the small Clef source/lock manifest, example, verification notes and synthetic reports outside the folder scheduled for deletion. Do not retain a duplicate old virtualenv or 16 GB weight backup permanently.
5. Prepare an oMLX-specific smoke test outside `projects/clef-server`; do not run the old script unchanged. It assumes wrapper-specific health responses, identity, error codes and usage fields. All tests use synthetic inputs and perform no real tool/device actions.
6. Check whether either server participates in an active cluster. If so, pause cluster inference through its supported lifecycle and do not run mixed versions; update all participating approved nodes before resuming. Do not silently expand this task to other hosts.

**Gate:** recoverable app/settings backups, preserved fixture evidence, adequate disk and approval for downtime/development release.

## 2. Upgrade and validate mac-mini-64 first

1. Stage the verified official app without replacing a running bundle.
2. Drain requests, stop/quit the old app through supported lifecycle controls, replace it, and start the new app. Do not create a second listener or background service.
3. Confirm both app and backend report the target version, the existing port/authentication still work and native kernels match the new MLX runtime. Preserve existing model root and per-model settings.
4. Review removed debug `OMLX_*` environment settings if present; translate an actually used setting only through supported per-model controls, with approval. Do not assume removed settings still take effect.
5. Check the changed CLI shim behavior: the new app no longer creates `/opt/homebrew/bin/omlx` links and may ask about the legacy link. Ensure existing scripts still resolve the app-managed shim; do not introduce a Homebrew installation or blindly delete the link.
6. Run a bounded synthetic chat/stream/tool-call-format check against an existing model; do not execute any generated tool call. Verify Pi catalog discovery and request shaping without changing the user's current provider/model.

**Gate:** healthy existing service and no regression in existing chat clients. On failure, restore the 0.7.0 app and settings before touching the other host or deleting anything.

## 3. Download the same Clef model through oMLX

1. On the 64 GB host, use oMLX's authenticated downloader: `POST /admin/api/hf/download` with `{"repo_id":"mlx-community/clef-4bit"}`. Use the existing **main** API credential privately; a sub-key is insufficient for this management endpoint. Inspect the running `/openapi.json` schema before issuing management calls.
2. Track the returned task ID through `GET /admin/api/hf/tasks`; verify task state before any retry. Completion means verified files plus discovery, not merely acceptance of the start request.
3. Expected managed destination: `/Users/dylanrapanan/.omlx/models/mlx-community/clef-4bit`. Keep old cached weights until the new installation passes tests. This host has enough disk for temporary overlap.
4. **Revision caveat:** the old snapshot is `d004817dc77fc70916d21be82d951d8028ae3a5c`; upstream HEAD observed during planning is `b973b6f405d02f8e9b83208c7e82ddf43a742eb6`. The reviewed oMLX downloader does not provide a revision pin in its download arguments. Compare upstream file metadata before starting and verify downloaded hashes, especially all backbone shards, joint head, head config, tokenizer and model config, against the old snapshot. Record the actual installed revision. If inference-relevant artifacts differ, stop for approval rather than claiming a byte-identical migration. A repository name alone does not establish identity.
5. Confirm all shards, tokenizer/processor assets, `joint_head.safetensors` and `joint_head_config.json` exist. oMLX should identify the model as `decision`, not ordinary VLM/chat. Prefer automatic detection; change the model-type override only if required and verified.
6. Set API alias `clef` if supported by the actual runtime schema and not already used. Otherwise record the discovered model ID and use that explicitly. Keep the model **unpinned** with a bounded idle TTL (proposed 300 seconds), using supported per-model settings.
7. Downloading custom-code files does not authorize executing them. Use oMLX's built-in decision engine, not `clef_mlx.py` or `trust_remote_code` as a workaround. Do not execute downloaded bytecode.

**Gate:** correct model identity, complete independent managed installation, decision-engine discovery and recorded revision.

## 4. Verify decision behavior and cut over

Use the 64 GB host's existing authenticated `http://127.0.0.1:8000/v1/systemone` endpoint, not port 8091 or `/v1/chat/completions`.

- Send `"truncate": false` on **every decision request**: oMLX defaults to truncation, whereas the wrapper rejected overflow.
- Test `choice`, `score` and `noul`; validate returned answer structure, finite bounded probabilities, probability sums, score semantics and usage using the new runtime contract.
- Repeat the existing 307-token synthetic fixture; compare top choices, score/probability outputs and latency against retained reports. Investigate deviations rather than requiring bitwise-identical results across different engines/chunking. Record tolerances and any approved revision change.
- Test the synthetic red image as a full base64 **data URI**. Do not rely on wrapper-specific bare base64/HTTP image URL support or cause outbound image fetches.
- Verify oversized context returns HTTP 413 with `truncate:false`. Verify invalid JSON/schema/type, empty questions, unsupported video and bounded request-body behavior, adapting to oMLX's actual error contract (400/422 differences are expected).
- Run a small repeated/concurrent workload; measure request latency, MLX/process memory where available, memory pressure and swap changes. Stop on unsafe pressure; do not disable safeguards.
- Validate Clef/chat coexistence with the existing catalog. Approve any necessary unloading of currently pinned models first; keep aggregate working sets within memory limits. Verify idle unloading and subsequent reload with bounded checks, not a permanent watcher.
- Confirm decision models remain excluded from Pi's chat-model picker. A separate future decision client/tool is needed if JARVIS is to use classification automatically; server installation does not add that integration.

**Gate:** text/image/error/overflow checks and existing chat checks pass; report records installed identity, latency/memory and remaining limitations. No obsolete assets are removed before this gate.

## 5. Upgrade mac-mini-16

1. Repeat the verified app replacement and rollback safeguards using the same release/asset.
2. Preserve all existing models, credentials, endpoints and memory settings. Do not download/load 27B Clef.
3. Verify actual backend version, native kernels, authenticated catalog, an existing lightweight model's synthetic chat/stream/tool-call-format behavior, and connectivity from the local client.
4. Check disk headroom and CLI shim resolution. Do not purge its ~8.3 GB KV cache or unrelated files to make space without separate approval.

If clustered, perform the version transition under the paused-cluster gate rather than allowing a mixed-version interval. Otherwise validate one host before interrupting the next.

**Gate:** both hosts healthy on the target release, or the failed host restored and the migration marked incomplete.

## 6. Remove obsolete Clef assets last

1. Confirm no wrapper process/listener remains on 8091 and no active client depends on it. Preserve the minimal migration fixtures/report outside the doomed folder.
2. Verify the new managed model's resolved files are not symlinks into the old HF cache; prove it survives an unload/reload before cleanup and retest after cleanup.
3. Use Hugging Face's supported **repository-scoped cache removal**, not a blind `rm -rf` of its model directory/global blob store. The old repo directory is only ~316 KB because large artifacts resolve into the shared `~/.cache/huggingface/hub/blobs/` store.
4. Re-run this preview immediately before deletion, while the old virtualenv still exists:

   ```bash
   cd /Users/dylanrapanan/JARVIS/projects/clef-server
   ./.venv/bin/hf cache rm model/mlx-community/clef-4bit --dry-run --json
   ```

   Planning preview returned `{"dry_run":true,"repos":1,"revisions":1,"size":"16.3G"}`. After the verification gates and explicit destructive-action approval, use the same scoped removal command **without** `--dry-run`, then verify cache inventory and actual reclaimed disk. Let the cache tool preserve blobs referenced by other repositories. Do not use global `cache prune` or delete the whole HF/Xet cache; inspect any identifiable Clef-only transport leftovers separately before proposing removal.
5. Delete exactly `/Users/dylanrapanan/JARVIS/projects/clef-server` (~638 MB, mostly its virtualenv) only after the cache tool has finished and evidence is retained. The folder is ignored by parent Git, so Git alone cannot restore it.
6. Recheck both oMLX services and rerun a short authenticated text/image decision check from a fresh Clef load. Record that the folder/cache entry are gone and the managed model still works.
7. Remove temporary DMG/staging copies after success. Retain small rollback app/settings backups until sir signs off; no old Clef weights should remain solely for rollback.

Downloading Clef again replaces roughly the same model storage elsewhere; this is primarily service consolidation, **not a net 16 GB disk saving**. Approximate net gain from removing the old virtualenv is ~638 MB, subject to shared blobs/filesystem accounting.

## Rollback and approval

**Historical safeguards only:** after successful verification, sir requested removal of both migration rollback bundles. They have been deleted; any future downgrade requires fresh installation/reconstruction. See the [completion report](CLEF_MIGRATION_RESULT.md).

- Before deletion: restore each failed host's private 0.7.0 app/settings backup and original lifecycle. Keep the old Clef assets available; stop new managed inference if necessary.
- After deletion: app/settings rollback still works, but restoring the standalone Clef model requires recovering the retained source/manifest and explicitly downloading the old pinned snapshot again. Do not pretend a metadata backup contains the removed weights.
- If exact-revision fidelity cannot be demonstrated, pause before cutover/deletion for a model-revision decision.
- Required execution approval: development release, maintenance window/restarts on both hosts, 27B Clef installed only on the 64 GB host, and scoped final deletion after passing gates.

## References

- Release and upgrade notes: https://github.com/jundot/omlx/releases/tag/v0.7.1.dev1
- Decision implementation/parity notes: https://github.com/jundot/omlx/pull/4315
- Versioned management API: https://github.com/jundot/omlx/blob/v0.7.1.dev1/docs/admin-api.md
- Model: https://huggingface.co/mlx-community/clef-4bit
