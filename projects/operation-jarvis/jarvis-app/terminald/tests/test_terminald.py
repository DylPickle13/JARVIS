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
import uuid
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
        self.assertEqual(first["ansiLines"], first["lines"])
        self.assertEqual(first["screenStart"], 0)
        capture_call = next(call[0] for call in runner.calls if "capture-pane" in call[0])
        self.assertIn("-e", capture_call)
        self.assertIn("-N", capture_call)
        self.assertEqual(capture_call[capture_call.index("-S") + 1], "-4")

        runner.capture = ("UPDATED\n" + ("\n" * 27)).encode()
        third = service.frame_after(0)
        self.assertEqual(third["sequence"], 2)
        self.assertEqual(third["lines"][0], "UPDATED")

    def test_frame_preserves_ansi_styles_and_strips_only_sgr_for_plain_lines(self):
        runner = FakeRunner()
        runner.capture = ("\x1b[3m\x1b[38;2;128;128;128mThinking\x1b[0m\n" + ("\n" * 27)).encode()
        frame = terminald.TerminalService(runner).frame_after(0)
        self.assertEqual(frame["lines"][0], "Thinking")
        self.assertEqual(frame["ansiLines"][0], "\x1b[3m\x1b[38;2;128;128;128mThinking\x1b[0m")

    def test_live_lines_remain_build_38_compatible_while_capture_adds_history(self):
        runner = FakeRunner()
        runner.capture = ("history-0\nhistory-1\nhistory-2\nhistory-3\n" + "screen\n" + ("\n" * 27)).encode()
        frame = terminald.TerminalService(runner).frame_after(0)
        self.assertEqual(frame["screenStart"], 4)
        self.assertEqual(len(frame["lines"]), 28)
        self.assertEqual(frame["lines"][0], "screen")
        self.assertEqual(len(frame["capturedLines"]), 32)
        self.assertEqual(frame["capturedLines"][0], "history-0")

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

                        payload = json.dumps({
                            "requestID": "disposable-request",
                            "dataBase64": base64.b64encode(b"fixture prompt").decode(),
                            "appendReturn": True,
                        }).encode()
                        for _ in range(2):
                            post = urllib_request.Request(
                                base + "/v1/terminal/input",
                                data=payload,
                                method="POST",
                                headers={
                                    "Authorization": "Bearer " + token,
                                    "Content-Type": "application/json",
                                },
                            )
                            with urllib_request.urlopen(post, context=context, timeout=5) as response:
                                self.assertTrue(json.load(response)["ok"])
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
