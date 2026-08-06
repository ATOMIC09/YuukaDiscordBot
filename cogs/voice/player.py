import asyncio
import array
import collections
import dataclasses
import math
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import discord
import yt_dlp

try:
    from yt_dlp.extractor.youtube.jsc._builtin import ejs
except ImportError:
    pass
from discord.ext import commands

from bot.logger import logger
from utils.embeds import success_embed, error_embed, info_embed
from utils.errors import UserError

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
SILENCE_FRAME = b"\x00" * PCM_FRAME_BYTES
BUFFER_SECONDS = 5.0
PREFILL_SECONDS = 1.0
CROSSFADE_SECONDS = 7.0
CROSSFADE_BUFFER_SECONDS = BUFFER_SECONDS
CROSSFADE_STARTUP_GRACE_SECONDS = 5.0
CROSSFADE_PRELOAD_LEAD_SECONDS = CROSSFADE_BUFFER_SECONDS + PREFILL_SECONDS


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
    def __init__(self, source: discord.AudioSource, buffer_seconds: float = BUFFER_SECONDS, prefill_seconds: float = PREFILL_SECONDS):
        self._source = source
        self._buffer_chunks = max(1, int(buffer_seconds * 1000 / FRAME_MS))
        self._prefill_chunks = max(1, int(prefill_seconds * 1000 / FRAME_MS))
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=self._buffer_chunks)
        self._ready = threading.Event()
        self._finished = threading.Event()
        self._stopped = threading.Event()
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

    def read(self) -> bytes:
        while True:
            try:
                return self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._finished.is_set() and self._queue.empty():
                    return b''

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        self._stopped.set()
        try:
            self._source.cleanup()
        except Exception:
            pass


class SeamlessCrossfadeSource(discord.AudioSource):
    """A persistent Discord source that can mix in a preloaded PCM stream."""

    def __init__(self, current: BufferedAudioSource):
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
        self._lock = threading.Lock()

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

    def _mix_pcm(self, current: bytes, next_frame: bytes, fade_index: int) -> bytes:
        current_samples = array.array("h")
        current_samples.frombytes(current)
        next_samples = array.array("h")
        next_samples.frombytes(next_frame)
        out_gain = self._fade_out_gains[fade_index]
        in_gain = self._fade_in_gains[fade_index]
        for index, next_sample in enumerate(next_samples):
            sample = round(current_samples[index] * out_gain + next_sample * in_gain)
            current_samples[index] = max(-32768, min(32767, sample))
        return current_samples.tobytes()

    def read(self) -> bytes:
        current = self._current.read()
        callback = None
        finish_callback = None
        with self._lock:
            next_source = self._next

        if not next_source:
            return current

        with self._lock:
            if self._frames_until_fade > 0:
                if current:
                    self._frames_until_fade -= 1
                    return current
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
            return current
        if not current:
            # Outgoing deck is spent mid-fade. Keep running the same curve
            # against silence so the incoming track still ramps up to full
            # instead of snapping there, which clicks.
            current = SILENCE_FRAME

        mixed = self._mix_pcm(current, next_frame, fade_index)
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
        self.volume: float = 1.0
        self.is_playing_loop: bool = False
        self.skip_request: bool = False
        self.last_controller_message: discord.WebhookMessage | discord.Message | None = None
        self.last_queue_message: discord.WebhookMessage | discord.Message | None = None
        self.text_channel: discord.TextChannel | discord.Thread | None = None
        self.idle_task: asyncio.Task | None = None

class PlayerControls(discord.ui.View):
    def __init__(self, cog: "PlayerCog", state: "AudioState"):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state
        self.update_buttons()

    def update_buttons(self):
        self.rewind.disabled = len(self.state.history) == 0

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
        self.crossfade.label = "Crossfade"
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

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏮️", row=0)
    async def rewind(self, button: discord.ui.Button, interaction: discord.Interaction):
        ok = await self.cog._rewind_async(self.state.guild_id)
        if not ok:
            return await interaction.response.send_message("ไม่มีเพลงก่อนหน้าให้ย้อนกลับนะคะ (´・ω・)", ephemeral=True)
        await interaction.response.defer()

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="⏸️", row=0)
    async def pause_resume(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.state.voice_client:
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่นะคะ", ephemeral=True)
            
        if self.state.voice_client.is_paused():
            self.state.voice_client.resume()
            self.cog._mark_playback_resumed(self.state)
        elif self.state.voice_client.is_playing():
            self.state.voice_client.pause()
            self.cog._mark_playback_paused(self.state)
        else:
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่นะคะ", ephemeral=True)
            
        self.update_buttons()
        await interaction.response.edit_message(view=self)

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
            
        self.update_buttons()
        
        embed = self.cog._build_player_embed(self.state.current, self.state)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Crossfade", style=discord.ButtonStyle.secondary, emoji="🔀", row=1)
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

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="⏹️", row=0)
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

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary)
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🔢", style=discord.ButtonStyle.secondary)
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

class PlayerCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.states: dict[int, AudioState] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)

    def get_state(self, guild_id: int) -> AudioState:
        if guild_id not in self.states:
            self.states[guild_id] = AudioState(self.bot, guild_id)
        return self.states[guild_id]

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
        
        # Append queue
        desc = ""
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
            self._executor,
            lambda: ytdl.extract_info(query, download=download)
        )
        return data

    async def _hydrate_track(self, track: Track) -> bool:
        """Resolve a flat-playlist track into a playable stream."""
        if track.stream_url:
            return True

        data = await self._extract_info(track.original_url, download=False)
        if not data:
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
        task = asyncio.current_task()
        try:
            if state.playback_started_at is not None:
                elapsed = self._current_playback_position(state)
                await asyncio.sleep(max(0.0, CROSSFADE_STARTUP_GRACE_SECONDS - elapsed))
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
            if not await self._hydrate_track(candidate) or candidate.duration <= 0:
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

            next_audio = BufferedAudioSource(
                discord.FFmpegPCMAudio(candidate.stream_url, **ffmpeg_options),
                buffer_seconds=CROSSFADE_BUFFER_SECONDS,
            )
            await asyncio.get_event_loop().run_in_executor(
                self._executor, next_audio.wait_ready
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
                    self._request_crossfade_prepare, state
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

    async def _play_next_async(self, guild_id: int, auto_send: bool = True):
        state = self.get_state(guild_id)
        if not state.voice_client or not state.voice_client.is_connected():
            state.current = None
            state.queue.clear()
            state.history.clear()
            state.forward_history.clear()
            state.crossfade_next = None
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

        # JIT extraction for flat playlist tracks
        if not track.stream_url:
            try:
                await self._hydrate_track(track)
            except Exception as e:
                logger.error(f"Error extracting stream url for {track.original_url}: {e}")
                # Skip to next if failed
                self.bot.loop.create_task(self._play_next_async(guild_id))
                return

        if not track.stream_url:
            logger.warning(f"Could not find stream URL for {track.title}, skipping.")
            self.bot.loop.create_task(self._play_next_async(guild_id))
            return

        try:
            buffered_source = BufferedAudioSource(
                discord.FFmpegPCMAudio(track.stream_url, **ffmpeg_options)
            )
            persistent_source = SeamlessCrossfadeSource(buffered_source)
            volume_source = discord.PCMVolumeTransformer(persistent_source, volume=state.volume)

            # Wait for the buffer to actually pre-fill (rather than a blind fixed sleep)
            # before Discord starts pulling frames on its strict 20ms clock.
            await asyncio.get_event_loop().run_in_executor(self._executor, buffered_source.wait_ready)

            def after_playing(e):
                if e:
                    logger.error(f"Player error in guild {guild_id}: {e}")
                self.bot.loop.create_task(self._play_next_async(guild_id))

            state.voice_client.play(volume_source, after=after_playing)
            state.active_audio_source = persistent_source
            state.current_played = True
            state.playback_started_at = self.bot.loop.time()
            state.playback_paused_at = None
            state.playback_offset_seconds = 0.0
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
            self.bot.loop.create_task(self._play_next_async(guild_id))

    music = discord.SlashCommandGroup("music", "🎵 ระบบเครื่องเล่นเพลง")

    @music.command(name="leave", description="👋 ออกจากห้องเสียง")
    async def leave(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client:
            raise UserError("หนูไม่ได้อยู่ในห้องนะคะ", "หนูไม่ได้อยู่ในห้องเสียงไหนเลยนะคะ (´-ω-`)")

        state = self.get_state(ctx.guild.id)
        self._clear_crossfade(state)
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

        if not ctx.guild.voice_client or not ctx.guild.voice_client.is_connected():
            if ctx.guild.voice_client:
                try:
                    await ctx.guild.voice_client.disconnect(force=True)
                except Exception:
                    pass
            state.voice_client = await channel.connect()
        else:
            state.voice_client = ctx.guild.voice_client

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

        if not ctx.guild.voice_client or not ctx.guild.voice_client.is_connected():
            if ctx.guild.voice_client:
                try:
                    await ctx.guild.voice_client.disconnect(force=True)
                except Exception:
                    pass
            state.voice_client = await channel.connect()
        else:
            state.voice_client = ctx.guild.voice_client

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

    @music.command(name="volume", description="🔊 ปรับระดับเสียง (0-100)")
    async def volume(self, ctx: discord.ApplicationContext, level: discord.Option(int, min_value=0, max_value=100)):
        state = self.get_state(ctx.guild.id)
        state.volume = level / 100.0
        
        if ctx.voice_client and ctx.voice_client.source:
            if isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
                ctx.voice_client.source.volume = state.volume
                
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
                
        await ctx.respond(embed=success_embed("🔉 ปรับเสียง", f"ปรับเสียงเป็น {level}% แล้วนะคะ (・`ω´・)"))


def setup(bot: discord.Bot):
    bot.add_cog(PlayerCog(bot))
