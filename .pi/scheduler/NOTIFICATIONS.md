# Scheduled-job notification summaries

The scheduler stores a dedicated `results.notification_summary` alongside the unchanged full output, error, and existing history summary. SQLite adds the nullable column automatically on connection; existing results are retained. Pending legacy results without this column populated are summarized from retained output when dispatched.

`runner.py:notification_summary` produces deterministic digests of the current scripts' text output contracts:

- Apple Refurb: Canadian availability, cheapest changed M4 Pro Mac mini listing when present, change count; US-only signals explicitly state they cannot ship to Canada. The price is scoped to the changed M4 Pro mini listings, not all stock.
- Gear Hunter: new-listing count, compact item names and prices, remaining-item count when necessary, and shared location when it fits.
- Projects Backup: completed project count, archive size and replacements; skips and dry runs are labeled separately.
- Failures: exception/error cause where recognizable, otherwise a bounded first line. Unknown job formats also use a bounded first line.

`apns_provider.py` retains the strict Lock Screen privacy filter, link handling, UTF-8/payload bounds and existing result routing. Titles use friendly job names. Both devices receive the same body, limited to 140 characters including the failure prefix. Successful notifications no longer have a redundant `Completed` prefix. Displayed length still depends on device and accessibility settings.

Silent successful runs remain silent. Error retention, Apple outage deduplication, delivery/retry policy, schedules and full Jobs detail output are unchanged. No additional AI calls or app rebuilds are needed. The scheduled runner starts fresh each tick and reads these changes automatically.

When changing a script's output format, update the corresponding digest parser and fixtures. Never infer backup success from exit status alone, mix US and Canadian availability, or select prices from unrelated product families.

Tests (no live pushes):

```sh
PYTHONPATH=.pi/scheduler python3 -m unittest discover -s .pi/scheduler/tests -v
```
