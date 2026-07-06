"""
cogs/voice/listener.py
Voice receive cog — listens to users speaking in a voice channel.

Uses pycord's Sink API (discord.sinks) to capture raw PCM audio per user.

How it works:
  1. Bot joins a voice channel (or reuses an existing VoiceClient)
  2. `voice_client.start_recording(sink, callback)` begins capturing audio
  3. When `voice_client.stop_recording()` is called, the callback fires
  4. `sink.audio_data` is a dict[user_id, AudioData] with raw PCM bytes

AI Pipeline Hook:
  The callback (`_on_recording_done`) is where AI processing plugs in.
  Each user's audio data should be forwarded to an STT / hotword / AI model.
  See the TODO comment below.

Slash Commands (to be implemented):
  /listen start  — Start recording audio from the voice channel
  /listen stop   — Stop recording and process captured audio
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger


class ListenerCog(commands.Cog, name="Voice Listener"):
    """Voice receive — listen to users speaking and pipe audio to the AI pipeline."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self._active_sinks: dict[int, discord.sinks.Sink] = {}  # guild_id → active sink

    # ------------------------------------------------------------------
    # Recording callback
    # ------------------------------------------------------------------

    async def _on_recording_done(
        self,
        sink: discord.sinks.Sink,
        channel: discord.TextChannel,
        *args,
    ) -> None:
        """
        Called automatically by pycord when stop_recording() is invoked.
        `sink.audio_data` is a dict of {user_id: AudioData}.
        AudioData.file is a BytesIO object containing raw PCM audio.
        """
        logger.info(f"Recording finished in guild {channel.guild.id}. Processing audio...")

        for user_id, audio in sink.audio_data.items():
            user = self.bot.get_user(user_id)
            logger.debug(f"Received audio from user: {user} ({user_id})")

            # TODO: AI PIPELINE HOOK
            # Forward `audio.file` (BytesIO, raw PCM) to your AI pipeline here.
            # Example integrations:
            #   - Speech-to-text (Whisper, Google STT, Azure STT)
            #   - Hotword detection
            #   - Voice activity detection + AI response
            # audio.file.seek(0)
            # await ai_pipeline.process(user_id, audio.file)

    # ------------------------------------------------------------------
    # TODO: Implement slash commands below
    # ------------------------------------------------------------------

    # listen = discord.SlashCommandGroup("listen", "Voice listening commands")

    # @listen.command(name="start", description="Start listening to the voice channel")
    # async def listen_start(self, ctx: discord.ApplicationContext) -> None: ...

    # @listen.command(name="stop", description="Stop listening and process audio")
    # async def listen_stop(self, ctx: discord.ApplicationContext) -> None: ...


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ListenerCog(bot))
