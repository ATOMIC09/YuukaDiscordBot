"""
cogs/voice/tts.py
Text-to-speech cog — converts text to audio and plays it in a voice channel.

The actual TTS engine is not yet decided. This is a stub with the intended
interface. When implementing, choose one of:
  - edge-tts    : Free, Microsoft Edge TTS voices (`uv add edge-tts`)
  - openai TTS  : High quality, requires OpenAI API key
  - gTTS        : Google TTS, free but lower quality
  - pyttsx3     : Offline, no API key needed

Slash Commands (to be implemented):
  /tts speak <text>   — Speak text in the caller's voice channel
  /tts voice <name>   — Set the TTS voice/model
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger


class TTSCog(commands.Cog, name="TTS"):
    """Text-to-speech — convert text to audio and play it in a voice channel."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # TODO: TTS ENGINE
    # Choose and implement a TTS engine. Recommended: edge-tts
    # Example:
    #   import edge_tts
    #   communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
    #   await communicate.save("output.mp3")
    #   source = discord.FFmpegPCMAudio("output.mp3")
    #   voice_client.play(source)
    # ------------------------------------------------------------------

    # tts = discord.SlashCommandGroup("tts", "Text-to-speech commands")

    # @tts.command(name="speak", description="Speak text in your voice channel")
    # async def tts_speak(self, ctx: discord.ApplicationContext, text: str) -> None: ...

    # @tts.command(name="voice", description="Set the TTS voice")
    # async def tts_voice(self, ctx: discord.ApplicationContext, voice: str) -> None: ...


def setup(bot: discord.Bot) -> None:
    bot.add_cog(TTSCog(bot))
