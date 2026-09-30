#!/usr/bin/env python3
"""Resumable, nationwide watcher for Long & McQuade's Used Anywhere filter."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
import requests

BASE = "https://www.long-mcquade.com"
STATE = Path(__file__).with_name("used_state.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
}
SCHEMA = 1
# Gift Cards is a special, unfiltered sales page, not a used-stock catalogue.
NON_INVENTORY_DEPARTMENT_IDS = {"56"}
MAX_OUTPUT_UNITS = 100
MAX_OUTPUT_BYTES = 60 * 1024  # Below the scheduler's 64 KiB retained-output limit.


def text(value):
    return re.sub(r"\s+", " ", str(value)).strip()


def response_problem(html):
    if not html.strip():
        return "Empty response"
    lowered = html.lower()
    for marker in ("too many requests", "cf-chl-", "just a moment"):
        if marker in lowered:
            kind = "Rate-limited" if marker == "too many requests" else "Blocked"
            return f"{kind} response (marker={marker!r})"
    return None


def soup(html):
    problem = response_problem(html)
    if problem:
        raise ValueError(f"{problem}; checkpoint preserved")
    return BeautifulSoup(html, "html.parser")


def public_url(href):
    url = urljoin(BASE + "/", href)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in ("long-mcquade.com", "www.long-mcquade.com"):
        raise ValueError("Unexpected off-site inventory link")
    # Some catalogue cards use the bare domain. Keep links on the canonical
    # HTTPS host while still rejecting unrelated domains and userinfo/ports.
    return parsed._replace(scheme="https", netloc=urlparse(BASE).netloc).geturl()


def department_id(url):
    match = re.match(r"/departments/(\d+)(?:/|$)", urlparse(url).path)
    return match[1] if match else None


def discover_departments(html):
    found = {}
    for anchor in soup(html).select("a[href]"):
        url = public_url(anchor["href"]) if "/departments/" in anchor["href"] else None
        identifier = department_id(url) if url else None
        if identifier and identifier not in NON_INVENTORY_DEPARTMENT_IDS:
            found.setdefault(identifier, {"url": url.split("?", 1)[0], "name": text(anchor.get_text(" ", strip=True))})
    if len(found) < 40:
        raise ValueError(f"Only {len(found)} departments found; refusing incomplete nationwide discovery")
    return list(found.values())


def parse_catalogue(html):
    page = soup(html)
    used_filter = page.select_one('input[name="StockFilter"][value="6"]')
    if used_filter is None or not used_filter.has_attr("checked"):
        raise ValueError("Used Anywhere filter is not active")
    counter = page.select_one(".pagination-count")
    match = re.search(r"Products\s+([\d,]+)\s+to\s+([\d,]+)\s+of\s+([\d,]+)", text(counter.get_text(" ")) if counter else "")
    if not match:
        if not page.select("a.products-item-link") and "We currently do not have stock in our retail stores." in page.get_text(" ", strip=True):
            return [], 0, 0
        raise ValueError("Catalogue pagination count missing")
    first, last, total = (int(x.replace(",", "")) for x in match.groups())
    products = {}
    cards = page.select("a.products-item-link")
    for card in cards:
        stock_links = card.select('a[href*="instore_stock"]')
        image = card.select_one("img")
        name = text(image.get("alt") or image.get("title") or "") if image else ""
        if not name:
            # Some legitimate cards (e.g. Paiste 2002 cymbals) have blank
            # image metadata. Use the visible brand/model, not price text.
            brand = card.select_one(".products-item-descr > p.fw-bolder:not(.text-grey)")
            model = card.select_one(".products-item-descr > p.text-grey")
            if model and text(model.get_text(" ")):
                name = " - ".join(text(node.get_text(" ")) for node in (brand, model) if node and text(node.get_text(" ")))
        # Do not mistake the catalogue's NEW retail price for a used-unit price.
        for link in stock_links:
            query = parse_qs(urlparse(link["href"]).query)
            sku = query.get("Sku", [""])[0]
            if not sku.isdigit() or not name:
                raise ValueError("Inventory card SKU or name missing")
            product_path = urlparse(card.get("href", "")).path
            product_id = re.match(r"/(\d+)/", product_path)
            if not product_id:
                raise ValueError("Product ID missing")
            products[sku] = {"sku": sku, "product_id": product_id[1], "name": name,
                             "link": public_url(card["href"]), "stock_link": stock_url(sku)}
    if total and (not cards or not products):
        raise ValueError("Nonempty catalogue has no parseable inventory cards")
    if total and len(cards) != last - first + 1:
        raise ValueError("Catalogue card count does not match pagination")
    return list(products.values()), last, total


def stock_url(sku):
    return BASE + "/?" + urlencode({"page": "instore_stock", "usedFirst": 1, "Sku": sku})


def parse_stores(html, product):
    page = soup(html)
    if "In Store Stock" not in page.get_text(" ", strip=True):
        raise ValueError("Store inventory page missing")
    tasks = []
    for row in page.select("[data-store-id][data-sku]"):
        if not row.select_one(".used-available,.demo-available"):
            continue
        if row["data-sku"] != product["sku"]:
            raise ValueError("Store inventory SKU mismatch")
        # The site groups demo/returns with used availability. Query each group,
        # deduplicate physical units later, and retain the site's condition label.
        for mode, selector in ((0, ".used-available"), (1, ".demo-available")):
            if not row.select_one(selector):
                continue
            location = row.select_one('a[href*="/location/"]')
            if location is None:
                raise ValueError("Store location link missing")
            parts = urlparse(location["href"]).path.strip("/").split("/")
            location_column = location.find_parent("td") or location.find_parent("div", class_="col-md-4")
            name = location_column.select_one("span.fs-5.fw-bolder,span.fw-bolder.fs-5") if location_column else None
            if name is None or len(parts) < 3:
                raise ValueError("Store name or province missing")
            tasks.append({"product": product, "store_id": row["data-store-id"], "store": text(name.get_text(" ")),
                          "province": parts[1].replace("-", " "), "demo": mode,
                          "product_id": row.get("data-product-id", product["product_id"])})
    # Legitimate sold-out products can have no available stores.
    if not page.select("[data-store-id]") and "Out of Stock" not in page.get_text(" "):
        raise ValueError("Store inventory rows missing")
    return tasks


def labeled(card, label):
    for strong in card.select("strong"):
        if text(strong.get_text()).rstrip(":").casefold() == label.casefold():
            return text(strong.parent.get_text(" ", strip=True)).split(":", 1)[1].strip()
    return ""


def parse_units(html, task):
    page = soup(html)
    wrapper = page.select_one("div.fw-normal.fs-7")
    if wrapper is None:
        raise ValueError("Stock detail wrapper missing")
    result = []
    cards = wrapper.select("div.mb-3.p-2.bg-light-grey")
    if not cards and wrapper.select("strong"):
        raise ValueError("Stock detail markup changed")
    for card in cards:
        sku, serial = labeled(card, "SKU"), labeled(card, "Serial")
        price, condition = labeled(card, "Sale Price"), labeled(card, "Condition")
        if sku != task["product"]["sku"] or not re.fullmatch(r"\$[\d,]+(?:\.\d{2})?", price) or not condition:
            raise ValueError("Incomplete or mismatched unit details")
        # The demo endpoint also returns rental-only units at the new price,
        # with no purchase link. They are not used items for sale.
        if condition.casefold() == "available for rent":
            continue
        stock_id = ""
        has_sale_link = False
        for anchor in card.select("a[href]"):
            query = parse_qs(urlparse(anchor["href"]).query)
            candidate_id = query.get("locationsStockID", [""])[0]
            stock_id = candidate_id or stock_id
            # Inspect identifiers only. NEVER follow add-to-cart links.
            location_id = query.get("pickupInStoreId", query.get("ShipDirect", []))
            if location_id and location_id[0] != task["store_id"]:
                raise ValueError("Stock detail store mismatch")
            if query.get("action", [""])[0] in ("addUsedToCart", "addDemoToCart"):
                public_url(anchor["href"])  # Sale evidence must be on-site.
                if query.get("ProductsID", [task["product_id"]])[0] != task["product_id"]:
                    raise ValueError("Stock detail product mismatch")
                has_sale_link |= candidate_id.isdigit() and bool(location_id)
        # Condition is sometimes a free-form store note, not a stock type
        # (e.g. missing packaging / pickup only). An explicit, matching
        # used/demo purchase action proves sale eligibility independently.
        if not re.search(r"\b(used|demo|return)\b", condition, re.I) and not has_sale_link:
            raise ValueError(f"Unexpected inventory condition without used/demo sale link: {condition}")
        serial_missing = serial.casefold() in ("", "n/a", "none", "unknown", "-", "0")
        if serial_missing and not stock_id:
            raise ValueError("Unit has neither a serial nor a stock ID")
        key = f"{sku}:serial:{serial.casefold()}" if not serial_missing else f"{sku}:stock:{task['store_id']}:{stock_id}"
        result.append({"id": key, "sku": sku, "serial": serial, "stock_id": stock_id,
                       "name": task["product"]["name"], "price": price, "condition": condition,
                       "store": task["store"], "store_id": task["store_id"], "province": task["province"],
                       "link": stock_url(sku), "product_link": task["product"]["link"]})
    return result


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fresh_state():
    return {"schema": SCHEMA, "baseline_complete": False, "cycles_completed": 0, "stage": "discover",
            "catalogue_queue": [], "products": {}, "product_queue": [], "store_queue": [],
            "known_units": {}, "pending_alerts": [], "created_at": now(), "requests_total": 0}


def load_state(path):
    if not path.exists():
        return fresh_state()
    # Fail closed: a corrupt checkpoint must not re-alert all existing stock.
    data = json.loads(path.read_text())
    required = set(fresh_state()) - {"created_at"}
    if not isinstance(data, dict) or not required <= data.keys() or data["schema"] != SCHEMA:
        raise ValueError("Invalid checkpoint; restore state rather than resetting it")
    if data["stage"] not in ("discover", "catalogue", "inventory"):
        raise ValueError("Invalid checkpoint stage")
    return data


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".used-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def exclusive_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


class BudgetExhausted(Exception):
    pass


class Client:
    def __init__(self, max_requests=150, interval=4.2, max_seconds=720):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.max_requests, self.interval = max_requests, interval
        self.deadline = time.monotonic() + max_seconds
        self.last_request = 0.0
        self.count = 0

    def _request_once(self, method, url, **kwargs):
        if self.count >= self.max_requests or time.monotonic() + 35 >= self.deadline:
            raise BudgetExhausted
        wait = self.interval - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        if time.monotonic() + 35 >= self.deadline:
            raise BudgetExhausted
        self.last_request = time.monotonic()
        self.count += 1
        return self.session.request(method, url, timeout=(10, 25), **kwargs)

    def request(self, method, url, **kwargs):
        # These GETs and LocationStockSerials POSTs only read public inventory.
        # Retry at most once; never retry a block or explicit rate limit.
        for attempt in range(2):
            retryable = False
            try:
                response = self._request_once(method, url, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                issue = f"Transport failure ({type(exc).__name__})"
                diagnostic = f"{method} {url}"
                retryable = True
            else:
                diagnostic = (f"{method} {url}; HTTP {response.status_code}; "
                              f"bytes={len(response.content)}; "
                              f"content-type={text(response.headers.get('Content-Type', 'unknown'))[:80]!r}; "
                              f"retry-after={text(response.headers.get('Retry-After', ''))[:80]!r}")
                problem = response_problem(response.text)
                if response.status_code >= 400:
                    issue = f"HTTP {response.status_code}"
                    # A block/rate-limit body or Retry-After takes precedence
                    # even when the server uses a nominally transient status.
                    retryable = (response.status_code in (502, 503, 504)
                                 and not response.headers.get("Retry-After")
                                 and (problem is None or problem == "Empty response"))
                    if problem:
                        issue += f": {problem}"
                elif problem:
                    issue = problem
                    retryable = problem == "Empty response" and not response.headers.get("Retry-After")
                else:
                    return response.text
            error = ValueError(f"{issue}; {diagnostic}; checkpoint preserved")
            if not retryable or attempt:
                raise error
            delay = max(30.0, self.interval)
            if self.count >= self.max_requests or time.monotonic() + delay + 35 >= self.deadline:
                # Do not disguise a failed response as a successful budget yield.
                raise ValueError(f"{error}; retry unavailable within batch budget")
            time.sleep(delay)

    def get(self, url):
        return self.request("GET", url)

    def details(self, task):
        return self.request("POST", BASE + "/includes/AjaxFunctions.php",
                            data={"action": "LocationStockSerials", "storeId": task["store_id"], "demo": task["demo"],
                                  "productId": task["product_id"], "sku": task["product"]["sku"]},
                            headers={"X-Requested-With": "XMLHttpRequest", "Referer": task["product"]["stock_link"]})


def enable_initial_output(state):
    """Queue previously seeded units once; preserve scan position and identity history."""
    if state.get("initial_output_enabled", False):
        return 0
    pending_ids = {unit["id"] for unit in state["pending_alerts"]}
    backlog = [{**unit, "initial_inventory": True} for unit in state["known_units"].values()
               if unit["id"] not in pending_ids]
    state["pending_alerts"].extend(backlog)
    state["initial_output_enabled"] = True
    return len(backlog)


def record_units(state, units):
    for unit in units:
        if unit["id"] not in state["known_units"]:
            if state["baseline_complete"] or state.get("initial_output_enabled", False):
                state["pending_alerts"].append({**unit, "initial_inventory": not state["baseline_complete"]})
            state["known_units"][unit["id"]] = {"first_seen": now(), **unit}
        else:
            state["known_units"][unit["id"]].update(unit)


def step(state, client):
    requested = True
    if state["stage"] == "discover":
        departments = discover_departments(client.get(BASE + "/"))
        state.update(stage="catalogue", departments=departments, cycle_started_at=now(),
                     catalogue_queue=[{**d, "offset": 0} for d in departments], products={}, product_queue=[], store_queue=[])
    elif state["stage"] == "catalogue":
        task = state["catalogue_queue"][0]
        url = task["url"] + "?" + urlencode({"StockFilter": 6, "PerPage": 64, "Current": task["offset"]})
        if department_id(task["url"]) in NON_INVENTORY_DEPARTMENT_IDS:
            # Old checkpoints may still contain Gift Cards. Advance only that
            # known non-inventory task without resetting discovery or history.
            products, last, total = [], 0, 0
            requested = False
        else:
            try:
                html = client.get(url)
                products, last, total = parse_catalogue(html)
            except (ValueError, requests.RequestException) as exc:
                raise ValueError(f"{task.get('name', 'Department')} catalogue ({url}): {exc}") from exc
        if total and last <= task["offset"]:
            raise ValueError("Pagination did not advance")
        state["products"].update({p["sku"]: p for p in products})
        state["catalogue_queue"].pop(0)
        if last < total:
            state["catalogue_queue"].append({**task, "offset": last})
        if not state["catalogue_queue"]:
            if not state["products"]:
                raise ValueError("Nationwide catalogue unexpectedly empty")
            state.update(stage="inventory", product_queue=list(state["products"]))
    else:
        if state["store_queue"]:
            task = state["store_queue"][0]
            try:
                html = client.details(task)
                units = parse_units(html, task)
            except (ValueError, requests.RequestException) as exc:
                raise ValueError(f"SKU {task['product']['sku']} at {task['store']} (demo={task['demo']}): {exc}") from exc
            record_units(state, units)
            state["store_queue"].pop(0)
        elif state["product_queue"]:
            sku = state["product_queue"][0]
            product = state["products"][sku]
            tasks = parse_stores(client.get(product["stock_link"]), product)
            state["store_queue"] = tasks
            state["product_queue"].pop(0)
        else:
            state.update(stage="discover", baseline_complete=True,
                         cycles_completed=state["cycles_completed"] + 1, cycle_finished_at=now())
            if "baseline_completed_at" not in state:
                state["baseline_completed_at"] = now()
            return False  # Stop at cycle boundary, even if the budget remains.
    state["requests_total"] += int(requested)
    state["last_checked_at"] = now()
    return True


def run_batch(state, path, client):
    while True:
        try:
            more = step(state, client)
        except BudgetExhausted:
            break
        save_state(path, state)  # Queue advances ONLY after a parsed response.
        if not more:
            break


def format_alerts(units):
    label = "inventory units (includes initial inventory)" if any(u.get("initial_inventory", False) for u in units) else "new units"
    lines = [f"--- Long & McQuade Used: {len(units)} {label} ---"]
    for unit in units:
        name = unit["name"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        lines.extend([f"Gear: [{name}]({unit['link']})", f"Price: {unit['price']}",
                      f"Condition: {unit['condition']}", f"Location: {unit['store']}, {unit['province']}",
                      f"Serial: {unit['serial'] or 'Not provided'}", "-" * 30])
    return "\n".join(lines)


def pop_output_batch(state):
    """Bound output without discarding entries the scheduler would truncate."""
    selected, rendered = [], ""
    for unit in state["pending_alerts"][:MAX_OUTPUT_UNITS]:
        candidate = format_alerts(selected + [unit])
        if len(candidate.encode("utf-8")) > MAX_OUTPUT_BYTES:
            if not selected:
                raise ValueError("Single inventory entry exceeds the output byte limit; queue preserved")
            break
        selected.append(unit)
        rendered = candidate
    del state["pending_alerts"][:len(selected)]
    return rendered


def status(state):
    return {k: state.get(k) for k in ("baseline_complete", "baseline_completed_at", "stage", "cycles_completed",
                                     "cycle_started_at", "cycle_finished_at", "last_checked_at", "requests_total")} | {
        "departments": len(state.get("departments", [])), "products_discovered": len(state["products"]),
        "catalogue_pages_pending": len(state["catalogue_queue"]), "products_pending": len(state["product_queue"]),
        "store_groups_pending": len(state["store_queue"]), "known_units": len(state["known_units"]),
        "alerts_pending": len(state["pending_alerts"]),
        "initial_output_enabled": state.get("initial_output_enabled", False)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=STATE)
    parser.add_argument("--requests", type=int, default=150, help="HTTP requests per bounded batch")
    parser.add_argument("--interval-seconds", type=float, default=4.2, help="At least 4.2 seconds between ALL requests")
    parser.add_argument("--max-seconds", type=int, default=720, help="Stop before the scheduler's 900s timeout")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="Read checkpoint; no network or alerts")
    mode.add_argument("--show-existing", action="store_true", help="Enable initial inventory output and queue recorded units once; no network")
    args = parser.parse_args(argv)
    if args.requests < 1 or args.interval_seconds < 4.2 or not 40 <= args.max_seconds <= 720:
        parser.error("Require requests >= 1, interval >= 4.2s, and max-seconds between 40 and 720")
    try:
        if args.status:
            print(json.dumps(status(load_state(args.state_file)), indent=2))
            return 0
        with exclusive_lock(args.state_file) as acquired:
            if not acquired:
                if args.show_existing:
                    raise ValueError("Active scan holds the checkpoint lock; retry --show-existing after it finishes")
                return 0
            state = load_state(args.state_file)
            if args.show_existing:
                queued = enable_initial_output(state)
                save_state(args.state_file, state)
                print(json.dumps({"initial_output_enabled": True, "previously_recorded_units_queued": queued,
                                  "alerts_pending": len(state["pending_alerts"]), "max_units_per_output": MAX_OUTPUT_UNITS}))
                return 0
            client = Client(args.requests, args.interval_seconds, args.max_seconds)
            try:
                run_batch(state, args.state_file, client)
            finally:
                client.session.close()
            alerts = state["pending_alerts"]
            if alerts:
                rendered = pop_output_batch(state)
                save_state(args.state_file, state)
                print(rendered, flush=True)
        return 0
    except Exception as exc:
        print(f"Long & McQuade Used check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
