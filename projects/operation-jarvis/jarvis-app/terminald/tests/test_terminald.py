import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from terminald import jarvis_terminald as terminald


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.capture = ("JARVIS\n" + ("\n" * 27)).encode()

    def run(self, arguments, input_data=None, timeout=5, check=True):
        arguments = list(arguments)
        self.calls.append((arguments, input_data))
        if "display-message" in arguments:
            stdout = b"48\t28\t2\t6\t0\t1\t4\t0\n"
            return subprocess.CompletedProcess(arguments, 0, stdout, b"")
        if "capture-pane" in arguments:
            return subprocess.CompletedProcess(arguments, 0, self.capture, b"")
        return subprocess.CompletedProcess(arguments, 0, b"", b"")


class TerminalServiceTests(unittest.TestCase):
    def test_frame_capture_is_stable_until_content_changes(self):
        runner = FakeRunner()
        service = terminald.TerminalService(runner)

        first = service.frame_after(0)
        second = service.frame_after(0)
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 1)
        self.assertEqual(first["columns"], 48)
        self.assertEqual(first["rows"], 28)
        self.assertEqual(first["cursorRow"], 6)
        self.assertTrue(first["mouseMode"])
        self.assertEqual(len(first["lines"]), 28)

        runner.capture = ("UPDATED\n" + ("\n" * 27)).encode()
        third = service.frame_after(0)
        self.assertEqual(third["sequence"], 2)
        self.assertEqual(third["lines"][0], "UPDATED")

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

        with self.assertRaises(terminald.TerminalError):
            service.send_input("request-2", b"x" * (terminald.MAX_INPUT_BYTES + 1), False)

    def test_append_return_is_explicit(self):
        runner = FakeRunner()
        service = terminald.TerminalService(runner)
        service.send_input("request-return", b"hello", append_return=True)
        send_key_calls = [call for call in runner.calls if "send-keys" in call[0]]
        self.assertEqual(len(send_key_calls), 1)
        self.assertEqual(send_key_calls[0][0][-1], "Enter")

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
