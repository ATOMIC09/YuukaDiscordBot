"""
cogs/voice/listener.py
Voice receive cog — listens to users speaking and transcribes in real-time.

How it works
------------
1. Bot joins a voice channel (or reuses an existing VoiceClient)
2. `voice_client.start_recording(sink, callback)` begins capturing audio.
   bot/patches.py fixes the interface mismatch between the new receive stack
   (which passes VoiceData objects) and the old WaveSink (which expects bytes).
3. When `voice_client.stop_recording()` is called, the callback fires.
4. sink.audio_data contains raw PCM BytesIO per user (keyed by user_id int).
   We wrap each one in a proper WAV container ourselves (skipping the broken
   WaveSink.format_audio which relies on vc.recording / vc.decoder).
5. Each user's WAV is passed to Typhoon ASR for transcription.
6. Transcript is logged to terminal: [STT] username: text

PCM format from Opus decoder (pycord hardcoded):
  - Sample rate : 48 000 Hz
  - Channels    : 2 (stereo)
  - Sample width: 2 bytes (16-bit signed, little-endian)

DAVE note
---------
pycord 2.8.0 fully supports DAVE (Discord E2E Encryption) when `davey` is
installed. The RuntimeWarning from start_recording() is a stale TODO comment
— it is suppressed by bot/patches.py. Voice receive works correctly.

Slash Commands
--------------
  /listen start  — Join voice channel and start recording
  /listen stop   — Stop recording, transcribe, print transcripts to terminal
"""

from __future__ import annotations

import asyncio
import io
import wave

import discord
from discord.ext import commands

from bot.logger import logger
from cogs.voice.stt import load_model, transcribe_wav_bytes
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
    """Voice receive — listen to users speaking and transcribe via Typhoon ASR."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # guild_id → active WaveSink
        self._active_sinks: dict[int, discord.sinks.WaveSink] = {}

        # Kick off model load in the background when the cog loads
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, load_model)
        except RuntimeError:
            # No running loop yet — model will lazy-load on first transcription
            pass

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

        transcripts: dict[str, str] = {}

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
                transcripts[display] = "*(no speech)*"
                continue

            # Wrap raw PCM in a proper WAV container for Typhoon ASR
            # (WaveSink.format_audio is broken in 2.8, we do it ourselves)
            wav_buf = _pcm_to_wav(raw_pcm)

            # --- STT Temporarily Disabled ---
            # transcript = await transcribe_wav_bytes(wav_buf, display)
            # transcripts[display] = transcript if transcript else "*(no speech detected)*"
            
            import os
            os.makedirs("assets/audio", exist_ok=True)
            filename = f"assets/audio/recorded_{user_id}.wav"
            with open(filename, "wb") as f:
                f.write(wav_buf.read())
            
            logger.info(f"Saved audio from {display} to {filename}")
            transcripts[display] = f"*(Audio saved to {filename})*"

            # TODO: AI PIPELINE HOOK
            # Forward transcript to AI pipeline here:
            # await ai_pipeline.process(user_id, transcript)

        # Post summary embed to Discord
        lines = [f"🎙️ **{name}**\n> {text}" for name, text in transcripts.items()]
        await channel.send(embed=success_embed(
            "Recording Saved",
            f"Processed **{len(transcripts)}** speaker(s):\n\n" + "\n\n".join(lines),
        ))

        logger.info(f"Transcription done for guild {guild_id}")

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

        # bot/patches.py already added __sink_listeners__, walk_children, is_opus,
        # and the critical write() fix at the Sink class level — no per-instance
        # patching needed here.
        sink = discord.sinks.WaveSink()
        # CRITICAL: sink.client is a property returning self.vc.
        # PacketDecoder._process_packet() asserts self.sink.client and uses
        # self.sink.client._ssrc_to_id to resolve SSRC→user.
        # The new AudioReader never calls sink.init(), so vc stays None.
        # Setting it manually fixes the AssertionError that crashes the PacketRouter.
        sink.vc = voice_client  # type: ignore[attr-defined]
        sink._text_channel = ctx.channel  # type: ignore[attr-defined]

        self._active_sinks[guild_id] = sink

        # The AudioReader calls `after(exception)` synchronously from a background
        # thread. An `async def` callback just creates a coroutine that is never
        # awaited. We wrap it in a sync shim that schedules the coroutine on the
        # bot's event loop via run_coroutine_threadsafe().
        loop = asyncio.get_event_loop()

        def _callback_shim(exception: Exception | None) -> None:
            asyncio.run_coroutine_threadsafe(
                self._on_recording_done(exception), loop
            )

        voice_client.start_recording(sink, _callback_shim)

        logger.info(f"Started recording in guild {guild_id}, channel '{voice_channel.name}'")
        await ctx.respond(embed=info_embed(
            "🔴 Recording Started",
            f"Now listening in **{voice_channel.name}**.\n\n"
            "Speak in **Thai** for best accuracy with Typhoon ASR.\n"
            "Run `/listen stop` when done — transcripts appear in the terminal.",
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
            "Transcribing audio… results will appear in the terminal and here shortly.",
        ))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ListenerCog(bot))
