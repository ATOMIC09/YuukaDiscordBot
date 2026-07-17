"""
cogs/voice/transcribe.py
Speech-to-Text provider using Typhoon ASR Real-Time.

Model: typhoon-ai/typhoon-asr-realtime (FastConformer-Transducer, 114M params)
Optimized for Thai language and CPU-first inference.

Usage
-----
Call `load_model()` once at bot startup (or let it lazy-load on first transcription).
Then call `transcribe_pcm(pcm_bytes, sample_rate, user_display)` from listener.py.

Architecture
------------
- Model is loaded once and reused (singleton pattern via module-level variable).
- Inference runs in a thread pool executor to avoid blocking the asyncio event loop.
- Audio from WaveSink is 16-bit stereo PCM at 48kHz; we write it to a temporary
  WAV file which the typhoon-asr package reads and resamples internally to 16kHz mono.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import error_embed, info_embed, success_embed, warning_embed

if TYPE_CHECKING:
    pass

from utils.stt import _pcm_to_wav, load_model, transcribe_wav_bytes


class RealtimeWaveSink(discord.sinks.WaveSink):
    """A custom sink that monitors for silence and triggers transcription."""
    
    def __init__(self, bot: discord.Bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot
        self.last_sizes: dict[int, int] = {}
        self.silence_time: dict[int, float] = {}
        self.monitor_task = asyncio.create_task(self._monitor())

    async def _monitor(self):
        while True:
            await asyncio.sleep(0.3)
            now = time.time()
            
            try:
                users = list(self.audio_data.keys())
            except RuntimeError:
                continue

            for user_id in users:
                audio_data = self.audio_data.get(user_id)
                if not audio_data:
                    continue
                
                current_size = audio_data.file.tell()
                last_size = self.last_sizes.get(user_id, 0)
                
                if current_size > last_size:
                    self.last_sizes[user_id] = current_size
                    self.silence_time[user_id] = now
                elif current_size > 0:
                    last_speak = self.silence_time.get(user_id, now)
                    if now - last_speak >= 0.5:
                        await self._process_and_clear(user_id)

    async def _process_and_clear(self, user_id: int):
        # Remove from tracking
        self.last_sizes.pop(user_id, None)
        self.silence_time.pop(user_id, None)
        
        # Pop the audio data to start fresh on next speech packet
        audio_data = self.audio_data.pop(user_id, None)
        if not audio_data:
            return
            
        audio_data.file.seek(0)
        raw_pcm = audio_data.file.read()
        byte_count = len(raw_pcm)
        
        if byte_count < 1024:
            return
            
        wav_buf = _pcm_to_wav(raw_pcm)
        user = self.bot.get_user(user_id)
        display = str(user) if user else f"Unknown ({user_id})"
        
        # Trigger realtime STT
        transcript = await transcribe_wav_bytes(wav_buf, display)
        if transcript:
            channel = getattr(self, "_text_channel", None)
            if channel:
                await channel.send(f"🎙️ **{display}**: {transcript}")

    def cleanup(self):
        super().cleanup()
        if hasattr(self, "monitor_task") and not self.monitor_task.done():
            self.monitor_task.cancel()


class STTCog(commands.Cog, name="Realtime STT"):
    """Voice receive — listen to users speaking and transcribe realtime."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self._active_sinks: dict[int, RealtimeWaveSink] = {}

    async def _on_recording_done(self, exception: Exception | None, /) -> None:
        """Called by pycord when stop_recording() is invoked."""
        active_sink: RealtimeWaveSink | None = None
        channel: discord.TextChannel | None = None
        found_guild_id: int | None = None

        for guild_id, sink in list(self._active_sinks.items()):
            ch = getattr(sink, "_text_channel", None)
            if ch is not None:
                active_sink = sink
                channel = ch
                found_guild_id = guild_id
                break

        if active_sink is None or channel is None or found_guild_id is None:
            logger.debug("_on_recording_done fired but no active sink found")
            return

        guild_id = found_guild_id
        
        self._active_sinks.pop(guild_id, None)
        logger.info(f"Realtime recording finished in guild {guild_id}.")

        if exception:
            logger.error(f"Recording error in guild {guild_id}: {exception!r}")

        # Send summary embed to Discord
        embed = success_embed(
            "Transcription Stopped",
            "Realtime STT session stopped. Check the terminal for transcripts.",
        )
        await channel.send(embed=embed)

    transcribe = discord.SlashCommandGroup("transcribe", "Realtime transcription commands")

    @transcribe.command(name="start", description="Join your voice channel and start realtime transcription")
    async def transcribe_start(self, ctx: discord.ApplicationContext) -> None:
        """Start recording audio from the invoker's voice channel and transcribe it."""
        await ctx.defer()

        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.respond(embed=error_embed(
                "Not in a Voice Channel",
                "You must be in a voice channel for me to start transcribing.",
            ))
            return

        guild_id = ctx.guild.id

        if guild_id in self._active_sinks:
            await ctx.respond(embed=warning_embed(
                "Already Transcribing",
                "I'm already transcribing in this server. Use `/transcribe stop` first.",
            ))
            return

        voice_channel = ctx.author.voice.channel
        voice_client: discord.VoiceClient | None = ctx.guild.voice_client

        if voice_client is None:
            try:
                voice_client = await voice_channel.connect()
            except discord.ClientException as exc:
                logger.error(f"Failed to connect to voice channel: {exc}")
                await ctx.respond(embed=error_embed(
                    "Connection Failed",
                    f"Could not join **{voice_channel.name}**: `{exc}`",
                ))
                return
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)

        sink = RealtimeWaveSink(self.bot)
        sink._text_channel = ctx.channel  # type: ignore[attr-defined]

        self._active_sinks[guild_id] = sink

        loop = asyncio.get_event_loop()

        def _callback_shim(sink: discord.sinks.Sink, *args) -> None:
            asyncio.run_coroutine_threadsafe(
                self._on_recording_done(None), loop
            )

        voice_client.start_recording(sink, _callback_shim, True)

        logger.info(f"Started realtime transcription in guild {guild_id}, channel '{voice_channel.name}'")
        await ctx.respond(embed=info_embed(
            "🔴 Transcription Started",
            f"Now transcribing in **{voice_channel.name}**.\n\n"
            "Run `/transcribe stop` when done. Transcripts will show up in the terminal.",
        ))

    @transcribe.command(name="stop", description="Stop realtime transcription")
    async def transcribe_stop(self, ctx: discord.ApplicationContext) -> None:
        """Stop transcription and clean up."""
        await ctx.defer()

        guild_id = ctx.guild.id
        voice_client: discord.VoiceClient | None = ctx.guild.voice_client

        if guild_id not in self._active_sinks or voice_client is None:
            await ctx.respond(embed=warning_embed(
                "Not Transcribing",
                "There is no active transcription session.\nUse `/transcribe start` to begin.",
            ))
            return

        try:
            voice_client.stop_recording()
        except discord.ClientException as exc:
            logger.warning(
                f"stop_recording() raised '{exc}' — recording may have already "
                "auto-stopped. Cleaning up active sink."
            )
            self._active_sinks.pop(guild_id, None)

        logger.info(f"Stopped transcription in guild {guild_id}")
        await ctx.respond(embed=info_embed(
            "⏹️ Transcription Stopped",
            "Realtime transcription session has ended.",
        ))


def setup(bot: discord.Bot) -> None:
    """Pre-load the STT model at bot startup and add the STTCog."""
    load_model()
    bot.add_cog(STTCog(bot))

