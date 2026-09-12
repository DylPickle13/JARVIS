# Scheduled-job notification summaries

The scheduler saves a short `results.notification_summary` for alerts, alongside the full output, error, and history summary. Connecting to SQLite adds the nullable column without removing old results. If an older pending result has no notification summary, dispatch generates one from its saved output.

`runner.py:notification_summary` uses fixed parsing rules for each supported script's text output:

- Apple Refurb: Canadian availability, cheapest changed M4 Pro Mac mini listing when present, change count; US-only signals explicitly state they cannot ship to Canada. The price is scoped to the changed M4 Pro mini listings, not all stock.
- Gear Hunter: new-listing count, compact item names and prices, remaining-item count when necessary, and shared location when it fits.
- Projects Backup: completed project count, archive size and replacements; skips and dry runs are labeled separately.
- Failures: exception/error cause where recognizable, otherwise a bounded first line. Unknown job formats also use a bounded first line.

`apns_provider.py` applies the Lock Screen privacy filter, link handling, UTF-8 and payload limits, and result routing. Titles use readable job names. Both devices receive the same body, capped at 140 characters including any failure prefix. Successful alerts omit `Completed`. How much text is visible depends on the device and accessibility settings.

Successful runs with no output stay silent. Summaries do not change error retention, Apple outage deduplication, delivery/retry rules, schedules, or full Jobs output. They need no extra AI call or app rebuild: the scheduled runner starts fresh each tick and reads the parser code then.

When changing a script's output format, update the corresponding digest parser and fixtures. Never infer backup success from exit status alone, mix US and Canadian availability, or select prices from unrelated product families.

Tests (no live pushes):

```sh
PYTHONPATH=.pi/scheduler python3 -m unittest discover -s .pi/scheduler/tests -v
```
