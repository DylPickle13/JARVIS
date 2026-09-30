"""Offline tests: parser boundaries, restart/resume, seeding and notifications."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import used_scraper as watcher

PRODUCT = {"sku": "123", "product_id": "456", "name": "Maker - [Pedal]", "link": watcher.BASE + "/456/Pedal.htm", "stock_link": watcher.stock_url("123")}
TASK = {"product": PRODUCT, "store_id": "61", "store": "Pickering", "province": "Ontario", "demo": 0, "product_id": "456"}


def catalogue(total=1, last=1):
    return f'''<input name="StockFilter" value="6" checked>
    <span class="pagination-count">Products 1 to {last} of {total}</span>''' + ('''
    <a class="products-item-link" href="/456/Pedal.htm"><img alt="Maker - [Pedal]">
    <span>Price: $999.00</span><a href="/?page=instore_stock&amp;Sku=123">Used Available</a></a>''' if total else "")


def stores():
    return '''<h1>In Store Stock</h1><div class="row" data-store-id="61" data-sku="123" data-product-id="456">
    <div class="col-12 col-md-8"><span class="fw-bolder fs-5">New in Stock</span><p class="used-available">Used</p></div>
    <div class="col-12 col-md-4"><span class="fs-5 fw-bolder">Pickering</span>
    <a href="/location/Ontario/Pickering/">Hours</a></div></div>'''


def details(serial="ABC", condition="Used", price="$75.00", stock_id="999", store_id="61"):
    return f'''<div class="fw-normal fs-7"><div class="mb-3 p-2 bg-light-grey"><div class="row">
    <div><div><strong>SKU:</strong> 123</div><div><strong>Serial:</strong> {serial}</div>
    <div><strong>Sale Price:</strong> {price}</div></div>
    <div><strong>Condition:</strong><span>{condition}</span></div>
    <a href="/?action=addUsedToCart&amp;locationsStockID={stock_id}&amp;pickupInStoreId={store_id}">Pick up</a>
    </div></div></div>'''


class FakeClient:
    def __init__(self, responses, limit=100):
        self.responses = iter(responses)
        self.limit = limit
        self.calls = []

    def get(self, url):
        if len(self.calls) >= self.limit:
            raise watcher.BudgetExhausted
        self.calls.append(url)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value

    def details(self, task):
        return self.get("DETAIL:" + task["store_id"])


class WatcherTests(unittest.TestCase):
    def test_discover_all_departments_deduplicates_id(self):
        html = ''.join(f'<a href="/departments/{i}/Category.htm">Category {i}</a>' for i in range(88))
        self.assertEqual(len(watcher.discover_departments(html + html)), 88)
        with self.assertRaises(ValueError):
            watcher.discover_departments('<h1>Home page changed</h1>')

    def test_catalogue_ignores_new_retail_price_and_requires_used_filter(self):
        products, last, total = watcher.parse_catalogue(catalogue())
        self.assertEqual(products[0]["sku"], "123")
        self.assertNotIn("price", products[0])
        self.assertEqual((last, total), (1, 1))
        with self.assertRaises(ValueError):
            watcher.parse_catalogue(catalogue().replace(" checked", ""))

    def test_empty_catalogue_is_valid_but_missing_cards_is_not(self):
        self.assertEqual(watcher.parse_catalogue(catalogue(0, 0)), ([], 0, 0))
        empty = '<input name="StockFilter" value="6" checked><p>We currently do not have stock in our retail stores.</p>'
        self.assertEqual(watcher.parse_catalogue(empty), ([], 0, 0))
        with self.assertRaises(ValueError):
            watcher.parse_catalogue('<input name="StockFilter" value="6" checked><span class="pagination-count">Products 1 to 64 of 99</span>')

    def test_store_name_not_new_stock_badge_and_no_province_restriction(self):
        tasks = watcher.parse_stores(stores(), PRODUCT)
        self.assertEqual(tasks[0]["store"], "Pickering")
        self.assertEqual(tasks[0]["province"], "Ontario")
        bc = stores().replace("Ontario", "British-Columbia").replace("Pickering", "Vancouver")
        self.assertEqual(watcher.parse_stores(bc, PRODUCT)[0]["province"], "British Columbia")
        mixed = stores().replace('<p class="used-available">Used</p>', '<p class="used-available">Used</p><p class="demo-available">Demo</p>')
        self.assertEqual(len(watcher.parse_stores(mixed, PRODUCT)), 2)

    def test_actual_unit_price_and_serial_identity(self):
        units = watcher.parse_units(details(), TASK)
        self.assertEqual(units[0]["price"], "$75.00")
        self.assertEqual(units[0]["id"], "123:serial:abc")
        self.assertEqual(units[0]["link"], watcher.stock_url("123"))
        self.assertNotIn("addUsedToCart", units[0]["link"])
        self.assertEqual(watcher.parse_units(details(serial="abc", stock_id="1000"), TASK)[0]["id"], units[0]["id"])

    def test_demo_returns_keep_condition_and_empty_sold_stock(self):
        self.assertEqual(watcher.parse_units(details(condition="Demo , Return"), TASK)[0]["condition"], "Demo , Return")
        self.assertEqual(watcher.parse_units('<div class="fw-normal fs-7"></div>', TASK), [])
        with self.assertRaises(ValueError):
            watcher.parse_units('', TASK)
        with self.assertRaises(ValueError):
            watcher.parse_units('<html>Just a moment...</html>', TASK)
        with self.assertRaises(ValueError):
            watcher.parse_units(details(store_id="99"), TASK)
        with self.assertRaises(ValueError):
            watcher.parse_units(details(price="not a price"), TASK)

    def test_missing_serial_fallback_not_price_based(self):
        self.assertEqual(watcher.parse_units(details(serial="N/A"), TASK)[0]["id"], "123:stock:61:999")
        with self.assertRaises(ValueError):
            watcher.parse_units(details(serial="", stock_id=""), TASK)

    def test_seed_quiet_new_serial_only_once_and_price_changes_quiet(self):
        state = watcher.fresh_state()
        unit = watcher.parse_units(details(), TASK)[0]
        watcher.record_units(state, [unit])
        self.assertEqual(state["pending_alerts"], [])
        state["baseline_complete"] = True
        watcher.record_units(state, [unit, {**unit, "price": "$50.00"}])
        self.assertEqual(state["pending_alerts"], [])
        new = watcher.parse_units(details(serial="NEW"), TASK)[0]
        watcher.record_units(state, [new, new])
        self.assertEqual(len(state["pending_alerts"]), 1)
        self.assertIn('Condition: Used', watcher.format_alerts(state["pending_alerts"]))
        self.assertIn(r'\[Pedal\]', watcher.format_alerts(state["pending_alerts"]))

    def test_pagination_and_resume_after_budget(self):
        state = watcher.fresh_state()
        state.update(stage="catalogue", catalogue_queue=[{"url": watcher.BASE + "/departments/1/Test.htm", "name": "Test", "offset": 0}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.run_batch(state, path, FakeClient([catalogue(total=2)], limit=1))
            saved = watcher.load_state(path)
            self.assertEqual(saved["catalogue_queue"][0]["offset"], 1)
            self.assertEqual(saved["stage"], "catalogue")
            second = catalogue(total=2).replace('Products 1 to 1', 'Products 2 to 2')
            watcher.run_batch(saved, path, FakeClient([second, stores(), details()], limit=3))
            final = watcher.load_state(path)
            self.assertTrue(final["baseline_complete"])
            self.assertEqual(final["cycles_completed"], 1)
            self.assertEqual(len(final["known_units"]), 1)
            self.assertEqual(final["pending_alerts"], [])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failure_leaves_queue_and_checkpoint_untouched(self):
        state = watcher.fresh_state()
        state.update(stage="inventory", store_queue=[TASK])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.save_state(path, state)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                watcher.run_batch(state, path, FakeClient(['<h1>Changed markup</h1>']))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(state["store_queue"], [TASK])

    def test_pending_alerts_survive_restart(self):
        state = watcher.fresh_state()
        state.update(stage="inventory", baseline_complete=True, store_queue=[TASK, TASK])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.run_batch(state, path, FakeClient([details()], limit=1))
            restarted = watcher.load_state(path)
            self.assertEqual(len(restarted["pending_alerts"]), 1)
            watcher.run_batch(restarted, path, FakeClient([details()], limit=1))
            self.assertEqual(len(restarted["pending_alerts"]), 1)

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('not json')
            with self.assertRaises(ValueError):
                watcher.load_state(path)
            path.write_text('{}')
            with self.assertRaises(ValueError):
                watcher.load_state(path)

    def test_concurrent_run_is_silent_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with watcher.exclusive_lock(path) as first:
                self.assertTrue(first)
                with watcher.exclusive_lock(path) as second:
                    self.assertFalse(second)

    def test_request_rate_and_budget(self):
        client = watcher.Client(max_requests=1)
        with patch.object(client.session, "request") as request:
            request.return_value.text = "response"
            self.assertEqual(client.get(watcher.BASE), "response")
            with self.assertRaises(watcher.BudgetExhausted):
                client.get(watcher.BASE)
            self.assertEqual(request.call_count, 1)
        client.session.close()


if __name__ == "__main__":
    unittest.main()
