# Audio sync coverage v2

The confidence score is a correlation, not a probability. Percentage below means the fraction of sampled windows passing the existing signal/ambiguity checks, not a percentage of the recording's duration or a probability of correct sync.

Policy in `spectral_sync.py`:
- Strictly more than 75% of all sampled windows must pass, with at least five accepted windows. Nine samples require seven matches; exactly 75% fails.
- Accepted window centres must reach the first and last quarters, include the middle half, and span at least half the analyzed duration and two window lengths.
- The old first/last 20% requirement is replaced by quarters; the old 60% match-count threshold is tightened, not relaxed.
- All accepted matches participate in the timing checks: no removal of inconvenient confident outliers.
- Correlation >=0.35, peak ratio >=1.5, at least three active bands, drift/spread <=1/30s, residual <=1/60s and cross-camera cycle agreement <=1/60s remain unchanged.

Validation: 157 tests pass, including seven new coverage-policy tests and existing silence, unrelated audio, loops, drift, missing chunks and nonfinite-input rejection tests.

Read-only reanalysis of take `20260909-200506-80f4839a` verified source checksums and passed all three pair comparisons (8/9 windows each, 88.9%). Samsung reference offsets: LG +0.500s, iPhone -1.205s. Pair cycle error 0s; estimated drift magnitudes below 8ms over this take. Evidence: `validation/spectral-coverage-v2-validation.json`.

This diagnostic run did not replace the failed pipeline report, import into Resolve, touch REAPER or modify media. Use the dashboard's preparation retry to run the normal guarded pipeline on this take. Independent visual sync and long-session validation remain outstanding.
