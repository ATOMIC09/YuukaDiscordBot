"""
utils/voice_hub.py
Single owner of Discord voice *receive* for each guild.

Why this exists
---------------
A ``VoiceClient`` supports exactly one active sink. Before this module,
``/record``, ``/transcribe`` and ``/ai voice`` each called ``start_recording()``
on the same client and silently fought over it — whoever started last won, and
whoever stopped first killed everyone else's capture. The hub owns the sink and
fans its output out to any number of subscribers instead.

What one capture produces
-------------------------
**A time-aligned timeline** per speaker (``sink.audio_data``) for ``/record``,
which needs every speaker laid onto one shared clock so the mixdown lines up.
It is only collected while some subscriber asks for it, because it grows
without bound — a voice-chat session that ran for an hour would otherwise hold
an hour of silence-padded PCM per speaker in RAM.

**Speech segments** — one utterance per user, closed after a short run of
silence. Discord clients run their own VAD and simply stop sending RTP packets
when a user is quiet, so "no packets for N ms" is a free and accurate
end-of-utterance signal. This replaces the previous approach of polling
``WaveSink``'s file position from the event loop, which raced with the reader
thread writing to that same file and clipped segments.

Threading
---------
``write()`` runs on pycord's ``AudioReader`` thread; the monitor runs on the
event loop. Both touch the same buffers, so every mutation is under
``self._lock``. Subscriber callbacks are dispatched as tasks so one slow
handler cannot stall segmentation for everybody else.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import discord

from bot.logger import logger
from utils.audio import BYTES_PER_FRAME, BYTES_PER_SECOND, OPUS_SAMPLE_RATE

SegmentCallback = Callable[["SpeechSegment"], Awaitable[None]]


@dataclass(frozen=True)
class SpeechSegment:
    """One continuous utterance from one speaker."""

    guild_id: int
    user_id: int
    pcm: bytes  # 48 kHz stereo 16-bit, as produced by pycord's Opus decoder
    started_at: float  # perf_counter of the first packet
    ended_at: float  # perf_counter when silence closed the segment
    truncated: bool = False  # hit the max-length cap while still talking

    @property
    def duration(self) -> float:
        return len(self.pcm) / BYTES_PER_SECOND


@dataclass
class _Utterance:
    """Mutable in-progress segment for one user."""

    started_at: float
    last_packet: float
    buf: bytearray = field(default_factory=bytearray)


class SegmentingSink(discord.sinks.Sink):
    """
    Recording sink that emits per-utterance segments, and optionally also
    maintains the shared per-speaker timeline that ``/record`` needs.

    Timeline alignment (when enabled)
    ---------------------------------
    pycord's base ``Sink.write()`` appends whatever PCM arrives with zero
    regard for real elapsed time, so pauses between sentences vanish and there
    is no way to line multiple speakers up against each other afterwards.

    Gaps within a single speaker's own stream are measured using each packet's
    RTP timestamp — a 48 kHz sample clock stamped by Discord's client at encode
    time — rather than wall-clock time at the moment we process it. This was
    confirmed necessary by testing: our own packet processing can stall for
    seconds at a time (thread scheduling, not network loss — sequence numbers
    stayed contiguous throughout), which wall-clock timing mistook for real
    silence, corrupting playback.

    RTP clocks are not comparable across speakers (each starts at an arbitrary
    per-session offset), so wall-clock is used exactly once per speaker, to
    anchor their first packet onto the shared session timeline — a one-time
    offset rather than a per-gap error that compounds.
    """

    def __init__(
        self,
        *,
        guild_id: int,
        loop: asyncio.AbstractEventLoop,
        on_segment: SegmentCallback,
        silence_s: float = 0.8,
        min_segment_s: float = 0.4,
        max_segment_s: float = 20.0,
        collect_timeline: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.guild_id = guild_id
        self.collect_timeline = collect_timeline

        self._loop = loop
        self._on_segment = on_segment
        self._silence_s = silence_s
        self._min_segment_s = min_segment_s
        self._max_segment_s = max_segment_s

        self._lock = threading.Lock()
        self._utterances: dict[int, _Utterance] = {}

        # asyncio only holds a weak reference to a running task, so a dispatch
        # we don't keep a handle on can be garbage-collected mid-flight.
        self._dispatch_tasks: set[asyncio.Task] = set()

        # Timeline state (only used when collect_timeline is on)
        self._start_time: float | None = None
        self._last_rtp_ts: dict[int, int] = {}
        self._last_pcm_len: dict[int, int] = {}

        self.finished = False
        self._monitor_task = loop.create_task(
            self._monitor(), name=f"voice_segment_monitor_{guild_id}"
        )

    # ── capture path (AudioReader thread) ─────────────────────────────────

    def write(self, data, user) -> None:
        from discord.voice.packets import VoiceData

        is_voice_data = isinstance(data, VoiceData)
        pcm = data.pcm if is_voice_data else data
        if not pcm:
            return

        user_id = getattr(user, "id", None) or 0
        rtp_ts = data.packet.timestamp if is_voice_data else None
        now = time.perf_counter()

        with self._lock:
            if self.collect_timeline:
                self._append_timeline(user_id, pcm, rtp_ts, now)

            utterance = self._utterances.get(user_id)
            if utterance is None:
                utterance = _Utterance(started_at=now, last_packet=now)
                self._utterances[user_id] = utterance

            utterance.buf.extend(pcm)
            utterance.last_packet = now

    def _append_timeline(
        self, user_id: int, pcm: bytes, rtp_ts: int | None, now: float
    ) -> None:
        """Lay this packet onto the shared timeline. Caller holds the lock."""
        if self._start_time is None:
            self._start_time = now

        buf = self.audio_data.setdefault(user_id, bytearray())
        last_rtp_ts = self._last_rtp_ts.get(user_id)
        last_pcm_len = self._last_pcm_len.get(user_id)

        if rtp_ts is not None and last_rtp_ts is not None and last_pcm_len is not None:
            delta_samples = (rtp_ts - last_rtp_ts) & 0xFFFFFFFF
            gap = delta_samples * BYTES_PER_FRAME - last_pcm_len
        else:
            # First packet from this user: no prior RTP timestamp to diff
            # against, so anchor them via wall-clock — once, not per gap.
            gap = (
                int((now - self._start_time) * OPUS_SAMPLE_RATE) * BYTES_PER_FRAME
                - len(buf)
            )

        if gap > 0:
            buf.extend(b"\x00" * gap)

        buf.extend(pcm)

        if rtp_ts is not None:
            self._last_rtp_ts[user_id] = rtp_ts
        self._last_pcm_len[user_id] = len(pcm)

    # ── segmentation (event loop) ─────────────────────────────────────────

    async def _monitor(self) -> None:
        """Close utterances that have gone quiet, and hand them to subscribers."""
        try:
            while not self.finished:
                await asyncio.sleep(0.1)
                now = time.perf_counter()
                ready: list[tuple[int, _Utterance, bool]] = []

                with self._lock:
                    for user_id, utterance in list(self._utterances.items()):
                        idle = now - utterance.last_packet
                        length = len(utterance.buf) / BYTES_PER_SECOND

                        # The max-length cap splits mid-sentence, but without it
                        # a monologue would never reach the model at all.
                        too_long = length >= self._max_segment_s
                        if idle >= self._silence_s or too_long:
                            self._utterances.pop(user_id, None)
                            ready.append((user_id, utterance, too_long))

                for user_id, utterance, truncated in ready:
                    self._emit(user_id, utterance, now, truncated)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # never let the monitor die silently
            logger.error(f"[VoiceHub] Segment monitor crashed for {self.guild_id}: {exc}")

    def _emit(
        self, user_id: int, utterance: _Utterance, now: float, truncated: bool
    ) -> None:
        pcm = bytes(utterance.buf)
        duration = len(pcm) / BYTES_PER_SECOND

        if duration < self._min_segment_s:
            logger.debug(
                f"[VoiceHub] Dropped {duration * 1000:.0f}ms blip from user {user_id}"
            )
            return

        segment = SpeechSegment(
            guild_id=self.guild_id,
            user_id=user_id,
            pcm=pcm,
            started_at=utterance.started_at,
            ended_at=now,
            truncated=truncated,
        )
        logger.debug(
            f"[VoiceHub] Segment: user={user_id} {duration:.2f}s truncated={truncated}"
        )
        task = asyncio.create_task(self._on_segment(segment))
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)

    def cleanup(self) -> None:
        self.finished = True
        if not self._monitor_task.done():
            self._monitor_task.cancel()


@dataclass
class _Subscriber:
    key: str
    on_segment: SegmentCallback | None
    want_timeline: bool


@dataclass
class _Recorder:
    voice_client: discord.VoiceClient
    sink: SegmentingSink
    subscribers: dict[str, _Subscriber] = field(default_factory=dict)


class VoiceHub:
    """Per-guild voice-receive coordinator. Import the ``voice_hub`` singleton."""

    def __init__(self) -> None:
        self._recorders: dict[int, _Recorder] = {}

    # ── public API ────────────────────────────────────────────────────────

    def subscribe(
        self,
        voice_client: discord.VoiceClient,
        key: str,
        *,
        on_segment: SegmentCallback | None = None,
        want_timeline: bool = False,
    ) -> SegmentingSink:
        """
        Register interest in this guild's voice receive, starting the capture
        if it isn't already running. *key* identifies the feature subscribing
        (``"record"``, ``"transcribe"``, ``"ai_voice"``) and must be passed
        back to :meth:`unsubscribe`.
        """
        guild_id = voice_client.guild.id
        recorder = self._recorders.get(guild_id)

        if recorder is None:
            recorder = self._start(voice_client, want_timeline=want_timeline)
        elif recorder.voice_client is not voice_client:
            # The bot reconnected or moved channels — the old client's sink is
            # attached to a dead reader, so rebuild against the live one.
            logger.info(f"[VoiceHub] Voice client replaced in guild {guild_id}, restarting capture")
            existing = dict(recorder.subscribers)
            self._stop(guild_id)
            recorder = self._start(voice_client, want_timeline=want_timeline)
            recorder.subscribers.update(existing)

        recorder.subscribers[key] = _Subscriber(key, on_segment, want_timeline)
        self._sync_timeline(recorder)

        logger.info(
            f"[VoiceHub] '{key}' subscribed in guild {guild_id} "
            f"({len(recorder.subscribers)} active: {', '.join(recorder.subscribers)})"
        )
        return recorder.sink

    def unsubscribe(self, guild_id: int, key: str) -> None:
        """
        Drop a subscription, stopping the capture once nobody is left. Safe to
        call for a key that was never registered.
        """
        recorder = self._recorders.get(guild_id)
        if recorder is None:
            return

        recorder.subscribers.pop(key, None)
        if not recorder.subscribers:
            logger.info(f"[VoiceHub] Last subscriber left guild {guild_id}, stopping capture")
            self._stop(guild_id)
        else:
            self._sync_timeline(recorder)
            logger.info(
                f"[VoiceHub] '{key}' unsubscribed in guild {guild_id} "
                f"({', '.join(recorder.subscribers)} remain)"
            )

    def sink_for(self, guild_id: int) -> SegmentingSink | None:
        recorder = self._recorders.get(guild_id)
        return recorder.sink if recorder else None

    def has_subscriber(self, guild_id: int, key: str) -> bool:
        recorder = self._recorders.get(guild_id)
        return bool(recorder and key in recorder.subscribers)

    def stop_guild(self, guild_id: int) -> None:
        """Tear down everything for a guild — used when the bot leaves voice."""
        if guild_id in self._recorders:
            logger.info(f"[VoiceHub] Force-stopping capture in guild {guild_id}")
            self._stop(guild_id)

    # ── internals ─────────────────────────────────────────────────────────

    def _start(
        self, voice_client: discord.VoiceClient, *, want_timeline: bool
    ) -> _Recorder:
        from bot.config import config

        guild_id = voice_client.guild.id
        loop = asyncio.get_running_loop()

        sink = SegmentingSink(
            guild_id=guild_id,
            loop=loop,
            on_segment=lambda seg: self._dispatch(seg),
            silence_s=config.stt_silence_ms / 1000,
            min_segment_s=config.stt_min_segment_ms / 1000,
            max_segment_s=config.stt_max_segment_s,
            collect_timeline=want_timeline,
        )
        recorder = _Recorder(voice_client=voice_client, sink=sink)
        self._recorders[guild_id] = recorder

        # PYCORD 2.8.0 / PR 3159 BUG WORKAROUND:
        # AudioReader.run() checks `if self.after and self.args:`. With no
        # *args, self.args is `()` which is falsy, silently dropping the
        # callback — so we pass a dummy `True`.
        voice_client.start_recording(sink, self._on_recording_stopped, True)
        logger.info(f"[VoiceHub] Capture started in guild {guild_id}")
        return recorder

    def _stop(self, guild_id: int) -> None:
        recorder = self._recorders.pop(guild_id, None)
        if recorder is None:
            return

        recorder.sink.cleanup()
        try:
            recorder.voice_client.stop_recording()
        except (discord.ClientException, AttributeError) as exc:
            # Already auto-stopped internally (e.g. the reader died, or the
            # client disconnected) — nothing left to stop.
            logger.debug(f"[VoiceHub] stop_recording() in guild {guild_id}: {exc}")

    def _sync_timeline(self, recorder: _Recorder) -> None:
        """Only pay the memory cost of the timeline while someone wants it."""
        wanted = any(sub.want_timeline for sub in recorder.subscribers.values())
        recorder.sink.collect_timeline = wanted

    async def _dispatch(self, segment: SpeechSegment) -> None:
        recorder = self._recorders.get(segment.guild_id)
        if recorder is None:
            return

        # Run subscribers concurrently: /transcribe and /ai voice can both be
        # live, and a handler that waits on an LLM must not hold up the other.
        handlers = [
            (sub.key, sub.on_segment(segment))
            for sub in list(recorder.subscribers.values())
            if sub.on_segment is not None
        ]
        if not handlers:
            return

        results = await asyncio.gather(
            *(coro for _, coro in handlers), return_exceptions=True
        )
        for (key, _), result in zip(handlers, results):
            if isinstance(result, Exception):
                logger.error(
                    f"[VoiceHub] Subscriber '{key}' raised on segment "
                    f"from user {segment.user_id}: {result}"
                )

    @staticmethod
    def _on_recording_stopped(sink: discord.sinks.Sink, *args) -> None:
        """Called from the reader thread when capture ends. Nothing to do —
        subscribers read what they need before unsubscribing."""
        logger.debug(f"[VoiceHub] Reader stopped for guild {getattr(sink, 'guild_id', '?')}")


# Singleton — import this object everywhere
voice_hub = VoiceHub()
