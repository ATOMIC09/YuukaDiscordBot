"""
cogs/voice/player.py
Audio playback cog.

Responsibilities:
  - Managing one VoiceClient per guild (stored in self._voice_clients dict)
  - Maintaining a per-guild audio queue (collections.deque)
  - Playing audio via discord.FFmpegPCMAudio + discord.PCMVolumeTransformer
  - Streaming from URLs using yt-dlp to extract stream URLs

Slash Commands (to be implemented):
  /join    — Join the caller's voice channel
  /leave   — Disconnect from voice channel and clear queue
  /play    — Play audio from a URL or search query (uses yt-dlp)
  /pause   — Pause current playback
  /resume  — Resume paused playback
  /stop    — Stop playback and clear queue
  /skip    — Skip current track
  /queue   — Show the current audio queue
  /volume  — Set playback volume (0–100)
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger


class PlayerCog(commands.Cog, name="Voice Player"):
    """Audio playback — join, play, queue, and control audio in voice channels."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # TODO: Add per-guild voice client and queue state management

    # ------------------------------------------------------------------
    # TODO: Implement slash commands below
    # ------------------------------------------------------------------

    # @discord.slash_command(name="join", description="Join your voice channel")
    # async def join(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="leave", description="Leave the voice channel")
    # async def leave(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="play", description="Play audio from a URL or search query")
    # async def play(self, ctx: discord.ApplicationContext, query: str) -> None: ...

    # @discord.slash_command(name="pause", description="Pause the current track")
    # async def pause(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="resume", description="Resume paused playback")
    # async def resume(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="stop", description="Stop playback and clear the queue")
    # async def stop(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="skip", description="Skip the current track")
    # async def skip(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="queue", description="Show the audio queue")
    # async def queue(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="volume", description="Set playback volume (0-100)")
    # async def volume(self, ctx: discord.ApplicationContext, level: int) -> None: ...


def setup(bot: discord.Bot) -> None:
    bot.add_cog(PlayerCog(bot))
