import concurrent.futures
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_jarvisd import jarvisd


def activity(models=None):
    return {"active_models": {"models": models or [], "model_memory_used": 1024,
        "model_memory_max": 2048,
        "total_active_requests": sum(m.get("active_requests", 0) or 0 for m in (models or [])),
        "total_waiting_requests": sum(m.get("waiting_requests", 0) or 0 for m in (models or [])),
        "memory_pressure": {"enabled": True, "pressure_level": "soft"}}}


def model(**extra):
    return {"id": "Qwen-test-4bit", "active_requests": 0, "waiting_requests": 0,
        "is_loading": False, "estimated_size": 1024, **extra}


class OMLXTests(unittest.TestCase):
    def test_allowlist_excludes_credentials_content_paths_and_request_ids(self):
        raw = activity([model(generating=[{"request_id": "private-request", "prompt": "PRIVATE",
            "output": "PRIVATE", "generated_tokens": 42, "tokens_per_second": 12.5,
            "elapsed_seconds": 3, "max_tokens": 100}],
            activities=[{"detail": "PRIVATE filename", "metadata": {"password": "PRIVATE"}}])])
        raw.update(api_key="PRIVATE", host="PRIVATE")
        raw["active_models"]["models"][0]["path"] = "PRIVATE"
        safe = jarvisd._omlx_activity(raw)
        wire = json.dumps(safe)
        for secret in ["PRIVATE", "private-request", "api_key", "max_tokens", "prompt", "output", "metadata"]:
            self.assertNotIn(secret, wire)
        request = safe["models"][0]["requests"][0]
        self.assertEqual(request["generatedTokens"], 42)
        self.assertEqual(request["tokensPerSecond"], 12.5)
        self.assertEqual(safe["memoryKind"], "process")
        self.assertEqual(safe["memoryPressure"], "soft")

    def test_real_prefill_only_and_no_loading_or_generation_percentage(self):
        safe = jarvisd._omlx_activity(activity([model(is_loading=True, loading_elapsed_seconds=4,
            loading_estimated_seconds=100, prefilling=[{"processed": 50, "total": 100, "speed": 25,
                "elapsed": 2, "detail": "not forwarded"}])]))
        row = safe["models"][0]
        self.assertEqual(row["loadingElapsedSeconds"], 4)
        self.assertNotIn("loading_estimated_seconds", json.dumps(row))
        self.assertEqual(row["requests"][0]["processedTokens"], 50)
        self.assertEqual(row["requests"][0]["totalTokens"], 100)

    def test_multiple_models_requests_loading_and_idle_are_retained(self):
        a = model(id="z", active_requests=2, waiting_requests=1,
            generating=[{"generated_tokens": 3}, {"generated_tokens": 4}],
            waiting=[{"queue_position": 1, "elapsed_seconds": 10}])
        b = model(id="a", is_loading=True)
        c = model(id="idle")
        safe = jarvisd._omlx_activity(activity([a, b, c]))
        self.assertEqual([m["id"] for m in safe["models"]], ["a", "idle", "z"])
        self.assertEqual(safe["models"][2]["activeRequests"], 2)
        self.assertEqual(len(safe["models"][2]["requests"]), 3)
        self.assertEqual(safe["models"][1]["requests"], [])

    def test_no_models_is_online_but_malformed_missing_evidence_is_not_ready(self):
        self.assertEqual(jarvisd._omlx_activity(activity())["models"], [])
        for raw in [None, {}, {"active_models": {}}, {"active_models": {"models": None}},
                    activity([{}]), activity([model(is_loading=None)]), activity([model(active_requests=True)]),
                    activity([model(active_requests=-1)]), activity([model(waiting_requests=None)]),
                    activity([model(generating={})]), activity([model(), model()])]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                jarvisd._omlx_activity(raw)

    def test_missing_or_contradictory_totals_cannot_claim_ready(self):
        for value in [None, True, 1, -1]:
            raw = activity()
            raw["active_models"]["total_active_requests"] = value
            with self.assertRaises(ValueError): jarvisd._omlx_activity(raw)
        raw = activity([model(active_requests=2)])
        raw["active_models"]["total_active_requests"] = 0
        with self.assertRaises(ValueError): jarvisd._omlx_activity(raw)

    def test_bad_optional_numbers_remain_unknown(self):
        for bad in [True, -1, float("nan"), float("inf"), "20", 2**54]:
            safe = jarvisd._omlx_activity(activity([model(actual_size=bad,
                generating=[{"generated_tokens": bad, "tokens_per_second": bad}])]))
            self.assertIsNone(safe["models"][0]["observedBytes"])
            self.assertIsNone(safe["models"][0]["requests"][0]["tokensPerSecond"])
            self.assertIsNone(safe["models"][0]["requests"][0]["generatedTokens"])
        self.assertIsNone(jarvisd._omlx_number(1.5, integer=True))

    def test_model_and_request_bounds_fail_instead_of_silently_hiding_work(self):
        for raw in [activity([model(id=str(i)) for i in range(129)]),
                    activity([model(generating=[{}] * 513)]),
                    activity([model(id="x" * 513)]), activity([model(id="bad\nname")])]:
            with self.assertRaises(ValueError): jarvisd._omlx_activity(raw)

    def fake_connection(self, status=200, payload=None):
        connection = mock.MagicMock()
        response = connection.getresponse.return_value
        response.status = status
        response.isclosed.side_effect = [False, False]
        response.read1.side_effect = [json.dumps(payload or activity()).encode(), b""]
        return connection

    def test_transport_is_fixed_read_only_path_no_redirect_or_stats(self):
        for status in [200, 301, 302, 401, 403, 404, 500]:
            connection = self.fake_connection(status)
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(jarvisd.http.client, "HTTPConnection", return_value=connection) as factory:
                result = jarvisd._omlx_collect("mac-mini-16")
            factory.assert_called_once_with("192.168.21.30", 8000, timeout=2.0)
            connection.request.assert_called_once_with("GET", "/admin/api/activity", headers={"Accept": "application/json"})
            self.assertEqual(result["ok"], status == 200)
            if status in [401, 403]: self.assertEqual(result["error"], "Authentication required.")
            connection.close.assert_called_once()

    def test_transport_timeout_body_bounds_and_schema_fail_closed_with_safe_error(self):
        for failure in [TimeoutError("PRIVATE"), ValueError("PRIVATE")]:
            connection = self.fake_connection()
            connection.getresponse.side_effect = failure
            with mock.patch.object(jarvisd.http.client, "HTTPConnection", return_value=connection):
                result = jarvisd._omlx_collect("mac-mini-64")
            self.assertEqual(result, {"ok": False, "error": "oMLX activity unavailable."})
        connection = self.fake_connection()
        connection.getresponse.return_value.read1.side_effect = [b"x" * (jarvisd.OMLX_MAX_BODY + 1)]
        with mock.patch.object(jarvisd.http.client, "HTTPConnection", return_value=connection):
            self.assertFalse(jarvisd._omlx_collect("mac-mini-64")["ok"])

    def test_dripping_headers_cannot_hold_a_collector_past_deadline(self):
        # Real local HTTP socket; redirect the fixed-port connection factory to
        # an isolated ephemeral fixture, never either production oMLX server.
        import socket
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        stopped = threading.Event()
        def drip():
            peer, _ = listener.accept()
            with peer:
                peer.recv(4096)
                try:
                    for byte in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"x" * 100:
                        if stopped.wait(0.1): break
                        peer.sendall(bytes([byte]))
                except OSError:
                    pass
        worker = threading.Thread(target=drip, daemon=True)
        worker.start()
        factory = jarvisd.http.client.HTTPConnection
        start = time.monotonic()
        try:
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(jarvisd.http.client, "HTTPConnection",
                side_effect=lambda host, requested_port, timeout: factory("127.0.0.1", port, timeout=timeout)):
                result = jarvisd._omlx_collect("mac-mini-64")
            self.assertFalse(result["ok"])
            self.assertLess(time.monotonic() - start, 2.8)
        finally:
            stopped.set()
            listener.close()
            worker.join(timeout=1)

    def test_invalid_configuration_never_contacts_public_or_redirect_destination(self):
        for host in ["8.8.8.8", "example.com", "0.0.0.0", "224.1.1.1", "127.0.0.1:9999"]:
            with mock.patch.dict(os.environ, {"JARVISD_OMLX_64_HOST": host}), mock.patch.object(jarvisd.http.client, "HTTPConnection") as connection:
                self.assertFalse(jarvisd._omlx_collect("mac-mini-64")["ok"])
                connection.assert_not_called()

    def test_optional_cookie_is_private_and_never_appears_in_status(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cookie"
            path.write_text("session=PRIVATE")
            path.chmod(0o600)
            connection = self.fake_connection()
            with mock.patch.dict(os.environ, {"JARVISD_OMLX_64_COOKIE_FILE": str(path)}), mock.patch.object(jarvisd.http.client, "HTTPConnection", return_value=connection):
                result = jarvisd._omlx_collect("mac-mini-64")
                self.assertTrue(result["ok"])
                self.assertNotIn("PRIVATE", json.dumps(result))
                self.assertEqual(connection.request.call_args.kwargs["headers"]["Cookie"], "session=PRIVATE")
                path.chmod(0o644)
                self.assertFalse(jarvisd._omlx_collect("mac-mini-64")["ok"])

    def coordinator(self, collectors, now=lambda: 100):
        coordinator = jarvisd.StateCoordinator(collectors=collectors, now=now,
            freshness_limits={s: 6 for s in collectors}, intervals={s: 2 for s in collectors},
            idle_intervals={s: 60 for s in collectors}, active_lease_seconds=6)
        self.addCleanup(coordinator.stop)
        return coordinator

    def complete(self, coordinator, server, result):
        future = concurrent.futures.Future()
        future.set_result(result)
        coordinator._complete(server, future, 0)

    def test_per_server_last_good_age_failure_and_recovery_are_independent(self):
        now = [100]
        ids = jarvisd.OMLX_SERVER_IDS
        coordinator = self.coordinator({s: lambda: {} for s in ids}, now=lambda: now[0])
        # Inspect snapshots deterministically, without running background I/O.
        coordinator.start = lambda: None
        good = jarvisd._omlx_activity(activity([model(active_requests=1)]))
        self.complete(coordinator, ids[0], good)
        self.complete(coordinator, ids[1], good)
        with mock.patch.object(jarvisd, "OMLX_COORDINATOR", coordinator):
            now[0] = 102
            self.complete(coordinator, ids[1], {"ok": False, "error": "Authentication required."})
            result = jarvisd.collect_omlx()
            self.assertFalse(result["servers"][0]["stale"])
            self.assertTrue(result["servers"][1]["stale"])
            self.assertEqual(result["servers"][1]["ageSeconds"], 2)
            self.assertEqual(result["servers"][1]["models"], good["models"])
            now[0] = 107
            self.assertTrue(jarvisd.collect_omlx()["servers"][0]["stale"])
            self.complete(coordinator, ids[1], good)
            self.assertFalse(jarvisd.collect_omlx()["servers"][1]["stale"])

    def test_cold_snapshot_and_slow_peer_do_not_block_or_duplicate_work(self):
        release = threading.Event()
        calls = []
        ids = jarvisd.OMLX_SERVER_IDS
        def slow():
            calls.append("slow")
            release.wait(2)
            return jarvisd._omlx_activity(activity())
        coordinator = self.coordinator({ids[0]: lambda: jarvisd._omlx_activity(activity()), ids[1]: slow}, now=time.time)
        self.addCleanup(release.set)
        with mock.patch.object(jarvisd, "OMLX_COORDINATOR", coordinator):
            start = time.monotonic()
            for _ in range(20): jarvisd.collect_omlx()
            self.assertLess(time.monotonic() - start, 0.3)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                result = jarvisd.collect_omlx()["servers"]
                if result[0].get("models") is not None and calls: break
                time.sleep(0.005)
            self.assertFalse(result[0]["stale"])
            self.assertTrue(result[1]["stale"])
            self.assertEqual(calls, ["slow"])

    def test_distinct_lease_and_two_second_foreground_sixty_second_idle(self):
        coordinator = jarvisd.OMLX_COORDINATOR
        self.assertIsNot(coordinator, jarvisd.STATE_COORDINATOR)
        with coordinator._lock:
            for server in jarvisd.OMLX_SERVER_IDS:
                self.assertEqual(coordinator._interval_locked(server, coordinator._active_until - 1), 2)
                self.assertEqual(coordinator._interval_locked(server, coordinator._active_until + 1), 60)

    def test_endpoint_requires_authentication_and_serves_only_cached_read(self):
        handler = object.__new__(jarvisd.Handler)
        handler.path = "/api/v1/omlx"
        handler._send = mock.Mock()
        for allowed in [False, True]:
            handler._auth_or_respond = mock.Mock(return_value=allowed)
            with mock.patch.object(jarvisd, "collect_omlx", return_value={"ok": True}) as collect:
                handler.do_GET()
                self.assertEqual(collect.call_count, int(allowed))
            handler._auth_or_respond.assert_called_once()
        handler._send.assert_called_once_with(200, {"ok": True})


if __name__ == "__main__": unittest.main()
