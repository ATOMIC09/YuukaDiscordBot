"""
cogs/voice/stt.py
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

# Module-level state
_model_loaded: bool = False
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
_transcribe_fn = None  # set after model load

# Opus decoder output constants (pycord hardcoded values)
_OPUS_CHANNELS = 2
_OPUS_SAMPLE_WIDTH = 2      # bytes per sample per channel (16-bit)
_OPUS_SAMPLE_RATE = 48_000  # Hz


def _pcm_to_wav(pcm_bytes: bytes) -> io.BytesIO:
    """Wrap raw PCM bytes in a proper WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_OPUS_CHANNELS)
        wf.setsampwidth(_OPUS_SAMPLE_WIDTH)
        wf.setframerate(_OPUS_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    buf.seek(0)
    return buf


def load_model(device: str = "cpu") -> None:
    """
    Load the Typhoon ASR model. Call once at startup.
    Safe to call multiple times — subsequent calls are no-ops.

    Args:
        device: "cpu" (default) or "cuda" if a GPU is available.
    """
    global _model_loaded, _transcribe_fn

    if _model_loaded:
        return

    logger.info(f"Loading Typhoon ASR model on {device.upper()}...")
    try:
        from typhoon_asr import transcribe as _typhoon_transcribe  # type: ignore[import]

        # Warm-up: import triggers model download on first run.
        # Store the function reference for later calls.
        _transcribe_fn = _typhoon_transcribe
        _model_loaded = True
        logger.info("Typhoon ASR ready")
    except ImportError:
        logger.error(
            "typhoon-asr is not installed. Run: uv add typhoon-asr\n"
            "STT transcription will be disabled."
        )


def _run_transcribe(wav_path: str) -> str:
    """
    Blocking transcription call — runs in a thread pool.
    Returns the transcript string (empty string on failure).
    """
    if _transcribe_fn is None:
        return ""
    try:
        result = _transcribe_fn(wav_path, device="cpu")
        text_val = result.get("text", "")
        if hasattr(text_val, "text"):
            text_val = text_val.text
        return str(text_val).strip()
    except Exception as exc:
        logger.error(f"STT transcription error: {exc}")
        return ""


async def transcribe_wav_bytes(
    wav_bytes: io.BytesIO,
    user_display: str,
) -> str:
    """
    Transcribe audio from a BytesIO WAV file asynchronously.

    WaveSink produces 48kHz 16-bit stereo WAV. We write it to a temp file
    so typhoon-asr can read and resample it internally.

    Args:
        wav_bytes: BytesIO from sink.audio_data[user_id].file (already seeked to 0)
        user_display: Human-readable username string for logging

    Returns:
        Transcript text, or empty string if model not loaded / silence.
    """
    if not _model_loaded:
        logger.warning("STT model not loaded — skipping transcription for %s", user_display)
        return ""

    loop = asyncio.get_running_loop()

    # Write to a temp .wav file that typhoon-asr can open
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes.read())
        tmp_path = tmp.name

    transcript = await loop.run_in_executor(_executor, _run_transcribe, tmp_path)

    # Clean up temp file
    try:
        import os
        os.unlink(tmp_path)
    except OSError:
        pass

    if transcript:
        logger.info(f"[STT] {user_display}: {transcript}")
    else:
        logger.debug(f"[STT] {user_display}: (no speech detected)")

    return transcript


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
                # Dictionary changed size during iteration
                continue

            for user_id in users:
                audio_data = self.audio_data.get(user_id)
                if not audio_data:
                    continue
                
                current_size = audio_data.file.tell()
                last_size = self.last_sizes.get(user_id, 0)
                
                if current_size > last_size:
                    # User is currently speaking
                    self.last_sizes[user_id] = current_size
                    self.silence_time[user_id] = now
                elif current_size > 0:
                    # Size hasn't changed. Have they been silent for long enough?
                    last_speak = self.silence_time.get(user_id, now)
                    if now - last_speak >= 0.5:
                        # 1 second of silence -> trigger STT and reset
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
        await transcribe_wav_bytes(wav_buf, display)

    def cleanup(self):
        super().cleanup()
        if hasattr(self, "monitor_task") and not self.monitor_task.done():
            self.monitor_task.cancel()


class STTCog(commands.Cog, name="Realtime STT"):
    """Voice receive — listen to users speaking and transcribe realtime."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # guild_id -> active RealtimeWaveSink
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

