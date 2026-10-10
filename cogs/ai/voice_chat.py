"""
cogs/ai/voice_chat.py
AI voice chat — speak to Yuuka, she answers out loud.

This cog has NO slash commands. All /ai commands are owned by AIChatCog (chat.py)
to avoid duplicate SlashCommandGroup registration. This cog exposes:
  - start_session(ctx)     called by AIChatCog.ai_voice
  - stop_session(guild_id) called by AIChatCog.ai_stop

How speech reaches the LLM
--------------------------
1. `utils.voice_hub` owns voice receive and closes an utterance after a short
   run of packet silence (Discord clients stop sending RTP packets when a user
   is quiet, so that is a free and accurate end-of-speech signal).
2. `utils.wake_acoustic` scores the raw segment against a trained wake-word
   model *before* anything gets transcribed. This is a cheap pre-filter, not
   the trigger — a miss means "not worth transcribing", not "definitely not
   Yuuka", so every segment goes through it, every time. It also cuts earlier talk
   off the front of a segment when a pause comes before her name, and a score at
   or above STT_WAKE_ACOUSTIC_CONFIDENT_SCORE chimes before STT has run (see
   `_on_segment`).
3. `utils.stt` transcribes the segment with faster-whisper, which handles the
   Thai/English code-switching this server actually speaks.
4. `utils.wake` decides whether Yuuka was addressed. **This gate is the whole
   point**: without it she replies to every sentence anyone says in the room.
   There is no standing follow-up window — every utterance needs the wake
   word, on purpose. What she does is answer it Assistant-style: the moment
   the transcript shows her name she plays a short chime (`utils.chime`), and
   if nothing but her name was said she listens to that speaker's *next*
   utterance (`_start_listening`), with no wake word, for
   `STT_LISTEN_WINDOW_S`. The chime is the cue that she is listening, so it
   is never ambiguous, and it only ever sounds for a real match: the acoustic
   score is not trusted that far (it is weak on some speakers and fires on
   ordinary talk). That speaker's next segment waits for the verdict rather
   than racing it (`verifying`).
   While a track plays she cannot `play()` (one VoiceClient), so the chime and her
   voice are mixed into the track's own mixer instead, with the music turned down
   under them (`SeamlessCrossfadeSource.add_overlay`). Only a paused track leaves
   her no way to be heard, and a short text notice stands in then.
5. The accepted text goes through the same LLM → TTS → playback path as a
   typed message.
6. The reply comes from the agent loop (`utils.ai.run_agent`), which may call
   tools first. The sentence she writes before a tool is spoken right away so
   the room is not left in silence while it runs. A tool that runs a bot
   command (`utils.ai_actions`) also waits for that speech to finish first
   (a track cannot start while she is mid-sentence — one VoiceClient). The
   session is never torn down: while music plays she keeps listening and
   answers over it.

Each spoken turn logs how long every stage took, counted from the moment the hub
closed the segment (`[Timing]` lines, see `_mark`), so a slow reply can be traced
to its stage instead of guessed at.

Both a typed message and a spoken one land in `_respond()`, so the two entry
points cannot drift apart.

Listeners:
  - on_message            — generates LLM reply + TTS when @mentioned
  - on_voice_state_update — auto-cleanup if bot is kicked from voice
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field

import discord
from discord.ext import commands

from bot.config import config
from bot.logger import logger
from utils import chime, wake
from utils.audio import boost_pcm, decode_to_pcm, music_mixer, pcm_duration_seconds
from utils.ai import YuukaContext, run_agent
from utils.ai.context import stamp
from utils.ai.progress import TurnProgress
from utils.ai.tools.memory import disclosure_note
from utils.embeds import (
    ai_disclosure_field,
    build_embed,
    COLOR_SUCCESS,
    error_embed,
    info_embed,
)
from utils.ai.confirm import ConfirmActionView, spoken_decision
from utils.errors import UserError, UserWarning
from utils.stt import ensure_loaded, model_description, transcribe_pcm
from utils.tts import synthesize_speech
from utils.voice_hub import SpeechSegment, voice_hub
from utils.wake_acoustic import acoustic_wake

_HUB_KEY = "ai_voice"

# ──────────────────────────────────────────────────────────────────────────────
# Voice-mode system prompt suffix — injected at runtime, not stored in .env
# The base system prompt already covers brevity and conversational tone.
# This only adds voice-specific constraints: output goes to TTS audio, so
# markdown symbols, code blocks, and formatting tags must be avoided entirely.
# ──────────────────────────────────────────────────────────────────────────────
_VOICE_PROMPT_SUFFIX = (
    "\n\nVOICE MODE: Your reply will be read aloud via text-to-speech. "
    "CRITICAL RULES: "
    "1. Keep responses VERY SHORT and concise (1-5 sentences maximum). After a web search, "
    "start with a SHORT spoken answer (1-3 sentences) and put the results, lists and links "
    "AFTER A BLANK LINE: they are shown in the text chat and never read aloud, so do not "
    "repeat them in the spoken part. "
    "2. DO NOT use emojis of any kind. "
    "3. DO NOT write out physical actions or expressions in parentheses/asterisks (e.g., (หน้าแดง), *ถอนหายใจ*). Vocal sounds like 'ฮ่าๆ' or 'อ่า' are OK. "
    "4. DO NOT use markdown, code blocks, asterisks, or special formatting. "
    "5. Some user turns arrive from speech recognition and may contain "
    "misheard words, especially names and mixed Thai/English. Infer what was "
    "meant from context; ask for a repeat only if it is genuinely unclear. "
    "6. To use a tool, write only the call, with nothing before it: an action says its own "
    "short line out loud when it runs, so you never need to speak first. Never think out "
    "loud in your reply; everything you write is spoken."
)

# Added to the system prompt while more than one person is in the voice channel, so a
# reply says who it is for (several people can be waiting on her at once).
_MULTI_SPEAKER_NOTE = (
    "\n\nSeveral people are talking to you in this call. Each user turn shows who "
    "spoke. Start your reply by addressing that person by the name shown, so the room "
    "knows who it is for, then answer. Skip the name if it is only symbols or emoji."
)

# Requests waiting behind the one she is answering. A room of friends never gets near
# this; it only bounds a stuck turn.
_MAX_PENDING = 6

# Stands in for the chime when it cannot be mixed in: a paused track, or her own clip
# holding the voice client. Over a playing track the chime itself sounds.
_LISTENING_NOTICE = "-# (๑•̀ᴗ•́)و หนูฟังอยู่ค่ะ เซนเซย์ พูดได้เลยน้า"

# When the acoustic model is sure it was her name (the early chime) and the transcript
# has no name in it, STT misheard it. Fewer characters than this is all that was said
# (the mishearings seen were 2-8: "8日", "ยุคค่ะ", "อยู่ป่ะ", "You got it."), so she
# listens for the request; more is the request itself.
_MIN_REQUEST_CHARS = 12

_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Includes Discord's <https://...> form, which tool results use for links.
_BARE_URL = re.compile(r"<?https?://[^\s>]+>?")

# Whether a reply ends by asking the speaker something. Thai marks a question with
# คะ (a statement takes ค่ะ), but "นะคะ" softens a statement, so it does not count.
_TRAILING_NOISE = re.compile(r"(?:\s|[.!…~。]|\([^)]*\))+$")
_ASKS = re.compile(
    r"(?:\?|？|(?<!นะ)คะ|ไหม|มั้ย|หรือเปล่า|เหรอ|หรอ|อะไร|ไหน|ใคร|ยังไง|เท่าไหร่|กี่[ก-๙]*)$"
)


def _asks_user(text: str) -> bool:
    return bool(_ASKS.search(_TRAILING_NOISE.sub("", text.strip())))


def _spoken_chars(text: str) -> int:
    """How much was said: characters that are not spaces or punctuation (Thai marks count)."""
    return sum(1 for ch in text if not ch.isspace() and unicodedata.category(ch)[0] != "P")


def _speakable(text: str) -> str:
    """The text as it should be read aloud: links are never spoken."""
    text = _MD_LINK.sub(r"\1", text)
    text = _BARE_URL.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE_END = re.compile(r"[.!?…。！？]+(?=\s|$)")
_PARAGRAPH = re.compile(r"\n\s*\n")
# Said after a reply that was cut short for speech. The whole reply is in the chat.
_MORE_IN_CHAT = "ที่เหลือหนูพิมพ์ไว้ในแชทแล้วนะคะ เซนเซย์"
# A Discord message holds 2000 characters.
_CHAT_CHUNK = 1900


def _clip(text: str, limit: int) -> str:
    """`text` cut to at most `limit` characters at a sentence end, else at a space."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends and ends[-1] >= limit * 0.4:
        return window[: ends[-1]].strip()
    space = window.rfind(" ")
    if space >= limit * 0.4:
        return window[:space].strip()
    return window.strip()


def _spoken_part(text: str, limit: int) -> tuple[str, bool]:
    """What of a reply she reads aloud, and whether the chat holds more than that.

    The model puts the short spoken answer first and any detail after a blank line, so
    the first paragraph is spoken; one longer than `limit` is clipped as well."""
    paragraphs = [p for p in _PARAGRAPH.split(text.strip()) if p.strip()]
    if not paragraphs:
        return "", False
    head = _speakable(paragraphs[0])
    more = len(paragraphs) > 1
    if len(head) > limit:
        head, more = _clip(head, limit), True
    return head, more


def _chat_chunks(text: str, size: int = _CHAT_CHUNK) -> list[str]:
    """`text` in pieces that fit one Discord message, split at line ends where it can."""
    chunks: list[str] = []
    current = ""
    for line in text.strip().split("\n"):
        while len(line) > size:
            cut = line.rfind(" ", 0, size)
            cut = cut if cut > size * 0.4 else size
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:cut])
            line = line[cut:].lstrip()
        if current and len(current) + 1 + len(line) > size:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current.strip():
        chunks.append(current)
    return chunks


# Echo guard: a speaker without headphones has Yuuka's own voice coming back
# through their mic. Anything captured while she was talking (plus a short
# tail) is discarded rather than transcribed.
_ECHO_TAIL_S = 0.4

# How long a speaker's next segment waits for the verdict on the one before it
# (is that her name?). Longer than a normal STT round trip, short enough that a
# stalled request cannot hold the speaker back.
_VERDICT_WAIT_S = 5.0

# How long the "stopped listening" chime waits for a start chime still ringing. A chime
# is about 0.4 s (0.6 s cold); this covers it, and is too short to hold anything up
# behind her own speech, which it then simply skips.
_END_CHIME_WAIT_S = 0.8

# How long past a clip's own length to wait for it to come out of the music mixer. Only
# reached when the track was paused or stopped under it.
_OVERLAY_GRACE_S = 5.0

# Upper bound on waiting for queued speech to finish playing. Only reached when
# the audio worker has died, which must not wedge the turn forever.
_SPEECH_DRAIN_TIMEOUT_S = 60.0


def _mark(display: str, label: str, t0: float | None) -> None:
    """Log that a stage of a spoken turn finished, in seconds since `t0`.

    `t0` is when the hub closed the segment, which is `STT_SILENCE_MS` after the
    speaker actually stopped, so add that to what a speaker felt."""
    if t0 is not None:
        logger.info(f"[Timing] {display}: {label} +{time.perf_counter() - t0:.2f}s")


@dataclass
class _Request:
    """One thing someone asked her, waiting for or in the middle of its turn."""

    user_id: int | None
    speaker: str
    text: str
    member: discord.Member | None = None
    heard_at: float | None = None  # when its segment closed, for the timing log


@dataclass
class _Timing:
    """One timed spoken turn. It rides along with each clip she queues, because the
    audio worker plays it after `_respond` has already returned."""

    speaker: str
    t0: float
    first_output_logged: bool = False


def _mark_turn(session: "VoiceChatSession", label: str) -> None:
    """`_mark` for the spoken turn the session is answering, if it is timed."""
    if session.timing is not None:
        _mark(session.timing.speaker, label, session.timing.t0)


def _mark_first_output(timing: _Timing | None, label: str) -> None:
    """Log the first thing of a turn the room could hear or read; later ones are not news."""
    if timing is not None and not timing.first_output_logged:
        timing.first_output_logged = True
        _mark(timing.speaker, label, timing.t0)


@dataclass
class VoiceChatSession:
    """All state for a single active voice-chat session (one per guild)."""

    text_channel: discord.TextChannel
    voice_client: discord.VoiceClient
    history: list[dict] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None

    # The interval during which Yuuka herself was audible, in perf_counter
    # terms. Segments overlapping it are echo and get dropped.
    speaking_from: float = 0.0
    speaking_until: float = 0.0

    # One in-flight generation per guild. A request that arrives meanwhile (a second
    # speaker, or the same one asking again) waits in `pending` and is answered in turn.
    busy: bool = False
    active: _Request | None = None
    pending: deque = field(default_factory=deque)

    # Speakers she is listening to after their bare wake word, by user id. The
    # window itself is `awaiting_answer`; this task only sounds the closing chime
    # if it runs out unused (see _start_listening).
    listening: dict[int, asyncio.Task] = field(default_factory=dict)

    # The "she is listening" text notice per speaker, while a track keeps the chime
    # from sounding; removed again when the window closes.
    notices: dict[int, discord.Message] = field(default_factory=dict)

    # Speakers whose last segment is still being transcribed to see if it was her name,
    # by user id. Set once that verdict is known, so a segment that arrives meanwhile
    # (a request right after the name) waits for it instead of being gated on its own.
    verifying: dict[int, asyncio.Event] = field(default_factory=dict)

    # The spoken turn being answered, or None for a typed one. See `_mark`.
    timing: _Timing | None = None

    # Whether the room has already been told she is typing instead of speaking.
    # Explaining it once per silent stretch is helpful; repeating it above every
    # reply is noise. Cleared again the moment she manages to speak out loud.
    text_fallback_announced: bool = False

    # A proposed action waiting for its requester's spoken yes or no, by user id.
    # Only the requester's own voice counts. Entries are checked with `view.done`,
    # so a button press or a timeout needs no cleanup here.
    pending_confirms: dict[int, ConfirmActionView] = field(default_factory=dict)

    # She just asked this person a question: user id → perf_counter deadline for
    # the start of their answer. One use. Also the listening window after a bare
    # wake word.
    awaiting_answer: dict[int, float] = field(default_factory=dict)


class AIVoiceChatCog(commands.Cog, name="AI Voice Chat"):
    """
    AI voice chat logic.

    No slash commands here — all /ai commands live in AIChatCog (chat.py).
    This cog exposes start_session() / stop_session() as public methods that
    AIChatCog calls via self.bot.cogs.get("AI Voice Chat").
    """

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # guild_id → VoiceChatSession
        self.active_sessions: dict[int, VoiceChatSession] = {}

    # ──────────────────────────────────────────────────────────────────────
    # Audio worker — drains the queue and plays MP3s one at a time (FIFO)
    # ──────────────────────────────────────────────────────────────────────

    async def _audio_worker(self, guild_id: int) -> None:
        """Background task: plays queued MP3 files in order, cleans up after each."""
        session = self.active_sessions.get(guild_id)
        if session is None:
            return

        logger.debug(f"[AI Voice] Audio worker started for guild {guild_id}")
        try:
            while True:
                mp3_path, spoken_text, timing = await session.queue.get()

                vc = session.voice_client
                if not vc or not vc.is_connected():
                    logger.warning(
                        f"[AI Voice] Voice client gone for guild {guild_id}, posting the line instead"
                    )
                    self._discard(mp3_path)
                    await self._post_unspoken(session, spoken_text, timing)
                    session.queue.task_done()
                    continue

                # A playing track takes her voice into its own mixer, which ducks the
                # music under it: play() would raise on a client that is busy.
                if music_mixer(vc) is not None:
                    await self._speak_over_music(session, mp3_path, spoken_text, timing)
                    session.queue.task_done()
                    continue

                # Anything else holding the client (a paused track, her own earlier
                # clip) leaves no slot. Losing the audio slot is not a reason to lose
                # the answer, so it goes to the text channel instead of nowhere.
                if vc.is_playing() or vc.is_paused():
                    logger.info(
                        f"[AI Voice] Voice client busy in guild {guild_id}, posting the line instead"
                    )
                    self._discard(mp3_path)
                    await self._post_unspoken(session, spoken_text, timing)
                    session.queue.task_done()
                    continue

                play_done = asyncio.Event()
                loop = asyncio.get_event_loop()  # capture before entering the thread

                def _after(error: Exception | None) -> None:
                    if error:
                        logger.error(f"[AI Voice] Playback error in guild {guild_id}: {error}")
                    loop.call_soon_threadsafe(play_done.set)

                # Mark the echo window open before the first sample plays.
                session.speaking_from = time.perf_counter()
                session.speaking_until = float("inf")

                source = discord.FFmpegPCMAudio(mp3_path)
                vc.play(source, after=_after)
                chime.mark_warm(vc)
                _mark_first_output(timing, "first sound")

                await play_done.wait()

                session.speaking_until = time.perf_counter() + _ECHO_TAIL_S
                # She has her voice back, so the next silent stretch is worth
                # explaining again.
                session.text_fallback_announced = False

                try:
                    os.unlink(mp3_path)
                    logger.debug(f"[AI Voice] Deleted temp file {mp3_path}")
                except OSError as e:
                    logger.warning(f"[AI Voice] Could not delete temp file {mp3_path}: {e}")

                session.queue.task_done()

        except asyncio.CancelledError:
            logger.debug(f"[AI Voice] Audio worker cancelled for guild {guild_id}")
            session.speaking_until = time.perf_counter()

    async def _speak_over_music(
        self, session: VoiceChatSession, mp3_path: str, spoken_text: str, timing: _Timing | None
    ) -> None:
        """Say a clip over the track that is playing, with the music turned down."""
        try:
            pcm = await decode_to_pcm(mp3_path)
        except Exception as exc:
            logger.error(f"[AI Voice] Could not decode her clip to mix over the music: {exc}")
            pcm = b""
        finally:
            self._discard(mp3_path)

        # Looked up again: the track may have changed or paused while decoding.
        mixer = music_mixer(session.voice_client)
        if not pcm or mixer is None:
            await self._post_unspoken(session, spoken_text, timing)
            return

        duration = pcm_duration_seconds(pcm)
        loop = asyncio.get_running_loop()
        done = asyncio.Event()
        # Her voice is audible for the clip plus the duck's lead-in. The end is finite
        # on purpose: stop_session reads an infinite one as her own clip owning the
        # client and would stop the track.
        now = time.perf_counter()
        session.speaking_from = now
        session.speaking_until = now + duration + 0.1 + _ECHO_TAIL_S
        mixer.add_overlay(
            boost_pcm(pcm, config.speech_over_music_gain), lambda: loop.call_soon_threadsafe(done.set)
        )
        _mark_first_output(timing, "first sound (over the music)")

        try:
            await asyncio.wait_for(done.wait(), timeout=duration + _OVERLAY_GRACE_S)
        except asyncio.TimeoutError:
            logger.warning("[AI Voice] Her clip never came out of the music mixer (track paused or stopped?)")
        session.speaking_until = time.perf_counter() + _ECHO_TAIL_S
        session.text_fallback_announced = False

    # ──────────────────────────────────────────────────────────────────────
    # Speech input — segment → transcript → wake gate → reply
    # ──────────────────────────────────────────────────────────────────────

    async def _on_segment(self, segment: SpeechSegment) -> None:
        session = self.active_sessions.get(segment.guild_id)
        if session is None:
            return

        # Drop anything captured while Yuuka was audible — that is her own
        # voice coming back through somebody's speakers.
        if segment.ended_at > session.speaking_from and segment.started_at < session.speaking_until:
            logger.debug(
                f"[AI Voice] Dropped {segment.duration:.1f}s of echo from user {segment.user_id}"
            )
            return

        # A Member, not just a User: running a command on someone's behalf needs
        # to know which voice channel they are sitting in. A cache miss only
        # costs the ability to run actions for them, so the name still falls
        # back to the user cache rather than degrading every log line too.
        guild = self.bot.get_guild(segment.guild_id)
        member = guild.get_member(segment.user_id) if guild else None
        user = member or self.bot.get_user(segment.user_id)
        display = user.display_name if user else f"Unknown ({segment.user_id})"

        # Another bot in the room is never a speaker. Its chimes and music score on
        # the acoustic model, and if it is also a Yuuka the two answer each other's
        # chime forever, each round costing an STT request.
        if user is not None and user.bot:
            logger.debug(f"[AI Voice] Ignored {segment.duration:.1f}s from bot {display}")
            return

        # Their previous segment may still be on its way through STT, and whether it
        # was her name decides what this one is (a request, or just talk). Wait for
        # that verdict rather than gate this segment on its own.
        pending = session.verifying.get(segment.user_id)
        if pending is not None:
            try:
                await asyncio.wait_for(pending.wait(), timeout=_VERDICT_WAIT_S)
            except asyncio.TimeoutError:
                pass

        # A pending confirmation is the one thing heard without the wake word: the
        # requester answering "ยืนยัน" or "ยกเลิก" to a proposal Yuuka just made. It
        # is scoped to that speaker, ends with the 60 s button, and only a short
        # yes/no utterance counts; anything else falls through to the normal gate.
        result = None
        view = session.pending_confirms.get(segment.user_id)
        if view is not None and view.done:
            session.pending_confirms.pop(segment.user_id, None)
        elif view is not None:
            result = await transcribe_pcm(segment.pcm, display)
            decision = spoken_decision(result.text) if result.text else None
            if decision is not None:
                logger.info(f"[AI Voice] Spoken answer from {display}: {result.text!r} -> {decision}")
                session.pending_confirms.pop(segment.user_id, None)
                await view.decide_by_voice(decision)
                return
            if not result.text:
                return

        # Likewise for what she is waiting to hear from this speaker: the answer to
        # a question she just asked (a missing detail, which of two members), or
        # the request after a bare wake word (see _start_listening). It belongs to
        # that speaker alone and is used up by their next utterance, so it never
        # turns into a standing "awake" state.
        deadline = session.awaiting_answer.pop(segment.user_id, None)
        if deadline is not None and segment.started_at <= deadline:
            if result is None:
                result = await transcribe_pcm(segment.pcm, display)
                _mark(display, "transcript (answer)", segment.ended_at)
            if not result.text:
                # A cough or a breath must not use up the window.
                if time.perf_counter() < deadline:
                    session.awaiting_answer.setdefault(segment.user_id, deadline)
                return
            text = result.text
            again = wake.detect(
                text,
                config.stt_wake_words,
                threshold=config.stt_wake_threshold,
                head_chars=config.stt_wake_head_chars,
                anywhere=config.stt_wake_anywhere,
            )
            # Her name again ("Yuuka" repeated because nothing seemed to happen) is
            # not the request: say she is listening once more.
            if again and not again.remainder:
                logger.info(f"[AI Voice] {display} said her name again: {text!r}")
                self._relisten(session, segment.user_id, display)
                return
            if again:
                text = again.remainder  # the name is addressing, not content
            self._cancel_listening(session, segment.user_id)
            # The window is used: the same "stopped listening" sound as when it runs out,
            # and the reply that follows says she got it.
            asyncio.create_task(self._end_chime(session))
            logger.info(f"[AI Voice] Heard {display} while listening: {text}")
            await self._announce_and_respond(
                segment.guild_id, session, display, text, member,
                heard=result.text, heard_at=segment.ended_at,
                user_id=segment.user_id,
            )
            return

        # Cheap pre-filter: is this worth transcribing at all? Runs on every
        # segment — there is no standing "awake" state that skips it.
        # (Skipped when a pending confirmation already had it transcribed.)
        acoustic = None if result is not None else await acoustic_wake.detect(segment.pcm, segment.pauses)
        heard, acoustic_score = (True, 0.0) if acoustic is None else (acoustic.heard, acoustic.score)
        if not heard:
            logger.debug(
                f"[AI Voice] No acoustic wake hit from {display} "
                f"(score {acoustic_score:.3f} < {config.stt_wake_acoustic_threshold}), skipping STT"
            )
            return

        logger.debug(
            f"[AI Voice] Acoustic wake hit from {display} "
            f"(score {acoustic_score:.3f} >= {config.stt_wake_acoustic_threshold})"
        )
        _mark(display, "acoustic gate passed", segment.ended_at)

        # A score this high is her name, and STT is slower than the person can stand to
        # wait for a sign of it: chime now, then let the transcript decide what she was
        # asked. Anyone she is already answering is left to the normal path, where the
        # transcript says whether it is a repeat. Below this score the acoustic score is
        # not proof of her name (weak on some voices, and it fires on ordinary talk), so
        # nothing is signalled until the transcript confirms it.
        # A request said with the name (`oneshot`) gets no ding: it waits for STT and then the
        # "got it" tik-tik alone, since there is nothing left to listen for.
        early: bool | None = None  # None = no early chime; else whether it could sound
        if (
            acoustic is not None
            and acoustic.confident
            and not acoustic.oneshot
            and not self._already_asked(session, segment.user_id, "")
        ):
            early = chime.play(session.voice_client, "wake")
            _mark(display, "chime (acoustic)" if early else "chime skipped (voice busy)", segment.ended_at)

        # Until the verdict is in, this speaker's next segment waits on `verifying`.
        verdict: asyncio.Event | None = None
        if result is None:
            verdict = asyncio.Event()
            session.verifying[segment.user_id] = verdict

        remainder = ""
        try:
            if result is None:
                # Earlier talk before a pause that precedes her name stays out of it, so STT
                # is shorter and the chatter is not taken for the request.
                heard_pcm = segment.pcm[acoustic.cut:] if acoustic is not None and acoustic.cut else segment.pcm
                result = await transcribe_pcm(heard_pcm, display)
                _mark(display, "transcript", segment.ended_at)
            if not result.text:
                if early is not None:
                    # She chimed, so she is listening: a name STT could not hear still is one.
                    self._start_listening(session, segment.user_id, display, chimed=early)
                return

            match = wake.detect(
                result.text,
                config.stt_wake_words,
                threshold=config.stt_wake_threshold,
                head_chars=config.stt_wake_head_chars,
                anywhere=config.stt_wake_anywhere,
            )
            if match:
                logger.info(
                    f"[AI Voice] Wake word '{match.word}' matched at {match.score:.0f} "
                    f"(threshold {config.stt_wake_threshold}) from {display}"
                )
                remainder = match.remainder
            elif early is None:
                # Logged at debug with the score so STT_WAKE_THRESHOLD can be
                # tuned against what these speakers' mics actually produce.
                logger.debug(
                    f"[AI Voice] No wake word from {display} "
                    f"(best {match.score:.0f} vs {match.word or '—'}, "
                    f"threshold {config.stt_wake_threshold}): {result.text}"
                )
                return
            else:
                # The model is sure it was her name and the transcript has none, so STT
                # misheard it ("ยุคค่ะ", "8日"). Little else said means that was all of it;
                # more is the request, name and all, which the model reads past.
                remainder = result.text if _spoken_chars(result.text) >= _MIN_REQUEST_CHARS else ""
                logger.info(
                    f"[AI Voice] Acoustic score {acoustic_score:.3f} but no name in {result.text!r} from "
                    f"{display}: taken as {'a request' if remainder else 'her name'}"
                )

            if early is None:
                if self._already_asked(session, segment.user_id, remainder):
                    # No chime and no new window: a second signal would only open a
                    # listening window whose next sentence goes to the model.
                    logger.info(f"[AI Voice] {display} repeated a request she is already on: {result.text!r}")
                    return
                # A request said with her name is already heard in full, so it gets the
                # "got it" tik-tik; her name alone gets the ding that says "go on".
                chimed = chime.play(session.voice_client, "got" if remainder else "wake")
                _mark(display, "chime" if chimed else "chime skipped (voice busy)", segment.ended_at)
            else:
                chimed = early  # it sounded before STT
                if remainder and early:
                    # Taken for a bare name, but a request came with it: the ding already
                    # rang, so the tik-tik follows to say she has it.
                    asyncio.create_task(self._end_chime(session, "got"))
            if not remainder:
                # Just her name and nothing else: she listens for the next thing
                # this speaker says.
                self._start_listening(session, segment.user_id, display, chimed=chimed)
        finally:
            if verdict is not None:
                verdict.set()
                if session.verifying.get(segment.user_id) is verdict:
                    session.verifying.pop(segment.user_id, None)

        if remainder:
            # The request came with her name, so there is nothing left to listen for.
            await self._announce_and_respond(
                segment.guild_id, session, display, remainder, member,
                heard=result.text, heard_at=segment.ended_at,
                user_id=segment.user_id,
            )

    def _start_listening(
        self,
        session: VoiceChatSession,
        user_id: int,
        display: str,
        *,
        chimed: bool = True,
        window: float | None = None,
    ) -> float:
        """Open the no-wake-word window for `user_id`'s next utterance.

        Returns its deadline. `chimed=False` means the chime could not sound (a track
        holds the voice client), so a text notice says she is listening instead."""
        window = config.stt_listen_window_s if window is None else window
        deadline = time.perf_counter() + window
        session.awaiting_answer[user_id] = deadline
        self._cancel_listening(session, user_id)
        session.listening[user_id] = asyncio.create_task(
            self._listen_expiry(session, user_id, deadline),
            name=f"listen_{session.text_channel.guild.id}_{user_id}",
        )
        logger.debug(f"[AI Voice] Listening to {display} for {window:.0f}s")

        if not chimed:
            asyncio.create_task(self._post_listening_notice(session, user_id, window))
        return deadline

    async def _end_chime(self, session: VoiceChatSession, kind: str = "done") -> None:
        """The chime after a start chime: "done" (stopped listening) or "got" (a request came
        with the name after all). The start chime may still be ringing (it can sound
        before STT, and a quick transcript lands half a second later), and a busy client
        skips a chime, so wait for it briefly. Music is no reason to wait: over a track the
        chime is mixed in."""
        vc = session.voice_client
        give_up = time.perf_counter() + _END_CHIME_WAIT_S
        while vc is not None and vc.is_playing() and music_mixer(vc) is None and time.perf_counter() < give_up:
            await asyncio.sleep(0.02)
        chime.play(vc, kind)

    def _relisten(self, session: VoiceChatSession, user_id: int, display: str) -> None:
        """She was called again while listening: signal again and restart the window."""
        self._start_listening(
            session, user_id, display, chimed=chime.play(session.voice_client, "wake")
        )

    async def _post_listening_notice(
        self, session: VoiceChatSession, user_id: int, window: float
    ) -> None:
        try:
            message = await session.text_channel.send(_LISTENING_NOTICE, delete_after=window)
        except discord.HTTPException:
            return
        session.notices[user_id] = message

    def _drop_notice(self, session: VoiceChatSession, user_id: int) -> None:
        message = session.notices.pop(user_id, None)
        if message is not None:
            asyncio.create_task(self._delete_quietly(message))

    @staticmethod
    async def _delete_quietly(message: discord.Message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            pass  # already gone (delete_after) or not ours to delete

    def _cancel_listening(self, session: VoiceChatSession, user_id: int) -> None:
        task = session.listening.pop(user_id, None)
        if task is not None:
            task.cancel()
        self._drop_notice(session, user_id)

    async def _listen_expiry(
        self, session: VoiceChatSession, user_id: int, deadline: float
    ) -> None:
        """Sound the closing chime if the window ran out without a word.

        `awaiting_answer` stays the authority on whether the window is still open;
        this only decides whether to say it has closed. Silent when the window was
        used (the entry is gone) or when the speaker is mid-sentence, in which case
        that sentence still counts, because it started before the deadline."""
        try:
            await asyncio.sleep(max(0.0, deadline - time.perf_counter()))
        except asyncio.CancelledError:
            return
        if session.listening.get(user_id) is asyncio.current_task():
            session.listening.pop(user_id, None)
        if session.awaiting_answer.get(user_id) != deadline:
            return
        started = voice_hub.speaking_since(session.text_channel.guild.id, user_id)
        if started is not None and started <= deadline:
            return
        session.awaiting_answer.pop(user_id, None)
        logger.debug(f"[AI Voice] Listening window for user {user_id} closed unused")
        chime.play(session.voice_client, "done")

    async def _announce_and_respond(
        self,
        guild_id: int,
        session: VoiceChatSession,
        display: str,
        prompt: str,
        member: discord.Member | None = None,
        heard: str | None = None,
        heard_at: float | None = None,
        user_id: int | None = None,
    ) -> None:
        """Post what she heard, then generate and speak a reply.

        `prompt` is what the LLM is given — the wake word stripped out, since it
        is addressing and not content. `heard` is the raw transcript to display.
        They differ because cutting the wake word out of the middle of a
        sentence leaves a mangled quote ("Hey play never gonna give you up"),
        and the whole point of posting the line is to show what she actually
        heard when a reply looks like a non-sequitur.
        """
        # The 💬 marks it as voice *chat*: /transcribe posts live captions under
        # 🎙️, and two identical-looking streams are impossible to tell apart.
        try:
            await session.text_channel.send(f"💬 **{display}**: {heard or prompt}")
        except discord.HTTPException:
            pass

        await self._respond(guild_id, session, display, prompt, member, heard_at, user_id)

    # ──────────────────────────────────────────────────────────────────────
    # Shared reply path — used by both spoken and typed input
    # ──────────────────────────────────────────────────────────────────────

    async def _remember(self, session: VoiceChatSession, speaker: str, text: str) -> None:
        """Append a user turn to history, trimming to the configured window."""
        timestamp = stamp(discord.utils.utcnow())
        session.history.append({"role": "user", "content": f"[{timestamp}] {speaker}: {text}"})
        while len(session.history) > config.max_history_length:
            session.history.pop(1)  # preserve system prompt at index 0

    @staticmethod
    def _discard(mp3_path: str) -> None:
        """Delete a temp clip that is not going to be played."""
        try:
            os.unlink(mp3_path)
        except OSError:
            pass

    async def _post_unspoken(
        self, session: VoiceChatSession, text: str, timing: _Timing | None = None
    ) -> None:
        """Deliver in text what she could not say out loud.

        Reached whenever she cannot be heard: a paused track, her own earlier
        clip, or a lost connection. Silently dropping the line makes her look broken; the
        answer is the point, the voice is only the medium.

        Sent as a plain message rather than an embed: this is her ordinary reply
        that happens to be typed, and wrapping every one in a titled box buries
        the content it is supposed to deliver. The reason is explained once per
        silent stretch and then left alone.
        """
        if not text.strip():
            return

        body = text
        if not session.text_fallback_announced:
            # Discord subtext ("-# ") renders small and grey, so the reason sits
            # above the reply without competing with it.
            body = "-# 🔇 ตอนนี้หนูพูดไม่ได้ (เพลงหยุดอยู่ หรือมีเสียงอื่นเล่นอยู่) ขอพิมพ์ตอบแทนนะคะ\n" + text
            session.text_fallback_announced = True

        try:
            await session.text_channel.send(body)
        except discord.HTTPException as exc:
            logger.warning(f"[AI Voice] Could not post an unspoken line: {exc}")
        else:
            _mark_first_output(timing, "answer posted as text")

    async def _post_reply(self, session: VoiceChatSession, text: str) -> None:
        """Show her whole reply in the text chat, as well as saying part of it.

        A spoken reply is short, so the detail (a search's results, links) lives here.
        Links do not unfurl and nobody is pinged by what she quotes."""
        for i, chunk in enumerate(_chat_chunks(text)):
            body = f"💬 **Yuuka**: {chunk}" if i == 0 else chunk
            try:
                await session.text_channel.send(
                    body, suppress_embeds=True, allowed_mentions=discord.AllowedMentions.none()
                )
            except discord.HTTPException as exc:
                logger.warning(f"[AI Voice] Could not post her reply: {exc}")
                return

    async def _speak(
        self, session: VoiceChatSession, text: str, *, posted: bool = False, typed: bool = True
    ) -> None:
        """Say `text` out loud, or post it if the voice slot is taken.

        The check here is an optimisation, not the safety net: synthesizing an
        MP3 the worker is only going to discard costs an Edge-TTS round trip and
        a temp file for nothing. The worker still re-checks, because music can
        start in the gap between this line and playback.

        `posted` says the text is already in the chat (`_post_reply`), so a voice
        slot that is taken only needs the reason, not the line again. `typed=False`
        is for a line that is worth nothing in text (an action's "done", which its
        embed already says): it is dropped when it cannot be spoken.
        """
        if not text.strip():
            return

        vc = session.voice_client
        if vc and (vc.is_playing() or vc.is_paused()) and music_mixer(vc) is None:
            if not typed:
                logger.info("[AI Voice] Voice slot taken, not typing a line that is only for speech")
                return
            logger.info("[AI Voice] Voice slot taken, answering in text without synthesizing")
            if posted:
                if not session.text_fallback_announced:
                    session.text_fallback_announced = True
                    try:
                        await session.text_channel.send(
                            "-# 🔇 ตอนนี้หนูพูดไม่ได้ (เพลงหยุดอยู่ หรือมีเสียงอื่นเล่นอยู่) อ่านคำตอบในแชทได้เลยนะคะ"
                        )
                    except discord.HTTPException:
                        pass
                _mark_first_output(session.timing, "answer posted as text")
            else:
                await self._post_unspoken(session, text, session.timing)
            return

        spoken = _speakable(text)
        if not spoken:
            return

        try:
            mp3_path = await synthesize_speech(spoken)
            _mark_turn(session, "speech synthesized")
            # The original text, links included, rides along so the worker can
            # still deliver the answer if it turns out it cannot play the audio
            # (nothing to deliver when the chat already has it).
            await session.queue.put((mp3_path, "" if posted or not typed else text, session.timing))
            logger.debug(f"[AI Voice] Enqueued audio (queue size: {session.queue.qsize()})")
        except Exception as exc:
            logger.error(f"[AI Voice] TTS synthesis failed: {exc}")

    async def _say_reply(self, session: VoiceChatSession, text: str, *, clip: bool = False) -> str:
        """Read aloud (a stretch of) her reply; returns what was said.

        `clip` is for a reply built on a web search, whose results are too long to listen
        to: only the spoken part is read. The chat already has, or is about to get, all of
        it (`_post_reply`), so a reply that is cut for speech says where the rest is.
        Any other reply is read whole."""
        if clip:
            spoken, more = _spoken_part(text, config.voice_spoken_max_chars)
        else:
            spoken, more = _speakable(text), False
        if not spoken:
            return ""
        if more:
            logger.info(f"[AI Voice] Reply of {len(text)} chars: reading {len(spoken)}, the rest is in the chat")
        await self._speak(session, f"{spoken} {_MORE_IN_CHAT}" if more else spoken, posted=True)
        return spoken

    async def _await_speech(self, session: VoiceChatSession) -> None:
        """Block until everything queued has actually finished playing.

        Normal replies do not need this — the worker gets to them in its own
        time. An action does: `vc.play()` raises on a client that is already
        playing, so a track must not start while she is still mid-sentence.
        """
        try:
            await asyncio.wait_for(session.queue.join(), timeout=_SPEECH_DRAIN_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("[AI Voice] Timed out waiting for queued speech to finish")

    def _already_asked(self, session: VoiceChatSession, user_id: int, text: str) -> bool:
        """Whether she is already on this: they have a request being answered or waiting.

        With no text (the bare name) any such request counts, because "Yuuka" said
        again is someone who thinks she did not hear, not a new call. With text it
        has to be the same words, so a different request is still taken."""
        mine = [r for r in (session.active, *session.pending) if r is not None and r.user_id == user_id]
        if not text:
            return bool(mine)
        key = wake.normalize(text)
        return any(wake.normalize(r.text) == key for r in mine)

    @staticmethod
    def _sync_speaker_note(session: VoiceChatSession) -> None:
        """Tell the model to name who it is answering, while more than one person is here."""
        if not session.history or session.history[0].get("role") != "system":
            return
        channel = getattr(session.voice_client, "channel", None)
        people = sum(1 for m in getattr(channel, "members", ()) if not m.bot)
        base = session.history[0]["content"].replace(_MULTI_SPEAKER_NOTE, "")
        session.history[0]["content"] = base + (_MULTI_SPEAKER_NOTE if people > 1 else "")

    async def _respond(
        self,
        guild_id: int,
        session: VoiceChatSession,
        speaker: str,
        text: str,
        member: discord.Member | None = None,
        heard_at: float | None = None,
        user_id: int | None = None,
    ) -> None:
        """Answer a request now, or queue it behind the one she is already answering.

        `heard_at` is when the spoken request's segment closed, for the timing log."""
        if user_id is None and member is not None:
            user_id = member.id
        request = _Request(user_id, speaker, text, member, heard_at)

        if session.busy:
            # Dropping it would leave the second person talking to nobody, and
            # they would just say her name again.
            if len(session.pending) >= _MAX_PENDING:
                dropped = session.pending.popleft()
                logger.warning(f"[AI Voice] Queue full in guild {guild_id}, dropped {dropped.speaker}'s request")
            session.pending.append(request)
            logger.info(
                f"[AI Voice] Busy in guild {guild_id}, queued {speaker}'s request "
                f"({len(session.pending)} waiting)"
            )
            return

        session.busy = True
        try:
            while request is not None:
                session.active = request
                try:
                    await self._run_turn(guild_id, session, request)
                except Exception as exc:
                    logger.error(f"[AI Voice] Turn for {request.speaker} failed in guild {guild_id}: {exc}")
                request = session.pending.popleft() if session.pending else None
        finally:
            session.busy = False
            session.active = None

    async def _run_turn(self, guild_id: int, session: VoiceChatSession, request: _Request) -> None:
        """Generate one reply and speak it, or run the command it asks for."""
        speaker, text, member = request.speaker, request.text, request.member
        # Remembered now and not on arrival, so history stays in the order she answered.
        await self._remember(session, speaker, text)
        self._sync_speaker_note(session)

        session.timing = _Timing(speaker, request.heard_at) if request.heard_at is not None else None
        _mark_turn(session, "asking the model")
        full_response = ""
        done: list[dict] = []  # what tools did this turn, for the history
        spoken_upto = 0  # how much of full_response has already been spoken
        said = ""  # the last part of the reply she read aloud, to see whether it asked something
        searched = False  # a web search ran this turn, so its reply is clipped for speech
        acknowledged = False  # an action's own "done" line has been said this turn

        async def before_action(extra: str = "") -> None:
            # Anything she said earlier in the turn went out on a status
            # event. The tool's own line goes next, and the track must not
            # start until all of it has been said.
            if extra:
                await self._speak(session, extra)
            await self._await_speech(session)

        # Without a resolved Member there is nobody to run a command on
        # behalf of, so no action tools are offered.
        ctx = YuukaContext(
            bot=self.bot,
            guild=session.text_channel.guild,
            requester=member,
            channel=session.text_channel,
            voice=True,
            before_action=before_action,
        )

        # A slow turn shows what she is doing, so nobody has to repeat the request.
        progress = TurnProgress(session.text_channel)
        try:
            async with session.text_channel.typing():
                async for msg_type, chunk in run_agent(session.history, ctx):
                    progress.feed(msg_type, chunk)
                    if msg_type == "plan" and any(c["name"] == "web_search" for c in chunk):
                        searched = True
                    if msg_type == "error":
                        dev_msg = chunk.get("dev", chunk) if isinstance(chunk, dict) else chunk
                        user_msg = chunk.get("user", chunk) if isinstance(chunk, dict) else chunk
                        logger.error(f"[AI Voice] LLM error in guild {guild_id}: {dev_msg}")
                        await session.text_channel.send(
                            embed=error_embed("AI Error", str(user_msg))
                        )
                        return
                    elif msg_type == "content":
                        full_response += chunk
                    elif msg_type == "done":
                        done.extend(chunk)
                    elif msg_type == "status":
                        # A tool is about to run. Say anything she has written
                        # so far now. Text right before a call is dropped
                        # upstream, so this is usually empty. The status
                        # text itself is never spoken.
                        pending = full_response[spoken_upto:]
                        if pending.strip():
                            said = await self._say_reply(session, pending, clip=searched) or said
                            spoken_upto = len(full_response)
                    elif msg_type == "action":
                        # Said when the command failed, or when she gave no
                        # acknowledgement of her own. Out loud if the slot
                        # is free, in text if a track has taken it. A failure always
                        # says something new; a success is acknowledged once per
                        # turn, or ten queued songs are ten sentences, each of which
                        # the next command waits for.
                        if not chunk.ok:
                            await self._speak(session, chunk.spoken_fallback)
                        elif not full_response.strip() and not acknowledged:
                            acknowledged = True
                            # Spoken only: the action's embed already says it is done.
                            await self._speak(session, chunk.spoken_fallback, typed=False)
        except Exception as exc:
            logger.error(f"[AI Voice] LLM error in guild {guild_id}: {exc}")
            await session.text_channel.send(embed=error_embed("AI Error", str(exc)))
            return
        finally:
            await progress.finish()

        _mark_turn(session, "model finished")

        # An action-only turn has no text but still happened: without it in the
        # history the request looks unanswered and gets done again.
        session.history.extend(done)
        if not full_response:
            if not done:
                logger.warning(f"[AI Voice] Empty response in guild {guild_id}")
            return

        logger.debug(f"[AI Voice] LLM response ({len(full_response)} chars): {full_response}")
        session.history.append({"role": "assistant", "content": full_response})

        # The whole reply goes in the chat; only its spoken part is read aloud.
        await self._post_reply(session, full_response)

        tail = full_response[spoken_upto:]
        if tail.strip():
            if spoken_upto:
                # _speak posts text instead of speaking while the voice
                # client is busy, and that includes her own earlier sentence.
                await self._await_speech(session)
            said = await self._say_reply(session, tail, clip=searched) or said

        # The window opens when she stops talking, not when she starts.
        if member is not None and _asks_user(said or full_response):
            await self._await_speech(session)
            self._start_listening(
                session,
                member.id,
                speaker,
                window=config.stt_answer_window_s,
                chimed=chime.play(session.voice_client, "wake"),
            )

    # ──────────────────────────────────────────────────────────────────────
    # Public API — called by AIChatCog
    # ──────────────────────────────────────────────────────────────────────

    def expect_answer(self, guild_id: int, view: ConfirmActionView) -> None:
        """Let `view`'s requester confirm or cancel it by voice, no wake word needed.

        Called by `utils.ai.tools.actions` right after it posts the buttons."""
        session = self.active_sessions.get(guild_id)
        if session is not None:
            session.pending_confirms[view.requester.id] = view
            # She has just said "say yes or press the button": the chime says she is
            # listening for it. Her line is already over (`before_action` waits).
            chime.play(session.voice_client, "wake")

    async def announce(self, guild_id: int, text: str) -> None:
        """Say `text` in this guild's voice session, if she is free to.

        For results that arrive after a turn has ended: a confirmed action, a
        fired reminder. If music or her own speech holds the voice client the
        answer is already visible as an embed, so nothing is posted here.
        """
        session = self.active_sessions.get(guild_id)
        if session is None:
            return
        vc = session.voice_client
        if not vc or vc.is_paused() or (vc.is_playing() and music_mixer(vc) is None):
            return
        if not session.busy:
            session.timing = None  # not part of the last spoken turn
        await self._speak(session, text)

    async def _open_session(
        self,
        *,
        guild_id: int,
        voice_client: discord.VoiceClient,
        text_channel,
        history: list[dict] | None = None,
    ) -> tuple[VoiceChatSession, bool]:
        """Register a live session and start listening. Returns (session, stt_ready).

        Shared by `/ai voice` and the automatic resume after a song, so the two
        cannot drift into subtly different sessions.
        """
        # Loading the model can mean a multi-gigabyte download on first run.
        # Voice chat still works without it (typed input), so a failure here
        # degrades rather than aborts.
        stt_ready = await ensure_loaded()

        if history is None:
            history = [{
                "role": "system",
                "content": config.openrouter_system_prompt + _VOICE_PROMPT_SUFFIX,
            }]

        session = VoiceChatSession(
            text_channel=text_channel,
            voice_client=voice_client,
            history=history,
        )
        self.active_sessions[guild_id] = session

        session.worker = asyncio.create_task(
            self._audio_worker(guild_id), name=f"voice_worker_{guild_id}"
        )

        if stt_ready:
            voice_hub.subscribe(voice_client, _HUB_KEY, on_segment=self._on_segment)

        # Open the audio stream now: the first sound on a fresh connection is
        # otherwise clipped on the listeners' side, and the first chime would be it.
        chime.warm_up(voice_client)

        return session, stt_ready

    async def start_session(self, ctx: discord.ApplicationContext) -> None:
        """Join caller's voice channel and activate a voice-chat session."""
        await ctx.defer()

        guild_id = ctx.guild.id

        # Guard: must be in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError(
                "ยังไม่ได้เข้าห้องเสียงค่ะ",
                "เข้าห้องเสียงก่อนนะคะ แล้วค่อยเรียกหนูมาน้า (・`ω´・)",
            )

        # Guard: already active in this guild
        if guild_id in self.active_sessions:
            raise UserWarning(
                "หนูกำลังทำงานอยู่ค่ะ",
                "หนูมีเซสชั่น AI Voice อยู่แล้วนะคะ ใช้ `/ai stop` ก่อนถ้าอยากเริ่มใหม่ค่า",
            )

        # Guard: text chat already active in this guild
        chat_cog = self.bot.cogs.get("AI Chat")
        if chat_cog and hasattr(chat_cog, "active_channels"):
            for ch_id in list(chat_cog.active_channels.keys()):
                ch = self.bot.get_channel(ch_id)
                if ch and getattr(ch, "guild", None) and ch.guild.id == guild_id:
                    raise UserWarning(
                        "หนูกำลัง Chat อยู่ค่ะ",
                        "หนูมีเซสชั่น `/ai chat` อยู่แล้วนะคะ ใช้ `/ai stop` ก่อนน้า",
                    )

        voice_channel = ctx.author.voice.channel
        voice_client: discord.VoiceClient | None = ctx.guild.voice_client

        if voice_client is None:
            try:
                voice_client = await voice_channel.connect()
            except discord.ClientException as exc:
                logger.error(f"[AI Voice] Failed to connect to voice channel: {exc}")
                raise UserError(
                    "เข้าห้องไม่ได้ค่ะ",
                    f"หนูเข้าห้อง **{voice_channel.name}** ไม่ได้ค่ะ: `{exc}`",
                )
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)

        _, stt_ready = await self._open_session(
            guild_id=guild_id, voice_client=voice_client, text_channel=ctx.channel
        )

        logger.info(
            f"[AI Voice] Session started in guild {guild_id}, "
            f"voice='{voice_channel.name}', text='{ctx.channel.name}', "
            f"stt={model_description() if stt_ready else 'disabled'}, "
            f"wake={config.stt_wake_words}"
        )

        wake_list = " / ".join(f"**{w}**" for w in config.stt_wake_words[:4])
        if stt_ready:
            how = (
                f"พูดชื่อหนู ({wake_list}) ตรงไหนของประโยคก็ได้ค่ะ "
                "เช่น *«ยูกะ ตอนนี้กี่โมงแล้ว»* หรือ *«แล้วอีกแบบคืออะไรล่ะยูกะ»*\n"
                "ถ้าเรียกแค่ชื่อหนู หนูจะ *ติ๊ง* ให้ได้ยินแล้วฟังต่ออีกประโยคเลยค่ะ พูดคำสั่งตามได้เลยน้า "
                "แต่หลังตอบแล้วต้องเรียกชื่อหนูใหม่นะคะ\n"
                f"หรือจะ `@mention` ในช่อง **{ctx.channel.name}** ก็ได้ค่ะ!\n\n"
                "🎵 สั่งเปิดเพลงด้วยเสียงได้ด้วยนะคะ เช่น *«ยูกะ เปิดเพลง YOASOBI ให้หน่อย»* "
                "หนูจะเรียก `/music` ให้เอง แล้วบอกในช่องนี้ว่าใช้คำสั่งอะไรไปค่ะ\n"
                "(ระหว่างมีเพลงเล่นอยู่หนูจะเบาเสียงเพลงลงแล้วพูดทับให้ค่ะ "
                "แต่ถ้าหยุดเพลงชั่วคราวไว้ หนูจะพิมพ์ตอบในช่องนี้แทนน้า)"
            )
        else:
            how = (
                "⚠️ ระบบฟังเสียงยังไม่พร้อมค่ะ (โหลดโมเดลไม่สำเร็จ)\n"
                f"ตอนนี้คุยกับหนูได้โดย `@mention` ในช่อง **{ctx.channel.name}** นะคะ"
            )

        voice_note = (
            f"เสียงพูดจะถูกแปลงเป็นข้อความผ่าน `{model_description()}` "
            "และคำตอบจะถูกอ่านออกเสียงผ่าน Microsoft Edge TTS ค่ะ"
            if stt_ready
            else "เสียงพูดจะยังไม่ถูกส่งไปที่ไหนเพราะระบบฟังเสียงปิดอยู่ค่ะ"
        )
        if memory_note := disclosure_note(self.bot, ctx.guild):
            voice_note += f"\n{memory_note}"

        await ctx.respond(embed=build_embed(
            "🎙️ AI Voice Chat เริ่มแล้วค่ะ",
            f"หนูเข้ามาอยู่ในห้อง **{voice_channel.name}** แล้วนะคะ 🎧\n\n"
            f"{how}\n\nใช้ `/ai stop` เมื่อต้องการหยุดน้า",
            COLOR_SUCCESS,
            fields=[ai_disclosure_field(config.openrouter_model, extra_note=voice_note)],
        ))

    async def stop_session(self, guild_id: int) -> bool:
        """
        Stop the voice session for *guild_id*.
        Returns True if a session was active and stopped, False otherwise.
        """
        if guild_id not in self.active_sessions:
            return False

        session = self.active_sessions.pop(guild_id)
        voice_hub.unsubscribe(guild_id, _HUB_KEY)

        for task in session.listening.values():
            task.cancel()

        # Cancel the audio worker
        if session.worker and not session.worker.done():
            session.worker.cancel()
            try:
                await session.worker
            except asyncio.CancelledError:
                pass

        # Stop her own speech, then leave only if nobody else is using the
        # connection. This used to disconnect unconditionally, which killed
        # music playback and any live capture that happened to share the client.
        # Only her own speech. is_playing() is equally true when the music
        # player owns the client, and stopping that would kill a track somebody
        # queued — speaking_until is infinite exactly while a TTS clip is mid-air.
        vc = session.voice_client
        if vc and vc.is_playing() and session.speaking_until == float("inf"):
            vc.stop()

        guild = self.bot.get_guild(guild_id)
        if guild:
            await voice_hub.release_voice(guild)

        logger.info(f"[AI Voice] Session stopped in guild {guild_id}")
        return True

    # ──────────────────────────────────────────────────────────────────────
    # on_message — respond when @mentioned
    # ──────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        session = self.active_sessions.get(message.guild.id)
        if session is None:
            return

        # Only respond to messages in the linked text channel
        if message.channel.id != session.text_channel.id:
            return

        content = message.clean_content.strip()
        if not content:
            return

        # Only generate a spoken response when @mentioned; everything else is
        # kept for context only.
        if self.bot.user not in message.mentions:
            await self._remember(session, message.author.display_name, content)
            return

        logger.info(f"[AI Voice] Triggered by {message.author} in guild {message.guild.id}")
        await self._respond(
            message.guild.id, session, message.author.display_name, content, message.author
        )

    # ──────────────────────────────────────────────────────────────────────
    # on_voice_state_update — clean up if bot is kicked from voice
    # ──────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member != self.bot.user:
            return

        # Bot left a voice channel
        if before.channel is not None and after.channel is None:
            guild_id = member.guild.id
            if guild_id in self.active_sessions:
                logger.info(f"[AI Voice] Bot disconnected from voice in guild {guild_id}. Cleaning up.")
                session = self.active_sessions.pop(guild_id)
                voice_hub.unsubscribe(guild_id, _HUB_KEY)
                for task in session.listening.values():
                    task.cancel()
                if session.worker and not session.worker.done():
                    session.worker.cancel()
                    try:
                        await session.worker
                    except asyncio.CancelledError:
                        pass
                await session.text_channel.send(embed=info_embed(
                    "🔇 ถูกตัดการเชื่อมต่อค่ะ",
                    "หนูถูกเตะออกจากห้องเสียงค่ะ เซสชั่น AI voice ถูกหยุดโดยอัตโนมัติแล้วน้า",
                ))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(AIVoiceChatCog(bot))
