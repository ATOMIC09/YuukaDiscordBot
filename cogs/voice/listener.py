"""
cogs/voice/listener.py
Voice receive cog — listens to users speaking and saves audio.

How it works
------------
1. Bot joins a voice channel (or reuses an existing VoiceClient)
2. `voice_client.start_recording(sink, callback)` begins capturing audio.
3. When `voice_client.stop_recording()` is called, the callback fires.
4. sink.audio_data contains raw PCM BytesIO per user (keyed by user_id int).
   We encode each one to Ogg Opus via FFmpeg ourselves.
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
  /record start  — Join voice channel and start recording
  /record stop   — Stop recording and send audio files to channel
"""

from __future__ import annotations

import asyncio
import io
import pathlib
import time

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import error_embed, info_embed, success_embed, warning_embed
from utils.errors import UserError, UserWarning

# Opus decoder output constants (pycord hardcoded values)
_OPUS_CHANNELS = 2
_OPUS_SAMPLE_RATE = 48_000  # Hz


async def _pcm_to_opus(raw_pcm: bytes, bitrate: str = "32k") -> bytes:
    """
    Encode raw 48kHz stereo 16-bit PCM straight to Ogg Opus bytes via FFmpeg,
    entirely in memory (no intermediate file).

    WaveSink.format_audio() is broken in pycord 2.8 (references vc.recording
    and vc.decoder which don't exist in the new VoiceClient), so we feed the
    raw PCM to FFmpeg ourselves using the known Opus decoder output format.
    Per-user PCM has no real stereo separation (both channels carry the same
    speaker), so we downmix to mono on output — free size savings, no quality
    loss. Combined with a voice-tuned bitrate and VBR collapsing silence,
    this keeps recordings well clear of Discord's upload limit.
    """
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-f", "s16le",
        "-ar", str(_OPUS_SAMPLE_RATE),
        "-ac", str(_OPUS_CHANNELS),
        "-i", "pipe:0",
        "-c:a", "libopus",
        "-application", "voip",
        "-ac", "1",
        "-b:a", bitrate,
        "-vbr", "on",
        "-f", "ogg",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(input=raw_pcm)
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="ignore"))
    return stdout


class ListenerCog(commands.Cog, name="Voice Listener"):
    """Voice receive — listen to users speaking and save audio."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self._active_sinks: dict[int, discord.sinks.WaveSink] = {}

    async def _on_recording_done(self, exception: Exception | None, /) -> None:
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
                "ไม่ได้ยินเสียงเลยค่ะ",
                "หนูไม่เห็นได้ยินใครพูดอะไรเลยค่ะ... ไม่แน่ใจว่าไมค์ช็อตรึเปล่าน้า (´-ω-`)\n"
                "หรือว่าระบบถอดรหัสของ Discord (DAVE) อาจจะมีปัญหาค่ะ",
            ))
            return

        files_to_send: list[discord.File] = []
        pending_saves: list[tuple[str, bytes]] = []  # fallback disk writes if the send below fails
        summary_lines: list[str] = []
        upload_limit = channel.guild.filesize_limit if channel.guild else 10 * 1024 * 1024

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

            try:
                opus_bytes = await _pcm_to_opus(raw_pcm)
                if len(opus_bytes) > upload_limit:
                    logger.debug(f"{display}'s recording exceeded the upload limit at 32k, re-encoding at 16k.")
                    opus_bytes = await _pcm_to_opus(raw_pcm, bitrate="16k")
            except RuntimeError as exc:
                logger.error(f"Opus encoding failed for {display}: {exc}")
                summary_lines.append(f"🎙️ **{display}**: *(encoding failed)*")
                continue

            logger.info(f"Encoded audio for {display}: {len(opus_bytes) / 1024:.1f} KB")

            filename = f"recorded_{user_id}_{int(time.time())}.ogg"
            files_to_send.append(discord.File(io.BytesIO(opus_bytes), filename=filename))
            pending_saves.append((filename, opus_bytes))

            summary_lines.append(f"🎙️ **{display}**: `{filename}`")

        # Post summary embed to Discord with the audio files attached
        embed = success_embed(
            "บันทึกเสียงเรียบร้อยค่ะ",
            f"เย้! หนูรวบรวมเสียงของ **{len(active_sink.audio_data)}** คนมาให้แล้วน้า 🎵\n\n" + "\n".join(summary_lines),
        )

        try:
            await channel.send(embed=embed, files=files_to_send)
            logger.info(f"Audio sent for guild {guild_id}")
        except discord.HTTPException as exc:
            logger.error(f"Failed to send audio (likely due to file size): {exc}")
            save_dir = pathlib.Path("assets/audio/recordings")
            save_dir.mkdir(parents=True, exist_ok=True)
            for filename, opus_bytes in pending_saves:
                (save_dir / filename).write_bytes(opus_bytes)
            error_msg_embed = warning_embed(
                "ไฟล์ใหญ่เกินไปค่ะ",
                "ไฟล์เสียงใหญ่เกินไป หนูส่งเข้า Discord ไม่ไหวค่ะ (｡•́︿•̀｡)\n\nแต่ไม่ต้องห่วงนะคะ หนูเซฟเก็บไว้ที่ `assets/audio/recordings/` ให้แล้วน้า"
            )
            await channel.send(embed=error_msg_embed)

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    record = discord.SlashCommandGroup("record", "🎧 คำสั่งบันทึกเสียงในห้องเสียง")

    @record.command(name="start", description="🔴 เข้าห้องเสียงและเริ่มบันทึกเสียง")
    async def record_start(self, ctx: discord.ApplicationContext) -> None:
        """Start recording audio from the invoker's voice channel."""
        await ctx.defer()

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError(
                "ยังไม่ได้เข้าห้องเสียงค่ะ",
                "เซนเซย์ยังไม่ได้เข้าห้องเสียงเลยนะคะ เข้าห้องก่อนแล้วค่อยเรียกหนูน้า (・`ω´・)",
            )

        guild_id = ctx.guild.id

        if guild_id in self._active_sinks:
            raise UserWarning(
                "หนูทำงานอยู่นะคะ",
                "หนูกำลังอัดเสียงอยู่ที่ห้องอื่นนะคะ ต้องให้หนูหยุดอัดก่อนน้า ลองใช้คำสั่ง `/record stop` ดูนะคะ (｡>﹏<)",
            )

        voice_channel = ctx.author.voice.channel
        voice_client: discord.VoiceClient | None = ctx.guild.voice_client

        if voice_client is None:
            try:
                voice_client = await voice_channel.connect()
            except discord.ClientException as exc:
                logger.error(f"Failed to connect to voice channel: {exc}")
                raise UserError(
                    "เข้าห้องไม่ได้ค่ะ",
                    f"แงงง หนูเข้าไปในห้อง **{voice_channel.name}** ไม่ได้ค่ะ... เกิดข้อผิดพลาดนิดหน่อย (T⌓T): `{exc}`",
                )
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
            "🔴 เริ่มอัดเสียงแล้วค่ะ",
            f"หนูเข้ามาแล้วค่ะ! ตอนนี้กำลังตั้งใจฟังทุกคนอยู่ในห้อง **{voice_channel.name}** น้า 🎧\n\n"
            "ถ้าคุยกันเสร็จแล้ว อย่าลืมใช้คำสั่ง `/record stop` นะคะ!",
        ))

    @record.command(name="stop", description="⏹️ หยุดบันทึกเสียงและส่งไฟล์เสียงที่บันทึกไว้")
    async def record_stop(self, ctx: discord.ApplicationContext) -> None:
        """Stop recording and trigger the transcription pipeline."""
        await ctx.defer()

        guild_id = ctx.guild.id
        voice_client: discord.VoiceClient | None = ctx.guild.voice_client

        if guild_id not in self._active_sinks or voice_client is None:
            raise UserWarning(
                "ยังไม่ได้อัดเสียงค่ะ",
                "เอ๊ะ... หนูยังไม่ได้อัดเสียงเลยนะคะ ถ้าอยากให้หนูอัด ใช้คำสั่ง `/record start` ก่อนน้า (・_・;)",
            )

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
            "⏹️ หยุดอัดเสียงแล้วค่ะ",
            "หนูหยุดอัดเสียงแล้วค่ะ! ขอเวลาประมวลผลแป๊บนึงนะคะ เดี๋ยวหนูส่งไฟล์ให้ค่า (´• ω •`) ♡",
        ))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ListenerCog(bot))
