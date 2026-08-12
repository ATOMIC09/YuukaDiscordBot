import asyncio
import collections
import dataclasses
import math
import queue
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from urllib.parse import urlparse

import discord
import numpy as np
import yt_dlp

try:
    from yt_dlp.extractor.youtube.jsc._builtin import ejs
except ImportError:
    pass
from discord.ext import commands

from bot.logger import logger
from utils.embeds import success_embed, error_embed, info_embed
from utils.errors import UserError
from utils.playlist_store import (
    PlaylistDataError,
    PlaylistExpiredError,
    PlaylistNotFoundError,
    PlaylistTrack,
    SavedPlaylist,
    PlaylistStore,
    PlaylistStoreError,
)

yt_dlp.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'extract_flat': 'in_playlist',
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'options': '-vn',
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 0 -probesize 32",
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

FRAME_MS = 20
PCM_FRAME_BYTES = 3840  # 20 ms of 48 kHz, 16-bit, stereo PCM
PCM_DTYPE = "<i2"  # what ffmpeg's `-f s16le` writes, regardless of host endianness
PCM_SAMPLE_MIN = -32768
PCM_SAMPLE_MAX = 32767
SILENCE_FRAME = b"\x00" * PCM_FRAME_BYTES
BUFFER_SECONDS = 5.0
PREFILL_SECONDS = 1.0
CROSSFADE_SECONDS = 7.0
CROSSFADE_BUFFER_SECONDS = BUFFER_SECONDS
CROSSFADE_STARTUP_MAX_WAIT_SECONDS = 20.0
CROSSFADE_STARTUP_POLL_SECONDS = 0.25
CROSSFADE_PRELOAD_LEAD_SECONDS = CROSSFADE_BUFFER_SECONDS + PREFILL_SECONDS
SEEK_BACKWARD_SECONDS = 10.0
SEEK_FORWARD_SECONDS = 30.0
PROGRESS_BAR_SLOTS = 20


def equal_power_gains(fade_frames: int) -> tuple[list[float], list[float]]:
    """Constant-energy fade curves, one gain pair per frame of the overlap.

    A linear ramp drops both tracks to 0.5 amplitude at the midpoint, which for
    uncorrelated audio sums to half the power - an audible 3 dB sag every time.
    cos/sin keeps `out**2 + in**2 == 1` the whole way across instead. The tables
    run to `fade_frames` inclusive so the final frame can index a clean 0.0/1.0.
    """
    step = math.pi / 2 / fade_frames
    fade_out = [math.cos(index * step) for index in range(fade_frames + 1)]
    fade_in = [math.sin(index * step) for index in range(fade_frames + 1)]
    return fade_out, fade_in

class BufferedAudioSource(discord.AudioSource):
    """
    Wraps a PCM AudioSource with a background thread that reads ahead into an
    in-memory queue, so a momentary network/decode stall doesn't turn into an
    audible gap - Discord's playback thread drains the queue instead of racing
    ffmpeg's pipe directly.
    """
    def __init__(
        self,
        source: discord.AudioSource,
        buffer_seconds: float = BUFFER_SECONDS,
        prefill_seconds: float = PREFILL_SECONDS,
        on_underrun=None,
    ):
        self._source = source
        self._buffer_chunks = max(1, int(buffer_seconds * 1000 / FRAME_MS))
        self._prefill_chunks = max(1, int(prefill_seconds * 1000 / FRAME_MS))
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=self._buffer_chunks)
        self._ready = threading.Event()
        self._finished = threading.Event()
        self._stopped = threading.Event()
        self._on_underrun = on_underrun
        self._consecutive_underruns = 0
        self._thread = threading.Thread(target=self._buffer_loop, daemon=True)
        self._thread.start()

    def _buffer_loop(self):
        try:
            filled = 0
            while not self._stopped.is_set():
                data = self._source.read()
                if not data:
                    break
                while not self._stopped.is_set():
                    try:
                        self._queue.put(data, timeout=0.2)
                        break
                    except queue.Full:
                        continue
                if not self._ready.is_set():
                    filled += 1
                    if filled >= self._prefill_chunks:
                        self._ready.set()
        finally:
            self._finished.set()
            self._ready.set()

    def wait_ready(self, timeout: float = 3.0):
        self._ready.wait(timeout=timeout)

    def started_ok(self) -> bool:
        """Whether the decoder produced audio rather than dying on startup.

        Only meaningful before anything drains the queue: a decoder that has
        already finished without a single buffered frame never played at all,
        which is what an expired stream URL looks like.
        """
        return not (self._finished.is_set() and self._queue.empty())

    def is_full(self) -> bool:
        """Whether the buffer has reached its full depth and gone idle.

        Right after a track starts, this thread is racing to fill from the 1s
        prefill up to the full cushion, competing for network/CPU the whole
        way. Once full, it just tops off one frame per 20ms and has slack to
        spare - the buffer is a lot less exposed to competing background work.
        """
        return self._queue.full()

    def read(self) -> bytes:
        try:
            frame = self._queue.get_nowait()
        except queue.Empty:
            if self._finished.is_set():
                return b''
            # Discord requests a frame every 20 ms. Blocking this send thread
            # for 500 ms on a slow decoder turns one buffer miss into a long,
            # audible stutter. Keep the audio clock moving with silence while
            # the background reader catches up instead.
            self._consecutive_underruns += 1
            if self._on_underrun and (
                self._consecutive_underruns == 1
                or self._consecutive_underruns % 250 == 0
            ):
                try:
                    self._on_underrun(self._consecutive_underruns)
                except Exception:
                    pass
            return SILENCE_FRAME
        self._consecutive_underruns = 0
        return frame

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        self._stopped.set()
        try:
            self._source.cleanup()
        except Exception:
            pass


class SeamlessCrossfadeSource(discord.AudioSource):
    """A persistent Discord source that can mix in a preloaded PCM stream.

    Volume is applied here rather than by wrapping this source in a
    `PCMVolumeTransformer`: the pinned py-cord build scales samples with a
    Python loop, and stacking that on top of the fade would mean two
    per-sample passes per frame on the voice send thread.
    """

    def __init__(self, current: BufferedAudioSource, volume: float = 1.0):
        self._current = current
        self._next: BufferedAudioSource | None = None
        self._fade_frames = 0
        self._fade_frame = 0
        self._frames_until_fade = 0
        self._mix_started = False
        self._fade_out_gains: list[float] = []
        self._fade_in_gains: list[float] = []
        self._on_fade_started = None
        self._on_fade_finished = None
        self._volume = max(0.0, float(volume))
        self._generation = 0
        self._lock = threading.Lock()

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float):
        # A bare float assignment; `read` snapshots it once per frame.
        self._volume = max(0.0, float(value))

    def schedule_crossfade(
        self,
        next_source: BufferedAudioSource,
        duration: float,
        frames_until_fade: int,
        on_fade_started,
        on_fade_finished,
    ):
        fade_frames = max(1, round(duration * 1000 / FRAME_MS))
        # Built outside the lock: this is the only trigonometry in the path, and
        # the send thread must never wait on it.
        fade_out, fade_in = equal_power_gains(fade_frames)
        with self._lock:
            self._next = next_source
            self._fade_frames = fade_frames
            self._fade_out_gains = fade_out
            self._fade_in_gains = fade_in
            self._fade_frame = 0
            self._frames_until_fade = max(0, frames_until_fade)
            self._mix_started = False
            self._on_fade_started = on_fade_started
            self._on_fade_finished = on_fade_finished

    def cancel_scheduled_crossfade(self):
        with self._lock:
            if self._mix_started:
                return None
            next_source = self._next
            self._next = None
            self._on_fade_started = None
            self._on_fade_finished = None
            return next_source

    def has_pending_crossfade(self) -> bool:
        with self._lock:
            return self._next is not None

    def is_crossfade_active(self) -> bool:
        with self._lock:
            return self._next is not None and self._mix_started

    def current_buffer_full(self) -> bool:
        with self._lock:
            current = self._current
        return current.is_full()

    def swap_current(self, new_source: BufferedAudioSource) -> BufferedAudioSource | None:
        """Replace the playing deck in place - how a seek lands.

        The voice client goes on pulling frames from this same object, so the
        track never "ends" and `after_playing` never advances the queue. The
        caller must have cleared any armed crossfade first: its frame countdown
        was measured against the deck being retired. Returns the displaced deck
        so the caller can tear it down away from the send thread.
        """
        with self._lock:
            displaced = self._current
            self._current = new_source
            self._generation += 1
        return displaced

    def _scale(self, frame: bytes, gain: float) -> bytes:
        if not frame:
            return frame
        if gain == 1.0:
            return frame
        samples = np.frombuffer(frame, dtype=PCM_DTYPE).astype(np.float32)
        samples *= gain
        np.clip(samples, PCM_SAMPLE_MIN, PCM_SAMPLE_MAX, out=samples)
        return samples.astype(PCM_DTYPE).tobytes()

    def _mix(self, current: bytes, next_frame: bytes, fade_index: int, volume: float) -> bytes:
        """Blend both decks and apply volume in a single vectorised pass."""
        out_gain = self._fade_out_gains[fade_index] * volume
        in_gain = self._fade_in_gains[fade_index] * volume
        mixed = np.frombuffer(current, dtype=PCM_DTYPE).astype(np.float32) * out_gain
        mixed += np.frombuffer(next_frame, dtype=PCM_DTYPE).astype(np.float32) * in_gain
        np.clip(mixed, PCM_SAMPLE_MIN, PCM_SAMPLE_MAX, out=mixed)
        return mixed.astype(PCM_DTYPE).tobytes()

    def read(self) -> bytes:
        with self._lock:
            deck = self._current
            generation = self._generation
        current = deck.read()
        volume = self._volume
        callback = None
        finish_callback = None
        with self._lock:
            if generation != self._generation:
                # A seek retired this deck while we were blocked reading it.
                # The empty frame that a torn-down deck returns means "replaced",
                # not "track over" - passing it on would stop the voice client
                # and advance the queue. Emit 20 ms of silence instead and let
                # the next call pick up the deck that took its place.
                return SILENCE_FRAME
            next_source = self._next

        if not next_source:
            return self._scale(current, volume)

        with self._lock:
            if self._frames_until_fade > 0:
                if current:
                    self._frames_until_fade -= 1
                    return self._scale(current, volume)
                # The outgoing stream ended before the position estimate said it
                # would. Begin the overlap now rather than dropping into silence
                # and tearing down a deck that is already buffered and ready.
                self._frames_until_fade = 0
            fade_index = min(self._fade_frame, self._fade_frames)
            if self._fade_frame == 0 and self._on_fade_started:
                self._mix_started = True
                callback = self._on_fade_started
                self._on_fade_started = None

        if callback:
            callback()

        next_frame = next_source.read()
        if not next_frame:
            return self._scale(current, volume)
        if not current:
            # Outgoing deck is spent mid-fade. Keep running the same curve
            # against silence so the incoming track still ramps up to full
            # instead of snapping there, which clicks.
            current = SILENCE_FRAME

        mixed = self._mix(current, next_frame, fade_index, volume)
        with self._lock:
            self._fade_frame += 1
            if self._fade_frame >= self._fade_frames:
                old_current = self._current
                self._current = next_source
                self._next = None
                self._on_fade_started = None
                finish_callback = self._on_fade_finished
                self._on_fade_finished = None
                old_current.cleanup()
        if finish_callback:
            finish_callback()
        return mixed

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        with self._lock:
            sources = (self._current, self._next)
            self._next = None
            self._on_fade_started = None
            self._on_fade_finished = None
        for source in sources:
            if source:
                source.cleanup()

def format_duration(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "Live/Unknown"
    years, rem = divmod(int(seconds), 31536000)
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if years > 0:
        return f"{years}y {days}d {hours:02d}:{mins:02d}:{secs:02d}"
    if days > 0:
        return f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"

def render_progress_bar(position: float, duration: int, paused: bool = False) -> str:
    head = "⏸️" if paused else "▶️"
    elapsed = format_duration(int(position)) if position >= 1 else "0:00"
    if duration <= 0:
        return f"{head} 🔴 **LIVE**  `{elapsed}`"
    ratio = min(1.0, max(0.0, position / duration))
    knob = int(ratio * (PROGRESS_BAR_SLOTS - 1))
    bar = "▬" * knob + "🔘" + "▬" * (PROGRESS_BAR_SLOTS - 1 - knob)
    return f"{head} {bar}\n`{elapsed} / {format_duration(duration)}`"

def parse_timestamp(raw: str) -> float | None:
    parts = raw.strip().split(":")
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        return None
    total = 0.0
    for part in parts:
        total = total * 60 + int(part)
    return total

@dataclasses.dataclass
class Track:
    title: str
    duration: int
    thumbnail: str
    requester: discord.User | discord.Member
    original_url: str
    stream_url: str | None = None
    uploader: str | None = None
    view_count: int | None = None
    cover_bytes: bytes | None = None
    like_count: int | None = None
    comment_count: int | None = None
    upload_date: str | None = None
    album: str | None = None
    year: str | None = None
    channel_follower_count: int | None = None
    filesize: int | None = None
    bitrate: float | None = None

    def __post_init__(self):
        if self.duration is None:
            self.duration = 0

class AudioState:
    def __init__(self, bot: discord.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue: collections.deque[Track] = collections.deque()
        self.current: Track | None = None
        self.current_played: bool = False
        self.history: collections.deque[Track] = collections.deque(maxlen=10)
        self.forward_history: collections.deque[Track] = collections.deque(maxlen=10)
        self.is_rewinding: bool = False
        self.rewind_lock: asyncio.Lock = asyncio.Lock()
        self.seek_lock: asyncio.Lock = asyncio.Lock()
        self.voice_client: discord.VoiceClient | None = None
        self.loop_mode: str = "off"  # "off", "track", "queue"
        self.crossfade_enabled: bool = False
        self.crossfade_next: Track | None = None
        self.crossfade_audio_source: BufferedAudioSource | None = None
        self.active_audio_source: SeamlessCrossfadeSource | None = None
        self.crossfade_task: asyncio.Task | None = None
        self.crossfade_prepare_task: asyncio.Task | None = None
        self.playback_started_at: float | None = None
        self.playback_paused_at: float | None = None
        self.playback_offset_seconds: float = 0.0
        self.restore_start_position_seconds: float = 0.0
        self.volume: float = 1.0
        self.is_playing_loop: bool = False
        self.skip_request: bool = False
        self.last_controller_message: discord.WebhookMessage | discord.Message | None = None
        self.last_queue_message: discord.WebhookMessage | discord.Message | None = None
        self.text_channel: discord.TextChannel | discord.Thread | None = None
        self.idle_task: asyncio.Task | None = None
        self.suppress_next_after: bool = False
        self.playback_generation: int = 0

class PlayerControls(discord.ui.View):
    def __init__(self, cog: "PlayerCog", state: "AudioState"):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state
        self.update_buttons()

    def update_buttons(self):
        self.rewind.disabled = len(self.state.history) == 0

        # Live streams have no duration to seek within, and mid-fade there are
        # two tracks playing at once with no single position to move.
        can_seek = self.cog._can_seek(self.state)
        self.seek_back.disabled = not can_seek
        self.seek_forward.disabled = not can_seek

        if self.state.voice_client and self.state.voice_client.is_paused():
            self.pause_resume.emoji = "▶️"
            self.pause_resume.style = discord.ButtonStyle.primary
        else:
            self.pause_resume.emoji = "⏸️"
            self.pause_resume.style = discord.ButtonStyle.success
            
        if self.state.loop_mode == "off":
            self.loop.emoji = "🔁"
            self.loop.style = discord.ButtonStyle.secondary
        elif self.state.loop_mode == "queue":
            self.loop.emoji = "🔁"
            self.loop.style = discord.ButtonStyle.primary
        elif self.state.loop_mode == "track":
            self.loop.emoji = "🔂"
            self.loop.style = discord.ButtonStyle.success

        # Use Blurple for the enabled state and grey while disabled.
        self.crossfade.label = None
        self.crossfade.emoji = "🔀"
        self.crossfade.style = (
            discord.ButtonStyle.primary
            if self.state.crossfade_enabled
            else discord.ButtonStyle.secondary
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("หนูไม่เห็นเซนเซย์ในห้องเสียงเลยนะคะ (´・ω・)", ephemeral=True)
            return False
        if self.state.voice_client and interaction.user.voice.channel.id != self.state.voice_client.channel.id:
            await interaction.response.send_message("เซนเซย์อยู่คนละห้องกับหนูนะคะ (・`ω´・)", ephemeral=True)
            return False
        return True

    async def _handle_seek(self, interaction: discord.Interaction, delta: float):
        state = self.state
        if not self.cog._can_seek(state):
            return await interaction.response.send_message(
                "ตอนนี้เลื่อนเวลาไม่ได้ค่ะ (´・ω・)", ephemeral=True
            )
        if state.seek_lock.locked():
            # Opening a decoder takes about a second; let the one in flight land
            # rather than stacking another FFmpeg process behind it.
            return await interaction.response.send_message(
                "รอสักครู่นะคะ หนูกำลังเลื่อนเพลงอยู่ค่ะ (´・ω・)", ephemeral=True
            )

        await interaction.response.defer()
        async with state.seek_lock:
            track = state.current
            if not track:
                return
            position = self.cog._current_playback_position(state)
            target = min(max(0.0, position + delta), max(0.0, track.duration - 1))
            await self.cog._seek_async(state, target)

        self.update_buttons()
        try:
            if state.current:
                embed = self.cog._build_player_embed(state.current, state)
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.edit_original_response(view=self)
        except Exception:
            pass

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏮️", row=0)
    async def rewind(self, button: discord.ui.Button, interaction: discord.Interaction):
        ok = await self.cog._rewind_async(self.state.guild_id)
        if not ok:
            return await interaction.response.send_message("ไม่มีเพลงก่อนหน้าให้ย้อนกลับนะคะ (´・ω・)", ephemeral=True)
        await interaction.response.defer()

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏪", row=0)
    async def seek_back(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._handle_seek(interaction, -SEEK_BACKWARD_SECONDS)

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="⏸️", row=0)
    async def pause_resume(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.state.voice_client:
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่นะคะ", ephemeral=True)
            
        if self.state.voice_client.is_paused():
            self.state.voice_client.resume()
            self.cog._mark_playback_resumed(self.state)
            self.cog._request_crossfade_prepare(self.state)
        elif self.state.voice_client.is_playing():
            self.state.voice_client.pause()
            self.cog._mark_playback_paused(self.state)
        else:
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่นะคะ", ephemeral=True)

        self.update_buttons()

        if self.state.current:
            embed = self.cog._build_player_embed(self.state.current, self.state)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏩", row=0)
    async def seek_forward(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._handle_seek(interaction, SEEK_FORWARD_SECONDS)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏭️", row=0)
    async def skip(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.state.voice_client or not self.state.voice_client.is_playing():
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่ให้ข้ามนะคะ", ephemeral=True)
        
        self.state.skip_request = True
        self.state.voice_client.stop()
        await interaction.response.defer()

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🔁", row=1)
    async def loop(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.state.loop_mode == "off":
            self.state.loop_mode = "queue"
        elif self.state.loop_mode == "queue":
            self.state.loop_mode = "track"
        else:
            self.state.loop_mode = "off"

        self.cog._refresh_crossfade_for_loop_change(self.state)
        self.update_buttons()
        
        embed = self.cog._build_player_embed(self.state.current, self.state)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🔀", row=1)
    async def crossfade(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.state.crossfade_enabled = not self.state.crossfade_enabled
        if not self.state.crossfade_enabled:
            self.cog._cancel_prepared_crossfade(self.state)
        if self.state.crossfade_enabled:
            logger.debug(
                f"[Crossfade] guild {self.state.guild_id}: enabled via player button; "
                "preparing the queued next track for seamless mixing"
            )
        else:
            logger.debug(
                f"[Crossfade] guild {self.state.guild_id}: disabled via player button; "
                "future transitions will not be crossfaded"
            )
        self.update_buttons()

        if self.state.current:
            embed = self.cog._build_player_embed(self.state.current, self.state)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            # The player controller can be clicked while the first track is
            # still being prepared, before `_play_next_async` assigns current.
            await interaction.response.edit_message(view=self)

        if self.state.crossfade_enabled:
            self.cog._request_crossfade_prepare(self.state)

    async def save(self, button: discord.ui.Button, interaction: discord.Interaction):
        try:
            code, track_count = self.cog.save_playlist(self.state, interaction.user.id)
        except PlaylistDataError:
            logger.warning(
                f"Playlist save rejected in guild {self.state.guild_id}: empty or invalid queue"
            )
            await interaction.response.send_message(
                embed=error_embed("บันทึกคิวไม่ได้ค่ะ", "ไม่มีเพลงให้บันทึกในคิวตอนนี้นะคะ"),
                ephemeral=True,
            )
            return
        except PlaylistStoreError:
            logger.error(f"Playlist save failed in guild {self.state.guild_id}")
            await interaction.response.send_message(
                embed=error_embed("บันทึกคิวไม่ได้ค่ะ", "ระบบจัดเก็บเพลย์ลิสต์มีปัญหาชั่วคราว ลองใหม่อีกครั้งนะคะ"),
                ephemeral=True,
            )
            return

        logger.info(f"Saved playlist in guild {self.state.guild_id} with {track_count} tracks")
        await interaction.response.send_message(
            embed=success_embed(
                "💾 บันทึกเพลย์ลิสต์แล้วค่ะ",
                f"รหัสเพลย์ลิสต์คือ `{code}`\nแชร์ให้คนอื่นใช้ `/music restore {code}` ได้ภายใน 30 วันนะคะ",
            ),
            ephemeral=True,
        )

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="⏹️", row=1)
    async def stop(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.cog._clear_crossfade(self.state)
        self.state.queue.clear()
        self.state.history.clear()
        self.state.forward_history.clear()
        self.state.loop_mode = "off"
        self.state.last_controller_message = None

        if self.state.voice_client and self.state.voice_client.is_playing():
            self.state.voice_client.stop()

        try:
            embeds = interaction.message.embeds
            if embeds:
                embeds[0].color = discord.Color.dark_theme()
                embeds[0].description = None
                await interaction.response.edit_message(embed=embeds[0], view=None)
            else:
                await interaction.response.edit_message(view=None)
        except Exception:
            pass
        
    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏱️", row=1)
    async def refresh(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.update_buttons()
        if self.state.current:
            embed = self.cog._build_player_embed(self.state.current, self.state)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="💾", row=1)
    async def save_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.save(button, interaction)


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.state.last_controller_message:
            try:
                await self.state.last_controller_message.edit(view=self)
            except Exception:
                pass

class JumpToPageModal(discord.ui.Modal):
    def __init__(self, paginator: "QueuePaginator"):
        super().__init__(title="ไปหน้าไหนดีคะ?")
        self.paginator = paginator

        self.page_input = discord.ui.InputText(
            label=f"หมายเลขหน้า (1-{paginator.total_pages})",
            placeholder="พิมพ์หมายเลขหน้าที่ต้องการค่ะ",
            style=discord.InputTextStyle.short,
            required=True,
        )
        self.add_item(self.page_input)

    async def callback(self, interaction: discord.Interaction):
        raw = self.page_input.value.strip()
        if not raw.isdigit() or not (1 <= int(raw) <= self.paginator.total_pages):
            return await interaction.response.send_message(
                embed=error_embed("เลขหน้าไม่ถูกต้องค่ะ", f"กรุณาใส่เลขหน้าระหว่าง 1-{self.paginator.total_pages} นะคะ (´・ω・)"),
                ephemeral=True
            )

        self.paginator.current_page = int(raw)
        self.paginator.update_buttons()
        await interaction.response.edit_message(embed=self.paginator.get_embed(), view=self.paginator)

class QueuePaginator(discord.ui.View):
    def __init__(self, state: "AudioState", items_per_page: int = 10):
        super().__init__(timeout=None)
        self.state = state
        self.items_per_page = items_per_page
        self.current_page = 1
        self.total_pages = max(1, math.ceil(len(self._queue_tracks()) / self.items_per_page))
        self.update_buttons()

    def _queue_tracks(self) -> list[Track]:
        return ([self.state.crossfade_next] if self.state.crossfade_next else []) + list(self.state.queue)
        
    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎶 คิวเพลงทั้งหมด", color=discord.Color.blurple())
        
        desc = ""
        if self.state.current:
            dur_str = format_duration(self.state.current.duration)
            desc += f"**▶️ กำลังเล่น:** [{self.state.current.title}]({self.state.current.original_url}) `[{dur_str}]`\n\n"
            
        queue_tracks = self._queue_tracks()
        if not queue_tracks:
            desc += "*คิวว่างเปล่าค่ะ*"
            embed.description = desc
            return embed
            
        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        queue_slice = queue_tracks[start_idx:end_idx]
        
        for i, track in enumerate(queue_slice, start=start_idx + 1):
            dur_str = format_duration(track.duration)
            entry = f"{i}. [{track.title}]({track.original_url})\n`[{dur_str}]` - {track.requester.mention}\n"
            if len(desc) + len(entry) > 4096:
                break
            desc += entry
        embed.description = desc
        total_duration = sum(t.duration or 0 for t in queue_tracks)
        total_str = format_duration(total_duration)
        embed.set_footer(text=f"หน้า {self.current_page}/{self.total_pages} | ทั้งหมด {len(queue_tracks)} เพลง | รวม {total_str}")
        return embed
        
    def update_buttons(self):
        self.total_pages = max(1, math.ceil(len(self._queue_tracks()) / self.items_per_page))
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
            
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
        self.jump_button.disabled = self.total_pages <= 1

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, row=0)
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢", style=discord.ButtonStyle.secondary, row=0)
    async def jump_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(JumpToPageModal(self))

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.secondary)
    async def reload_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

def _discord_timestamp(value, style: str = "F") -> str:
    return f"<t:{int(value.timestamp())}:{style}>"


class RestoreConfirmationView(discord.ui.View):
    def __init__(
        self,
        cog: "PlayerCog",
        playlist: SavedPlaylist,
        requester_id: int,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.playlist = playlist
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            embed=error_embed("ปุ่มนี้ไม่ใช่ของเซ็นเซย์ค่ะ", "เปิดหน้ารายการแล้วเลือกเพลย์ลิสต์ของตัวเองได้เลยนะคะ"),
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="♻️ โหลดเพลย์ลิสต์", style=discord.ButtonStyle.primary)
    async def confirm_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog._restore_saved_playlist(interaction, self.playlist.code)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=info_embed("ยกเลิกแล้วค่ะ", "คิวที่กำลังเล่นอยู่ยังเหมือนเดิมนะคะ"),
            view=None,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class DeletePlaylistConfirmationView(discord.ui.View):
    def __init__(
        self,
        cog: "PlayerCog",
        playlist: SavedPlaylist,
        requester_id: int,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.playlist = playlist
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            embed=error_embed("ปุ่มนี้ไม่ใช่ของเซ็นเซย์ค่ะ", "เปิดหน้ารายการแล้วเลือกเพลย์ลิสต์ที่ต้องการได้เลยนะคะ"),
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="🗑️ ลบเพลย์ลิสต์", style=discord.ButtonStyle.danger)
    async def confirm_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog._delete_saved_playlist(interaction, self.playlist.code)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=info_embed("ยกเลิกแล้วค่ะ", "เพลย์ลิสต์นี้ยังอยู่เหมือนเดิมนะคะ"),
            view=None,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class PlaylistDetailsPaginator(discord.ui.View):
    def __init__(self, cog: "PlayerCog", playlist: SavedPlaylist, items_per_page: int = 10):
        super().__init__(timeout=180)
        self.cog = cog
        self.playlist = playlist
        self.items_per_page = items_per_page
        self.current_page = 1
        self.total_pages = max(1, math.ceil(len(playlist.tracks) / items_per_page))
        self.update_buttons()

    def get_embed(self) -> discord.Embed:
        start = (self.current_page - 1) * self.items_per_page
        end = start + self.items_per_page
        tracks = self.playlist.tracks[start:end]
        lines = []
        for number, track in enumerate(tracks, start=start + 1):
            title = track["title"] or track["query"]
            lines.append(f"{number}. [{title}]({track['query']})")

        embed = discord.Embed(
            title="💾 รายละเอียดเพลย์ลิสต์",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="รหัสเพลย์ลิสต์", value=f"`{self.playlist.code}`", inline=False)
        embed.add_field(name="ผู้สร้าง", value=f"<@{self.playlist.owner_id}>", inline=True)
        embed.add_field(name="จำนวนเพลง", value=f"`{len(self.playlist.tracks)}` เพลง", inline=True)
        embed.add_field(
            name="สร้างเมื่อ",
            value=f"{_discord_timestamp(self.playlist.created_at)}\n{_discord_timestamp(self.playlist.created_at, 'R')}",
            inline=True,
        )
        embed.add_field(
            name="หมดอายุเมื่อ",
            value=f"{_discord_timestamp(self.playlist.expires_at)}\n{_discord_timestamp(self.playlist.expires_at, 'R')}",
            inline=True,
        )
        embed.set_footer(
            text=f"เพลง {start + 1}-{min(end, len(self.playlist.tracks))} จาก {len(self.playlist.tracks)} | หน้า {self.current_page}/{self.total_pages}"
        )
        return embed

    def update_buttons(self):
        self.previous_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, row=0)
    async def previous_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="♻️", style=discord.ButtonStyle.secondary)
    async def load_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._show_restore_confirmation(interaction, self.playlist)

    @discord.ui.button(label="🗑️", style=discord.ButtonStyle.danger)
    async def delete_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._show_delete_confirmation(interaction, self.playlist)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class PlaylistNumberModal(discord.ui.Modal):
    def __init__(self, paginator: "PlaylistListPaginator", action: str):
        titles = {
            "details": "ดูรายละเอียดเพลย์ลิสต์",
            "load": "โหลดเพลย์ลิสต์",
            "delete": "ลบเพลย์ลิสต์",
        }
        super().__init__(title=titles[action])
        self.paginator = paginator
        self.action = action
        self.number_input = discord.ui.InputText(
            label=f"หมายเลขเพลย์ลิสต์ (1-{len(paginator.playlists)})",
            placeholder="พิมพ์หมายเลขจากรายการนะคะ",
            style=discord.InputTextStyle.short,
            required=True,
        )
        self.add_item(self.number_input)

    async def callback(self, interaction: discord.Interaction):
        raw = self.number_input.value.strip()
        if not raw.isdigit() or not (1 <= int(raw) <= len(self.paginator.playlists)):
            await interaction.response.send_message(
                embed=error_embed(
                    "หมายเลขเพลย์ลิสต์ไม่ถูกต้องค่ะ",
                    f"กรุณาใส่หมายเลขระหว่าง 1-{len(self.paginator.playlists)} นะคะ (´・ω・)",
                ),
                ephemeral=True,
            )
            return

        playlist = self.paginator.playlists[int(raw) - 1]
        if self.action == "load":
            await self.paginator.cog._show_restore_confirmation(interaction, playlist)
            return
        if self.action == "delete":
            await self.paginator.cog._show_delete_confirmation(interaction, playlist)
            return

        details = PlaylistDetailsPaginator(self.paginator.cog, playlist)
        await interaction.response.send_message(embed=details.get_embed(), view=details)


class PlaylistListPaginator(discord.ui.View):
    def __init__(
        self,
        cog: "PlayerCog",
        guild_id: int,
        playlists: list[SavedPlaylist],
        items_per_page: int = 10,
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.playlists = playlists
        self.items_per_page = items_per_page
        self.current_page = 1
        self.total_pages = max(1, math.ceil(len(playlists) / items_per_page))
        self.message = None
        self.update_buttons()

    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(title="💾 เพลย์ลิสต์ที่บันทึกไว้", color=discord.Color.blurple())
        start = (self.current_page - 1) * self.items_per_page
        end = start + self.items_per_page
        lines = []
        for number, playlist in enumerate(self.playlists[start:end], start=start + 1):
            lines.append(
                f"**{number}.** `{playlist.code}` • `{len(playlist.tracks)}` เพลง\n"
                f"ผู้สร้าง: <@{playlist.owner_id}> • สร้าง {_discord_timestamp(playlist.created_at, 'R')}\n"
                f"หมดอายุ {_discord_timestamp(playlist.expires_at, 'R')}"
            )
        embed.description = "\n\n".join(lines) or "*ยังไม่มีเพลย์ลิสต์ที่ใช้ได้ค่ะ*"
        embed.set_footer(
            text=f"หน้า {self.current_page}/{self.total_pages} | ทั้งหมด {len(self.playlists)} เพลย์ลิสต์"
        )
        return embed

    def update_buttons(self):
        self.total_pages = max(1, math.ceil(len(self.playlists) / self.items_per_page))
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
        self.previous_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
        self.page_button.disabled = self.total_pages <= 1
        self.details_button.disabled = not self.playlists
        self.load_button.disabled = not self.playlists
        self.delete_button.disabled = not self.playlists

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, row=0)
    async def previous_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢", style=discord.ButtonStyle.secondary, row=0)
    async def page_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(JumpToPageModal(self))

    @discord.ui.button(label="📄", style=discord.ButtonStyle.secondary, row=1)
    async def details_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(PlaylistNumberModal(self, "details"))

    @discord.ui.button(label="♻️", style=discord.ButtonStyle.secondary, row=1)
    async def load_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(PlaylistNumberModal(self, "load"))

    @discord.ui.button(label="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(PlaylistNumberModal(self, "delete"))

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def reload_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        try:
            self.playlists = self.cog.playlist_store.list_playlists(self.guild_id)
        except PlaylistStoreError:
            await interaction.response.send_message(
                embed=error_embed("โหลดรายการไม่ได้ค่ะ", "ระบบจัดเก็บเพลย์ลิสต์มีปัญหาชั่วคราว ลองใหม่อีกครั้งนะคะ"),
                ephemeral=True,
            )
            return
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class PlayerCog(commands.Cog):
    def __init__(self, bot: discord.Bot, playlist_store: PlaylistStore | None = None):
        self.bot = bot
        self.states: dict[int, AudioState] = {}
        # yt-dlp can be CPU-heavy and its work cannot be cancelled once it has
        # started. Keep it away from decoder prefill/cleanup so metadata work
        # never delays the path that supplies audio frames.
        self._metadata_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="music-metadata"
        )
        self._decoder_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="music-decoder"
        )
        self._crossfade_metadata_job: Future[dict | None] | None = None
        self.playlist_store = playlist_store or PlaylistStore()

    def cog_unload(self):
        self._metadata_executor.shutdown(wait=False, cancel_futures=True)
        self._decoder_executor.shutdown(wait=False, cancel_futures=True)

    def get_state(self, guild_id: int) -> AudioState:
        if guild_id not in self.states:
            self.states[guild_id] = AudioState(self.bot, guild_id)
        return self.states[guild_id]

    async def _show_restore_confirmation(
        self, interaction: discord.Interaction, playlist: SavedPlaylist
    ) -> None:
        view = RestoreConfirmationView(self, playlist, interaction.user.id)
        await interaction.response.send_message(
            embed=info_embed(
                "♻️ โหลดเพลย์ลิสต์นี้ไหมคะ?",
                f"เพลย์ลิสต์นี้มี `{len(playlist.tracks)}` เพลง และจะแทนที่คิวที่กำลังเล่นอยู่ค่ะ",
            ),
            view=view,
            ephemeral=True,
        )

    async def _show_delete_confirmation(
        self, interaction: discord.Interaction, playlist: SavedPlaylist
    ) -> None:
        view = DeletePlaylistConfirmationView(self, playlist, interaction.user.id)
        await interaction.response.send_message(
            embed=info_embed(
                "🗑️ ลบเพลย์ลิสต์นี้ไหมคะ?",
                f"เพลย์ลิสต์นี้มี `{len(playlist.tracks)}` เพลง และจะไม่สามารถกู้คืนได้นะคะ",
            ),
            view=view,
            ephemeral=True,
        )

    async def _delete_saved_playlist(
        self, interaction: discord.Interaction, code: str
    ) -> None:
        is_followup = interaction.response.is_done()
        if not is_followup:
            await interaction.response.defer(ephemeral=True)

        async def respond(*, embed: discord.Embed) -> None:
            if is_followup:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.edit_original_response(embed=embed)

        try:
            playlist = self.playlist_store.delete_playlist(code, interaction.guild.id)
        except PlaylistNotFoundError:
            logger.warning(f"Playlist delete rejected in guild {interaction.guild.id}: unavailable playlist")
            await respond(
                embed=error_embed("ลบเพลย์ลิสต์ไม่ได้ค่ะ", "เพลย์ลิสต์นี้ถูกลบหรือถูกใช้ไปแล้วนะคะ")
            )
            return
        except PlaylistExpiredError:
            logger.warning(f"Playlist delete rejected in guild {interaction.guild.id}: expired playlist")
            await respond(
                embed=error_embed("ลบเพลย์ลิสต์ไม่ได้ค่ะ", "เพลย์ลิสต์นี้หมดอายุไปแล้วค่ะ")
            )
            return
        except PlaylistDataError:
            logger.warning(f"Playlist delete rejected in guild {interaction.guild.id}: malformed playlist")
            await respond(
                embed=error_embed("ลบเพลย์ลิสต์ไม่ได้ค่ะ", "ข้อมูลเพลย์ลิสต์นี้ใช้ไม่ได้ค่ะ")
            )
            return
        except PlaylistStoreError:
            logger.exception(f"Playlist delete failed in guild {interaction.guild.id}")
            await respond(
                embed=error_embed("ลบเพลย์ลิสต์ไม่ได้ค่ะ", "ระบบจัดเก็บเพลย์ลิสต์มีปัญหาชั่วคราว ลองใหม่อีกครั้งนะคะ")
            )
            return

        logger.info(
            f"Deleted playlist in guild {interaction.guild.id} with {len(playlist.tracks)} tracks"
        )
        await respond(
            embed=success_embed("🗑️ ลบเพลย์ลิสต์แล้วค่ะ", "ลบเพลย์ลิสต์นี้ออกจากรายการแล้วนะคะ")
        )

    async def _show_restore_confirmation_for_code(
        self, interaction: discord.Interaction, code: str
    ) -> None:
        try:
            playlist = self.playlist_store.details(code, interaction.guild.id)
        except PlaylistNotFoundError:
            await interaction.response.send_message(
                embed=error_embed("ไม่พบรหัสเพลย์ลิสต์ค่ะ", "ตรวจสอบรหัสแล้วลองใหม่อีกครั้งนะคะ"),
                ephemeral=True,
            )
            return
        except PlaylistExpiredError:
            await interaction.response.send_message(
                embed=error_embed("รหัสเพลย์ลิสต์หมดอายุแล้วค่ะ", "บันทึกใหม่อีกครั้งเพื่อรับรหัสใหม่นะคะ"),
                ephemeral=True,
            )
            return
        except PlaylistDataError:
            await interaction.response.send_message(
                embed=error_embed("ข้อมูลเพลย์ลิสต์ใช้ไม่ได้ค่ะ", "ข้อมูลที่บันทึกไว้ไม่สมบูรณ์ ลองบันทึกคิวใหม่อีกครั้งนะคะ"),
                ephemeral=True,
            )
            return
        except PlaylistStoreError:
            logger.error(f"Playlist restore confirmation failed in guild {interaction.guild.id}")
            await interaction.response.send_message(
                embed=error_embed("กู้คืนคิวไม่ได้ค่ะ", "ระบบจัดเก็บเพลย์ลิสต์มีปัญหาชั่วคราว ลองใหม่อีกครั้งนะคะ"),
                ephemeral=True,
            )
            return

        await self._show_restore_confirmation(interaction, playlist)

    async def _show_saved_playlists(self, ctx: discord.ApplicationContext) -> None:
        await ctx.defer()
        try:
            playlists = self.playlist_store.list_playlists(ctx.guild.id)
        except PlaylistStoreError:
            logger.error(f"Playlist list failed in guild {ctx.guild.id}")
            await ctx.interaction.edit_original_response(
                embed=error_embed(
                    "โหลดรายการไม่ได้ค่ะ",
                    "ระบบจัดเก็บเพลย์ลิสต์มีปัญหาชั่วคราว ลองใหม่อีกครั้งนะคะ",
                )
            )
            return

        if not playlists:
            await ctx.interaction.edit_original_response(
                embed=info_embed(
                    "ยังไม่มีเพลย์ลิสต์ค่ะ",
                    "ตอนนี้ไม่มีเพลย์ลิสต์ที่บันทึกไว้และยังใช้ได้เลยนะคะ (´・ω・)",
                )
            )
            return

        paginator = PlaylistListPaginator(self, ctx.guild.id, playlists)
        message = await ctx.interaction.edit_original_response(
            embed=paginator.get_embed(), view=paginator
        )
        paginator.message = message

    @staticmethod
    def _playlist_tracks(state: AudioState) -> list[Track]:
        tracks = [state.current] if state.current else []
        if state.crossfade_next:
            tracks.append(state.crossfade_next)
        tracks.extend(state.queue)
        return tracks

    @staticmethod
    def _is_youtube_track(track: Track) -> bool:
        host = (urlparse(track.original_url).hostname or "").lower()
        return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")

    def save_playlist(self, state: AudioState, owner_id: int) -> tuple[str, int]:
        all_tracks = self._playlist_tracks(state)
        tracks = [track for track in all_tracks if self._is_youtube_track(track)]
        playlist_tracks = [
            {
                "query": track.original_url or track.title,
                "title": track.title,
                "duration": max(0, int(track.duration or 0)),
            }
            for track in tracks
        ]
        start_position = (
            self._current_playback_position(state)
            if state.current and self._is_youtube_track(state.current)
            else 0.0
        )
        logger.debug(
            f"Playlist save snapshot in guild {state.guild_id}: "
            f"tracks={len(playlist_tracks)}, skipped_non_youtube={len(all_tracks) - len(tracks)}, "
            f"current={state.current is not None}, "
            f"crossfade_pending={state.crossfade_next is not None}, "
            f"resume_offset={start_position:.1f}s"
        )
        code = self.playlist_store.save(
            state.guild_id,
            owner_id,
            playlist_tracks,
            start_position_seconds=start_position,
        )
        logger.debug(
            f"Playlist save persisted in guild {state.guild_id}: tracks={len(playlist_tracks)}"
        )
        return code, len(playlist_tracks)

    @staticmethod
    def _restore_tracks(
        playlist_tracks: list[PlaylistTrack], requester: discord.User | discord.Member
    ) -> list[Track]:
        return [
            Track(
                title=str(item["title"] or item["query"]),
                duration=item.get("duration", 0) if isinstance(item.get("duration", 0), int) else 0,
                thumbnail="",
                requester=requester,
                original_url=str(item["query"]),
            )
            for item in playlist_tracks
        ]

    async def _ensure_voice_connection(
        self, ctx: discord.ApplicationContext | discord.Interaction, state: AudioState
    ) -> None:
        requester = getattr(ctx, "author", None) or ctx.user
        if not requester.voice or not requester.voice.channel:
            raise UserError(
                "ยังไม่ได้เข้าห้องเสียงค่ะ",
                "เซ็นเซย์ต้องเข้าห้องเสียงก่อน แล้วหนูจะตามเข้าไปนะคะ",
            )

        channel = requester.voice.channel
        voice_client = ctx.guild.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.channel.id != channel.id:
                raise UserError(
                    "อยู่คนละห้องค่ะ",
                    "เซ็นเซย์ต้องอยู่ห้องเสียงเดียวกับหนูก่อนนะคะ",
                )
            state.voice_client = voice_client
            return

        if voice_client:
            try:
                await voice_client.disconnect(force=True)
            except Exception:
                pass
        state.voice_client = await channel.connect()

    def _replace_queue(self, state: AudioState, tracks: list[Track]) -> None:
        # Invalidate callbacks and queued transitions belonging to the source
        # being stopped, before the restored queue becomes visible to them.
        state.playback_generation += 1
        logger.debug(
            f"Playlist restore replacing queue in guild {state.guild_id}: "
            f"tracks={len(tracks)}, generation={state.playback_generation}, "
            f"was_active={bool(state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()))}"
        )
        self._clear_crossfade(state)
        state.queue.clear()
        state.history.clear()
        state.forward_history.clear()
        state.current = None
        state.current_played = False
        state.skip_request = False
        state.queue.extend(tracks)

        if state.voice_client and (
            state.voice_client.is_playing() or state.voice_client.is_paused()
        ):
            state.suppress_next_after = True
            state.voice_client.stop()

    async def _restore_playlist_to_state(
        self,
        state: AudioState,
        playlist_tracks: list[PlaylistTrack],
        requester: discord.User | discord.Member,
        start_position_seconds: float = 0.0,
    ) -> None:
        self._replace_queue(state, self._restore_tracks(playlist_tracks, requester))
        state.restore_start_position_seconds = start_position_seconds
        logger.debug(
            f"Playlist restore queued in guild {state.guild_id}: "
            f"tracks={len(playlist_tracks)}, resume_offset={start_position_seconds:.1f}s"
        )
        await self._play_next_async(state.guild_id, auto_send=True)

    def _peek_next_track(self, state: AudioState) -> Track | None:
        """Which track follows `state.current`, honouring the loop mode.

        `_play_next_async` reaches the same answer imperatively when it advances
        the queue. The crossfade preloader has to agree with it, or a faded
        transition ends up playing a different song than a gapless one would.
        Under track loop - or queue loop with nothing else queued - the answer
        is the current track itself, and it gets crossfaded into itself.
        """
        if state.loop_mode == "track":
            return state.current
        if state.queue:
            return state.queue[0]
        if state.loop_mode == "queue":
            return state.current
        return None

    def _refresh_crossfade_for_loop_change(self, state: AudioState):
        """Recalculate a prepared successor after the loop mode changes."""
        if not state.crossfade_enabled:
            return

        # A scheduled deck was selected under the old mode.  It is safe to
        # discard until mixing starts; once mixing starts, the active transition
        # must finish and the completion hook will prepare the next successor.
        self._cancel_prepared_crossfade(state)
        logger.debug(
            f"[Crossfade] guild {state.guild_id}: loop mode changed to "
            f"{state.loop_mode}; recalculating successor"
        )
        self._request_crossfade_prepare(state)

    def _crossfade_still_valid(
        self, state: AudioState, current_track: Track, candidate: Track
    ) -> bool:
        """Whether a preload started for `candidate` is still the right thing.

        Preparing a crossfade means awaiting yt-dlp, then sleeping most of the
        song, then awaiting a decoder prefill. Playback can be skipped, stopped,
        re-queued or re-ordered across any of those, so every step re-checks.
        """
        return (
            state.crossfade_enabled
            and state.current is current_track
            and state.voice_client is not None
            and state.voice_client.is_playing()
            and state.crossfade_next is None
            and state.active_audio_source is not None
            and not state.active_audio_source.has_pending_crossfade()
            and self._peek_next_track(state) is candidate
        )

    def _clear_crossfade(self, state: AudioState):
        if state.crossfade_prepare_task and not state.crossfade_prepare_task.done():
            state.crossfade_prepare_task.cancel()
        state.crossfade_prepare_task = None
        if state.crossfade_task and not state.crossfade_task.done():
            state.crossfade_task.cancel()
        state.crossfade_task = None
        state.crossfade_next = None
        scheduled_source = (
            state.active_audio_source.cancel_scheduled_crossfade()
            if state.active_audio_source
            else None
        )
        if state.crossfade_audio_source:
            state.crossfade_audio_source.cleanup()
        elif scheduled_source:
            scheduled_source.cleanup()
        state.crossfade_audio_source = None

    def _cancel_prepared_crossfade(self, state: AudioState):
        pending = state.crossfade_next
        # Once the mixer has consumed its first fade frame, the incoming stream
        # belongs to active playback. Let that transition finish uninterrupted.
        if state.active_audio_source and state.active_audio_source.is_crossfade_active():
            return
        self._clear_crossfade(state)
        # A self-crossfade preloaded the track that is still playing; putting it
        # back in the queue would schedule it twice.
        if pending and pending is not state.current:
            state.queue.appendleft(pending)

    def _build_player_embed(self, track: Track, state: AudioState) -> discord.Embed:
        embed = discord.Embed(
            title=track.title,
            url=track.original_url,
            color=discord.Color(0x5865F2)
        )
        if track.thumbnail:
            embed.set_image(url=track.thumbnail)
        elif track.cover_bytes:
            embed.set_image(url="attachment://cover.jpg")
            
        if track.uploader:
            embed.add_field(name="🎤 ศิลปิน", value=f"`{track.uploader}`", inline=False)
        if track.album:
            embed.add_field(name="💿 อัลบั้ม", value=f"`{track.album}`", inline=False)

        dur_str = format_duration(track.duration)
        embed.add_field(name="⏳ ความยาว", value=f"`{dur_str}`", inline=True)
        embed.add_field(name="👤 ขอโดย", value=track.requester.mention, inline=True)
            
        if track.view_count or track.like_count or track.comment_count:
            if track.view_count:
                embed.add_field(name="👀 ยอดวิว", value=f"`{track.view_count:,}`", inline=True)
            if track.like_count:
                embed.add_field(name="👍 ยอดไลก์", value=f"`{track.like_count:,}`", inline=True)
            if track.comment_count:
                embed.add_field(name="💬 คอมเมนต์", value=f"`{track.comment_count:,}`", inline=True)
                
        if track.upload_date or track.channel_follower_count:
            if track.upload_date and len(track.upload_date) == 8:
                date_str = f"{track.upload_date[6:8]}/{track.upload_date[4:6]}/{track.upload_date[0:4]}"
                embed.add_field(name="📅 วันที่ลง", value=f"`{date_str}`", inline=True)
            if track.channel_follower_count:
                embed.add_field(name="👥 ผู้ติดตาม", value=f"`{track.channel_follower_count:,}`", inline=True)
                
        if track.year or track.filesize or track.bitrate:
            
            if track.year:
                embed.add_field(name="🗓️ ปี", value=f"`{track.year}`", inline=True)
            if track.filesize:
                mb = track.filesize / (1024 * 1024)
                embed.add_field(name="💾 ขนาดไฟล์", value=f"`{mb:.2f} MB`", inline=True)
            if track.bitrate:
                embed.add_field(name="🎵 บิตเรต", value=f"`{int(track.bitrate)} kbps`", inline=True)
        
        desc = ""
        # Guard against a stale caller: the bar belongs to the playing track,
        # and position is only meaningful for that one.
        if state.current is track:
            position = self._current_playback_position(state)
            if track.duration > 0:
                position = min(position, track.duration)
            paused = bool(state.voice_client and state.voice_client.is_paused())
            desc += render_progress_bar(position, track.duration, paused) + "\n\n"

        # Append queue
        queued_tracks = ([state.crossfade_next] if state.crossfade_next else []) + list(state.queue)
        if queued_tracks:
            desc += "**🎶 คิวถัดไป:**\n"
            for i, qtrack in enumerate(queued_tracks):
                if i < 5:
                    dur_str = format_duration(qtrack.duration)
                    desc += f"{i+1}. [{qtrack.title}]({qtrack.original_url})\n`[{dur_str}]` - {qtrack.requester.mention}\n"
            if len(queued_tracks) > 5:
                desc += f"\n*...และอีก {len(queued_tracks) - 5} เพลง*"
                
        if desc:
            embed.description = desc
            
        loop_th = {"off": "ปิด", "track": "เพลงเดียว", "queue": "ทั้งคิว"}.get(state.loop_mode, state.loop_mode)
        crossfade_th = "เปิด" if state.crossfade_enabled else "ปิด"
        embed.set_footer(
            text=(
                f"🔁 วนลูป: {loop_th}  |  🔀 Crossfade: {crossfade_th}"
                f"  |  🔊 ระดับเสียง: {int(state.volume * 100)}%"
            )
        )
            
        return embed

    async def _update_controller(self, state: AudioState, embed: discord.Embed):
        view = PlayerControls(self, state)
        
        file = None
        # Only upload if we have cover_bytes and NO thumbnail yet.
        if state.current and state.current.cover_bytes and not state.current.thumbnail:
            import io
            file = discord.File(io.BytesIO(state.current.cover_bytes), filename="cover.jpg")
            embed.set_image(url="attachment://cover.jpg")
            
        kwargs = {"embed": embed, "view": view}
        
        msg = None
        if state.last_controller_message:
            try:
                edit_kwargs = kwargs.copy()
                if file:
                    edit_kwargs["file"] = file
                    edit_kwargs["attachments"] = []
                else:
                    edit_kwargs["attachments"] = []
                msg = await state.last_controller_message.edit(**edit_kwargs)
            except Exception as e:
                logger.error(f"Error editing controller: {e}")
                
        if not msg and state.text_channel:
            send_kwargs = kwargs.copy()
            if file:
                send_kwargs["file"] = file
            msg = await state.text_channel.send(**send_kwargs)
            state.last_controller_message = msg

        # Cache the thumbnail URL if we just uploaded a file
        if msg and file and state.current:
            if msg.embeds and msg.embeds[0].image.url and msg.embeds[0].image.url.startswith("http"):
                state.current.thumbnail = msg.embeds[0].image.url
                state.current.cover_bytes = None
            elif msg.attachments:
                state.current.thumbnail = msg.attachments[0].url
                state.current.cover_bytes = None

    async def _send_controls(self, state: AudioState, ctx, embed: discord.Embed, edit_original: bool = False):
        if state.last_controller_message:
            try:
                embeds = state.last_controller_message.embeds
                if embeds:
                    embeds[0].color = discord.Color.dark_theme()
                    embeds[0].description = None
                    await state.last_controller_message.edit(embed=embeds[0], view=None)
                else:
                    await state.last_controller_message.edit(view=None)
            except Exception:
                pass
        
        view = PlayerControls(self, state)
        
        file = None
        if state.current and state.current.cover_bytes and not state.current.thumbnail:
            import io
            file = discord.File(io.BytesIO(state.current.cover_bytes), filename="cover.jpg")
            embed.set_image(url="attachment://cover.jpg")

        kwargs = {"embed": embed, "view": view}
        if file:
            kwargs["file"] = file
        
        if edit_original:
            msg = await ctx.interaction.edit_original_response(**kwargs)
            state.last_controller_message = msg
        else:
            msg = await ctx.respond(**kwargs)
            if isinstance(msg, discord.Interaction):
                msg = await msg.original_response()
            state.last_controller_message = msg

        if msg and file and state.current:
            if msg.embeds and msg.embeds[0].image.url and msg.embeds[0].image.url.startswith("http"):
                state.current.thumbnail = msg.embeds[0].image.url
                state.current.cover_bytes = None
            elif msg.attachments:
                state.current.thumbnail = msg.attachments[0].url
                state.current.cover_bytes = None

    async def _extract_info(self, query: str, download: bool = False) -> dict:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            self._metadata_executor,
            lambda: ytdl.extract_info(query, download=download)
        )
        return data

    async def _extract_crossfade_info(self, query: str) -> dict | None:
        """Resolve at most one crossfade candidate while a prior job runs.

        Cancelling an asyncio task cannot stop yt-dlp already running in a
        worker. Holding the concurrent future here prevents skips and track
        changes from piling further stale crossfade jobs into the executor.
        """
        existing_job = self._crossfade_metadata_job
        if existing_job and not existing_job.done():
            logger.debug("[Crossfade] metadata preload skipped; another job is still running")
            return None
        if existing_job and existing_job.done():
            self._crossfade_metadata_job = None

        job = self._metadata_executor.submit(ytdl.extract_info, query, download=False)
        self._crossfade_metadata_job = job
        try:
            return await asyncio.shield(asyncio.wrap_future(job))
        finally:
            if job.done() and self._crossfade_metadata_job is job:
                self._crossfade_metadata_job = None

    @staticmethod
    def _on_buffer_underrun(guild_id: int, consecutive_frames: int) -> None:
        logger.debug(
            f"[Audio buffer] guild {guild_id}: underrun for "
            f"{consecutive_frames * FRAME_MS}ms; sending silence while refilling"
        )

    def _buffered_audio_source(
        self,
        guild_id: int,
        source: discord.AudioSource,
        *,
        buffer_seconds: float = BUFFER_SECONDS,
    ) -> BufferedAudioSource:
        return BufferedAudioSource(
            source,
            buffer_seconds=buffer_seconds,
            on_underrun=lambda frames: self._on_buffer_underrun(guild_id, frames),
        )

    async def _hydrate_track(self, track: Track, *, crossfade_preload: bool = False) -> bool:
        """Resolve a flat-playlist track into a playable stream."""
        if track.stream_url:
            return True

        data = (
            await self._extract_crossfade_info(track.original_url)
            if crossfade_preload
            else await self._extract_info(track.original_url, download=False)
        )
        if not data:
            if crossfade_preload:
                return False
            raise RuntimeError("No data returned by yt-dlp (video might be unavailable).")

        track.stream_url = data.get("url")
        track.title = data.get("title", track.title)
        track.thumbnail = data.get("thumbnail", track.thumbnail)
        track.duration = data.get("duration") or track.duration or 0
        uploader = data.get("uploader", track.uploader)
        if "channel" in data and data["channel"] != uploader:
            uploader = f"{uploader} ({data['channel']})" if uploader else data["channel"]
        track.uploader = uploader
        track.view_count = data.get("view_count", track.view_count)
        track.like_count = data.get("like_count", track.like_count)
        track.comment_count = data.get("comment_count", track.comment_count)
        track.upload_date = data.get("upload_date", track.upload_date)
        track.channel_follower_count = data.get("channel_follower_count", track.channel_follower_count)
        return bool(track.stream_url)

    def _current_playback_position(self, state: AudioState) -> float:
        if state.playback_started_at is None:
            return state.playback_offset_seconds
        now = state.playback_paused_at or self.bot.loop.time()
        return state.playback_offset_seconds + max(0.0, now - state.playback_started_at)

    def _mark_playback_paused(self, state: AudioState):
        if state.playback_started_at is not None and state.playback_paused_at is None:
            state.playback_paused_at = self.bot.loop.time()

    def _mark_playback_resumed(self, state: AudioState):
        if state.playback_started_at is not None and state.playback_paused_at is not None:
            state.playback_started_at += self.bot.loop.time() - state.playback_paused_at
            state.playback_paused_at = None

    @staticmethod
    def _seek_ffmpeg_options(position: float) -> dict:
        """Input-seek to `position`. `-ss` has to land before `-i`, and py-cord
        builds its command line as `before_options` then `-i url`."""
        options = dict(ffmpeg_options)
        options["before_options"] = f"-ss {position:.3f} {options['before_options']}"
        return options

    def _can_seek(self, state: AudioState) -> bool:
        voice_client = state.voice_client
        voice_active = bool(
            voice_client
            and (voice_client.is_playing() or voice_client.is_paused())
        )
        return bool(
            state.current
            and state.current.duration > 0
            and state.current_played
            and voice_client
            and voice_client.is_connected()
            and voice_active
            and state.active_audio_source is not None
            and not state.active_audio_source.is_crossfade_active()
        )

    async def _seek_async(self, state: AudioState, target: float) -> bool:
        """Restart the decoder at `target` without ending the track.

        FFmpeg cannot seek a pipe that is already being drained, so this opens a
        second decoder at the new offset and hands it to the live mixer.
        Stopping the voice client to replay would fire `after_playing` and
        advance the queue, so the deck is swapped underneath it instead.
        """
        track = state.current
        mixer = state.active_audio_source
        if not track or not mixer or not track.stream_url:
            return False

        # An armed fade counts frames from the old position and the preload task
        # sleeps on the old remaining time; both are wrong the moment we jump.
        self._cancel_prepared_crossfade(state)

        new_source = self._buffered_audio_source(
            state.guild_id,
            discord.FFmpegPCMAudio(track.stream_url, **self._seek_ffmpeg_options(target)),
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._decoder_executor, new_source.wait_ready)

        # A stream URL that expired mid-session yields a decoder that dies
        # immediately. Swapping it in would read as end-of-track and skip the
        # song, so leave the deck that is playing fine exactly where it is.
        if not new_source.started_ok():
            new_source.cleanup()
            logger.warning(
                f"[Seek] guild {state.guild_id}: decoder produced no audio for "
                f"'{track.title}'; keeping the current stream"
            )
            self._request_crossfade_prepare(state)
            return False

        # Opening a decoder takes long enough for a skip, stop or disconnect to
        # have landed in the meantime.
        if (
            state.current is not track
            or state.active_audio_source is not mixer
            or not state.voice_client
            or not state.voice_client.is_connected()
        ):
            new_source.cleanup()
            return False

        displaced = mixer.swap_current(new_source)
        now = self.bot.loop.time()
        state.playback_offset_seconds = target
        state.playback_started_at = now
        # Seeking while paused stays paused, and reads back as `target` because
        # the position math stops the clock at `playback_paused_at`.
        state.playback_paused_at = now if state.voice_client.is_paused() else None

        if displaced:
            # Tearing down an FFmpeg process blocks; keep it off the event loop.
            await loop.run_in_executor(self._decoder_executor, displaced.cleanup)

        logger.debug(
            f"[Seek] guild {state.guild_id}: '{track.title}' -> "
            f"{format_duration(int(target))}"
        )
        self._request_crossfade_prepare(state)
        return True

    def _request_crossfade_prepare(self, state: AudioState):
        """Prepare the next stream after the newly started source is stable."""
        if (
            not state.crossfade_enabled
            or not state.current
            or not state.voice_client
            or not state.voice_client.is_playing()
            or (state.crossfade_prepare_task and not state.crossfade_prepare_task.done())
        ):
            return
        track = state.current
        state.crossfade_prepare_task = self.bot.loop.create_task(
            self._prepare_crossfade_after_startup(state, track)
        )

    async def _prepare_crossfade_after_startup(self, state: AudioState, track: Track):
        """Hold off preparing the next track until this one's own buffer can
        spare the CPU/network budget.

        Preparing the next track means a yt-dlp extraction (pure-Python,
        occasionally running a JS interpreter for signature decryption) that
        can hold the GIL long enough to starve this track's buffer thread.
        Right after a track starts, that thread is racing from a 1s prefill up
        to its full cushion and has no slack to give - competing with it here
        is exactly when it stutters. Waiting for the buffer to actually reach
        full depth (rather than guessing a fixed delay) adapts to whatever the
        network is doing instead of assuming a delay that fit one test run.
        """
        task = asyncio.current_task()
        try:
            deadline = self.bot.loop.time() + CROSSFADE_STARTUP_MAX_WAIT_SECONDS
            while self.bot.loop.time() < deadline:
                if (
                    not state.crossfade_enabled
                    or state.current is not track
                    or not state.voice_client
                    or not state.voice_client.is_playing()
                ):
                    return
                if state.active_audio_source and state.active_audio_source.current_buffer_full():
                    break
                await asyncio.sleep(CROSSFADE_STARTUP_POLL_SECONDS)
            if (
                state.crossfade_enabled
                and state.current is track
                and state.voice_client
                and state.voice_client.is_playing()
            ):
                await self._prepare_current_crossfade(state)
        finally:
            if state.crossfade_prepare_task is task:
                state.crossfade_prepare_task = None

    async def _prepare_current_crossfade(self, state: AudioState):
        """Preload the queued successor without replacing the active source."""
        if (
            not state.crossfade_enabled
            or not state.current
            or not state.voice_client
            or not state.voice_client.is_playing()
            or state.crossfade_next
            or not state.active_audio_source
            or state.active_audio_source.has_pending_crossfade()
            or state.current.duration <= 0
        ):
            return

        current_track = state.current
        candidate = self._peek_next_track(state)
        if candidate is None:
            return
        logger.debug(
            f"[Crossfade] guild {state.guild_id}: preloading next stream "
            f"'{candidate.title}' for active '{current_track.title}'"
        )
        try:
            if not await self._hydrate_track(candidate, crossfade_preload=True) or candidate.duration <= 0:
                logger.debug(
                    f"[Crossfade] guild {state.guild_id}: preload skipped; "
                    "next track has an unknown duration or no stream"
                )
                return

            if not self._crossfade_still_valid(state, current_track, candidate):
                logger.debug(
                    f"[Crossfade] guild {state.guild_id}: preload discarded; "
                    "playback changed while resolving the next stream"
                )
                return

            position = min(self._current_playback_position(state), current_track.duration)
            remaining = current_track.duration - position
            duration = min(CROSSFADE_SECONDS, remaining / 2, candidate.duration / 2)
            if duration < 0.5 or remaining <= 0.5:
                logger.debug(
                    f"[Crossfade] guild {state.guild_id}: preload skipped; "
                    "not enough of the current track remains"
                )
                return

            # Resolving metadata is cheap, but starting another FFmpeg decoder
            # during most of the current song can starve the active stream.
            # Open it only shortly before its buffered frames are needed.
            preload_delay = max(
                0.0,
                remaining - duration - CROSSFADE_PRELOAD_LEAD_SECONDS,
            )
            if preload_delay:
                await asyncio.sleep(preload_delay)

            if not self._crossfade_still_valid(state, current_track, candidate):
                return

            next_audio = self._buffered_audio_source(
                state.guild_id,
                discord.FFmpegPCMAudio(candidate.stream_url, **ffmpeg_options),
                buffer_seconds=CROSSFADE_BUFFER_SECONDS,
            )
            await asyncio.get_event_loop().run_in_executor(
                self._decoder_executor, next_audio.wait_ready
            )
            if not self._crossfade_still_valid(state, current_track, candidate):
                next_audio.cleanup()
                return

            position = min(self._current_playback_position(state), current_track.duration)
            remaining = current_track.duration - position
            duration = min(CROSSFADE_SECONDS, remaining / 2, candidate.duration / 2)
            if duration < 0.5 or remaining <= 0.5:
                next_audio.cleanup()
                return

            # Under a loop mode the successor can be the current track itself,
            # in which case it was never in the queue to begin with.
            if state.queue and state.queue[0] is candidate:
                state.queue.popleft()
            state.crossfade_next = candidate
            state.crossfade_audio_source = next_audio
            logger.debug(
                f"[Crossfade] guild {state.guild_id}: preload complete for "
                f"'{candidate.title}' (fade={duration:.1f}s)"
            )
            frames_until_fade = round(max(0.0, remaining - duration) * 1000 / FRAME_MS)
            state.active_audio_source.schedule_crossfade(
                next_audio,
                duration,
                frames_until_fade,
                lambda: self.bot.loop.call_soon_threadsafe(
                    lambda: self.bot.loop.create_task(
                        self._activate_crossfade(state, current_track, candidate, duration)
                    )
                ),
                lambda: self.bot.loop.call_soon_threadsafe(
                    lambda: self.bot.loop.create_task(
                        self._finish_crossfade(state, candidate)
                    )
                ),
            )
        except Exception as e:
            logger.warning(
                f"[Crossfade] guild {state.guild_id}: preload failed for "
                f"'{candidate.title}': {e}"
            )

    async def _idle_disconnect(self, guild_id: int):
        await asyncio.sleep(180)
        state = self.states.get(guild_id)
        if state and state.voice_client and state.voice_client.is_connected():
            await state.voice_client.disconnect()
            state.voice_client = None
            self._clear_crossfade(state)
            state.active_audio_source = None
            state.queue.clear()
            state.current = None
            state.history.clear()
            state.forward_history.clear()
            if state.text_channel:
                await state.text_channel.send(embed=info_embed("ไปแล้วค่า~", "หนูขอตัวออกก่อนนะคะ เพราะไม่มีเพลงเล่นมา 3 นาทีแล้ว (´・ω・)"))

    async def _rewind_async(self, guild_id: int) -> bool:
        """Pop the most recent history entry and play it, pushing the current
        track into forward history so a subsequent skip/next can redo back to it."""
        state = self.get_state(guild_id)
        if not state.voice_client or not state.voice_client.is_connected():
            return False

        async with state.rewind_lock:
            if not state.history:
                return False

            previous_track = state.history.pop()
            if state.current:
                state.forward_history.append(state.current)

            state.queue.appendleft(previous_track)
            state.is_rewinding = True
            state.skip_request = True

            if state.voice_client.is_playing() or state.voice_client.is_paused():
                state.voice_client.stop()
            else:
                self.bot.loop.create_task(self._play_next_async(guild_id))

        return True

    async def _activate_crossfade(
        self, state: AudioState, previous: Track, next_track: Track, duration: float
    ):
        """Move player state when the persistent source starts mixing frames."""
        if (
            state.current is not previous
            or state.crossfade_next is not next_track
        ):
            return

        logger.debug(
            f"[Crossfade] guild {state.guild_id}: crossfade occurred "
            f"'{previous.title}' -> '{next_track.title}' ({duration:.1f}s overlap)"
        )
        state.crossfade_next = None
        state.crossfade_audio_source = None
        state.crossfade_task = None
        if previous and state.current_played:
            state.history.append(previous)
        # `_play_next_async` sends the outgoing track back to the tail under
        # queue loop; a faded transition has to do the same or the song drops
        # out of the rotation one lap at a time. A self-crossfade (track loop,
        # or queue loop with nothing else queued) never left the rotation.
        if state.loop_mode == "queue" and previous is not next_track:
            state.queue.append(previous)
        state.current = next_track
        state.current_played = True
        state.playback_started_at = self.bot.loop.time()
        state.playback_paused_at = None
        state.playback_offset_seconds = 0.0
        logger.info(f"Playing track in guild {state.guild_id}: {next_track.title}")

        if state.text_channel:
            await self._update_controller(state, self._build_player_embed(next_track, state))

    async def _finish_crossfade(self, state: AudioState, track: Track):
        """Refresh controls once a crossfade has returned to one active deck."""
        if (
            state.current is not track
            or not state.current_played
            or not state.voice_client
            or not (state.voice_client.is_playing() or state.voice_client.is_paused())
            or not state.active_audio_source
            or state.active_audio_source.is_crossfade_active()
        ):
            return

        logger.debug(
            f"[Crossfade] guild {state.guild_id}: mix complete for "
            f"'{track.title}'; refreshing seek controls"
        )
        if state.text_channel:
            await self._update_controller(state, self._build_player_embed(track, state))
        self._request_crossfade_prepare(state)

    async def _play_next_async(
        self,
        guild_id: int,
        auto_send: bool = True,
        expected_generation: int | None = None,
    ):
        state = self.get_state(guild_id)
        if (
            expected_generation is not None
            and expected_generation != state.playback_generation
        ):
            logger.debug(f"Ignoring stale playback transition in guild {guild_id}")
            return
        playback_generation = state.playback_generation
        if not state.voice_client or not state.voice_client.is_connected():
            state.current = None
            state.queue.clear()
            state.history.clear()
            state.forward_history.clear()
            state.crossfade_next = None
            state.active_audio_source = None
            return

        # A previous track may still be waiting to open its delayed preload.
        # It must not block preparation for the new current track.
        if state.crossfade_prepare_task and not state.crossfade_prepare_task.done():
            state.crossfade_prepare_task.cancel()
        state.crossfade_prepare_task = None

        was_rewinding = state.is_rewinding
        state.is_rewinding = False
        pending = state.crossfade_next
        if pending is not None:
            # A preloaded successor was never mixed (skip/rewind/source end).
            self._clear_crossfade(state)
            # A self-crossfade preloads the track that is already playing; the
            # loop bookkeeping below re-queues it, so doing it here too would
            # make a skip replay the song instead of advancing past it.
            if pending is not state.current:
                if was_rewinding:
                    state.queue.insert(1, pending)
                else:
                    state.queue.appendleft(pending)

        if state.skip_request:
            state.skip_request = False
        else:
            if state.loop_mode == "track" and state.current:
                state.queue.appendleft(state.current)
            elif state.loop_mode == "queue" and state.current:
                state.queue.append(state.current)

        # Only a track that actually started playing belongs in history, and never
        # the track we just manually moved into forward_history via a rewind.
        if state.current and state.current_played and not was_rewinding:
            state.history.append(state.current)

        # Redo priority: forward history (from a previous rewind) before the normal queue.
        if state.forward_history and not was_rewinding:
            state.queue.appendleft(state.forward_history.pop())
        elif state.forward_history and was_rewinding:
            # The rewind itself is a hard transition to the previous track.
            # Put the track we came from immediately after it so its later,
            # natural ending can Crossfade back into the expected sequence.
            state.queue.insert(1, state.forward_history.pop())

        if len(state.queue) == 0:
            state.current = None
            # The source that just ended is finished; keeping the handle would
            # leave `/volume` and the crossfade guards pointing at a dead mixer.
            state.active_audio_source = None
            if state.last_controller_message:
                try:
                    embeds = state.last_controller_message.embeds
                    if embeds:
                        embeds[0].color = discord.Color.dark_theme()
                        embeds[0].description = None
                        await state.last_controller_message.edit(embed=embeds[0], view=None)
                    else:
                        await state.last_controller_message.edit(view=None)
                except Exception:
                    pass
                state.last_controller_message = None
            
            # Start idle timer
            if not state.idle_task:
                state.idle_task = self.bot.loop.create_task(self._idle_disconnect(guild_id))
            return

        # Cancel idle timer if exists
        if state.idle_task:
            state.idle_task.cancel()
            state.idle_task = None

        track = state.queue.popleft()
        state.current = track
        state.current_played = False
        start_position = state.restore_start_position_seconds
        state.restore_start_position_seconds = 0.0

        # JIT extraction for flat playlist tracks
        if not track.stream_url:
            try:
                await self._hydrate_track(track)
            except Exception as e:
                logger.error(f"Error extracting stream url for {track.original_url}: {e}")
                # Skip to next if failed
                self.bot.loop.create_task(
                    self._play_next_async(guild_id, expected_generation=playback_generation)
                )
                return

        if playback_generation != state.playback_generation:
            return

        if not track.stream_url:
            logger.warning(f"Could not find stream URL for {track.title}, skipping.")
            self.bot.loop.create_task(
                self._play_next_async(guild_id, expected_generation=playback_generation)
            )
            return

        if track.duration > 0:
            start_position = min(start_position, max(0.0, track.duration - 1))
        else:
            start_position = 0.0

        if start_position > 0:
            logger.debug(
                f"Playlist restore applying resume offset in guild {guild_id}: "
                f"offset={start_position:.1f}s"
            )

        try:
            buffered_source = self._buffered_audio_source(
                guild_id,
                discord.FFmpegPCMAudio(
                    track.stream_url,
                    **(
                        self._seek_ffmpeg_options(start_position)
                        if start_position > 0
                        else ffmpeg_options
                    ),
                )
            )
            # Volume lives inside the mixer rather than in a PCMVolumeTransformer
            # wrapper, so a frame costs one vectorised pass instead of two
            # per-sample Python loops on the voice send thread.
            persistent_source = SeamlessCrossfadeSource(buffered_source, volume=state.volume)

            # Wait for the buffer to actually pre-fill (rather than a blind fixed sleep)
            # before Discord starts pulling frames on its strict 20ms clock.
            await asyncio.get_event_loop().run_in_executor(
                self._decoder_executor, buffered_source.wait_ready
            )
            if playback_generation != state.playback_generation:
                buffered_source.cleanup()
                return

            def after_playing(e):
                if playback_generation != state.playback_generation:
                    return
                if state.suppress_next_after:
                    state.suppress_next_after = False
                    return
                if e:
                    logger.error(f"Player error in guild {guild_id}: {e}")
                self.bot.loop.call_soon_threadsafe(
                    lambda: self.bot.loop.create_task(
                        self._play_next_async(
                            guild_id, expected_generation=playback_generation
                        )
                    )
                )

            state.voice_client.play(persistent_source, after=after_playing)
            state.active_audio_source = persistent_source
            state.current_played = True
            state.playback_started_at = self.bot.loop.time()
            state.playback_paused_at = None
            state.playback_offset_seconds = start_position
            # Skip/rewind only disable the transition that just happened. Once
            # this track is playing, its own natural ending is eligible again.
            if state.crossfade_enabled:
                self._request_crossfade_prepare(state)
            logger.info(f"Playing track in guild {guild_id}: {track.title}")
            
            # Auto-update controller if this was an automatic track progression
            if auto_send and state.text_channel:
                embed = self._build_player_embed(track, state)
                await self._update_controller(state, embed)
        except Exception as e:
            logger.error(f"Error playing track in guild {guild_id}: {e}")
            self.bot.loop.create_task(
                self._play_next_async(guild_id, expected_generation=playback_generation)
            )

    music = discord.SlashCommandGroup("music", "🎵 ระบบเครื่องเล่นเพลง")

    @music.command(name="leave", description="👋 ออกจากห้องเสียง")
    async def leave(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client:
            raise UserError("หนูไม่ได้อยู่ในห้องนะคะ", "หนูไม่ได้อยู่ในห้องเสียงไหนเลยนะคะ (´-ω-`)")

        state = self.get_state(ctx.guild.id)
        self._clear_crossfade(state)
        state.active_audio_source = None
        state.queue.clear()
        state.current = None
        state.history.clear()
        state.forward_history.clear()
        state.loop_mode = "off"

        await ctx.voice_client.disconnect()
        state.voice_client = None

        await ctx.respond(embed=success_embed("ไปแล้วค่า~", "หนูออกจากห้องเสียงแล้วนะคะ ไว้เจอกันใหม่น้า! (・`ω´・)"))

    @music.command(name="local", description="📂 เล่นเพลงจากไฟล์แนบหรือประวัติแชท")
    @discord.option("file", description="อัปโหลดไฟล์เพลงที่นี่เลยค่ะ", required=False, type=discord.SlashCommandOptionType.attachment)
    async def local(self, ctx: discord.ApplicationContext, file: discord.Attachment = None):
        state = self.get_state(ctx.guild.id)
        state.text_channel = ctx.channel
        
        await ctx.defer(ephemeral=True)

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("หนูเข้าห้องไม่ได้ค่ะ", "เซนเซย์ต้องเข้าไปในห้องเสียงก่อนนะคะถึงจะให้หนูตามเข้าไปได้ (´・ω・)")

        channel = ctx.author.voice.channel
        
        if ctx.voice_client:
            if ctx.voice_client.channel.id != channel.id:
                raise UserError("คนละห้องค่ะ", "เซนเซย์อยู่คนละห้องกับหนูนะคะ มาหาหนูก่อนน้า (・`ω´・)")

        # Find file in history if not provided
        if not file:
            async for msg in ctx.channel.history(limit=50):
                if msg.attachments:
                    for att in msg.attachments:
                        if att.content_type and att.content_type.startswith(('audio/', 'video/')):
                            file = att
                            break
                if file:
                    break
            
            if not file:
                raise UserError("หาไฟล์ไม่เจอค่ะ", "ไม่เจอไฟล์เพลงใน 50 ข้อความล่าสุดเลยค่ะ รบกวนแนบไฟล์มาให้หนูด้วยนะคะ (´・ω・)")



        if file:
            await ctx.interaction.edit_original_response(embed=info_embed("<a:MagnifierGIF:1052563354910216252> กำลังโหลดไฟล์...", f"กำลังเตรียมไฟล์ `{file.filename}` นะคะ รอแป๊บนึงน้า (・`ω´・)"))
            
            import os
            temp_path = f"assets/audio/music/temp_{file.id}_{file.filename}"
            os.makedirs("assets/audio/music", exist_ok=True)
            await file.save(temp_path)
            
            try:
                from tinytag import TinyTag
                tag = TinyTag.get(temp_path, image=True)
                title = tag.title or file.filename
                uploader = tag.artist or "Local File"
                duration = int(tag.duration) if tag.duration else 0
                cover_bytes = tag.get_image()
                album = tag.album
                year = tag.year
                filesize = tag.filesize
                bitrate = tag.bitrate
            except Exception as e:
                logger.error(f"TinyTag error: {e}")
                title = file.filename
                uploader = "Local File"
                duration = 0
                cover_bytes = None
                album = None
                year = None
                filesize = None
                bitrate = None
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                        
            track = Track(
                title=title,
                duration=duration,
                thumbnail="",
                requester=ctx.author,
                original_url=file.url,
                stream_url=file.url,
                uploader=uploader,
                view_count=None,
                cover_bytes=cover_bytes,
                album=album,
                year=year,
                filesize=filesize,
                bitrate=bitrate
            )
            state.queue.append(track)
            
            
            await ctx.interaction.edit_original_response(embed=success_embed("✅ เพิ่มเข้าคิวแล้ว!", f"เพิ่ม `{title}` ลงคิวเรียบร้อยค่ะ! (๑>◡<๑)"))

        await self._ensure_voice_connection(ctx, state)

        if not state.current or not state.voice_client.is_playing():
            self.bot.loop.create_task(self._play_next_async(ctx.guild.id, auto_send=True))
        else:
            display_track = state.current if state.current else track
            embed = self._build_player_embed(display_track, state)
            await self._update_controller(state, embed)
            if state.crossfade_enabled:
                self._request_crossfade_prepare(state)

    @music.command(name="play", description="▶️ เปิดเพลงจาก YouTube (รองรับ Playlist)")
    @discord.option("query", description="ชื่อเพลงหรือ URL ของวิดีโอ/เพลย์ลิสต์ค่ะ")
    async def play(self, ctx: discord.ApplicationContext, query: str):
        state = self.get_state(ctx.guild.id)
        state.text_channel = ctx.channel
        
        await ctx.defer(ephemeral=True)

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("หนูเข้าห้องไม่ได้ค่ะ", "เซนเซย์ต้องเข้าไปในห้องเสียงก่อนนะคะถึงจะให้หนูตามเข้าไปได้ (´・ω・)")

        channel = ctx.author.voice.channel
        
        if ctx.voice_client:
            if ctx.voice_client.channel.id != channel.id:
                raise UserError("คนละห้องค่ะ", "เซนเซย์อยู่คนละห้องกับหนูนะคะ มาหาหนูก่อนน้า (・`ω´・)")

        await ctx.interaction.edit_original_response(embed=info_embed("<a:MagnifierGIF:1052563354910216252> กำลังค้นหา...", f"หนูกำลังหาข้อมูล `{query}` ให้นะคะ รอแป๊บนึงน้า (・`ω´・)"))



        # ytsearch1 if not URL (faster search)
        if not query.startswith(("http://", "https://")):
            query = f"ytsearch1:{query}"

        try:
            data = await self._extract_info(query, download=False)
        except Exception as e:
            logger.error(f"yt-dlp extract error: {e}")
            await ctx.interaction.edit_original_response(embed=error_embed("หาเพลงไม่เจอค่ะ", "แง... หนูหาเพลงนี้ไม่เจอ หรืออาจจะโหลดไม่ได้นะคะ ขอโทษด้วยค่ะ (╥﹏╥)"))
            return

        if not data:
            await ctx.interaction.edit_original_response(embed=error_embed("หาเพลงไม่เจอค่ะ", "ไม่มีข้อมูลเพลงนี้เลยค่ะ (╥﹏╥)"))
            return

        entries = [data]
        is_playlist = False
        if 'entries' in data:
            entries = list(data['entries'])
            is_playlist = True

        added_count = 0
        first_track = None

        for entry in entries:
            if not entry:
                continue
            
            url = entry.get('url')
            webpage_url = entry.get('webpage_url')
            if not webpage_url and 'id' in entry:
                webpage_url = f"https://www.youtube.com/watch?v={entry['id']}"

            title = entry.get('title', 'Unknown Title')
            duration = entry.get('duration', 0)
            thumbnail = entry.get('thumbnail', '')
            uploader = entry.get('uploader')
            if 'channel' in entry and entry['channel'] != uploader:
                uploader = f"{uploader} ({entry['channel']})" if uploader else entry['channel']
            view_count = entry.get('view_count')
            like_count = entry.get('like_count')
            comment_count = entry.get('comment_count')
            upload_date = entry.get('upload_date')
            channel_follower_count = entry.get('channel_follower_count')
            
            track = Track(
                title=title,
                duration=duration,
                thumbnail=thumbnail,
                requester=ctx.author,
                original_url=webpage_url,
                stream_url=url if not is_playlist else None,
                uploader=uploader,
                view_count=view_count,
                like_count=like_count,
                comment_count=comment_count,
                upload_date=upload_date,
                channel_follower_count=channel_follower_count
            )
            state.queue.append(track)
            if not first_track:
                first_track = track
            added_count += 1

        if added_count == 0:
            await ctx.interaction.edit_original_response(embed=error_embed("หาเพลงไม่เจอค่ะ", "หาเพลงไม่เจอเลยค่ะ (╥﹏╥)"))
            return

        # Update the public controller message directly
        display_track = state.current if state.current else first_track
        embed = self._build_player_embed(display_track, state)
        await self._update_controller(state, embed)
        
        # Send ephemeral confirmation to the user
        msg = f"Playlist ({added_count} เพลง)" if is_playlist else f"[{first_track.title}]({first_track.original_url})"
        await ctx.interaction.edit_original_response(embed=success_embed("✅ เพิ่มเข้าคิวแล้ว!", f"เพิ่ม {msg} ลงคิวเรียบร้อยค่ะ! ไปดูที่หน้าเล่นเพลงได้เลยนะคะ (๑>◡<๑)"))

        await self._ensure_voice_connection(ctx, state)

        if not state.current or not state.voice_client.is_playing():
            # if playing is stopped, start it
            self.bot.loop.create_task(self._play_next_async(ctx.guild.id, auto_send=True))
        elif state.crossfade_enabled:
            self._request_crossfade_prepare(state)

    @music.command(name="pause", description="⏸️ หยุดเพลงชั่วคราว")
    async def pause(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ (´・ω・)")
        
        ctx.voice_client.pause()
        
        state = self.get_state(ctx.guild.id)
        self._mark_playback_paused(state)
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
            
        await ctx.respond(embed=info_embed("⏸️ หยุดเพลงชั่วคราว", "หนูหยุดเพลงให้ก่อนนะคะ (・`ω´・)"))

    @music.command(name="resume", description="⏯️ เล่นเพลงต่อ")
    async def resume(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_paused():
            raise UserError("เพลงไม่ได้หยุดอยู่นะคะ", "เพลงก็เล่นอยู่ปกตินี่นา หรือไม่ได้เปิดเพลงน้า (´-ω-`)")
            
        ctx.voice_client.resume()
        
        state = self.get_state(ctx.guild.id)
        self._mark_playback_resumed(state)
        # Arming is refused while paused, so a crossfade toggled on during the
        # pause would silently miss this track. Retry now.
        self._request_crossfade_prepare(state)
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)

        await ctx.respond(embed=info_embed("▶️ เล่นเพลงต่อ", "หนูเล่นเพลงต่อแล้วนะคะ! (๑>◡<๑)"))

    @music.command(name="stop", description="⏹️ หยุดเพลงและล้างคิวทั้งหมด")
    async def stop(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        self._clear_crossfade(state)
        state.queue.clear()
        state.history.clear()
        state.forward_history.clear()
        state.loop_mode = "off"
        
        if state.last_controller_message:
            try:
                embeds = state.last_controller_message.embeds
                if embeds:
                    embeds[0].color = discord.Color.dark_theme()
                    await state.last_controller_message.edit(embed=embeds[0], view=None)
                else:
                    await state.last_controller_message.edit(view=None)
            except Exception:
                pass
            state.last_controller_message = None
            
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.respond(embed=success_embed("⏹️ หยุดเพลงแล้วค่ะ", "หนูหยุดเพลงและเคลียร์คิวให้หมดแล้วนะคะ (・`ω´・)"))

    @music.command(name="skip", description="⏭️ ข้ามเพลงปัจจุบัน หรือข้ามไปเพลงที่ระบุ")
    async def skip(self, ctx: discord.ApplicationContext, position: discord.Option(int, description="ลำดับเพลงในคิวที่ต้องการข้ามไป", min_value=1, required=False) = None):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ ข้ามไม่ได้น้า (´・ω・)")
            
        state = self.get_state(ctx.guild.id)

        if state.crossfade_next:
            pending = state.crossfade_next
            self._clear_crossfade(state)
            # A self-crossfade preloaded the playing track; re-queueing it here
            # would make the skip replay it instead of advancing.
            if pending is not state.current:
                state.queue.appendleft(pending)

        if position:
            if position > len(state.queue):
                raise UserError("ไม่มีเพลงในคิวนั้นค่ะ", f"คิวมีแค่ {len(state.queue)} เพลงนะคะ (´-ω-`)")

            # Jumping to an explicit position diverges from any rewound path.
            state.forward_history.clear()

            for _ in range(position - 1):
                track = state.queue.popleft()
                if state.loop_mode == "queue":
                    state.queue.append(track)

        state.skip_request = True
        ctx.voice_client.stop()

        if not position and state.forward_history:
            next_track = state.forward_history[-1]
        else:
            next_track = state.queue[0] if len(state.queue) > 0 else None

        if next_track:
            embed = discord.Embed(
                title=f"เพลงถัดไป: {next_track.title}",
                url=next_track.original_url,
                description="⏭️ **ข้ามเพลงให้แล้วนะคะ!** นี่คือเพลงต่อไปค่ะ",
                color=discord.Color(0x5865F2)
            )
            if next_track.thumbnail:
                embed.set_thumbnail(url=next_track.thumbnail)
        else:
            embed = discord.Embed(
                title="ข้ามเพลง",
                description="⏭️ **ข้ามเพลงให้แล้วนะคะ!** (ไม่มีเพลงในคิวแล้วค่ะ)",
                color=discord.Color(0x5865F2)
            )
        await ctx.respond(embed=embed)

    @music.command(name="seek", description="⏩ เลื่อนไปยังเวลาที่ต้องการ")
    @discord.option("timestamp", description="เช่น 90, 1:30 หรือ 1:02:03")
    async def seek(self, ctx: discord.ApplicationContext, timestamp: str):
        state = self.get_state(ctx.guild.id)
        track = state.current
        if not track or not self._can_seek(state):
            return await ctx.respond(
                embed=error_embed("เลื่อนเวลาไม่ได้ค่ะ", "ตอนนี้ไม่มีเพลงที่เลื่อนเวลาได้อยู่เลยค่ะ (´・ω・)"),
                ephemeral=True
            )

        target = parse_timestamp(timestamp)
        if target is None:
            return await ctx.respond(
                embed=error_embed("รูปแบบเวลาไม่ถูกต้องค่ะ", "ลองพิมพ์แบบ `90`, `1:30` หรือ `1:02:03` ดูนะคะ (´・ω・)"),
                ephemeral=True
            )

        duration = track.duration
        if target >= duration:
            return await ctx.respond(
                embed=error_embed(
                    "เวลาเกินความยาวเพลงค่ะ",
                    f"เพลงนี้ยาว {format_duration(duration)} เท่านั้นนะคะ (´-ω-`)",
                ),
                ephemeral=True
            )
        if state.seek_lock.locked():
            return await ctx.respond(
                embed=error_embed("รอสักครู่นะคะ", "หนูกำลังเลื่อนเพลงอยู่ค่ะ (´・ω・)"),
                ephemeral=True
            )

        await ctx.defer()
        async with state.seek_lock:
            ok = await self._seek_async(state, target)

        if not ok:
            return await ctx.respond(
                embed=error_embed("เลื่อนเวลาไม่สำเร็จค่ะ", "เพลงเปลี่ยนไปก่อนที่หนูจะเลื่อนเสร็จค่ะ (´-ω-`)"),
                ephemeral=True
            )

        if state.current:
            await self._update_controller(state, self._build_player_embed(state.current, state))

        await ctx.respond(
            embed=success_embed("⏩ เลื่อนเวลาแล้ว", f"เลื่อนไปที่ {format_duration(int(target))} ให้แล้วนะคะ! (๑>◡<๑)")
        )

    @music.command(name="previous", description="⏮️ ย้อนกลับไปเพลงก่อนหน้า")
    async def previous(self, ctx: discord.ApplicationContext):
        ok = await self._rewind_async(ctx.guild.id)
        if not ok:
            raise UserError("ย้อนกลับไม่ได้ค่ะ", "ไม่มีเพลงก่อนหน้าให้ย้อนกลับ หรือหนูไม่ได้อยู่ในห้องเสียงเลยค่ะ (´・ω・)")

        await ctx.respond(embed=success_embed("⏮️ ย้อนกลับเพลง", "หนูย้อนกลับไปเพลงก่อนหน้าให้แล้วนะคะ! (๑>◡<๑)"))

    @music.command(name="nowplaying", description="🎵 ดูเพลงที่กำลังเล่นอยู่")
    async def nowplaying(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        state.text_channel = ctx.channel
        if not state.current:
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ (´・ω・)")

        embed = self._build_player_embed(state.current, state)
        await self._send_controls(state, ctx, embed, edit_original=False)

    @music.command(name="loop", description="🔁 ตั้งค่าการวนลูปเพลง")
    async def loop(self, ctx: discord.ApplicationContext, mode: discord.Option(str, choices=["off", "track", "queue"])):
        state = self.get_state(ctx.guild.id)
        state.loop_mode = mode
        self._refresh_crossfade_for_loop_change(state)
        
        if mode == "off":
            msg = "ปิดการวนลูปแล้วนะคะ (・`ω´・)"
        elif mode == "track":
            msg = "จะวนลูปเพลงนี้ไปเรื่อยๆ เลยค่ะ! (๑>◡<๑)"
        else:
            msg = "จะวนลูปทั้งคิวเลยนะคะ! (・`ω´・)"
            
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
            
        await ctx.respond(embed=success_embed("ตั้งค่าลูป", msg))

    @music.command(name="queue", description="📜 ดูคิวเพลงทั้งหมด")
    async def queue(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if not state.current and len(state.queue) == 0:
            return await ctx.respond(embed=info_embed("คิวว่าง", "ไม่มีเพลงในคิวเลยค่ะ (´・ω・)"), ephemeral=True)

        if state.last_queue_message:
            try:
                await state.last_queue_message.edit(view=None)
            except Exception:
                pass
            state.last_queue_message = None

        paginator = QueuePaginator(state, items_per_page=10)
        msg = await ctx.respond(embed=paginator.get_embed(), view=paginator)
        if isinstance(msg, discord.Interaction):
            msg = await msg.original_response()
        paginator.message = msg
        state.last_queue_message = msg

    @music.command(name="restore", description="♻️ กู้คืนคิวเพลงที่บันทึกไว้")
    @discord.option("code", description="รหัสเพลย์ลิสต์ xxxx-xxxx หรือพิมพ์ list")
    async def restore(self, ctx: discord.ApplicationContext, code: str):
        if code.strip().lower() == "list":
            return await self._show_saved_playlists(ctx)

        await self._show_restore_confirmation_for_code(ctx.interaction, code)

    async def _restore_saved_playlist(
        self, interaction: discord.Interaction, code: str
    ) -> None:
        state = self.get_state(interaction.guild.id)
        state.text_channel = interaction.channel
        is_followup = interaction.response.is_done()
        if not is_followup:
            await interaction.response.defer(ephemeral=True)

        async def respond(*, embed: discord.Embed) -> None:
            if is_followup:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.edit_original_response(embed=embed)

        try:
            playlist_tracks = self.playlist_store.load(code, interaction.guild.id)
            logger.debug(
                f"Playlist restore validated in guild {interaction.guild.id}: "
                f"tracks={len(playlist_tracks)}"
            )
        except PlaylistNotFoundError:
            logger.warning(f"Playlist restore rejected in guild {interaction.guild.id}: invalid code")
            await respond(
                embed=error_embed("ไม่พบรหัสเพลย์ลิสต์ค่ะ", "ตรวจสอบรหัสแล้วลองใหม่อีกครั้งนะคะ")
            )
            return
        except PlaylistExpiredError:
            logger.warning(f"Playlist restore rejected in guild {interaction.guild.id}: expired code")
            await respond(
                embed=error_embed("รหัสเพลย์ลิสต์หมดอายุแล้วค่ะ", "บันทึกใหม่อีกครั้งเพื่อรับรหัสใหม่นะคะ")
            )
            return
        except PlaylistDataError:
            logger.warning(f"Playlist restore rejected in guild {interaction.guild.id}: malformed data")
            await respond(
                embed=error_embed("ข้อมูลเพลย์ลิสต์ใช้ไม่ได้ค่ะ", "ข้อมูลที่บันทึกไว้ไม่สมบูรณ์ ลองบันทึกคิวใหม่อีกครั้งนะคะ")
            )
            return
        except PlaylistStoreError:
            logger.error(f"Playlist restore failed in guild {interaction.guild.id}: datastore error")
            await respond(
                embed=error_embed("กู้คืนคิวไม่ได้ค่ะ", "ระบบจัดเก็บเพลย์ลิสต์มีปัญหาชั่วคราว ลองใหม่อีกครั้งนะคะ")
            )
            return

        try:
            await self._ensure_voice_connection(interaction, state)
            saved_playlist = self.playlist_store.consume_playlist(code, interaction.guild.id)
            logger.debug(
                f"Playlist restore consumed in guild {interaction.guild.id}: "
                f"tracks={len(saved_playlist.tracks)}, "
                f"resume_offset={saved_playlist.start_position_seconds:.1f}s"
            )
            await self._restore_playlist_to_state(
                state,
                saved_playlist.tracks,
                interaction.user,
                saved_playlist.start_position_seconds,
            )
        except UserError as error:
            logger.warning(f"Playlist restore rejected in guild {interaction.guild.id}: voice validation")
            await respond(
                embed=error_embed(error.title, error.description)
            )
            return
        except PlaylistStoreError:
            logger.warning(f"Playlist restore failed in guild {interaction.guild.id}: playlist was unavailable")
            await respond(
                embed=error_embed("กู้คืนคิวไม่ได้ค่ะ", "เพลย์ลิสต์นี้ถูกใช้หรือเปลี่ยนแปลงแล้ว ลองบันทึกคิวใหม่อีกครั้งนะคะ")
            )
            return
        except Exception:
            logger.exception(f"Playlist restore failed in guild {interaction.guild.id}: playback setup")
            await respond(
                embed=error_embed("กู้คืนคิวไม่ได้ค่ะ", "หนูเริ่มเล่นเพลย์ลิสต์นี้ไม่ได้ ลองใหม่อีกครั้งนะคะ")
            )
            return

        logger.info(
            f"Restored playlist in guild {interaction.guild.id} with {len(saved_playlist.tracks)} tracks"
        )
        await respond(
            embed=success_embed(
                "♻️ กู้คืนเพลย์ลิสต์แล้วค่ะ",
                f"กำลังเริ่มเล่น {len(saved_playlist.tracks)} เพลงตามลำดับที่บันทึกไว้นะคะ",
            )
        )

    @music.command(name="volume", description="🔊 ปรับระดับเสียง (0-100)")
    async def volume(self, ctx: discord.ApplicationContext, level: discord.Option(int, min_value=0, max_value=100)):
        state = self.get_state(ctx.guild.id)
        state.volume = level / 100.0
        
        if state.active_audio_source:
            state.active_audio_source.volume = state.volume

        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
                
        await ctx.respond(embed=success_embed("🔉 ปรับเสียง", f"ปรับเสียงเป็น {level}% แล้วนะคะ (・`ω´・)"))


def setup(bot: discord.Bot):
    bot.add_cog(PlayerCog(bot))
