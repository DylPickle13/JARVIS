# Long & McQuade Used

Separate nationwide watcher for the regular Long & McQuade catalogue's **Used Anywhere** filter (`StockFilter=6`). It does **not** use Gear Hunter, modify Gear Hunter's state, or change that job.

## Coverage and alerts

- Discovers all inventory department IDs linked from the public navigation (currently 86 distinct inventory departments, across all categories, including print music and accessories). Gift Cards (department 56) is a special unfiltered sales page, not a used-stock catalogue, and is explicitly excluded. Existing checkpoints containing it resume safely without resetting history.
- Paginates every department's filtered results; deduplicates products by SKU.
- Follows each product's public store-inventory view without a province/store filter.
- Loads serial-level availability for **every** store with used/demo availability, not just the three nearby stores that the website expands automatically.
- Uses the **actual unit sale price**, never the new retail price shown on catalogue cards.
- Mirrors Used Anywhere: this also includes **demo and return inventory**. Alerts retain the source's condition label.
- Remembers SKU + case-insensitive serial across scans, prices, disappearances and store transfers. Units without serials use SKU + store + stock ID instead. It does not alert on price changes.
- Links point to the public inventory page. Purchase/add-to-cart URLs are inspected for IDs only and are **never followed**.

The entire **first sweep is a silent baseline**. New-unit alerts begin after that sweep completes. This is a rolling scan, not a simultaneous nationwide snapshot: stock can sell before an alert is read, pagination can shift, and brief appearances between sweeps may be missed. Alerts mean **newly seen**, not a guarantee of the store's acquisition date.

## Scheduling and load

JARVIS Shopping job: **Long & McQuade Used** (`job_922207a7b5e1`). Direct Python execution, every **15 minutes**, independently of Gear Hunter.

Each run performs up to 150 HTTP requests, spaced at least **4.2 seconds apart** (under 15 requests/minute, leaving headroom below the site's stated 20-request/minute limit). The 720-second time budget leaves room below the scheduler's default 900-second execution timeout. No immediate retries, parallel fetching, or full rescan every 15 minutes.

A complete nationwide sweep can require many thousands of requests and **may take several days** at this polite rate. The 15-minute schedule is the **batch cadence**, not a promise that every item is checked every 15 minutes. Baseline seeding continues automatically across runs; its duration depends on catalogue and store-stock volume. `--status` reports progress; alert silence during baseline is intentional.

Each successful parsed response atomically checkpoints its queue position. Time/request budgets yield silently and resume next run. A fetch, HTTP 429, block, parse mismatch or corrupt state fails visibly without advancing the failed task. File locking makes overlapping manual/scheduled checks silent no-ops. Previously discovered alerts are checkpointed and held across failed batches. Output is quiet if there are no new units.

Like the existing direct-stdout watcher, notification delivery is not transactional with state updates: a crash after clearing pending output but before the scheduler receives it can lose that batch's alert. The watcher prefers not to replay already-seen inventory.

## Files

- `used_scraper.py`: bounded scanner and CLI.
- `test_used_scraper.py`: offline regression tests.
- `requirements.txt`: already satisfied by the main JARVIS virtualenv.
- `used_state.json`: private-permission, atomic resumable checkpoint, cumulative unit history, pending alerts; gitignored.
- `used_state.json.lock`: process lock; gitignored.

Do **not** delete/reset a checkpoint casually: doing so discards deduplication history and starts another silent baseline. Restore a backup for corruption rather than treating it as empty state.

## Commands

From `/Users/dylanrapanan/JARVIS`:

```sh
# Bounded normal scan: silent unless it discovers new inventory after baseline.
.venv/bin/python projects/long-mcquade-used/used_scraper.py

# Inspect checkpoint only, no network access or notification.
.venv/bin/python projects/long-mcquade-used/used_scraper.py --status

# Smaller live batch; same persistent checkpoint and safe request spacing.
.venv/bin/python projects/long-mcquade-used/used_scraper.py --requests 10

# Offline tests, no real notifications or network access.
.venv/bin/python -m unittest discover -s projects/long-mcquade-used -v
```

`--state-file PATH` isolates a manual test from production. `--interval-seconds` may increase (not decrease) request spacing. `--max-seconds` may reduce the batch duration. Offline progress output must not be used as the scheduled command; otherwise it would notify every run.

## Example alert

```text
--- Long & McQuade Used: 1 new units ---
Gear: [BOSS - Blues Driver](https://www.long-mcquade.com/?page=instore_stock&usedFirst=1&Sku=46677)
Price: $114.00
Condition: Used
Location: Toronto (Danforth), Ontario
Serial: M2S5472
------------------------------
```

Live parser validation confirmed used and demo/return units with their actual prices. Site markup is subject to change; parser failures intentionally stop instead of silently dropping national coverage. Catalogue errors include the department and URL for diagnosis; an inactive Used Anywhere filter on any inventory department remains a hard failure.
