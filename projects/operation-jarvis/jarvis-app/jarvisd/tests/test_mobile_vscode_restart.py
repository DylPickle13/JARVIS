import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "jarvis-mobile-vscode-restart.py"
spec = importlib.util.spec_from_file_location("jarvis_mobile_vscode_restart", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
restart = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = restart
spec.loader.exec_module(restart)


class MobileVscodeRestartTests(unittest.TestCase):
    def fixture(self, *, lifecycle_by_slot=None, now=None):
        root = Path(self.tempdir.name) / "JARVIS"
        (root / ".pi" / "runtime" / "local-pi-sessions").mkdir(parents=True)
        (root / "projects").mkdir()
        home = Path(self.tempdir.name) / "home"
        session_dir = restart.session_directory(root, home)
        session_dir.mkdir(parents=True)
        status_dir = root / ".pi" / "runtime" / "local-pi-sessions"
        now = now or dt.datetime(2026, 9, 4, 18, 0, tzinfo=dt.timezone.utc)
        lifecycle_by_slot = lifecycle_by_slot or {}
        pane_lines = []
        session_files = {}
        for slot, name in restart.SLOT_NAMES.items():
            pid = 10_000 + slot
            pane_id = f"%{slot - 1}"
            session_file = session_dir / f"2026-09-04T18-00-00-000Z_slot{slot}.jsonl"
            session_file.write_text("{\"type\":\"session\"}\n", encoding="utf-8")
            session_files[slot] = session_file
            payload = {
                "version": 2,
                "id": f"local:{pid}",
                "pid": pid,
                "lifecycle": lifecycle_by_slot.get(slot, "idle"),
                "source": restart.STATUS_SOURCE,
                "reason": "test",
                "cwd": str(root),
                "sessionFile": str(session_file),
                "updatedAt": now.isoformat().replace("+00:00", "Z"),
            }
            (status_dir / f"{pid}-session.json").write_text(json.dumps(payload), encoding="utf-8")
            pane_lines.append(f"{name}\t0\t0\t{pane_id}\t0\t{pid}\t80\t24")
        return root, status_dir, session_dir, now, "\n".join(pane_lines), session_files

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_snapshots_bind_fixed_panes_to_their_exact_session_files(self):
        root, status_dir, session_dir, now, pane_output, session_files = self.fixture()
        snapshots = restart.snapshots_from_panes(
            pane_output,
            project_root=root,
            status_dir=status_dir,
            expected_session_dir=session_dir,
            now=now,
        )

        self.assertEqual([item.slot for item in snapshots], [1, 2, 3, 4, 5, 6])
        self.assertEqual([item.pane_id for item in snapshots], ["%0", "%1", "%2", "%3", "%4", "%5"])
        self.assertEqual([item.session_file for item in snapshots], [session_files[index] for index in range(1, 7)])
        self.assertTrue(all(item.lifecycle == "idle" for item in snapshots))

    def test_any_non_idle_slot_refuses_the_whole_restart(self):
        root, status_dir, session_dir, now, pane_output, _ = self.fixture(lifecycle_by_slot={3: "running"})

        with self.assertRaisesRegex(restart.RestartError, r"slot 3 .*running"):
            restart.snapshots_from_panes(
                pane_output,
                project_root=root,
                status_dir=status_dir,
                expected_session_dir=session_dir,
                now=now,
            )

    def test_stale_status_refuses_without_guessing_a_session(self):
        stale_now = dt.datetime(2026, 9, 4, 17, 59, 40, tzinfo=dt.timezone.utc)
        root, status_dir, session_dir, now, pane_output, _ = self.fixture(now=stale_now)
        current = now + dt.timedelta(seconds=11)

        with self.assertRaisesRegex(restart.RestartError, "stale"):
            restart.snapshots_from_panes(
                pane_output,
                project_root=root,
                status_dir=status_dir,
                expected_session_dir=session_dir,
                now=current,
            )

    def test_empty_current_session_path_is_valid(self):
        root, status_dir, session_dir, now, pane_output, session_files = self.fixture()
        session_files[5].unlink()

        snapshots = restart.snapshots_from_panes(
            pane_output,
            project_root=root,
            status_dir=status_dir,
            expected_session_dir=session_dir,
            now=now,
        )
        self.assertEqual(snapshots[4].session_file, session_files[5])
        self.assertFalse(snapshots[4].session_file.exists())

    def test_session_path_must_stay_inside_the_fixed_project_directory(self):
        root, status_dir, session_dir, now, pane_output, _ = self.fixture()
        outside = Path(self.tempdir.name) / "outside.jsonl"
        outside.write_text("not selected", encoding="utf-8")
        status_path = status_dir / "10001-session.json"
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        payload["sessionFile"] = str(outside)
        status_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(restart.RestartError, "outside"):
            restart.snapshots_from_panes(
                pane_output,
                project_root=root,
                status_dir=status_dir,
                expected_session_dir=session_dir,
                now=now,
            )

    def test_newest_descriptor_wins_for_a_process_that_switched_sessions(self):
        root, status_dir, session_dir, now, pane_output, session_files = self.fixture()
        old_path = status_dir / "10001-old.json"
        newest_path = status_dir / "10001-new.json"
        old_payload = json.loads((status_dir / "10001-session.json").read_text(encoding="utf-8"))
        old_payload["updatedAt"] = (now - dt.timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
        old_path.write_text(json.dumps(old_payload), encoding="utf-8")
        new_session = session_dir / "2026-09-04T18-01-00-000Z_new.jsonl"
        new_session.write_text("{\"type\":\"session\"}\n", encoding="utf-8")
        newest_payload = dict(old_payload)
        newest_payload["updatedAt"] = now.isoformat().replace("+00:00", "Z")
        newest_payload["sessionFile"] = str(new_session)
        newest_path.write_text(json.dumps(newest_payload), encoding="utf-8")
        (status_dir / "10001-session.json").unlink()

        snapshots = restart.snapshots_from_panes(
            pane_output,
            project_root=root,
            status_dir=status_dir,
            expected_session_dir=session_dir,
            now=now,
        )
        self.assertEqual(snapshots[0].session_file, new_session)
        self.assertNotEqual(snapshots[0].session_file, session_files[0 + 1])

    def test_respawn_command_has_fixed_identity_and_no_tmux_server_kill(self):
        root, status_dir, session_dir, now, pane_output, session_files = self.fixture()
        snapshots = restart.snapshots_from_panes(
            pane_output,
            project_root=root,
            status_dir=status_dir,
            expected_session_dir=session_dir,
            now=now,
        )
        arguments = restart.respawn_arguments(snapshots[0], root)

        self.assertEqual(arguments[:6], ["respawn-pane", "-k", "-c", str(root), "-t", "=jarvis-ios:0.0"])
        self.assertIn("--tui-mode regular", arguments[6])
        self.assertIn(f"--session {session_files[0 + 1]}", arguments[6])
        self.assertIn("-u SSH_CONNECTION", arguments[6])
        self.assertNotIn("kill-session", arguments[6])
        self.assertNotIn("kill-server", arguments[6])

    def test_fixed_pane_parser_rejects_missing_or_extra_panes(self):
        with self.assertRaisesRegex(restart.RestartError, "missing or ambiguous"):
            restart.parse_fixed_panes("jarvis-ios\t0\t0\t%0\t0\t1001\t80\t24")

        rows = []
        for slot, name in restart.SLOT_NAMES.items():
            rows.append(f"{name}\t0\t0\t%{slot - 1}\t0\t{1000 + slot}\t80\t24")
        rows.append("jarvis-ios\t0\t1\t%9\t0\t1099\t80\t24")
        with self.assertRaisesRegex(restart.RestartError, "missing or ambiguous"):
            restart.parse_fixed_panes("\n".join(rows))


if __name__ == "__main__":
    unittest.main()
