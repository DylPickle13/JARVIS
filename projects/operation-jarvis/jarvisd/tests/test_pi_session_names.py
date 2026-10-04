"""Offline fixtures only; no real session history or service/hardware access."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from daemon_loader import load_daemon
from jarvisd_core import pi_session_names as names

jarvisd = load_daemon("jarvisd_session_names_test")


class PiSessionNamesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.history_root = self.root / "sessions"
        self.history_root.mkdir()
        self.path = self.history_root / "active.jsonl"
        self.reader = names.PiSessionNameReader()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, *entries, path=None, session_id="fixture"):
        p = path or self.path
        rows = [{"type": "session", "version": 3, "id": session_id}, *entries]
        p.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        return p

    def read(self, path=None):
        return self.reader.read(str(path or self.path), root=self.history_root)

    def append(self, row):
        with self.path.open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    def test_only_latest_explicit_metadata_is_exposed_never_message_content(self):
        self.write({"type": "session_info", "name": "Earlier name"},
                   {"type": "message", "name": "Not a session name", "message": {"role": "user", "content": "private prompt"}},
                   {"type": "session_info", "name": "  Dashboard names 🎛️  "},
                   {"type": "custom", "data": {"type": "session_info", "name": "Nested impostor"}})
        before = self.path.read_bytes()
        self.assertEqual(self.read(), "Dashboard names 🎛️")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn("private prompt", repr(self.reader._entries))

    def test_rename_and_clear_do_not_resurrect_an_older_title(self):
        self.write({"type": "session_info", "name": "Original"})
        self.assertEqual(self.read(), "Original")
        self.append({"type": "session_info", "name": "Renamed"})
        self.assertEqual(self.read(), "Renamed")
        self.append({"type": "session_info", "name": ""})
        self.assertIsNone(self.read())
        self.append({"type": "message", "message": {"role": "assistant", "content": "Another invented topic"}})
        self.assertIsNone(self.read())

    def test_metadata_only_and_unnamed_conversations_have_no_invented_title(self):
        for entry in ({"type": "model_change"}, {"type": "message", "message": {"role": "user", "content": "Name this from my prompt"}}):
            self.write(entry)
            self.assertIsNone(self.read())

    def test_names_are_single_line_bounded_unicode_and_not_terminal_instructions(self):
        for invalid in (None, 12, True, {}, "", "  ", "x" * 257, "a\nb", "a\rb", "a\tb", "\x1b[31mname", "a\x00b", "a\u2028b", "a\u202eb", "a\u2066b", "a\ud800b"):
            self.assertIsNone(names.validated_name(invalid), repr(invalid))
        for valid in ("x" * 256, "Jarvis app", "Session names 🎛️", "日本語のセッション"):
            self.assertEqual(names.validated_name(valid), valid)
        self.write({"type": "session_info", "name": "Old"}, {"type": "session_info", "name": 123})
        self.assertIsNone(self.read())

    def test_missing_outside_symlink_directory_and_relative_paths_fail_closed(self):
        self.assertIsNone(self.read())
        self.write({"type": "session_info", "name": "Valid"})
        outside = self.root / "outside.jsonl"
        outside.write_bytes(self.path.read_bytes())
        link = self.history_root / "link.jsonl"
        link.symlink_to(self.path)
        for p in (outside, link, self.history_root, Path("active.jsonl")):
            self.assertIsNone(self.read(p))
        fifo = self.history_root / "pipe.jsonl"
        os.mkfifo(fifo)
        self.assertIsNone(self.read(fifo))

    def test_malformed_or_wrong_session_headers_never_expose_a_name(self):
        for header in ("", "not json\n", '{}\n', '{"type":"message"}\n', '{"type":"session","version":9,"id":"x"}\n', '{"type":"session","version":3}\n'):
            self.path.write_text(header + '{"type":"session_info","name":"Must not escape"}\n')
            self.assertIsNone(self.read())

    def test_partial_append_is_unknown_until_complete_and_does_not_cache_raw_text(self):
        self.write({"type": "session_info", "name": "Old"})
        self.assertEqual(self.read(), "Old")
        with self.path.open("a") as stream:
            stream.write('{"type":"session_info","name":"New"}')
        self.assertIsNone(self.read())
        self.assertNotIn('"type":"session_info"', repr(self.reader._entries))
        with self.path.open("a") as stream:
            stream.write("\n")
        self.assertEqual(self.read(), "New")

    def test_tail_finds_latest_name_without_scanning_a_large_conversation(self):
        self.write({"type": "message", "message": {"role": "toolResult", "content": "x" * 10_000}},
                   {"type": "session_info", "name": "Tail name"})
        with mock.patch.object(names, "MAX_READ_BYTES", 256):
            self.assertEqual(self.read(), "Tail name")
        self.assertEqual(self.reader._entries[self.path.resolve()].offset, self.path.stat().st_size)

    def test_name_before_a_large_message_warms_incrementally_with_bounded_work(self):
        self.write({"type": "session_info", "name": "Real name"},
                   {"type": "message", "message": {"role": "toolResult", "content": "x" * 70_000}})
        with mock.patch.object(names, "MAX_READ_BYTES", 20_000):
            self.assertIsNone(self.read())
            self.assertIsNone(self.read())
            for _ in range(5):
                result = self.read()
                if result is not None:
                    break
            self.assertEqual(result, "Real name")
        self.assertLess(len(repr(self.reader._entries)), 1000)

    def test_replacement_truncation_and_same_size_rewrite_reset_identity(self):
        self.write({"type": "session_info", "name": "Alpha"})
        self.assertEqual(self.read(), "Alpha")
        self.write({"type": "session_info", "name": "Bravo"})
        self.assertEqual(self.read(), "Bravo")
        replacement = self.history_root / "replacement.jsonl"
        self.write({"type": "session_info", "name": "New file"}, path=replacement, session_id="new-id")
        replacement.replace(self.path)
        self.assertEqual(self.read(), "New file")
        self.write(session_id="untouched")
        self.assertIsNone(self.read())

    def test_oversized_name_metadata_clears_previous_name_and_large_messages_do_not(self):
        self.write({"type": "session_info", "name": "Keep this name"})
        self.assertEqual(self.read(), "Keep this name")
        self.append({"type": "message", "message": {"role": "toolResult", "content": "x" * 70_000}})
        self.assertEqual(self.read(), "Keep this name")
        self.append({"type": "session_info", "name": "x" * 70_000})
        self.assertIsNone(self.read())

    def test_cache_is_bounded_and_does_not_share_names_between_files(self):
        with mock.patch.object(names, "MAX_CACHED_FILES", 2):
            for index in range(4):
                p = self.history_root / f"{index}.jsonl"
                self.write({"type": "session_info", "name": f"Name {index}"}, path=p)
                self.assertEqual(self.read(p), f"Name {index}")
            self.assertEqual(len(self.reader._entries), 2)

    def test_only_fresh_exact_tmux_pid_descriptor_can_supply_the_name(self):
        self.write({"type": "session_info", "name": "Actual Pi title"})
        now = dt.datetime(2026, 10, 4, 16, 0, tzinfo=dt.timezone.utc)
        status_dir = self.root / "status"
        status_dir.mkdir()
        descriptor = {"version": 2, "pid": 111, "source": "pi-extension-local-session-status",
                      "lifecycle": "running", "sessionFile": str(self.path), "updatedAt": now.isoformat()}
        marker = status_dir / "111-active.json"
        marker.write_text(json.dumps(descriptor))
        tmux = subprocess.CompletedProcess([], 0, "jarvis-ios\t0\t111\n", "")
        with mock.patch.object(jarvisd, "PI_LOCAL_SESSIONS", status_dir), \
             mock.patch.object(jarvisd, "PI_SESSION_HISTORY_ROOT", self.history_root), \
             mock.patch.object(jarvisd, "_PI_SESSION_NAMES", self.reader), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=tmux) as run:
            states = jarvisd._mobile_pi_session_states(now=now)
            self.assertEqual(states[0], {"sessionID": 1, "lifecycle": "running", "active": True, "name": "Actual Pi title"})
            self.assertNotIn("name", states[1])
            run.assert_called_once()  # No additional subprocess or transport.
            descriptor['updatedAt'] = (now - dt.timedelta(seconds=61)).isoformat()
            marker.write_text(json.dumps(descriptor))
            with mock.patch.object(self.reader, "read", side_effect=AssertionError("stale file must not be inspected")):
                self.assertNotIn("name", jarvisd._mobile_pi_session_states(now=now)[0])

    def test_latest_descriptor_switch_never_leaks_the_previous_conversation_name(self):
        self.write({"type": "session_info", "name": "Previous conversation"})
        status_dir = self.root / "status"
        status_dir.mkdir()
        now = dt.datetime(2026, 10, 4, 16, 0, tzinfo=dt.timezone.utc)
        old = {"version": 2, "pid": 111, "source": "pi-extension-local-session-status", "lifecycle": "running",
               "sessionFile": str(self.path), "updatedAt": (now - dt.timedelta(seconds=1)).isoformat()}
        (status_dir / "111-old.json").write_text(json.dumps(old))
        new_path = self.history_root / "resumed.jsonl"
        self.write({"type": "session_info", "name": "Current conversation"}, path=new_path)
        (status_dir / "111-new.json").write_text(json.dumps(dict(old, sessionFile=str(new_path), updatedAt=now.isoformat())))
        tmux = subprocess.CompletedProcess([], 0, "jarvis-ios\t0\t111\n", "")
        with mock.patch.object(jarvisd, "PI_LOCAL_SESSIONS", status_dir), \
             mock.patch.object(jarvisd, "PI_SESSION_HISTORY_ROOT", self.history_root), \
             mock.patch.object(jarvisd, "_PI_SESSION_NAMES", self.reader), \
             mock.patch.object(jarvisd.subprocess, "run", return_value=tmux):
            self.assertEqual(jarvisd._mobile_pi_session_states(now=now)[0]["name"], "Current conversation")
            # Tied descriptors cannot establish which conversation is current.
            (status_dir / "111-old.json").write_text(json.dumps(dict(old, updatedAt=now.isoformat())))
            self.assertNotIn("name", jarvisd._mobile_pi_session_states(now=now)[0])
