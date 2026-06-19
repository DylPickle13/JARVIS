from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import discord

import config

config.load_project_env(config.DOTENV_PATH)
LOGGER = config.get_logger("operation_jarvis.voice.discord_bot")

# Import after loading .env because discord_voice reads voice settings at module import time.
import discord_voice


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()


class VoiceControlDiscordBot:
    """Standalone Operation JARVIS Discord voice bot.

    This runner keeps the live Discord voice ASR -> LLM -> TTS stack testable
    outside the main JARVIS bot. It only listens for voice-state changes, joins the
    configured voice channel, and delegates all voice processing to discord_voice.py.
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True

        self.client = discord.Client(intents=intents)
        self._voice_manager = discord_voice.JarvisVoiceManager(self.client)
        self._register_events()

    def _register_events(self) -> None:
        @self.client.event
        async def on_ready() -> None:
            LOGGER.info("Operation JARVIS voice bot connected as %s", self.client.user)
            await self._voice_manager.sync_all_voice_channels()

        @self.client.event
        async def on_voice_state_update(
            member: discord.Member,
            before: discord.VoiceState,
            after: discord.VoiceState,
        ) -> None:
            self._voice_manager.handle_voice_state_update(member, before, after)

    def run(self) -> None:
        self.client.run(DISCORD_BOT_TOKEN, log_level=logging.WARNING)


def main() -> int:
    if not DISCORD_BOT_TOKEN:
        LOGGER.error("Missing DISCORD_BOT_TOKEN environment variable.")
        return 1

    bot = VoiceControlDiscordBot()
    bot.run()
    return 0


if __name__ == "__main__":
    LOGGER.info("Starting standalone Operation JARVIS voice bot...")
    raise SystemExit(main())
