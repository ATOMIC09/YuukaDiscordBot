"""
cogs/voice/listener.py
Voice receive cog — listens to users speaking and saves audio.

How it works
------------
1. Bot joins a voice channel (or reuses an existing VoiceClient)
2. We subscribe to `utils.voice_hub` with `want_timeline=True`. The hub owns
   the one sink a VoiceClient allows and lays every speaker's PCM onto a
   shared timeline — see SegmentingSink's docstring for why RTP timestamps
   rather than wall-clock time are used to measure gaps.
3. `/record stop` reads `sink.audio_data` and unsubscribes. The capture only
   actually stops if no other feature (`/transcribe`, `/ai voice`) is still
   listening.
4. sink.audio_data contains raw PCM bytearrays per user (keyed by user_id
   int), each aligned to the same timeline. We encode each one to Ogg
   Opus via FFmpeg, and also down-mix all speakers together into one
   combined "meeting recording" file via FFmpeg's amix filter.
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
import os
import pathlib
import tempfile
import time

import discord
from discord.ext import commands

from bot.logger import logger
from utils.audio import OPUS_CHANNELS as _OPUS_CHANNELS
from utils.audio import OPUS_SAMPLE_RATE as _OPUS_SAMPLE_RATE
from utils.embeds import info_embed, success_embed, warning_embed
from utils.errors import UserError, UserWarning
from utils.voice_hub import voice_hub

_HUB_KEY = "record"


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


async def _mix_and_encode(streams: list[bytes], bitrate: str = "32k") -> bytes:
    """
    Down-mix multiple time-aligned 48kHz stereo PCM streams (one per
    speaker, all sharing the same timeline courtesy of SegmentingSink)
    into a single mono Ogg Opus file via FFmpeg's `amix` filter — a
    "meeting recording" of everyone talking, rather than separate
    per-speaker files.

    FFmpeg needs one real input per stream (a single pipe can't carry
    several raw PCM streams at once), so each stream is written to a
    throwaway temp file for the duration of this call and removed
    afterward — this never touches assets/audio/recordings/.
    """
    tmp_paths: list[str] = []
    try:
        for stream in streams:
            with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tmp:
                tmp.write(stream)
                tmp_paths.append(tmp.name)

        cmd = ["ffmpeg", "-y"]
        for path in tmp_paths:
            cmd.extend(["-f", "s16le", "-ar", str(_OPUS_SAMPLE_RATE), "-ac", str(_OPUS_CHANNELS), "-i", path])

        cmd.extend([
            "-filter_complex", f"amix=inputs={len(tmp_paths)}:duration=longest",
            "-c:a", "libopus",
            "-application", "voip",
            "-ac", "1",
            "-b:a", bitrate,
            "-vbr", "on",
            "-f", "ogg",
            "pipe:1",
        ])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="ignore"))
        return stdout
    finally:
        for path in tmp_paths:
            try:
                os.remove(path)
            except OSError:
                pass


class ListenerCog(commands.Cog, name="Voice Listener"):
    """Voice receive — listen to users speaking and save audio."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # guild_id → text channel that /record start was invoked in
        self._sessions: dict[int, discord.TextChannel] = {}

    async def _deliver_recording(
        self,
        guild_id: int,
        channel: discord.TextChannel,
        audio_data: dict[int, bytearray],
    ) -> None:
        """Encode the captured timeline and post it to *channel*."""
        logger.info(f"Recording finished in guild {guild_id}. Processing audio...")
        logger.debug(
            f"audio_data keys: {list(audio_data.keys())} "
            f"({len(audio_data)} speaker(s))"
        )

        if not audio_data:
            await channel.send(embed=warning_embed(
                "ไม่ได้ยินเสียงเลยค่ะ",
                "หนูไม่เห็นได้ยินใครพูดอะไรเลยค่ะ... ไม่แน่ใจว่าไมค์ช็อตรึเปล่าน้า (´-ω-`)\n"
                "หรือว่าระบบถอดรหัสของ Discord (DAVE) อาจจะมีปัญหาค่ะ",
            ))
            return

        files_to_send: list[discord.File] = []
        pending_saves: list[tuple[str, bytes]] = []  # fallback disk writes if the send below fails
        summary_lines: list[str] = []
        valid_streams: list[bytes] = []  # per-speaker PCM that passed the length check, for mixing
        upload_limit = channel.guild.filesize_limit if channel.guild else 10 * 1024 * 1024
        timestamp = int(time.time())

        for user_id, buf in audio_data.items():
            user = self.bot.get_user(user_id)
            display = str(user) if user else f"Unknown ({user_id})"

            raw_pcm = bytes(buf)
            byte_count = len(raw_pcm)
            kb = byte_count / 1024
            logger.debug(f"Audio captured — user: {display}, size: {kb:.1f} KB raw PCM")

            if byte_count < 1024:
                logger.debug(f"Skipping {display} — audio too short ({byte_count} bytes)")
                summary_lines.append(f"🎙️ **{display}**: *(audio too short)*")
                continue

            valid_streams.append(raw_pcm)

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

            filename = f"recorded_{user_id}_{timestamp}.ogg"
            files_to_send.append(discord.File(io.BytesIO(opus_bytes), filename=filename))
            pending_saves.append((filename, opus_bytes))

            summary_lines.append(f"🎙️ **{display}**: `{filename}`")

        # Down-mix every speaker into one combined "meeting recording" file
        if len(valid_streams) > 1:
            try:
                mix_bytes = await _mix_and_encode(valid_streams)
                if len(mix_bytes) > upload_limit:
                    logger.debug("Meeting mix exceeded the upload limit at 32k, re-encoding at 16k.")
                    mix_bytes = await _mix_and_encode(valid_streams, bitrate="16k")

                mix_filename = f"meeting_mix_{timestamp}.ogg"
                files_to_send.append(discord.File(io.BytesIO(mix_bytes), filename=mix_filename))
                pending_saves.append((mix_filename, mix_bytes))
                summary_lines.append(f"🎧 **รวมทุกคน (Meeting Mix)**: `{mix_filename}`")
            except RuntimeError as exc:
                logger.error(f"Failed to mix combined audio: {exc}")

        # Post summary embed to Discord with the audio files attached
        embed = success_embed(
            "บันทึกเสียงเรียบร้อยค่ะ",
            f"เย้! หนูรวบรวมเสียงของ **{len(audio_data)}** คนมาให้แล้วน้า 🎵\n\n" + "\n".join(summary_lines),
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

        if guild_id in self._sessions:
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

        # The hub owns the sink — /transcribe and /ai voice can be listening to
        # the same VoiceClient, which only supports one sink between them.
        voice_hub.subscribe(voice_client, _HUB_KEY, want_timeline=True)
        self._sessions[guild_id] = ctx.channel

        logger.info(f"Started recording in guild {guild_id}, channel '{voice_channel.name}'")
        await ctx.respond(embed=info_embed(
            "🔴 เริ่มอัดเสียงแล้วค่ะ",
            f"หนูเข้ามาแล้วค่ะ! ตอนนี้กำลังตั้งใจฟังทุกคนอยู่ในห้อง **{voice_channel.name}** น้า 🎧\n\n"
            "ถ้าคุยกันเสร็จแล้ว อย่าลืมใช้คำสั่ง `/record stop` นะคะ!",
        ))

    @record.command(name="stop", description="⏹️ หยุดบันทึกเสียงและส่งไฟล์เสียงที่บันทึกไว้")
    async def record_stop(self, ctx: discord.ApplicationContext) -> None:
        """Stop recording and post the captured audio."""
        await ctx.defer()

        guild_id = ctx.guild.id

        if guild_id not in self._sessions:
            raise UserWarning(
                "ยังไม่ได้อัดเสียงค่ะ",
                "เอ๊ะ... หนูยังไม่ได้อัดเสียงเลยนะคะ ถ้าอยากให้หนูอัด ใช้คำสั่ง `/record start` ก่อนน้า (・_・;)",
            )

        channel = self._sessions.pop(guild_id)

        # Snapshot the timeline *before* unsubscribing: the hub may stop the
        # capture and drop the sink on the way out.
        sink = voice_hub.sink_for(guild_id)
        audio_data = dict(sink.audio_data) if sink else {}
        voice_hub.unsubscribe(guild_id, _HUB_KEY)
        # Safe before the file is delivered — the audio is already snapshotted,
        # and rendering it has nothing to do with being in the channel.
        await voice_hub.release_voice(ctx.guild)

        logger.info(f"Stopped recording in guild {guild_id}")
        await ctx.respond(embed=info_embed(
            "⏹️ หยุดอัดเสียงแล้วค่ะ",
            "หนูหยุดอัดเสียงแล้วค่ะ! ขอเวลาประมวลผลแป๊บนึงนะคะ เดี๋ยวหนูส่งไฟล์ให้ค่า (´• ω •`) ♡",
        ))

        await self._deliver_recording(guild_id, channel, audio_data)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Drop the subscription if the bot gets disconnected mid-recording."""
        if member != self.bot.user:
            return
        if before.channel is None or after.channel is not None:
            return

        guild_id = member.guild.id
        if self._sessions.pop(guild_id, None) is None:
            return

        logger.info(f"Bot left voice in guild {guild_id} — dropping /record session")
        voice_hub.unsubscribe(guild_id, _HUB_KEY)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ListenerCog(bot))
