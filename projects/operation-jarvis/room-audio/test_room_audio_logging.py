from __future__ import annotations

import io
import logging
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import room_audio_logging as bounded
import room_audio_server as server


class BoundedStderrTests(unittest.TestCase):
    def test_existing_stderr_handler_and_python_output_are_redirected_and_restored(self):
        original = io.StringIO()
        logger = logging.getLogger("fixture.room-audio-bounded")
        handler = logging.StreamHandler(original)
        before = (logger.handlers[:], logger.level, logger.propagate)
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "private" / "server.log"
                with mock.patch.object(sys, "stderr", original):
                    with bounded.bounded_stderr(path, max_bytes=1024, backup_count=3) as writer:
                        self.assertIs(sys.stderr, writer)
                        self.assertIs(handler.stream, writer)
                        logger.info("fixture logging")
                        print("fixture stderr", file=sys.stderr)
                    self.assertIs(sys.stderr, original)
                    self.assertIs(handler.stream, original)
                output = path.read_text()
                self.assertIn("fixture logging", output)
                self.assertIn("fixture stderr", output)
                self.assertEqual(original.getvalue(), "")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        finally:
            logger.handlers, logger.level, logger.propagate = before

    def test_rotation_keeps_only_the_configured_private_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "server.log"
            with bounded.bounded_stderr(path, max_bytes=256, backup_count=3) as writer:
                for index in range(30):
                    writer.write(f"{index:02d} " + "x" * 90 + "\n")
            files = list(path.parent.glob("server.log*"))
            self.assertEqual(len(files), 4)
            for item in files:
                self.assertLessEqual(item.stat().st_size, 256)
                self.assertEqual(stat.S_IMODE(item.stat().st_mode), 0o600)

    def test_setup_failure_retains_original_stderr_without_exception_details(self):
        original = io.StringIO()
        with mock.patch.object(sys, "stderr", original), \
                mock.patch.object(bounded, "BoundedLogWriter", side_effect=OSError("private fixture detail")):
            with bounded.bounded_stderr(Path("unused"), max_bytes=1024, backup_count=3) as writer:
                self.assertIsNone(writer)
                self.assertIs(sys.stderr, original)
        self.assertIn("retaining launchd stderr", original.getvalue())
        self.assertNotIn("private fixture detail", original.getvalue())

    def test_server_exception_propagates_and_stderr_is_restored(self):
        original = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(sys, "stderr", original):
            with self.assertRaisesRegex(RuntimeError, "fixture server failure"):
                with bounded.bounded_stderr(Path(directory) / "server.log", max_bytes=1024, backup_count=3):
                    raise RuntimeError("fixture server failure")
            self.assertIs(sys.stderr, original)

    def test_import_and_server_start_select_port_specific_logs_without_live_bridge(self):
        with mock.patch.object(sys, "argv", ["fixture", "--port", "8793"]), \
                mock.patch.dict(os.environ, {
                    "JARVIS_ROOM_AUDIO_LOG_FILE": "",
                    "JARVIS_ROOM_AUDIO_LOG_MAX_BYTES": "999999999",
                    "JARVIS_ROOM_AUDIO_LOG_BACKUP_COUNT": "999",
                }), \
                mock.patch.object(server, "bounded_stderr") as setup, \
                mock.patch.object(server, "_serve", return_value=0) as serve:
            self.assertEqual(server.main(), 0)
            setup.assert_called_once()
            self.assertEqual(setup.call_args.args[0].name, "server-8793.log")
            self.assertEqual(setup.call_args.kwargs["max_bytes"], 16 * 1024 * 1024)
            self.assertEqual(setup.call_args.kwargs["backup_count"], 10)
            serve.assert_called_once()


class AccessLogTests(unittest.TestCase):
    def make_handler(self, path="/client-state", method="POST", client="127.0.0.1"):
        handler = server.RoomAudioHandler.__new__(server.RoomAudioHandler)
        handler.path = path
        handler.command = method
        handler.client_address = (client, 1234)
        return handler

    def test_successful_telemetry_is_coalesced_with_count_after_interval(self):
        now = [0.0]
        gate = bounded.RoutineRequestLogGate(60, clock=lambda: now[0])
        handler = self.make_handler()
        with mock.patch.object(server, "ROUTINE_REQUEST_LOG_GATE", gate), \
                mock.patch.object(server.LOGGER, "info") as log:
            handler.log_request(200)
            handler.log_request(200)
            handler.log_request(200)
            self.assertEqual(log.call_count, 1)
            now[0] = 60
            handler.log_request(200)
            self.assertEqual(log.call_count, 2)
            self.assertEqual(log.call_args.args[-1], " suppressed=2")

    def test_request_failures_are_never_suppressed(self):
        gate = bounded.RoutineRequestLogGate(60, clock=lambda: 0)
        handler = self.make_handler()
        with mock.patch.object(server, "ROUTINE_REQUEST_LOG_GATE", gate), \
                mock.patch.object(server.LOGGER, "info") as log:
            handler.log_request(200)
            handler.log_request(200)
            handler.log_request(400)
            handler.log_request(500)
            self.assertEqual(log.call_count, 3)

    def test_turns_and_different_clients_remain_independent(self):
        gate = bounded.RoutineRequestLogGate(60, clock=lambda: 0)
        with mock.patch.object(server, "ROUTINE_REQUEST_LOG_GATE", gate), \
                mock.patch.object(server.LOGGER, "info") as log:
            self.make_handler(client="127.0.0.1").log_request(200)
            self.make_handler(client="127.0.0.2").log_request(200)
            turn = self.make_handler(path="/turn")
            turn.log_request(200)
            turn.log_request(200)
            self.assertEqual(log.call_count, 4)

    def test_queries_and_unknown_path_values_do_not_enter_access_logs(self):
        with mock.patch.object(server.LOGGER, "info") as log:
            self.make_handler(path="/turn-result?id=private-fixture", method="GET").log_request(404)
            self.make_handler(path="/private-fixture", method="GET").log_request(404)
            rendered = "\n".join(call.args[0] % call.args[1:] for call in log.call_args_list)
            self.assertIn("/turn-result", rendered)
            self.assertIn("/other", rendered)
            self.assertNotIn("private-fixture", rendered)

    def test_malformed_request_metadata_does_not_break_error_logging(self):
        with mock.patch.object(server.LOGGER, "info") as log:
            handler = server.RoomAudioHandler.__new__(server.RoomAudioHandler)
            handler.log_request(400)
            self.make_handler(path="http://[invalid", method="invalid-fixture").log_request(400)
            self.assertEqual(log.call_count, 2)
            rendered = "\n".join(call.args[0] % call.args[1:] for call in log.call_args_list)
            self.assertNotIn("invalid-fixture", rendered)


if __name__ == "__main__":
    unittest.main()
