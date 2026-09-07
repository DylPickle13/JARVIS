"""Pure fixture tests: no live sessions, tools, prompts or service restarts."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("jarvisd_new_status_test", Path(__file__).resolve().parents[1] / "jarvisd.py")
jarvisd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jarvisd)


class NewSessionStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.history_root = self.root / "sessions"
        self.history_root.mkdir()
        self.history = self.history_root / "exact.jsonl"
        self.status_dir = self.root / "status"
        self.status_dir.mkdir()
        self.now = dt.datetime(2026, 9, 7, 23, 0, tzinfo=dt.timezone.utc)
        self.patchers = [
            mock.patch.object(jarvisd, "PI_LOCAL_SESSIONS", self.status_dir),
            mock.patch.object(jarvisd, "PI_SESSION_HISTORY_ROOT", self.history_root),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def write_history(self, entries=()):
        rows = [{"type": "session", "version": 3, "id": "fixture"}, *entries]
        self.history.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def status(self, lifecycle="idle", **extra):
        payload = {
            "version": 2, "pid": 111, "source": "pi-extension-local-session-status",
            "lifecycle": lifecycle, "sessionFile": str(self.history), "updatedAt": self.now.isoformat(),
        }
        payload.update(extra)
        (self.status_dir / "111-session.json").write_text(json.dumps(payload))

    def lifecycle(self):
        return jarvisd._fresh_local_pi_lifecycle(111, now=self.now)

    def test_legacy_metadata_only_idle_becomes_new_without_reloading_pi(self):
        self.write_history([{"type": "model_change"}, {"type": "custom"}, {"type": "session_info"}])
        before = self.history.read_bytes()
        self.status()
        self.assertEqual(self.lifecycle(), "new")
        self.assertEqual(self.history.read_bytes(), before)
        self.assertEqual(jarvisd._mobile_pi_state(9, "new"), {"sessionID": 9, "lifecycle": "new", "active": False})

    def test_prompt_response_and_summarized_history_are_idle_not_new(self):
        for entry in (
            {"type": "message", "message": {"role": "user", "content": ""}},
            {"type": "message", "message": {"role": "assistant", "stopReason": "aborted"}},
            {"type": "compaction"}, {"type": "branch_summary"},
        ):
            with self.subTest(entry=entry):
                self.write_history([entry])
                self.status()
                self.assertEqual(self.lifecycle(), "idle")

    def test_appended_first_prompt_changes_new_to_idle_without_sticky_cache(self):
        self.write_history()
        self.status()
        self.assertEqual(self.lifecycle(), "new")
        with self.history.open("a") as history:
            history.write(json.dumps({"type": "message", "message": {"role": "user"}}) + "\n")
        self.assertEqual(self.lifecycle(), "idle")

    def test_explicit_in_memory_evidence_avoids_disk_even_for_ephemeral_sessions(self):
        with mock.patch.object(jarvisd, "_pi_history_has_conversation", side_effect=AssertionError("unexpected disk probe")):
            for lifecycle, has_conversation, expected in (("new", False, "new"), ("idle", True, "idle"), ("idle", False, "new"), ("new", True, "idle")):
                self.status(lifecycle, hasConversation=has_conversation, sessionFile="")
                self.assertEqual(self.lifecycle(), expected)

    def test_missing_malformed_partial_and_empty_history_do_not_manufacture_new(self):
        self.status()
        self.assertEqual(self.lifecycle(), "unknown")
        for content in ("", "not json\n", "{}\n", "[]\n", '{"type":"session","version":3}',
                        '{"type":"session","version":3}\n{"type":"message"}\n',
                        '{"type":"session","version":3}\n{"type":"future-entry"}\n'):
            with self.subTest(content=content):
                self.history.write_text(content)
                self.assertEqual(self.lifecycle(), "unknown")

    def test_legacy_v1_idle_uses_exact_history_too(self):
        self.write_history()
        self.status(version=1, active=False)
        self.assertEqual(self.lifecycle(), "new")
        self.status(version=1, active=True)
        self.assertEqual(self.lifecycle(), "running")

    def test_legacy_waiting_is_running_and_never_a_public_mode(self):
        self.status("waiting")
        self.assertEqual(self.lifecycle(), "running")
        self.assertNotIn("waiting", jarvisd.MOBILE_PI_PUBLIC_LIFECYCLES)

    def test_busy_and_stale_evidence_never_become_new(self):
        self.write_history()
        for lifecycle in ("running", "compacting", "unknown"):
            self.status(lifecycle)
            self.assertEqual(self.lifecycle(), lifecycle)
        self.status("new", hasConversation=False,
                    updatedAt=(self.now - dt.timedelta(seconds=61)).isoformat())
        self.assertIsNone(self.lifecycle())
        self.status("new", hasConversation=False, pid=222)
        self.assertIsNone(self.lifecycle())

    def test_newest_pid_descriptor_is_selected_before_reading_its_exact_history(self):
        self.write_history([{"type": "message", "message": {"role": "user"}}])
        self.status(updatedAt=(self.now - dt.timedelta(seconds=1)).isoformat())
        old_status = self.status_dir / "111-session.json"
        old_status.rename(self.status_dir / "111-old.json")
        self.history = self.history_root / "new-session.jsonl"
        self.write_history()
        self.status()
        self.assertEqual(self.lifecycle(), "new")

    def test_history_scope_symlinks_and_limits_fail_closed(self):
        self.write_history()
        self.assertIsNone(jarvisd._pi_history_has_conversation("relative.jsonl"))
        self.assertIsNone(jarvisd._pi_history_has_conversation(str(self.history_root)))
        outside = self.root / "outside.jsonl"
        outside.write_bytes(self.history.read_bytes())
        self.assertIsNone(jarvisd._pi_history_has_conversation(str(outside)))
        link = self.history_root / "link.jsonl"
        link.symlink_to(self.history)
        self.assertIsNone(jarvisd._pi_history_has_conversation(str(link)))
        with mock.patch.object(jarvisd, "MAX_PI_HISTORY_PROBE_BYTES", 10):
            self.assertIsNone(jarvisd._pi_history_has_conversation(str(self.history)))
        self.write_history([{"type": "model_change"}] * 4)
        with mock.patch.object(jarvisd, "MAX_PI_HISTORY_PROBE_LINES", 2):
            self.assertIsNone(jarvisd._pi_history_has_conversation(str(self.history)))

    def test_large_history_stops_at_first_positive_conversation_evidence(self):
        self.write_history([{"type": "message", "message": {"role": "user"}}])
        with self.history.open("a") as history:
            history.write("x" * (jarvisd.MAX_PI_HISTORY_PROBE_BYTES + 1))
        self.assertTrue(jarvisd._pi_history_has_conversation(str(self.history)))

    def test_new_is_inactive_in_aggregate_counts(self):
        self.status("new", hasConversation=False)
        with mock.patch.object(jarvisd, "_mobile_pi_session_states", return_value=[]), \
             mock.patch.object(jarvisd, "PI_RPC_SESSIONS", self.root / "missing"):
            result = jarvisd._pi_sessions()
        self.assertEqual(result["localTotal"], 1)
        self.assertEqual(result["localActive"], 0)
