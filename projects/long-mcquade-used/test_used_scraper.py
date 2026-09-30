"""Offline tests: parser boundaries, restart/resume, seeding and notifications."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from io import StringIO
import json
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


def details(serial="ABC", condition="Used", price="$75.00", stock_id="999", store_id="61", action="addUsedToCart"):
    return f'''<div class="fw-normal fs-7"><div class="mb-3 p-2 bg-light-grey"><div class="row">
    <div><div><strong>SKU:</strong> 123</div><div><strong>Serial:</strong> {serial}</div>
    <div><strong>Sale Price:</strong> {price}</div></div>
    <div><strong>Condition:</strong><span>{condition}</span></div>
    <a href="/?action={action}&amp;locationsStockID={stock_id}&amp;pickupInStoreId={store_id}">Pick up</a>
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
        departments = watcher.discover_departments(html + html)
        self.assertEqual(len(departments), 87)
        self.assertNotIn("56", {watcher.department_id(d["url"]) for d in departments})
        with self.assertRaises(ValueError):
            watcher.discover_departments('<h1>Home page changed</h1>')

    def test_cached_gift_cards_task_resumes_without_fetch_or_reset(self):
        state = watcher.fresh_state()
        unit = watcher.parse_units(details(), TASK)[0]
        watcher.record_units(state, [unit])
        state.update(stage="catalogue", catalogue_queue=[
            {"url": watcher.BASE + "/departments/56/", "name": "Gift Cards", "offset": 0},
            {"url": watcher.BASE + "/departments/10/Acoustic.htm", "name": "Acoustic Guitars", "offset": 0},
        ])
        client = FakeClient([catalogue(total=2)], limit=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.run_batch(state, path, client)
            resumed = watcher.load_state(path)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("/departments/10/", client.calls[0])
        self.assertEqual(resumed["requests_total"], 1)
        self.assertEqual(resumed["catalogue_queue"][0]["offset"], 1)
        self.assertEqual(resumed["known_units"], state["known_units"])
        self.assertIn(unit["id"], resumed["known_units"])
        self.assertFalse(resumed["baseline_complete"])
        self.assertEqual(resumed["pending_alerts"], [])

    def test_other_unfiltered_departments_fail_with_url_and_preserve_queue(self):
        for identifier in ("10", "560"):
            with self.subTest(identifier=identifier), tempfile.TemporaryDirectory() as directory:
                task = {"url": watcher.BASE + f"/departments/{identifier}/", "name": "Test", "offset": 0}
                state = watcher.fresh_state()
                state.update(stage="catalogue", catalogue_queue=[task])
                path = Path(directory) / "state.json"
                watcher.save_state(path, state)
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "Used Anywhere filter is not active") as error:
                    watcher.run_batch(state, path, FakeClient([catalogue().replace(" checked", "")]))
                self.assertIn(task["url"], str(error.exception))
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(state["catalogue_queue"], [task])

    def test_last_cached_gift_cards_task_enters_inventory(self):
        state = watcher.fresh_state()
        state.update(stage="catalogue", products={PRODUCT["sku"]: PRODUCT}, catalogue_queue=[
            {"url": watcher.BASE + "/departments/56/", "name": "Gift Cards", "offset": 0},
        ])
        client = FakeClient([])
        self.assertTrue(watcher.step(state, client))
        self.assertEqual(client.calls, [])
        self.assertEqual(state["requests_total"], 0)
        self.assertEqual(state["stage"], "inventory")
        self.assertEqual(state["product_queue"], [PRODUCT["sku"]])

    def test_catalogue_ignores_new_retail_price_and_requires_used_filter(self):
        products, last, total = watcher.parse_catalogue(catalogue())
        self.assertEqual(products[0]["sku"], "123")
        self.assertNotIn("price", products[0])
        self.assertEqual((last, total), (1, 1))
        with self.assertRaises(ValueError):
            watcher.parse_catalogue(catalogue().replace(" checked", ""))

    def test_blank_image_metadata_uses_visible_brand_and_model(self):
        html = catalogue().replace('alt="Maker - [Pedal]"', 'alt="" title=""').replace(
            '<span>Price: $999.00</span>', '''<div class="products-item-descr">
            <p class="d-md-none fw-bolder">Paiste</p>
            <p class="d-md-block d-none fw-bolder">Paiste</p>
            <p class="fw-bolder text-grey d-none d-md-block">2002 16” Crash</p>
            <p class="fw-bolder text-grey d-md-none">2002 16” Crash</p>
            <div><span>Price: $999.00</span></div></div>''')
        products, _, _ = watcher.parse_catalogue(html)
        self.assertEqual(products[0]["name"], "Paiste - 2002 16” Crash")
        self.assertEqual(products[0]["sku"], "123")
        self.assertNotIn("price", products[0])
        products, _, _ = watcher.parse_catalogue(html.replace('<img alt="" title="">', ''))
        self.assertEqual(products[0]["name"], "Paiste - 2002 16” Crash")
        with self.assertRaisesRegex(ValueError, "SKU or name missing"):
            watcher.parse_catalogue(catalogue().replace('alt="Maker - [Pedal]"', 'alt="" title=""'))

    def test_bare_domain_card_is_canonicalized_not_dropped(self):
        html = catalogue().replace('href="/456/Pedal.htm"', 'href="https://long-mcquade.com/456/Pedal.htm"')
        products, _, _ = watcher.parse_catalogue(html)
        self.assertEqual(products[0]["link"], watcher.BASE + "/456/Pedal.htm")
        for prefix in ("http://long-mcquade.com", "https://WWW.LONG-MCQUADE.COM", ""):
            self.assertEqual(watcher.public_url(prefix + "/456/Pedal.htm"), watcher.BASE + "/456/Pedal.htm")
        for url in ("https://example.com/456/Pedal.htm", "https://long-mcquade.com.evil.test/456/Pedal.htm",
                    "https://user@long-mcquade.com/456/Pedal.htm", "ftp://long-mcquade.com/456/Pedal.htm",
                    "https://long-mcquade.com:9999/456/Pedal.htm"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                watcher.public_url(url)

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

    def test_rental_only_units_do_not_block_or_become_sale_alerts(self):
        rental = details(serial="RENTAL", condition="Available for rent").replace(
            '<a href="/?action=addUsedToCart&amp;locationsStockID=999&amp;pickupInStoreId=61">Pick up</a>',
            '<div>Please contact store for details</div>')
        mixed = details().replace('</div></div></div>', '</div></div>' + rental.replace('<div class="fw-normal fs-7">', '', 1))
        units = watcher.parse_units(mixed, TASK)
        self.assertEqual([u["serial"] for u in units], ["ABC"])
        self.assertEqual(watcher.parse_units(rental, TASK), [])
        state = watcher.fresh_state()
        state.update(stage="inventory", baseline_complete=True, store_queue=[TASK])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.run_batch(state, path, FakeClient([rental], limit=1))
            resumed = watcher.load_state(path)
        self.assertEqual(resumed["store_queue"], [])
        self.assertEqual(resumed["pending_alerts"], [])
        self.assertEqual(resumed["known_units"], {})
        with self.assertRaisesRegex(ValueError, "Unexpected inventory condition"):
            watcher.parse_units(details(condition="Unrecognized", action="addNewToCart"), TASK)

    def test_free_form_conditions_use_verified_used_demo_sale_links(self):
        notes = ("Not in original packaging, only available for pickup",
                 "Small scratch on chassis; includes power supply", "Open box, missing manual")
        for action in ("addUsedToCart", "addDemoToCart"):
            for note in notes:
                with self.subTest(action=action, note=note):
                    html = details(condition=note, action=action).replace('/?action=', '/?ProductsID=456&amp;action=')
                    units = watcher.parse_units(html, {**TASK, "demo": 1})
                    self.assertEqual(len(units), 1)
                    self.assertEqual(units[0]["condition"], note)
                    self.assertEqual(units[0]["price"], "$75.00")
                    self.assertEqual(units[0]["id"], "123:serial:abc")
                    self.assertNotIn("ToCart", units[0]["link"])

    def test_free_form_notes_do_not_bypass_sale_identity_checks(self):
        note = "Not in original packaging, only available for pickup"
        html = details(condition=note, action="addDemoToCart")
        invalid = (
            html.replace("addDemoToCart", "addNewToCart"),
            html.replace("addDemoToCart", "unrecognizedAction"),
            html.replace('href="/?', 'href="https://example.com/?'),
            html.replace('/?action=', '/?ProductsID=9999&amp;action='),
            html.replace('pickupInStoreId=61', 'pickupInStoreId=99'),
            html.replace('locationsStockID=999', 'locationsStockID='),
            html.replace('pickupInStoreId=61', 'unrelated=61'),
            html.replace('<strong>SKU:</strong> 123', '<strong>SKU:</strong> 999'),
            html.replace('$75.00', 'not a price'),
            html.replace(note, ''),
        )
        for response in invalid:
            with self.subTest(response=response), self.assertRaises(ValueError):
                watcher.parse_units(response, TASK)

    def test_free_form_note_checkpoint_resume_and_alert_deduplication(self):
        note = "Not in original packaging, only available for pickup"
        html = details(condition=note, action="addDemoToCart")
        state = watcher.fresh_state()
        prior = watcher.parse_units(details(serial="PREVIOUS"), TASK)[0]
        watcher.record_units(state, [prior])
        state.update(stage="inventory", store_queue=[TASK, TASK])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.save_state(path, state)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "SKU 123 at Pickering"):
                watcher.run_batch(state, path, FakeClient([html.replace("addDemoToCart", "addNewToCart")]))
            self.assertEqual(path.read_bytes(), before)
            watcher.run_batch(state, path, FakeClient([html], limit=1))
            resumed = watcher.load_state(path)
            self.assertIn(prior["id"], resumed["known_units"])
            self.assertEqual(len(resumed["known_units"]), 2)
            self.assertEqual(resumed["pending_alerts"], [])
            resumed["baseline_complete"] = True
            watcher.run_batch(resumed, path, FakeClient([html], limit=1))
            self.assertEqual(watcher.load_state(path)["pending_alerts"], [])
        watcher.record_units(resumed, watcher.parse_units(details(serial="NEW", condition=note, action="addDemoToCart"), TASK))
        self.assertEqual(len(resumed["pending_alerts"]), 1)
        self.assertIn("Condition: " + note, watcher.format_alerts(resumed["pending_alerts"]))

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

    def test_enable_initial_output_backfills_once_without_reset(self):
        state = watcher.fresh_state()
        first = watcher.parse_units(details(), TASK)[0]
        second = watcher.parse_units(details(serial="SECOND"), TASK)[0]
        watcher.record_units(state, [first, second])
        state.update(stage="inventory", product_queue=["123"], store_queue=[TASK], requests_total=17)
        state["pending_alerts"] = [second]
        before = deepcopy(state)
        self.assertEqual(watcher.enable_initial_output(state), 1)
        self.assertEqual([u["id"] for u in state["pending_alerts"]], [second["id"], first["id"]])
        self.assertTrue(state["pending_alerts"][1]["initial_inventory"])
        for key in ("known_units", "stage", "product_queue", "store_queue", "requests_total", "baseline_complete"):
            self.assertEqual(state[key], before[key])
        self.assertEqual(watcher.enable_initial_output(state), 0)
        rendered = watcher.pop_output_batch(state)
        self.assertIn("includes initial inventory", rendered)
        self.assertEqual(state["pending_alerts"], [])
        self.assertEqual(watcher.enable_initial_output(state), 0)
        self.assertEqual(state["pending_alerts"], [])

    def test_initial_output_survives_restart_and_preserves_deduplication(self):
        state = watcher.fresh_state()
        first = watcher.parse_units(details(), TASK)[0]
        watcher.record_units(state, [first])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.save_state(path, state)
            old = watcher.load_state(path)  # Existing schema-1 checkpoint lacks the optional flag.
            self.assertFalse(watcher.status(old)["initial_output_enabled"])
            watcher.enable_initial_output(old)
            watcher.save_state(path, old)
            resumed = watcher.load_state(path)
        watcher.record_units(resumed, [first, {**first, "price": "$50.00"}])
        self.assertEqual(len(resumed["pending_alerts"]), 1)
        second = watcher.parse_units(details(serial="SECOND"), TASK)[0]
        watcher.record_units(resumed, [second, second])
        self.assertEqual(len(resumed["pending_alerts"]), 2)
        self.assertTrue(resumed["pending_alerts"][1]["initial_inventory"])
        watcher.pop_output_batch(resumed)
        resumed["baseline_complete"] = True
        watcher.record_units(resumed, [watcher.parse_units(details(serial="NEW"), TASK)[0]])
        self.assertFalse(resumed["pending_alerts"][0]["initial_inventory"])
        self.assertIn("1 new units", watcher.pop_output_batch(resumed))

    def test_output_batch_count_limit_keeps_remainder_and_order(self):
        state = watcher.fresh_state()
        unit = watcher.parse_units(details(), TASK)[0]
        state["pending_alerts"] = [{**unit, "id": str(i), "serial": str(i)} for i in range(105)]
        before = deepcopy(state["pending_alerts"])
        self.assertIn("100 new units", watcher.pop_output_batch(state))
        self.assertEqual(state["pending_alerts"], before[100:])
        self.assertIn("5 new units", watcher.pop_output_batch(state))
        self.assertEqual(state["pending_alerts"], [])

    def test_output_batch_utf8_limit_and_oversized_entry_fail_closed(self):
        state = watcher.fresh_state()
        unit = watcher.parse_units(details(), TASK)[0]
        state["pending_alerts"] = [{**unit, "serial": str(i), "name": "é" * 10000} for i in range(6)]
        before = deepcopy(state["pending_alerts"])
        output = watcher.pop_output_batch(state)
        self.assertLessEqual(len(output.encode("utf-8")), watcher.MAX_OUTPUT_BYTES)
        self.assertGreater(len(state["pending_alerts"]), 0)
        self.assertEqual(state["pending_alerts"], before[6 - len(state["pending_alerts"]):])
        state["pending_alerts"] = [{**unit, "name": "é" * watcher.MAX_OUTPUT_BYTES}]
        before = deepcopy(state["pending_alerts"])
        with self.assertRaisesRegex(ValueError, "queue preserved"):
            watcher.pop_output_batch(state)
        self.assertEqual(state["pending_alerts"], before)

    def test_show_existing_cli_configures_without_network(self):
        state = watcher.fresh_state()
        watcher.record_units(state, watcher.parse_units(details(), TASK))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.save_state(path, state)
            for count in (1, 0):
                output = StringIO()
                with patch.object(watcher, "Client") as client, redirect_stdout(output):
                    self.assertEqual(watcher.main(["--state-file", str(path), "--show-existing"]), 0)
                    client.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())["previously_recorded_units_queued"], count)
            self.assertEqual(len(watcher.load_state(path)["pending_alerts"]), 1)
            with watcher.exclusive_lock(path), redirect_stderr(StringIO()):
                self.assertEqual(watcher.main(["--state-file", str(path), "--show-existing"]), 1)

    def test_main_emits_bounded_baseline_inventory_and_keeps_backlog(self):
        state = watcher.fresh_state()
        unit = watcher.parse_units(details(), TASK)[0]
        watcher.record_units(state, [{**unit, "id": f"123:serial:{i}", "serial": str(i)} for i in range(105)])
        watcher.enable_initial_output(state)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.save_state(path, state)
            output = StringIO()
            with patch.object(watcher, "Client") as client, patch.object(watcher, "run_batch") as batch, redirect_stdout(output):
                self.assertEqual(watcher.main(["--state-file", str(path)]), 0)
                batch.assert_called_once()
                client.return_value.session.close.assert_called_once()
            self.assertIn("includes initial inventory", output.getvalue())
            self.assertIn("100 inventory units", output.getvalue())
            self.assertIn("Serial: 0", output.getvalue())
            resumed = watcher.load_state(path)
            self.assertEqual([u["serial"] for u in resumed["pending_alerts"]], [str(i) for i in range(100, 105)])
            self.assertFalse(resumed["baseline_complete"])
            self.assertEqual(resumed["known_units"], state["known_units"])

    def test_failed_scan_preserves_initial_output_backlog(self):
        state = watcher.fresh_state()
        watcher.record_units(state, watcher.parse_units(details(), TASK))
        watcher.enable_initial_output(state)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.save_state(path, state)
            before = path.read_bytes()
            output = StringIO()
            with patch.object(watcher, "Client"), patch.object(watcher, "run_batch", side_effect=ValueError("Changed markup")), redirect_stdout(output), redirect_stderr(StringIO()):
                self.assertEqual(watcher.main(["--state-file", str(path)]), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(watcher.load_state(path)["pending_alerts"]), 1)

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
            response = watcher.requests.Response()
            response.status_code = 200
            response._content = b"response"
            request.return_value = response
            self.assertEqual(client.get(watcher.BASE), "response")
            with self.assertRaises(watcher.BudgetExhausted):
                client.get(watcher.BASE)
            self.assertEqual(request.call_count, 1)
        client.session.close()


class ResponseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = 1000.0
        self.sleeps = []
        clock = patch.object(watcher.time, "monotonic", side_effect=lambda: self.clock)
        sleep = patch.object(watcher.time, "sleep", side_effect=self.advance)
        clock.start()
        sleep.start()
        self.addCleanup(clock.stop)
        self.addCleanup(sleep.stop)
        self.client = watcher.Client()
        self.addCleanup(self.client.session.close)
        request = patch.object(self.client.session, "request")
        self.request = request.start()
        self.addCleanup(request.stop)

    def advance(self, seconds):
        self.sleeps.append(seconds)
        self.clock += seconds

    @staticmethod
    def response(body, status=200, headers=None):
        response = watcher.requests.Response()
        response.status_code = status
        response._content = body.encode()
        response.headers.update({"Content-Type": "text/html", **(headers or {})})
        return response

    def test_empty_then_valid_recovers_with_one_delayed_retry(self):
        self.request.side_effect = [self.response(""), self.response(details())]
        self.assertEqual(self.client.details(TASK), details())
        self.assertEqual(self.client.count, 2)
        self.assertEqual(self.sleeps, [30.0])
        self.assertEqual(self.request.call_args_list[0], self.request.call_args_list[1])
        self.assertEqual(self.request.call_args.kwargs["data"]["action"], "LocationStockSerials")

    def test_persistent_empty_has_precise_metadata_and_only_two_attempts(self):
        self.request.return_value = self.response("   ")
        with self.assertRaisesRegex(ValueError, "Empty response.*HTTP 200.*bytes=3.*checkpoint preserved"):
            self.client.details(TASK)
        self.assertEqual(self.request.call_count, 2)
        self.assertEqual(self.sleeps, [30.0])

    def test_explicit_blocks_and_rate_limits_never_retry(self):
        for body, status, reason in (("Too many requests", 200, "Rate-limited"),
                                     ("<html>Just a moment...</html>", 200, "Blocked"),
                                     ("cf-chl-script", 503, "Blocked"),
                                     ("Too many requests", 503, "Rate-limited"),
                                     ("", 429, "HTTP 429")):
            with self.subTest(body=body, status=status):
                self.request.reset_mock()
                self.request.return_value = self.response(body, status)
                with self.assertRaisesRegex(ValueError, reason):
                    self.client.get(watcher.BASE)
                self.assertEqual(self.request.call_count, 1)

    def test_retry_after_is_reported_and_not_ignored(self):
        for body, status in (("", 200), ("Service unavailable", 503), ("", 429)):
            with self.subTest(status=status):
                self.request.reset_mock()
                self.request.return_value = self.response(body, status, {"Retry-After": "120"})
                with self.assertRaisesRegex(ValueError, "retry-after='120'"):
                    self.client.get(watcher.BASE)
                self.assertEqual(self.request.call_count, 1)

    def test_temporary_gateway_errors_recover_once(self):
        for status in (502, 503, 504):
            with self.subTest(status=status):
                self.request.reset_mock()
                self.request.side_effect = [self.response("Gateway failure", status), self.response(details())]
                self.assertEqual(self.client.details(TASK), details())
                self.assertEqual(self.request.call_count, 2)

    def test_transport_failures_recover_once(self):
        for exception in (watcher.requests.Timeout, watcher.requests.ConnectionError):
            with self.subTest(exception=exception):
                self.request.reset_mock()
                self.request.side_effect = [exception("private raw exception text"), self.response(details())]
                self.assertEqual(self.client.details(TASK), details())
                self.assertEqual(self.request.call_count, 2)

    def test_persistent_transport_failure_is_bounded_and_does_not_log_raw_exception(self):
        self.request.side_effect = watcher.requests.Timeout("sensitive raw exception text")
        with self.assertRaisesRegex(ValueError, "Transport failure.*Timeout.*checkpoint preserved") as error:
            self.client.details(TASK)
        self.assertNotIn("sensitive", str(error.exception))
        self.assertEqual(self.request.call_count, 2)

    def test_http_403_and_other_nontransient_errors_do_not_retry(self):
        for status in (400, 403, 404, 500):
            with self.subTest(status=status):
                self.request.reset_mock()
                self.request.return_value = self.response("Error", status)
                with self.assertRaisesRegex(ValueError, f"HTTP {status}"):
                    self.client.get(watcher.BASE)
                self.assertEqual(self.request.call_count, 1)

    def test_retry_respects_request_budget_and_reports_original_failure(self):
        self.client.max_requests = 1
        self.request.return_value = self.response("")
        with self.assertRaisesRegex(ValueError, "Empty response.*retry unavailable within batch budget"):
            self.client.details(TASK)
        self.assertEqual(self.request.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_retry_respects_time_budget_and_reports_original_failure(self):
        self.client.deadline = self.clock + 60
        self.request.return_value = self.response("")
        with self.assertRaisesRegex(ValueError, "Empty response.*retry unavailable within batch budget"):
            self.client.details(TASK)
        self.assertEqual(self.request.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_retry_never_reduces_configured_spacing(self):
        self.client.interval = 60
        self.request.side_effect = [self.response(""), self.response(details())]
        self.client.details(TASK)
        self.assertEqual(self.sleeps, [60])

    def test_recovery_advances_once_and_deduplicates_alerts(self):
        state = watcher.fresh_state()
        state.update(stage="inventory", baseline_complete=True, store_queue=[TASK, TASK])
        self.client.max_requests = 2
        self.request.side_effect = [self.response(""), self.response(details())]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            watcher.run_batch(state, path, self.client)
            resumed = watcher.load_state(path)
        self.assertEqual(resumed["store_queue"], [TASK])
        self.assertEqual(len(resumed["known_units"]), 1)
        self.assertEqual(len(resumed["pending_alerts"]), 1)
        self.assertEqual(resumed["requests_total"], 1)  # Counts parsed tasks, not attempts.

    def test_failure_preserves_checkpoint_queue_and_alerts_with_task_context(self):
        for response in (self.response(""), self.response("Too many requests"),
                         self.response("Changed markup")):
            with self.subTest(body=response.text):
                self.request.reset_mock()
                self.request.return_value = response
                state = watcher.fresh_state()
                state.update(stage="inventory", baseline_complete=True, store_queue=[TASK])
                watcher.record_units(state, watcher.parse_units(details(serial="PRIOR"), TASK))
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "state.json"
                    watcher.save_state(path, state)
                    before = path.read_bytes()
                    with self.assertRaisesRegex(ValueError, r"SKU 123 at Pickering \(demo=0\)"):
                        watcher.run_batch(state, path, self.client)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(state["store_queue"], [TASK])
                    self.assertEqual(len(state["pending_alerts"]), 1)
                self.assertEqual(self.request.call_count, 2 if not response.text else 1)


if __name__ == "__main__":
    unittest.main()
