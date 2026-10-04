"""Offline prompt parity checks; no model, microphone or speaker use."""
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock

import room_audio_server as server
import room_session10_service as supervisor


class RoomVoicePromptTests(unittest.TestCase):
    def test_supervisor_uses_normal_prompt_discovery_and_retains_history(self):
        history = Path('/fixture/retained conversation.jsonl')
        command = shlex.split(supervisor.pi_command(history, {
            'model': 'fixture/model', 'thinking': 'medium',
        }))
        self.assertEqual(command, [str(supervisor.ROOT / '.pi/scripts/pi-cli'), '--tui-mode', 'regular',
            '--session', str(history), '--model', 'fixture/model', '--thinking', 'medium'])
        self.assertNotIn('--append-system-prompt', command)
        self.assertNotIn('--system-prompt', command)
        self.assertNotIn('--no-context-files', command)
        self.assertNotIn('--no-extensions', command)
        self.assertNotIn('--new', command)
        self.assertEqual(supervisor.SESSION, '=jarvis-ios-10')
        self.assertEqual(supervisor.ROOT, server.PROJECT_ROOT)

    def test_standalone_prompt_reads_current_canonical_core_then_voice_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / '.pi/APPEND_SYSTEM.md'
            voice = root / 'voice/APPEND_SYSTEM.md'
            canonical.parent.mkdir()
            voice.parent.mkdir()
            canonical.write_text('Canonical core version one.')
            voice.write_text('Presentation-only overlay.')
            with mock.patch.object(server, 'PROJECT_ROOT', root), \
                 mock.patch.object(server, 'VOICE_ROOT', voice.parent):
                first = server.load_room_append_system_prompt()
                self.assertTrue(first.startswith('Canonical core version one.\n\nPresentation-only overlay.'))
                canonical.write_text('Canonical core version two.')
                second = server.load_room_append_system_prompt()
                self.assertTrue(second.startswith('Canonical core version two.\n\nPresentation-only overlay.'))
                self.assertNotIn('version one', second)
                self.assertNotIn('Raspberry Pi', second)

    def test_voice_source_has_no_separate_operational_policy(self):
        overlay = (server.VOICE_ROOT / 'APPEND_SYSTEM.md').read_text()
        self.assertIn('presentation only', overlay)
        self.assertIn('Only the confirmed final response is spoken', overlay)
        self.assertIn('essential safety information or truthful uncertainty', overlay)
        for stale in ('jarvis-cli', 'purifier-set', 'cast-spotify', 'everything you think'):
            self.assertNotIn(stale, overlay)


if __name__ == '__main__':
    unittest.main()
