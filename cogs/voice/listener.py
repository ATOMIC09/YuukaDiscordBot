"""
cogs/voice/listener.py
Voice receive cog — listens to users speaking in a voice channel.

Uses pycord's Sink API (discord.sinks) to capture raw PCM audio per user.

How it works:
  1. Bot joins a voice channel (or reuses an existing VoiceClient)
  2. `voice_client.start_recording(sink, callback)` begins capturing audio
  3. When `voice_client.stop_recording()` is called, the callback fires
  4. `sink.audio_data` is a dict[user_id, AudioData] with raw PCM bytes
     (wrapped in a .wav container when using WaveSink)

AI Pipeline Hook:
  The callback (`_on_recording_done`) is where AI processing plugs in.
  Each user's audio data should be forwarded to an STT / hotword / AI model.
  See the TODO comment below.

Slash Commands:
  /listen start  — Join voice channel and start recording
  /listen stop   — Stop recording, upload per-user .wav files to text channel
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import error_embed, info_embed, success_embed, warning_embed


class ListenerCog(commands.Cog, name="Voice Listener"):
    """Voice receive — listen to users speaking and pipe audio to the AI pipeline."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # guild_id → active sink (one per guild)
        self._active_sinks: dict[int, discord.sinks.WaveSink] = {}

    # ------------------------------------------------------------------
    # Recording callback
    # ------------------------------------------------------------------

    def _on_recording_done(self, exception: Exception | None, /) -> None:
        """
        Called automatically by pycord when stop_recording() is invoked.

        In pycord 2.7+ the callback takes exactly one positional-only parameter:
        `exception` — the error raised during recording, or None if clean.

        Since py-cord 2.8.0 invokes this callback synchronously from a background
        thread, we schedule the actual async work on the bot's main event loop.
        """
        import asyncio
        asyncio.run_coroutine_threadsafe(
            self._on_recording_done_async(exception),
            self.bot.loop
        )

    async def _on_recording_done_async(self, exception: Exception | None) -> None:
        """Asynchronously process and upload the recorded audio data."""
        # Locate the active sink and its paired text channel
        active_sink: discord.sinks.WaveSink | None = None
        channel: discord.TextChannel | None = None

        for g_id, sink in list(self._active_sinks.items()):
            ch = getattr(sink, "_text_channel", None)
            if ch is not None:
                # POP IT IMMEDIATELY to prevent double-execution!
                active_sink = self._active_sinks.pop(g_id, None)
                channel = ch
                break

        if active_sink is None or channel is None:
            logger.debug("_on_recording_done fired but no active sink found (likely a duplicate event)")
            return

        guild_id = channel.guild.id
        logger.info(f"Recording finished in guild {guild_id}. Processing audio...")

        if exception:
            logger.error(f"Recording error in guild {guild_id}: {exception}")

        if not active_sink.audio_data:
            await channel.send(embed=warning_embed(
                "No Audio Captured",
                "No speech was detected from any user during the recording session.",
            ))
            return

        # py-cord 2.8.0 regression: AudioReader._stop() commented out sink.cleanup().
        # We must call it manually to trigger format_audio (which writes the WAV headers).
        try:
            active_sink.cleanup()
        except Exception as exc:
            logger.error(f"Failed to cleanup sink for guild {guild_id}: {exc}")

        files: list[discord.File] = []
        summary_lines: list[str] = []

        for user_id, audio in active_sink.audio_data.items():
            user = self.bot.get_user(user_id)
            display = str(user) if user else f"Unknown ({user_id})"

            audio.file.seek(0, 2)          # seek to end
            byte_count = audio.file.tell()  # get size
            audio.file.seek(0)             # reset for reading

            kb = byte_count / 1024
            logger.debug(f"Audio captured — user: {display}, size: {kb:.1f} KB")

            # TODO: AI PIPELINE HOOK
            # Swap the file upload below for STT processing when ready.
            # Example:
            #   audio.file.seek(0)
            #   transcript = await stt_engine.transcribe(audio.file)
            #   await channel.send(f"**{display}:** {transcript}")

            safe_name = (user.name if user else f"user_{user_id}").replace(" ", "_")
            files.append(discord.File(audio.file, filename=f"{safe_name}.wav"))
            summary_lines.append(f"🎙️ **{display}** — `{kb:.1f} KB`")

        summary = "\n".join(summary_lines)
        await channel.send(
            embed=success_embed(
                "Recording Complete",
                f"Captured audio from **{len(files)}** user(s):\n\n{summary}\n\n"
                "*(Files attached below — play them in Discord to verify)*",
            ),
            files=files,
        )

        self._active_sinks.pop(guild_id, None)
        logger.info(f"Uploaded {len(files)} audio file(s) for guild {guild_id}")

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    listen = discord.SlashCommandGroup("listen", "Voice listening commands")

    @listen.command(name="start", description="Join your voice channel and start recording audio")
    async def listen_start(self, ctx: discord.ApplicationContext) -> None:
        """Start recording audio from the invoker's voice channel."""
        await ctx.defer()

        # Must be in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.respond(embed=error_embed(
                "Not in a Voice Channel",
                "You must be in a voice channel for me to start listening.",
            ))
            return

        guild_id = ctx.guild.id

        # Already recording in this guild
        if guild_id in self._active_sinks:
            await ctx.respond(embed=warning_embed(
                "Already Recording",
                "I'm already recording in this server. Use `/listen stop` first.",
            ))
            return

        voice_channel = ctx.author.voice.channel

        # Join or reuse existing VoiceClient
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

        # Start recording
        sink = discord.sinks.WaveSink()

        # pycord 2.8 regression: the new AudioReader → SinkEventRouter accesses
        # sink.__sink_listeners__, sink.walk_children(), and sink.is_opus() but
        # discord.sinks.WaveSink was never updated to define them (half-finished refactor).
        # Patching them satisfies the router and packet decoder.
        if not hasattr(sink, "__sink_listeners__"):
            sink.__sink_listeners__ = []  # type: ignore[attr-defined]
        if not hasattr(sink, "walk_children"):
            sink.walk_children = lambda: []  # type: ignore[attr-defined]
        if not hasattr(sink, "is_opus"):
            sink.is_opus = lambda: False  # type: ignore[attr-defined]
        sink.vc = voice_client  # type: ignore[attr-defined]

        # pycord 2.7+ changed the callback signature to take exactly ONE positional
        # parameter (the exception). Store the text channel on the sink so the
        # callback can access it without the deprecated *args pass-through.
        sink._text_channel = ctx.channel  # type: ignore[attr-defined]

        self._active_sinks[guild_id] = sink
        voice_client.start_recording(sink, self._on_recording_done)

        logger.info(f"Started recording in guild {guild_id}, channel '{voice_channel.name}'")
        await ctx.respond(embed=info_embed(
            "🔴 Recording Started",
            f"Now listening in **{voice_channel.name}**.\n\n"
            "Speak freely — run `/listen stop` when you're done.\n"
            "Each speaker's audio will be uploaded as a `.wav` file.",
        ))

    @listen.command(name="stop", description="Stop recording and upload captured audio files")
    async def listen_stop(self, ctx: discord.ApplicationContext) -> None:
        """Stop recording and trigger the audio callback."""
        await ctx.defer()

        guild_id = ctx.guild.id
        voice_client: discord.VoiceClient | None = ctx.guild.voice_client

        if guild_id not in self._active_sinks or voice_client is None:
            await ctx.respond(embed=warning_embed(
                "Not Recording",
                "There is no active recording session in this server.\n"
                "Use `/listen start` to begin.",
            ))
            return

        # stop_recording() calls _on_recording_done asynchronously
        voice_client.stop_recording()

        logger.info(f"Stopped recording in guild {guild_id}")
        await ctx.respond(embed=info_embed(
            "⏹️ Recording Stopped",
            "Processing audio… files will be posted here shortly.",
        ))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ListenerCog(bot))
