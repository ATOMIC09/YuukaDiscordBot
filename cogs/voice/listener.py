"""
cogs/voice/listener.py
Voice receive cog — listens to users speaking and saves audio.

How it works
------------
1. Bot joins a voice channel (or reuses an existing VoiceClient)
2. `voice_client.start_recording(sink, callback)` begins capturing audio.
3. When `voice_client.stop_recording()` is called, the callback fires.
4. sink.audio_data contains raw PCM BytesIO per user (keyed by user_id int).
   We wrap each one in a proper WAV container ourselves.
5. The audio files are attached to a message and sent back to the channel.

PCM format from Opus decoder (pycord hardcoded):
  - Sample rate : 48 000 Hz
  - Channels    : 2 (stereo)
  - Sample width: 2 bytes (16-bit signed, little-endian)

DAVE note
---------
pycord 2.8.0 fully supports DAVE (Discord E2E Encryption) when `davey` is
installed. Voice receive works correctly out of the box.

Slash Commands
--------------
  /listen start  — Join voice channel and start recording
  /listen stop   — Stop recording and send audio files to channel
"""

from __future__ import annotations

import asyncio
import io
import wave

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import error_embed, info_embed, success_embed, warning_embed

# Opus decoder output constants (pycord hardcoded values)
_OPUS_CHANNELS = 2
_OPUS_SAMPLE_WIDTH = 2      # bytes per sample per channel (16-bit)
_OPUS_SAMPLE_RATE = 48_000  # Hz


def _pcm_to_wav(pcm_bytes: bytes) -> io.BytesIO:
    """
    Wrap raw PCM bytes in a proper WAV container.

    WaveSink.format_audio() is broken in pycord 2.8 (references vc.recording
    and vc.decoder which don't exist in the new VoiceClient). We do it manually
    using the known Opus decoder output format.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_OPUS_CHANNELS)
        wf.setsampwidth(_OPUS_SAMPLE_WIDTH)
        wf.setframerate(_OPUS_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    buf.seek(0)
    return buf


class ListenerCog(commands.Cog, name="Voice Listener"):
    """Voice receive — listen to users speaking and save audio."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # guild_id -> active WaveSink
        self._active_sinks: dict[int, discord.sinks.WaveSink] = {}

    # ------------------------------------------------------------------
    # Recording callback (pycord 2.7+ single-parameter style)
    # ------------------------------------------------------------------

    async def _on_recording_done(self, exception: Exception | None, /) -> None:
        """
        Called by pycord when stop_recording() is invoked.

        Signature: exactly ONE positional-only parameter (exception).
        The text channel is stored on sink._text_channel at recording start.

        After bot/patches.py is applied:
        - sink.audio_data = {user_id (int): AudioData(BytesIO of raw PCM)}
        - We wrap each BytesIO in a WAV container manually (_pcm_to_wav)
        - Each WAV is transcribed by Typhoon ASR and logged to terminal

        TODO: AI PIPELINE HOOK
        After transcription, forward `transcript` to your AI pipeline here.
        """
        # Locate the active sink and its paired text channel
        active_sink: discord.sinks.WaveSink | None = None
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
        
        # Pop early to prevent duplicate executions from py-cord thread race conditions
        self._active_sinks.pop(guild_id, None)
        logger.info(f"Recording finished in guild {guild_id}. Processing audio...")

        if exception:
            logger.error(f"Recording error in guild {guild_id}: {exception!r}")

        logger.debug(
            f"audio_data keys: {list(active_sink.audio_data.keys())} "
            f"({len(active_sink.audio_data)} speaker(s))"
        )

        if not active_sink.audio_data:
            await channel.send(embed=warning_embed(
                "No Audio Captured",
                "No speech was detected. This can happen if:\n"
                "• No one spoke during the recording\n"
                "• DAVE decryption is not working (check `davey` is installed)",
            ))
            return

        files_to_send: list[discord.File] = []
        summary_lines: list[str] = []

        for user_id, audio_data in active_sink.audio_data.items():
            user = self.bot.get_user(user_id)
            display = str(user) if user else f"Unknown ({user_id})"

            # Get raw PCM bytes
            audio_data.file.seek(0)
            raw_pcm = audio_data.file.read()
            byte_count = len(raw_pcm)
            kb = byte_count / 1024
            logger.debug(f"Audio captured — user: {display}, size: {kb:.1f} KB raw PCM")

            if byte_count < 1024:
                logger.debug(f"Skipping {display} — audio too short ({byte_count} bytes)")
                summary_lines.append(f"🎙️ **{display}**: *(audio too short)*")
                continue

            # Wrap raw PCM in a proper WAV container
            wav_buf = _pcm_to_wav(raw_pcm)
            
            # Create a discord.File object to send
            filename = f"recorded_{user_id}.wav"
            files_to_send.append(discord.File(wav_buf, filename=filename))
            
            summary_lines.append(f"🎙️ **{display}**: Audio attached.")

        # Post summary embed to Discord with the audio files attached
        embed = success_embed(
            "Recording Saved",
            f"Processed **{len(active_sink.audio_data)}** speaker(s):\n\n" + "\n".join(summary_lines),
        )
        await channel.send(embed=embed, files=files_to_send)

        logger.info(f"Audio sent for guild {guild_id}")

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    listen = discord.SlashCommandGroup("listen", "Voice listening commands")

    @listen.command(name="start", description="Join your voice channel and start recording audio")
    async def listen_start(self, ctx: discord.ApplicationContext) -> None:
        """Start recording audio from the invoker's voice channel."""
        await ctx.defer()

        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.respond(embed=error_embed(
                "Not in a Voice Channel",
                "You must be in a voice channel for me to start listening.",
            ))
            return

        guild_id = ctx.guild.id

        if guild_id in self._active_sinks:
            await ctx.respond(embed=warning_embed(
                "Already Recording",
                "I'm already recording in this server. Use `/listen stop` first.",
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

        # PR 3159 provides native sink and DAVE support!
        sink = discord.sinks.WaveSink()
        sink._text_channel = ctx.channel  # type: ignore[attr-defined]

        self._active_sinks[guild_id] = sink

        # The AudioReader calls `after(exception)` synchronously from a background
        # thread. An `async def` callback just creates a coroutine that is never
        # awaited. We wrap it in a sync shim that schedules the coroutine on the
        # bot's event loop via run_coroutine_threadsafe().
        loop = asyncio.get_event_loop()

        def _callback_shim(sink: discord.sinks.Sink, *args) -> None:
            # In Pycord 2.8+, the callback receives (sink, *args).
            # The exception is no longer passed as a parameter.
            asyncio.run_coroutine_threadsafe(
                self._on_recording_done(None), loop
            )

        # PYCORD 2.8.0 / PR 3159 BUG WORKAROUND:
        # AudioReader.run() checks `if self.after and self.args:`.
        # If no *args are provided, self.args is `()` which evaluates to False,
        # silently dropping the callback! We pass a dummy `True` to prevent this.
        voice_client.start_recording(sink, _callback_shim, True)

        logger.info(f"Started recording in guild {guild_id}, channel '{voice_channel.name}'")
        await ctx.respond(embed=info_embed(
            "🔴 Recording Started",
            f"Now listening in **{voice_channel.name}**.\n\n"
            "Run `/listen stop` when done — audio files will be sent to this channel.",
        ))

    @listen.command(name="stop", description="Stop recording and transcribe captured audio")
    async def listen_stop(self, ctx: discord.ApplicationContext) -> None:
        """Stop recording and trigger the transcription pipeline."""
        await ctx.defer()

        guild_id = ctx.guild.id
        voice_client: discord.VoiceClient | None = ctx.guild.voice_client

        if guild_id not in self._active_sinks or voice_client is None:
            await ctx.respond(embed=warning_embed(
                "Not Recording",
                "There is no active recording session.\nUse `/listen start` to begin.",
            ))
            return

        # stop_recording() raises ClientException if the recording already
        # auto-stopped internally (e.g. PacketRouter died). Handle gracefully.
        try:
            voice_client.stop_recording()
        except discord.ClientException as exc:
            logger.warning(
                f"stop_recording() raised '{exc}' — recording may have already "
                "auto-stopped. Cleaning up active sink."
            )
            self._active_sinks.pop(guild_id, None)

        logger.info(f"Stopped recording in guild {guild_id}")
        await ctx.respond(embed=info_embed(
            "⏹️ Recording Stopped",
            "Processing audio... files will be sent here shortly.",
        ))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ListenerCog(bot))
