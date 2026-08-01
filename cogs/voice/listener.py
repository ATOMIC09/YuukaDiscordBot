"""
cogs/voice/listener.py
Voice receive cog — listens to users speaking and saves audio.

How it works
------------
1. Bot joins a voice channel (or reuses an existing VoiceClient)
2. `voice_client.start_recording(sink, callback)` begins capturing audio.
   We use a custom TimeAlignedSink rather than WaveSink: pycord's base
   Sink.write() just appends whatever PCM arrives with no regard for real
   elapsed time, so pauses between sentences vanish and nothing lines up
   across speakers. TimeAlignedSink pads each speaker's buffer with
   silence based on each packet's RTP timestamp (see its docstring for
   why wall-clock timing alone isn't reliable here).
3. When `voice_client.stop_recording()` is called, the callback fires.
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
import threading
import time

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import error_embed, info_embed, success_embed, warning_embed
from utils.errors import UserError, UserWarning

# Opus decoder output constants (pycord hardcoded values)
_OPUS_CHANNELS = 2
_OPUS_SAMPLE_RATE = 48_000  # Hz
_BYTES_PER_FRAME = _OPUS_CHANNELS * 2  # 16-bit samples, stereo


class TimeAlignedSink(discord.sinks.Sink):
    """
    Recording sink that lays each speaker's PCM onto a shared timeline
    instead of just concatenating packets back-to-back.

    pycord's base Sink.write() (discord/sinks/core.py) appends whatever PCM
    arrives with zero regard for real elapsed time, so pauses between
    sentences vanish and there's no way to line multiple speakers up against
    each other afterward.

    Gaps within a single speaker's own stream are measured using each
    packet's RTP timestamp — a 48kHz sample clock stamped by Discord's
    client at encode time — rather than wall-clock time at the moment we
    process it. This was confirmed necessary by testing: our own packet
    processing can stall for seconds at a time (thread scheduling, not
    network loss — sequence numbers stayed contiguous throughout), which
    wall-clock timing mistook for real silence, corrupting playback. RTP
    timestamps are immune to that since they reflect when the audio was
    actually captured, not when we got around to handling it.

    RTP clocks aren't comparable across different speakers' streams (each
    starts at an arbitrary per-session offset), so there's no source of
    truth for cross-speaker alignment. We fall back to wall-clock only
    once, to anchor each speaker's very first packet onto the shared
    session timeline (used by `_mix_and_encode`) — a one-time offset
    rather than a per-gap error, so it doesn't compound the way measuring
    every gap by wall-clock did.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._start_time: float | None = None
        self._lock = threading.Lock()
        self._last_seq: dict[int, int] = {}
        self._last_rtp_ts: dict[int, int] = {}
        self._last_pcm_len: dict[int, int] = {}

    def write(self, data, user) -> None:
        from discord.voice.packets import VoiceData

        is_voice_data = isinstance(data, VoiceData)
        pcm = data.pcm if is_voice_data else data
        if not pcm:
            return

        user_id = getattr(user, "id", None) or 0
        seq = data.packet.sequence if is_voice_data else None
        rtp_ts = data.packet.timestamp if is_voice_data else None

        with self._lock:
            now = time.perf_counter()
            if self._start_time is None:
                self._start_time = now

            buf = self.audio_data.setdefault(user_id, bytearray())
            last_rtp_ts = self._last_rtp_ts.get(user_id)
            last_pcm_len = self._last_pcm_len.get(user_id)

            if rtp_ts is not None and last_rtp_ts is not None and last_pcm_len is not None:
                delta_samples = (rtp_ts - last_rtp_ts) & 0xFFFFFFFF
                gap = delta_samples * _BYTES_PER_FRAME - last_pcm_len
            else:
                # First packet from this user this session: no prior RTP timestamp
                # to diff against, so anchor them onto the shared timeline via
                # wall-clock — a one-time offset, not compounded on every gap.
                gap = int((now - self._start_time) * _OPUS_SAMPLE_RATE) * _BYTES_PER_FRAME - len(buf)

            if gap > 0:
                buf.extend(b"\x00" * gap)

            if abs(gap) > _BYTES_PER_FRAME:
                last_seq = self._last_seq.get(user_id)
                seq_jump = (seq - last_seq) & 0xFFFF if seq is not None and last_seq is not None else None
                logger.debug(
                    f"[TimeAlignedSink] user={user_id} gap={gap / _BYTES_PER_FRAME / _OPUS_SAMPLE_RATE * 1000:.0f}ms "
                    f"seq_jump={seq_jump} pcm_len={len(pcm)} buf_len_before={len(buf)} "
                    f"elapsed={now - self._start_time:.3f}s"
                )

            buf.extend(pcm)

            if seq is not None:
                self._last_seq[user_id] = seq
            if rtp_ts is not None:
                self._last_rtp_ts[user_id] = rtp_ts
            self._last_pcm_len[user_id] = len(pcm)

    def cleanup(self) -> None:
        self.finished = True


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
    speaker, all sharing the same timeline courtesy of TimeAlignedSink)
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
        self._active_sinks: dict[int, TimeAlignedSink] = {}

    async def _on_recording_done(self, exception: Exception | None, /) -> None:
        active_sink: TimeAlignedSink | None = None
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
        valid_streams: list[bytes] = []  # per-speaker PCM that passed the length check, for mixing
        upload_limit = channel.guild.filesize_limit if channel.guild else 10 * 1024 * 1024
        timestamp = int(time.time())

        for user_id, buf in active_sink.audio_data.items():
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
        sink = TimeAlignedSink()
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
