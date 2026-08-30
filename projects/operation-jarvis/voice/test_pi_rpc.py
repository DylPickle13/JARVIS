from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pi_rpc


class PiRpcTests(unittest.TestCase):
    def test_forced_rpc_arguments_are_normalized(self) -> None:
        command = pi_rpc._strip_forced_rpc_args([
            "pi", "--model", "old/model", "--thinking=low", "--no-session", "--mode", "rpc"
        ])
        self.assertEqual(command, ["pi", "--mode", "rpc"])

    def test_session_uses_neutral_local_context(self) -> None:
        session = pi_rpc.PiRpcSession(context_id="room-audio", context_name="Room Audio")
        self.assertEqual(session.context_id, "room-audio")
        self.assertEqual(session.context_name, "Room Audio")
        self.assertFalse(hasattr(session, "channel_id"))
        session.stop()

    def test_client_uses_stable_neutral_command_ids(self) -> None:
        client = pi_rpc.PiRpcClient()
        commands: list[dict] = []
        client._send_command = commands.append  # type: ignore[method-assign]
        client.send_prompt("hello")
        client.send_steer("change")
        client.send_get_state()
        client.send_abort()
        self.assertEqual(
            [command["id"] for command in commands],
            ["jarvis-prompt", "jarvis-steer", "jarvis-get-state", "jarvis-abort"],
        )

    def test_retrying_agent_end_does_not_finish_prompt(self) -> None:
        session = pi_rpc.PiRpcSession()
        done = __import__("threading").Event()
        session._active_command = "prompt"
        session._active_done_event = done
        session._handle_event({"type": "agent_end", "willRetry": True})
        self.assertFalse(done.is_set())
        session._handle_event({"type": "agent_end", "willRetry": False, "messages": []})
        self.assertTrue(done.is_set())
        session.stop()


if __name__ == "__main__":
    unittest.main()
