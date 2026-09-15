# Purifier foreground refresh

Status: deployed as a backend-only continuation on 2026-09-15. The new daemon source is backend176 plus the foreground scheduling change; the sealed backend176 artifact remains untouched as rollback. Build181 iPhone/Watch apps are unchanged.

Active-client state requests schedule a shared purifier collection at most once per 60 seconds, using the same debounce as explicit refresh. Existing iPhone and Watch foreground state requests provide the cadence; both clients share one collector and in-flight guard. Actual timing is the first state request after the minute boundary, not an exact wall-clock timer.

No periodic purifier timer runs while clients are absent. Plain internal cache snapshots do not schedule collection. A read already queued or in flight may finish after the app closes. The existing active-state endpoint is the activity signal, so another consumer of that endpoint also counts as an active client.

Automatic refresh preserves VeSync cooldown/backoff and never requests cooldown recovery. Failed attempts remain debounced. The 90-second stale cutoff is unchanged: genuine failures should still appear stale rather than being hidden. No purifier settings are written.

Validation: 106 daemon tests pass, including foreground/manual shared debounce, two-client coalescing, in-flight suppression, background snapshots, and automatic refresh without cooldown override. The frozen-source suite also passed after supplying its repository-layout fixture dependencies; earlier layout failures remain recorded. A bounded live foreground-request observation produced successful two-device collections 60.53 seconds apart, with both devices fresh and no errors. All nine pane/PID/socket/history identities, terminal listeners, and unrelated config hashes were preserved; only the daemon PID and launch target changed. Private deployment evidence and the exact rollback plist are sealed under the JARVIS Application Support artifacts directory (`20260915T163002Z-backend-purifier-foreground-minute`). Physical iPhone/Watch owner validation remains pending.
