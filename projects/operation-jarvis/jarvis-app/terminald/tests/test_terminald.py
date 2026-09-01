import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib import request as urllib_request
from urllib.error import HTTPError
import uuid
from unittest import mock

from terminald import jarvis_terminald as terminald


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.capture = ("JARVIS\n" + ("\n" * 27)).encode()
        self.pane_pid = 4242
        self.pane_id = "%7"
        self.tmux_server_pid = 4000
        self.session_created_at = int(time.time()) - 60

    def run(self, arguments, input_data=None, timeout=5, check=True):
        arguments = list(arguments)
        self.calls.append((arguments, input_data))
        if "list-clients" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b"/dev/ttys001\n/dev/ttys002\n", b"")
        if "display-message" in arguments:
            format_string = next((value for value in arguments if "#{" in value), "")
            if "#{pane_width}" in format_string:
                stdout = "48\t28\t2\t6\t0\t1\t4\t0\t{}\t{}\t{}\t{}\n".format(
                    self.pane_pid,
                    self.pane_id,
                    self.tmux_server_pid,
                    self.session_created_at,
                ).encode()
            elif format_string == "#{history_size}\t#{pane_dead}\t#{pane_id}":
                stdout = "4\t0\t{}\n".format(self.pane_id).encode()
            else:
                stdout = "{}\t{}\t{}\t{}\t0\n".format(
                    self.pane_pid,
                    self.pane_id,
                    self.tmux_server_pid,
                    self.session_created_at,
                ).encode()
            if "capture-pane" in arguments:
                stdout += self.capture
            return subprocess.CompletedProcess(arguments, 0, stdout, b"")
        if "capture-pane" in arguments:
            return subprocess.CompletedProcess(arguments, 0, self.capture, b"")
        return subprocess.CompletedProcess(arguments, 0, b"", b"")


class FakeRoomSpeechClient:
    def __init__(self):
        self.texts = []
        self.audio = b"RIFF\x04\x00\x00\x00WAVE"

    def synthesize(self, text):
        self.texts.append(text)
        return self.audio


class FakeRouteService:
    def __init__(self, session_id):
        self.session_id = session_id
        self.calls = []
        self.closed = False

    def frame_after(self, after):
        self.calls.append(("frame", after))
        return {
            "sessionID": self.session_id,
            "sequence": max(1, after + 1),
            "paneID": "%{}".format(self.session_id),
            "columns": 48,
            "rows": 28,
            "cursorColumn": 0,
            "cursorRow": 0,
            "alternateScreen": False,
            "mouseMode": False,
            "historySize": 0,
            "lines": [""] * 28,
        }

    def history_page(self, start, limit):
        self.calls.append(("history", start, limit))
        return {
            "sessionID": self.session_id,
            "paneID": "%{}".format(self.session_id),
            "historySize": 0,
            "start": 0,
            "lines": [],
            "ansiLines": [],
        }

    def send_input(self, request_id, data, append_return):
        self.calls.append(("input", request_id, data, append_return))

    def synthesize_speech(self, response_id):
        self.calls.append(("speech", response_id))
        return b"RIFF\x04\x00\x00\x00WAVE"

    def close(self):
        self.closed = True


class TerminalServiceTests(unittest.TestCase):
    def frame_service(self, runner, **kwargs):
        service = terminald.TerminalService(runner, **kwargs)
        service.frame_poll_interval = 0.01
        service.long_poll_seconds = 0.05
        self.addCleanup(service.close)
        return service

    def test_frame_capture_is_stable_until_content_changes(self):
        runner = FakeRunner()
        service = self.frame_service(runner)

        first = service.frame_after(0)
        second = service.frame_after(first["sequence"])
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 1)
        self.assertEqual(first["sessionID"], 1)
        self.assertEqual(first["columns"], 48)
        self.assertEqual(first["rows"], 28)
        self.assertEqual(first["paneID"], runner.pane_id)
        self.assertEqual(first["cursorRow"], 6)
        self.assertTrue(first["mouseMode"])
        self.assertEqual(len(first["lines"]), 28)
        self.assertEqual(first["ansiLines"], first["lines"])
        self.assertEqual(first["screenStart"], 0)
        capture_call = next(call[0] for call in runner.calls if "capture-pane" in call[0])
        self.assertIn("display-message", capture_call)
        self.assertIn("-e", capture_call)
        self.assertIn("-N", capture_call)
        self.assertEqual(
            capture_call[capture_call.index("-S") + 1],
            str(-terminald.MAX_SCROLLBACK_ROWS),
        )

        runner.capture = ("UPDATED\n" + ("\n" * 27)).encode()
        third = service.frame_after(first["sequence"])
        self.assertEqual(third["sequence"], 2)
        self.assertEqual(third["lines"][0], "UPDATED")
        frame_calls = [call[0] for call in runner.calls if "capture-pane" in call[0]]
        self.assertTrue(all("display-message" in call for call in frame_calls))

    def test_fixed_slots_route_to_independent_tmux_targets_and_bootstraps(self):
        runner = FakeRunner()
        service = self.frame_service(runner, session_id=6)

        frame = service.frame_after(0)
        service.send_input("slot-six-input", b"six", append_return=True)
        service.ensure_session()

        self.assertEqual(frame["sessionID"], 6)
        capture_call = next(call[0] for call in runner.calls if "capture-pane" in call[0])
        self.assertEqual(capture_call[capture_call.index("-t") + 1], "=jarvis-ios-6:")
        paste_call = next(call[0] for call in runner.calls if "paste-buffer" in call[0])
        self.assertEqual(paste_call[paste_call.index("-t") + 1], "=jarvis-ios-6:")
        bootstrap_call = next(call[0] for call in runner.calls if str(terminald.BOOTSTRAP) in call[0])
        self.assertEqual(
            bootstrap_call,
            [str(terminald.BOOTSTRAP), "--slot", "6", "--ensure-only"],
        )
        with self.assertRaises(terminald.TerminalError):
            terminald.TerminalService(runner, session_id=7)
        with self.assertRaises(terminald.TerminalError):
            terminald.TerminalService(runner, session_id=True)

    def test_slot_frame_sequences_and_histories_are_independent(self):
        first_runner = FakeRunner()
        second_runner = FakeRunner()
        first_runner.capture = ("ONE\n" + ("\n" * 27)).encode()
        second_runner.capture = ("TWO\n" + ("\n" * 27)).encode()
        first = self.frame_service(first_runner, session_id=1)
        second = self.frame_service(second_runner, session_id=2)

        first_frame = first.frame_after(0)
        second_frame = second.frame_after(0)
        first_runner.capture = ("ONE UPDATED\n" + ("\n" * 27)).encode()
        updated = first.frame_after(first_frame["sequence"])

        self.assertEqual(first_frame["sessionID"], 1)
        self.assertEqual(second_frame["sessionID"], 2)
        self.assertEqual(second_frame["sequence"], 1)
        self.assertEqual(updated["sequence"], 2)
        self.assertEqual(second.last_frame["lines"][0], "TWO")

    def test_concurrent_long_polls_share_one_sampler_and_stop_when_idle(self):
        runner = FakeRunner()
        service = self.frame_service(runner)
        service.frame_poll_interval = 0.02
        service.long_poll_seconds = 0.07
        first = service.frame_after(0)
        time.sleep(0.11)
        captures_before = len([call for call in runner.calls if "capture-pane" in call[0]])
        results = []

        def poll():
            results.append(service.frame_after(first["sequence"]))

        threads = [threading.Thread(target=poll) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 2)
        self.assertTrue(all(frame["sequence"] == first["sequence"] for frame in results))
        captures_after = len([call for call in runner.calls if "capture-pane" in call[0]])
        self.assertGreaterEqual(captures_after - captures_before, 2)
        self.assertLessEqual(captures_after - captures_before, 5)

        time.sleep(0.12)
        idle_count = len([call for call in runner.calls if "capture-pane" in call[0]])
        time.sleep(0.06)
        self.assertEqual(
            len([call for call in runner.calls if "capture-pane" in call[0]]),
            idle_count,
        )

    def test_confirmed_input_wakes_active_sampler_immediately(self):
        runner = FakeRunner()
        service = self.frame_service(runner)
        service.frame_poll_interval = 1.0
        service.long_poll_seconds = 0.5
        first = service.frame_after(0)
        result = []

        thread = threading.Thread(
            target=lambda: result.append(service.frame_after(first["sequence"])),
        )
        thread.start()
        time.sleep(0.05)
        runner.capture = ("AFTER INPUT\n" + ("\n" * 27)).encode()
        service.send_input("sampler-wake", b"x", append_return=False)
        thread.join(timeout=0.4)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["sequence"], first["sequence"] + 1)
        self.assertEqual(result[0]["lines"][0], "AFTER INPUT")

    def test_history_pages_cover_full_tmux_history_in_bounded_exact_ansi_ranges(self):
        runner = FakeRunner()
        runner.capture = b"old-0\n\x1b[1mold-1\x1b[0m\nold-2\n"
        service = self.frame_service(runner)

        page = service.history_page(start=1, limit=3)

        self.assertEqual(page["sessionID"], 1)
        self.assertEqual(page["paneID"], runner.pane_id)
        self.assertEqual(page["historySize"], 4)
        self.assertEqual(page["start"], 1)
        self.assertEqual(page["lines"], ["old-0", "old-1", "old-2"])
        self.assertEqual(page["ansiLines"][1], "\x1b[1mold-1\x1b[0m")
        capture_call = next(call[0] for call in runner.calls if "capture-pane" in call[0])
        self.assertEqual(capture_call[capture_call.index("-S") + 1], "-3")
        self.assertEqual(capture_call[capture_call.index("-E") + 1], "-1")
        self.assertLessEqual(len(page["lines"]), terminald.MAX_HISTORY_PAGE_ROWS)

        with self.assertRaises(terminald.TerminalError):
            service.history_page(start=-1, limit=10)
        with self.assertRaises(terminald.TerminalError):
            service.history_page(start=0, limit=terminald.MAX_HISTORY_PAGE_ROWS + 1)

    def test_frame_preserves_ansi_styles_and_strips_only_sgr_for_plain_lines(self):
        runner = FakeRunner()
        runner.capture = ("\x1b[3m\x1b[38;2;128;128;128mThinking\x1b[0m\n" + ("\n" * 27)).encode()
        frame = self.frame_service(runner).frame_after(0)
        self.assertEqual(frame["lines"][0], "Thinking")
        self.assertEqual(frame["ansiLines"][0], "\x1b[3m\x1b[38;2;128;128;128mThinking\x1b[0m")

    def test_live_lines_remain_build_38_compatible_while_capture_adds_history(self):
        runner = FakeRunner()
        runner.capture = ("history-0\nhistory-1\nhistory-2\nhistory-3\n" + "screen\n" + ("\n" * 27)).encode()
        frame = self.frame_service(runner).frame_after(0)
        self.assertEqual(frame["screenStart"], 4)
        self.assertEqual(len(frame["lines"]), 28)
        self.assertEqual(frame["lines"][0], "screen")
        self.assertEqual(len(frame["capturedLines"]), 32)
        self.assertEqual(frame["capturedLines"][0], "history-0")

    def test_frame_publishes_only_semantic_speech_availability(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as temporary:
            speech_dir = Path(temporary)
            marker = speech_dir / "{}.json".format(runner.pane_pid)
            final_text = "Final answer only; never expose this text in a terminal frame."
            marker.write_text(
                json.dumps({
                    "version": 1,
                    "pid": runner.pane_pid,
                    "paneID": runner.pane_id,
                    "tmuxServerPID": runner.tmux_server_pid,
                    "publisherStartedAt": (runner.session_created_at + 1) * 1000,
                    "updatedAt": int(time.time() * 1000),
                    "status": "ready",
                    "responseID": "a" * 64,
                    "textByteCount": len(final_text.encode("utf-8")),
                    "text": final_text,
                }),
                encoding="utf-8",
            )
            marker.chmod(0o600)
            service = self.frame_service(runner, speech_dir=speech_dir)

            frame = service.frame_after(0)

            self.assertEqual(
                frame["speech"],
                {"available": True, "generating": False, "responseID": "a" * 64},
            )
            self.assertNotIn(final_text, json.dumps(frame))

            payload = json.loads(marker.read_text(encoding="utf-8"))
            payload.update({"status": "generating", "responseID": "", "textByteCount": 0, "text": ""})
            marker.write_text(json.dumps(payload), encoding="utf-8")
            marker.chmod(0o600)
            next_frame = service.frame_after(frame["sequence"])
            self.assertEqual(
                next_frame["speech"],
                {"available": False, "generating": True, "responseID": ""},
            )

    def test_speech_requires_current_response_id_and_forwards_only_marker_text(self):
        runner = FakeRunner()
        speech_client = FakeRoomSpeechClient()
        with tempfile.TemporaryDirectory() as temporary:
            speech_dir = Path(temporary)
            marker = speech_dir / "{}.json".format(runner.pane_pid)
            final_text = "The final response, sir."
            marker.write_text(
                json.dumps({
                    "version": 1,
                    "pid": runner.pane_pid,
                    "paneID": runner.pane_id,
                    "tmuxServerPID": runner.tmux_server_pid,
                    "publisherStartedAt": (runner.session_created_at + 1) * 1000,
                    "updatedAt": int(time.time() * 1000),
                    "status": "ready",
                    "responseID": "b" * 64,
                    "textByteCount": len(final_text.encode("utf-8")),
                    "text": final_text,
                }),
                encoding="utf-8",
            )
            marker.chmod(0o600)
            stale_cache_path = speech_dir / ("1-" + ("a" * 64) + ".wav")
            stale_cache_path.write_bytes(speech_client.audio)
            stale_cache_path.chmod(0o600)
            service = terminald.TerminalService(
                runner,
                speech_dir=speech_dir,
                room_speech_client=speech_client,
            )

            self.assertEqual(service.synthesize_speech("b" * 64), speech_client.audio)
            self.assertEqual(service.synthesize_speech("b" * 64), speech_client.audio)
            self.assertEqual(speech_client.texts, [final_text])
            cache_path = speech_dir / ("1-" + ("b" * 64) + ".wav")
            self.assertEqual(cache_path.read_bytes(), speech_client.audio)
            self.assertEqual(cache_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(speech_dir.glob("*.wav")), [cache_path])
            self.assertFalse(stale_cache_path.exists())
            with self.assertRaises(terminald.TerminalError):
                service.synthesize_speech("c" * 64)
            self.assertEqual(speech_client.texts, [final_text])

    def test_slot_scoped_speech_caches_are_independent_and_legacy_cache_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            speech_dir = Path(temporary)
            legacy = speech_dir / (("a" * 64) + ".wav")
            first = speech_dir / ("1-" + ("b" * 64) + ".wav")
            second = speech_dir / ("2-" + ("c" * 64) + ".wav")
            unrelated = speech_dir / "keep.wav"
            for path in (legacy, first, second, unrelated):
                path.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
                path.chmod(0o600)

            slot_one = terminald.TerminalService(FakeRunner(), speech_dir=speech_dir, session_id=1)
            slot_two = terminald.TerminalService(FakeRunner(), speech_dir=speech_dir, session_id=2)
            slot_two.remove_legacy_speech_cache()
            self.assertTrue(legacy.exists())
            slot_one.remove_legacy_speech_cache()

            self.assertFalse(legacy.exists())
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(slot_one._speech_cache_path("d" * 64).name, "1-" + ("d" * 64) + ".wav")
            self.assertEqual(slot_two._speech_cache_path("d" * 64).name, "2-" + ("d" * 64) + ".wav")

    def test_concurrent_duplicate_speech_requests_share_one_complete_render(self):
        class BlockingRoomSpeechClient(FakeRoomSpeechClient):
            def __init__(self):
                super().__init__()
                self.started = threading.Event()
                self.release = threading.Event()

            def synthesize(self, text):
                self.texts.append(text)
                self.started.set()
                if not self.release.wait(timeout=2):
                    raise AssertionError("test synthesis was not released")
                return self.audio

        runner = FakeRunner()
        speech_client = BlockingRoomSpeechClient()
        with tempfile.TemporaryDirectory() as temporary:
            speech_dir = Path(temporary)
            final_text = "Render this response exactly once."
            response_id = "d" * 64
            marker = speech_dir / "{}.json".format(runner.pane_pid)
            marker.write_text(
                json.dumps({
                    "version": 1,
                    "pid": runner.pane_pid,
                    "paneID": runner.pane_id,
                    "tmuxServerPID": runner.tmux_server_pid,
                    "publisherStartedAt": (runner.session_created_at + 1) * 1000,
                    "updatedAt": int(time.time() * 1000),
                    "status": "ready",
                    "responseID": response_id,
                    "textByteCount": len(final_text.encode("utf-8")),
                    "text": final_text,
                }),
                encoding="utf-8",
            )
            marker.chmod(0o600)
            service = terminald.TerminalService(
                runner,
                speech_dir=speech_dir,
                room_speech_client=speech_client,
            )
            results = []
            errors = []

            def synthesize():
                try:
                    results.append(service.synthesize_speech(response_id))
                except Exception as error:
                    errors.append(error)

            first = threading.Thread(target=synthesize)
            second = threading.Thread(target=synthesize)
            first.start()
            self.assertTrue(speech_client.started.wait(timeout=1))
            second.start()
            time.sleep(0.05)
            self.assertEqual(speech_client.texts, [final_text])
            speech_client.release.set()
            first.join(timeout=2)
            second.join(timeout=2)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, [speech_client.audio, speech_client.audio])
            self.assertEqual(speech_client.texts, [final_text])

    def test_input_is_byte_exact_bounded_and_deduplicated(self):
        runner = FakeRunner()
        service = terminald.TerminalService(runner)
        payload = b"\x1b[<64;8;12M"

        service.send_input("request-1", payload, append_return=False)
        service.send_input("request-1", payload, append_return=False)

        load_calls = [call for call in runner.calls if "load-buffer" in call[0]]
        paste_calls = [call for call in runner.calls if "paste-buffer" in call[0]]
        self.assertEqual(len(load_calls), 1)
        self.assertEqual(load_calls[0][1], payload)
        self.assertEqual(len(paste_calls), 1)
        self.assertIn("-S", paste_calls[0][0])
        self.assertIn("-r", paste_calls[0][0])
        refresh_calls = [call for call in runner.calls if "refresh-client" in call[0]]
        self.assertEqual(len(refresh_calls), 2)
        self.assertEqual(
            [call[0][call[0].index("-t") + 1] for call in refresh_calls],
            ["/dev/ttys001", "/dev/ttys002"],
        )

        with self.assertRaises(terminald.TerminalError):
            service.send_input("request-2", b"x" * (terminald.MAX_INPUT_BYTES + 1), False)

    def test_redraw_failure_after_delivery_never_makes_input_replayable(self):
        class RefreshFailureRunner(FakeRunner):
            def run(self, arguments, input_data=None, timeout=5, check=True):
                arguments = list(arguments)
                if "refresh-client" in arguments:
                    self.calls.append((arguments, input_data))
                    raise subprocess.TimeoutExpired(arguments, timeout)
                return super().run(arguments, input_data=input_data, timeout=timeout, check=check)

        runner = RefreshFailureRunner()
        service = terminald.TerminalService(runner)

        service.send_input("request-refresh-failure", b"send once", append_return=True)
        service.send_input("request-refresh-failure", b"send once", append_return=True)

        self.assertEqual(len([call for call in runner.calls if "paste-buffer" in call[0]]), 1)
        self.assertEqual(len([call for call in runner.calls if "refresh-client" in call[0]]), 1)

    def test_append_return_is_atomic_with_prompt(self):
        runner = FakeRunner()
        service = terminald.TerminalService(runner)
        service.send_input("request-return", b"hello", append_return=True)

        load_calls = [call for call in runner.calls if "load-buffer" in call[0]]
        paste_calls = [call for call in runner.calls if "paste-buffer" in call[0]]
        send_key_calls = [call for call in runner.calls if "send-keys" in call[0]]
        self.assertEqual(len(load_calls), 1)
        self.assertEqual(load_calls[0][1], b"hello\r")
        self.assertEqual(len(paste_calls), 1)
        self.assertEqual(send_key_calls, [])

        service.send_input("request-return-only", b"", append_return=True)
        return_loads = [call for call in runner.calls if "load-buffer" in call[0]]
        self.assertEqual(return_loads[-1][1], b"\r")

    def test_v2_http_routes_fixed_sessions_and_v1_remains_slot_one(self):
        token = "fixture-" + ("a" * 56)
        services = {session_id: FakeRouteService(session_id) for session_id in range(1, 7)}
        server = terminald.TerminalHTTPServer(
            ("127.0.0.1", 0),
            services[1],
            token,
            terminald.parse_cidrs("127.0.0.0/8"),
            services=services,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:{}".format(server.server_address[1])
        headers = {"Authorization": "Bearer " + token}

        def load_json(path):
            request = urllib_request.Request(base + path, headers=headers)
            with urllib_request.urlopen(request, timeout=5) as response:
                return json.load(response)

        def post_json(path, payload):
            request = urllib_request.Request(
                base + path,
                data=json.dumps(payload).encode(),
                method="POST",
                headers={**headers, "Content-Type": "application/json"},
            )
            with urllib_request.urlopen(request, timeout=5) as response:
                return response, response.read()

        try:
            self.assertEqual(load_json("/health")["sessionIDs"], [1, 2, 3, 4, 5, 6])
            frame = load_json("/v2/terminal/frame?after=7&sessionID=2")
            self.assertEqual(frame["sessionID"], 2)
            self.assertEqual(services[2].calls, [("frame", 7)])
            self.assertEqual(services[1].calls, [])

            history = load_json("/v2/terminal/history?start=9&limit=10&sessionID=6")
            self.assertEqual(history["sessionID"], 6)
            self.assertEqual(services[6].calls, [("history", 9, 10)])

            input_payload = {
                "requestID": "slot-six",
                "sessionID": 6,
                "dataBase64": base64.b64encode(b"six").decode(),
                "appendReturn": True,
            }
            _, raw_acknowledgement = post_json("/v2/terminal/input", input_payload)
            acknowledgement = json.loads(raw_acknowledgement)
            self.assertEqual(acknowledgement["sessionID"], 6)
            self.assertIn(("input", "slot-six", b"six", True), services[6].calls)

            response_id = "d" * 64
            response, audio = post_json(
                "/v2/terminal/speech",
                {"sessionID": 2, "responseID": response_id},
            )
            self.assertEqual(response.headers["X-JARVIS-Terminal-Session"], "2")
            self.assertEqual(audio[:4], b"RIFF")
            self.assertIn(("speech", response_id), services[2].calls)

            legacy = load_json("/v1/terminal/frame?after=0&sessionID=6")
            self.assertEqual(legacy["sessionID"], 1)
            legacy_input = dict(input_payload, requestID="legacy", sessionID=6)
            _, raw_legacy_ack = post_json("/v1/terminal/input", legacy_input)
            self.assertEqual(json.loads(raw_legacy_ack)["sessionID"], 1)
            self.assertIn(("input", "legacy", b"six", True), services[1].calls)

            for path in (
                "/v2/terminal/frame?after=0",
                "/v2/terminal/frame?after=0&sessionID=0",
                "/v2/terminal/frame?after=0&sessionID=7",
                "/v2/terminal/frame?after=0&sessionID=2&sessionID=3",
                "/v2/terminal/frame?after=0&sessionID=02",
            ):
                with self.assertRaises(HTTPError) as raised:
                    load_json(path)
                self.assertEqual(raised.exception.code, 400)
                raised.exception.close()

            for invalid_session in (False, 7, 2.0, "2", "02"):
                invalid_payload = dict(input_payload, sessionID=invalid_session)
                with self.assertRaises(HTTPError) as raised:
                    post_json("/v2/terminal/input", invalid_payload)
                self.assertEqual(raised.exception.code, 400)
                raised.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertTrue(all(service.closed for service in services.values()))

        with self.assertRaises(terminald.TerminalError):
            terminald.TerminalHTTPServer(
                ("127.0.0.1", 0),
                services[1],
                token,
                terminald.parse_cidrs("127.0.0.0/8"),
                services={1: services[1], 2: services[3]},
            )

    def test_disposable_bootstrap_maps_only_fixed_slots_and_preserves_panes(self):
        tmux = shutil.which("tmux")
        zsh = shutil.which("zsh")
        if not tmux or not zsh:
            self.skipTest("tmux or zsh is unavailable")
        socket = "jarvis-bootstrap-test-{}".format(uuid.uuid4().hex)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "jarvis-mobile-terminal.sh"
            source = terminald.BOOTSTRAP.read_text(encoding="utf-8")
            source = source.replace(
                'readonly TMUX_BIN="/opt/homebrew/bin/tmux"',
                'readonly TMUX_BIN="{}"'.format(tmux),
            ).replace(
                'readonly TMUX_SOCKET="jarvis-mobile"',
                'readonly TMUX_SOCKET="{}"'.format(socket),
            ).replace(
                'readonly TMUX_CONFIG="/Users/dylanrapanan/JARVIS/projects/operation-jarvis/jarvis-app/config/jarvis-mobile.tmux.conf"',
                'readonly TMUX_CONFIG="{}"'.format(terminald.APP_ROOT / "config" / "jarvis-mobile.tmux.conf"),
            ).replace(
                'readonly JARVIS_ROOT="/Users/dylanrapanan/JARVIS"',
                'readonly JARVIS_ROOT="{}"'.format(root),
            ).replace(
                "readonly PI_COMMAND='/opt/homebrew/bin/pi --tui-mode regular'",
                "readonly PI_COMMAND='sleep 30'",
            )
            script.write_text(source, encoding="utf-8")
            script.chmod(0o700)

            def ensure(slot):
                return subprocess.run(
                    [str(script), "--slot", str(slot), "--ensure-only"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )

            def pane_pid(session):
                return subprocess.run(
                    [tmux, "-L", socket, "display-message", "-p", "-t", session + ":", "#{pane_pid}"],
                    check=True,
                    stdout=subprocess.PIPE,
                    timeout=5,
                ).stdout.decode().strip()

            try:
                self.assertEqual(ensure(2).returncode, 0)
                first_pid = pane_pid("jarvis-ios-2")
                self.assertEqual(ensure(2).returncode, 0)
                self.assertEqual(pane_pid("jarvis-ios-2"), first_pid)
                self.assertEqual(ensure(1).returncode, 0)
                self.assertEqual(ensure(3).returncode, 0)
                self.assertEqual(ensure(4).returncode, 0)
                self.assertEqual(ensure(5).returncode, 0)
                self.assertEqual(ensure(6).returncode, 0)
                sessions = subprocess.run(
                    [tmux, "-L", socket, "list-sessions", "-F", "#{session_name}"],
                    check=True,
                    stdout=subprocess.PIPE,
                    timeout=5,
                ).stdout.decode().splitlines()
                self.assertEqual(
                    sorted(sessions),
                    ["jarvis-ios", "jarvis-ios-2", "jarvis-ios-3", "jarvis-ios-4", "jarvis-ios-5", "jarvis-ios-6"],
                )
                for session in sessions:
                    size = subprocess.run(
                        [tmux, "-L", socket, "show-options", "-wv", "-t", session + ":0", "window-size"],
                        check=True,
                        stdout=subprocess.PIPE,
                        timeout=5,
                    ).stdout.decode().strip()
                    self.assertEqual(size, "latest")

                for arguments in (
                    ["--slot", "0", "--ensure-only"],
                    ["--slot", "7", "--ensure-only"],
                    ["--slot", "1", "--slot", "2", "--ensure-only"],
                    ["--session", "jarvis-ios-2", "--ensure-only"],
                ):
                    rejected = subprocess.run(
                        [str(script), *arguments],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=5,
                    )
                    self.assertEqual(rejected.returncode, 64)
                self.assertEqual(pane_pid("jarvis-ios-2"), first_pid)
            finally:
                subprocess.run(
                    [tmux, "-L", socket, "kill-server"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )

    def test_disposable_tmux_history_pages_reach_oldest_retained_rows(self):
        tmux = shutil.which("tmux")
        if not tmux:
            self.skipTest("tmux is unavailable")
        socket = "jarvis-history-test-{}".format(uuid.uuid4().hex)
        session = "fixture"
        command = (
            "{} -c {}".format(
                shlex.quote(sys.executable),
                shlex.quote(
                    "import time; "
                    "[print(f'line-{i:04d}', flush=True) for i in range(600)]; "
                    "time.sleep(30)"
                ),
            )
        )
        subprocess.run(
            [tmux, "-L", socket, "new-session", "-d", "-s", session, "-x", "48", "-y", "20", command],
            check=True,
            timeout=10,
        )
        try:
            history_size = 0
            for _ in range(100):
                history_size = int(subprocess.run(
                    [tmux, "-L", socket, "display-message", "-p", "-t", session + ":", "#{history_size}"],
                    check=True,
                    stdout=subprocess.PIPE,
                    timeout=5,
                ).stdout)
                if history_size >= 580:
                    break
                time.sleep(0.02)
            self.assertGreaterEqual(history_size, 580)

            with mock.patch.object(terminald, "TMUX", tmux), \
                 mock.patch.object(terminald, "TMUX_SOCKET", socket), \
                 mock.patch.object(terminald, "TMUX_SESSION", session), \
                 mock.patch.object(terminald, "TMUX_TARGET", session + ":"):
                service = terminald.TerminalService()
                service.ensure_session = lambda: None
                oldest = service.history_page(start=0, limit=3)
                middle = service.history_page(start=500, limit=3)

            self.assertEqual([line.strip() for line in oldest["lines"]], ["line-0000", "line-0001", "line-0002"])
            self.assertEqual([line.strip() for line in middle["lines"]], ["line-0500", "line-0501", "line-0502"])
        finally:
            subprocess.run(
                [tmux, "-L", socket, "kill-server"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )

    def test_disposable_https_tmux_receives_one_prompt_and_one_return(self):
        tmux = shutil.which("tmux")
        if not tmux:
            self.skipTest("tmux is unavailable")
        socket = "jarvis-terminal-test-{}".format(uuid.uuid4().hex)
        session = "fixture"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "input.bin"
            reader = root / "reader.py"
            reader.write_text(
                "import pathlib,sys\n"
                "print('READY', flush=True)\n"
                "pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.readline())\n",
                encoding="utf-8",
            )
            command = "{} {}".format(shlex.quote(sys.executable), shlex.quote(str(reader)))
            command += " {}".format(shlex.quote(str(output)))
            subprocess.run(
                [tmux, "-L", socket, "new-session", "-d", "-s", session, "-x", "48", "-y", "20", command],
                check=True,
                timeout=10,
            )
            try:
                for _ in range(50):
                    captured = subprocess.run(
                        [tmux, "-L", socket, "capture-pane", "-p", "-t", session + ":"],
                        check=True,
                        stdout=subprocess.PIPE,
                        timeout=5,
                    ).stdout
                    if b"READY" in captured:
                        break
                    time.sleep(0.02)
                else:
                    self.fail("disposable tmux reader did not become ready")

                cert = root / "fixture-cert.pem"
                key = root / "fixture-key.pem"
                subprocess.run(
                    [
                        "/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                        "-days", "1", "-nodes", "-subj", "/CN=JARVIS Disposable Fixture",
                        "-keyout", str(key), "-out", str(cert),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                token = "fixture-" + ("a" * 56)
                with mock.patch.object(terminald, "TMUX", tmux), \
                     mock.patch.object(terminald, "TMUX_SOCKET", socket), \
                     mock.patch.object(terminald, "TMUX_SESSION", session), \
                     mock.patch.object(terminald, "TMUX_TARGET", session + ":"):
                    service = terminald.TerminalService()
                    service.ensure_session = lambda: None
                    server = terminald.TerminalHTTPServer(
                        ("127.0.0.1", 0),
                        service,
                        token,
                        terminald.parse_cidrs("127.0.0.0/8"),
                    )
                    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    tls.load_cert_chain(str(cert), str(key))
                    server.socket = tls.wrap_socket(server.socket, server_side=True)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        base = "https://127.0.0.1:{}".format(server.server_address[1])
                        context = ssl._create_unverified_context()
                        frame_request = urllib_request.Request(
                            base + "/v1/terminal/frame?after=0",
                            headers={"Authorization": "Bearer " + token},
                        )
                        with urllib_request.urlopen(frame_request, context=context, timeout=5) as response:
                            frame = json.load(response)
                        self.assertEqual(frame["columns"], 48)
                        self.assertEqual(frame["sessionID"], 1)

                        routed_frame_request = urllib_request.Request(
                            base + "/v2/terminal/frame?after=0&sessionID=1",
                            headers={"Authorization": "Bearer " + token},
                        )
                        with urllib_request.urlopen(routed_frame_request, context=context, timeout=5) as response:
                            routed_frame = json.load(response)
                        self.assertEqual(routed_frame["sessionID"], 1)

                        payload = json.dumps({
                            "requestID": "disposable-request",
                            "sessionID": 1,
                            "dataBase64": base64.b64encode(b"fixture prompt").decode(),
                            "appendReturn": True,
                        }).encode()
                        for _ in range(2):
                            post = urllib_request.Request(
                                base + "/v2/terminal/input",
                                data=payload,
                                method="POST",
                                headers={
                                    "Authorization": "Bearer " + token,
                                    "Content-Type": "application/json",
                                },
                            )
                            with urllib_request.urlopen(post, context=context, timeout=5) as response:
                                acknowledgement = json.load(response)
                                self.assertTrue(acknowledgement["ok"])
                                self.assertEqual(acknowledgement["sessionID"], 1)
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=5)

                for _ in range(100):
                    if output.exists():
                        break
                    time.sleep(0.02)
                self.assertEqual(output.read_bytes(), b"fixture prompt\n")
            finally:
                subprocess.run(
                    [tmux, "-L", socket, "kill-server"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )

    def test_provisioning_code_contains_valid_https_configuration_without_writing_repo(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            with mock.patch.object(terminald, "RUNTIME_DIR", runtime), \
                 mock.patch.object(terminald, "TOKEN_PATH", runtime / "token"), \
                 mock.patch.object(terminald, "CERT_PATH", runtime / "certificate.pem"), \
                 mock.patch.object(terminald, "KEY_PATH", runtime / "certificate-key.pem"):
                code = terminald.provisioning_code("192.0.2.10")
                encoded = code + ("=" * ((4 - len(code) % 4) % 4))
                payload = json.loads(base64.urlsafe_b64decode(encoded))
                self.assertEqual(payload["endpoint"], "https://192.0.2.10:8792")
                self.assertEqual(len(payload["token"]), 64)
                self.assertEqual(len(payload["certificateSHA256"]), 64)
                self.assertEqual(os.stat(runtime / "token").st_mode & 0o777, 0o600)
                self.assertEqual(os.stat(runtime / "certificate-key.pem").st_mode & 0o777, 0o600)

    def test_trusted_networks_are_explicit(self):
        networks = terminald.parse_cidrs("127.0.0.0/8,192.168.0.0/16,100.64.0.0/10")
        self.assertEqual(len(networks), 3)
        with self.assertRaises(terminald.TerminalError):
            terminald.parse_cidrs(" , ")

    def test_disconnected_long_poll_client_is_silently_closed(self):
        handler = object.__new__(terminald.TerminalRequestHandler)
        handler.close_connection = False
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock(side_effect=BrokenPipeError())
        handler.wfile = mock.Mock()

        handler._write_json(terminald.HTTPStatus.OK, {"ok": True})

        self.assertTrue(handler.close_connection)
        handler.wfile.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
