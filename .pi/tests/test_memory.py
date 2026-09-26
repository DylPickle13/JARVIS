"""Isolated behavioral tests; never open the production memory DB or .env."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("jarvis_memory", Path(__file__).resolve().parents[1] / "memory/memory.py")
memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "memory.sqlite"
        self.conn = memory.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def run_command(self, *argv):
        args = memory.build_parser().parse_args(list(argv))
        return args.func(self.conn, args)

    def remember(self, text, *argv):
        return self.run_command("remember", "--text", text, *argv)["memory"]

    def search(self, query, *argv):
        return self.run_command("search", query, *argv)["results"]

    def test_supersession_excluded_by_default_and_history_retained(self):
        old = self.remember("Server release alpha")
        new = self.remember("Server release beta", "--supersedes", old["id"])
        self.assertEqual([r["id"] for r in self.search("Server")], [new["id"]])
        self.assertEqual(len(self.search("Server", "--include-superseded")), 2)
        historical = memory.require_memory(self.conn, old["id"])
        self.assertEqual(historical["status"], "superseded")
        self.assertEqual(historical["superseded_by"], new["id"])
        self.assertEqual(historical["text"], old["text"])
        status = self.run_command("status")
        self.assertEqual(status["active_memories"], 1)
        self.assertEqual(status["superseded_memories"], 1)
        self.assertEqual(sum(status["by_kind"].values()), 1)

    def test_invalid_supersession_rolls_back_everything(self):
        old = self.remember("Original knowledge")
        before = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        with self.assertRaises(memory.MemoryError):
            self.remember("Replacement", "--supersedes", old["id"], "--supersedes", "missing")
        self.assertEqual(memory.require_memory(self.conn, old["id"])["status"], "active")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], before)

    def test_already_superseded_cannot_be_replaced_again(self):
        old = self.remember("Old fact")
        self.remember("Current fact", "--supersedes", old["id"])
        with self.assertRaises(memory.MemoryError):
            self.remember("Conflicting fact", "--supersedes", old["id"])

    def test_duplicate_is_idempotent_and_project_aware(self):
        old = self.remember("Stable fact", "--project", "one", "--topic", "state")
        duplicate = self.remember("  stable FACT  ", "--project", "one", "--topic", "state")
        self.assertEqual(old["id"], duplicate["id"])
        other = self.remember("Stable fact", "--project", "two", "--topic", "state")
        self.assertNotEqual(old["id"], other["id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)

    def test_all_term_results_precede_partial_hits(self):
        partial = self.remember("xylophone")
        full = self.remember("The xylophone deployment procedure is documented here. " + "deployment " * 30)
        result = self.search("what is our xylophone deployment")
        self.assertEqual(result[0]["id"], full["id"])
        self.assertIn(partial["id"], [r["id"] for r in result])
        self.assertEqual(len(self.search("xylophone deployment", "--limit", "1")), 1)

    def test_tag_project_topic_filters_combine(self):
        wanted = self.remember("Host setup", "--project", "music", "--topic", "routing", "--tags", "reaper,stable")
        self.remember("Host setup elsewhere", "--project", "app", "--topic", "routing", "--tags", "reaper,stable")
        self.remember("Host incomplete tags", "--project", "music", "--topic", "routing", "--tags", "reaper")
        rows = self.search("Host", "--project", "music", "--topic", "routing", "--tags", "reaper,stable")
        self.assertEqual([r["id"] for r in rows], [wanted["id"]])
        rows = self.run_command("list", "--project", "app")["results"]
        self.assertEqual(len(rows), 1)

    def test_fts_syntax_and_empty_meaningful_query(self):
        self.remember("host alpha-beta version v1")
        self.assertEqual(self.search("!!!"), [])
        self.assertEqual(self.search("what is the"), [])
        for query in ['" OR *', 'host NEAR("alpha")', "alpha-beta", "x", "v1", "'; DROP TABLE memories; --"]:
            self.search(query)
        self.assertEqual(self.run_command("status")["active_memories"], 1)

    def test_retrieval_is_not_usage_and_listing_does_not_touch_metrics(self):
        entry = self.remember("Persistent preference")
        self.run_command("list")
        row = memory.require_memory(self.conn, entry["id"])
        self.assertIsNone(row["last_retrieved_at"])
        self.search("preference")
        row = memory.require_memory(self.conn, entry["id"])
        self.assertIsNotNone(row["last_retrieved_at"])
        self.assertIsNone(row["last_used_at"])

    def test_source_update_and_verification_invalidation(self):
        entry = self.remember("Verified fact", "--source", "docs/setup.md", "--verified-at", "2026-09-19")
        updated = self.run_command("update", "--id", entry["id"], "--source", "docs/current.md", "--project", "app")["memory"]
        self.assertEqual(updated["source"], "docs/current.md")
        self.assertEqual(updated["verified_at"], "2026-09-19")
        updated = self.run_command("update", "--id", entry["id"], "--text", "Changed fact")["memory"]
        self.assertIsNone(updated["verified_at"])
        self.assertEqual(self.search("Changed")[0]["id"], entry["id"])
        self.assertEqual(self.search("Verified"), [])

    def test_confidence_rejects_nan_infinity_and_out_of_range(self):
        for value in ("nan", "inf", "-0.1", "1.1"):
            with self.subTest(value=value), self.assertRaises(memory.MemoryError):
                self.remember("Fact", "--confidence", value)
        entry = self.remember("Valid")
        with self.assertRaises(memory.MemoryError):
            self.run_command("update", "--id", entry["id"], "--confidence", "nan")

    def test_secrets_rejected_in_all_free_text_storage_fields(self):
        secret = "ghp_" + "x" * 25
        for field in ("text", "source", "tags", "cwd", "context-id", "project", "topic"):
            args = ["remember", "--text", "Safe", "--" + field, secret]
            with self.subTest(field=field), self.assertRaises(memory.MemoryError):
                self.run_command(*args)
        entry = self.remember("Safe")
        with self.assertRaises(memory.MemoryError):
            self.run_command("update", "--id", entry["id"], "--source", secret)

    def test_verification_date_validation(self):
        for value in ("yesterday", "2026-02-30", "2026-1-1", "2026-01-01T00:00:00Z"):
            with self.subTest(value=value), self.assertRaises(memory.MemoryError):
                self.remember("Fact", "--verified-at", value)

    def test_forget_purges_text_events_and_does_not_reactivate_history(self):
        old = self.remember("Old routing")
        new = self.remember("UniqueReplacementCanary", "--supersedes", old["id"])
        self.run_command("forget", "--id", new["id"])
        self.assertEqual(self.search("routing"), [])
        self.assertIsNone(memory.require_memory(self.conn, old["id"])["superseded_by"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events WHERE memory_id=?", (new["id"],)).fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memories_fts WHERE id=?", (new["id"],)).fetchone()[0], 0)
        self.assertNotIn(b"UniqueReplacementCanary", self.path.read_bytes())

    def test_permissions(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        for suffix in memory.SQLITE_SIDECAR_SUFFIXES:
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists():
                self.assertEqual(os.stat(sidecar).st_mode & 0o777, 0o600)

    def test_schema_v3_migration_preserves_existing_fields(self):
        entry = self.remember("Legacy content", "--tags", "legacy")
        self.conn.execute("UPDATE memories SET last_used_at='2026-01-01T00:00:00Z' WHERE id=?", (entry["id"],))
        self.conn.execute("DROP INDEX idx_memories_project_topic")
        for column in ("status", "superseded_by", "project", "topic", "verified_at", "last_retrieved_at"):
            self.conn.execute(f"ALTER TABLE memories DROP COLUMN {column}")
        self.conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
        self.conn.commit()
        before = dict(self.conn.execute("SELECT * FROM memories").fetchone())
        events = list(self.conn.execute("SELECT * FROM events"))
        memory.init_db(self.conn)
        memory.init_db(self.conn)  # idempotent migration
        after = dict(self.conn.execute("SELECT * FROM memories").fetchone())
        self.assertEqual(before, {key: after[key] for key in before})
        self.assertEqual(after["status"], "active")
        self.assertIsNone(after["verified_at"])
        self.assertIsNone(after["last_retrieved_at"])
        self.assertEqual(events, list(self.conn.execute("SELECT * FROM events")))
        self.assertEqual(self.search("Legacy")[0]["id"], entry["id"])


if __name__ == "__main__":
    unittest.main()
