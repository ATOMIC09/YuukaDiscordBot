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
   Yuuka", so every segment goes through it, every time.
3. `utils.stt` transcribes the segment with faster-whisper, which handles the
   Thai/English code-switching this server actually speaks.
4. `utils.wake` decides whether Yuuka was addressed. **This gate is the whole
   point**: without it she replies to every sentence anyone says in the room.
   There is no follow-up window — every utterance needs the wake word, on
   purpose, so it is never ambiguous whether she is listening right now. The
   one exception is a bare "just her name" segment: step 1's silence-based
   cut means a natural pause before the actual sentence lands as its own
   segment, so that one case gets a short bridge (`_bridge_timeout`) that
   waits briefly for the continuation. If nothing follows, it's dropped —
   a bare name alone is far more often a stray acoustic hit than someone
   deliberately calling her just to say hi.
5. The accepted text goes through the same LLM → TTS → playback path as a
   typed message.
6. If the model answers with an `[ACTION: ...]` tag instead of plain prose, it
   is asking to run one of the bot's own commands (`utils.ai_actions`). She
   speaks whatever she said before the tag, waits for it to actually finish
   (a track cannot start while she is mid-sentence — one VoiceClient), then
   runs the command. The session is never torn down: while music plays she
   keeps listening and answers in the text channel instead of out loud.

Both a typed message and a spoken one land in `_respond()`, so the two entry
points cannot drift apart.

Listeners:
  - on_message            — generates LLM reply + TTS when @mentioned
  - on_voice_state_update — auto-cleanup if bot is kicked from voice
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

import discord
from discord.ext import commands

from bot.config import config
from bot.logger import logger
from utils import ai_actions, wake
from utils.embeds import (
    ai_disclosure_field,
    build_embed,
    COLOR_SUCCESS,
    error_embed,
    info_embed,
)
from utils.errors import UserError, UserWarning
from utils.llm import generate_chat_stream_response
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
    "1. Keep responses VERY SHORT and concise (1-5 sentences maximum). "
    "2. DO NOT use emojis of any kind. "
    "3. DO NOT write out physical actions or expressions in parentheses/asterisks (e.g., (หน้าแดง), *ถอนหายใจ*). Vocal sounds like 'ฮ่าๆ' or 'อ่า' are OK. "
    "4. DO NOT use markdown, code blocks, asterisks, or special formatting. "
    "5. Some user turns arrive from speech recognition and may contain "
    "misheard words, especially names and mixed Thai/English. Infer what was "
    "meant from context; ask for a repeat only if it is genuinely unclear."
)

# Echo guard: a speaker without headphones has Yuuka's own voice coming back
# through their mic. Anything captured while she was talking (plus a short
# tail) is discarded rather than transcribed.
_ECHO_TAIL_S = 0.4

# Upper bound on waiting for queued speech to finish playing. Only reached when
# the audio worker has died, which must not wedge the turn forever.
_SPEECH_DRAIN_TIMEOUT_S = 60.0


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

    # One in-flight generation per guild — a second speaker interrupting mid
    # thought gets their words remembered, not answered twice over.
    busy: bool = False

    # A bare "just her name" segment starts a short-lived task here while it
    # waits for a possible continuation (see _on_segment). Not a standing
    # "awake" window — consumed or expired within one bridge.
    pending_bridge: dict[int, asyncio.Task] = field(default_factory=dict)

    # Whether the room has already been told she is typing instead of speaking.
    # Explaining it once per silent stretch is helpful; repeating it above every
    # reply is noise. Cleared again the moment she manages to speak out loud.
    text_fallback_announced: bool = False


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
                mp3_path, spoken_text = await session.queue.get()

                vc = session.voice_client
                if not vc or not vc.is_connected():
                    logger.warning(
                        f"[AI Voice] Voice client gone for guild {guild_id}, posting the line instead"
                    )
                    self._discard(mp3_path)
                    await self._post_unspoken(session, spoken_text)
                    session.queue.task_done()
                    continue

                # The music player shares this VoiceClient and play() raises on
                # one that is already busy. Her line loses to somebody's track —
                # but losing the audio slot is not a reason to lose the answer,
                # so it goes to the text channel instead of nowhere.
                if vc.is_playing() or vc.is_paused():
                    logger.info(
                        f"[AI Voice] Voice client busy in guild {guild_id}, posting the line instead"
                    )
                    self._discard(mp3_path)
                    await self._post_unspoken(session, spoken_text)
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

        # A bare "just her name" segment leaves a short-lived bridge task
        # waiting for exactly this: the next segment from that same speaker.
        # If one arrives in time, it's the rest of the sentence the pause
        # split off — skip the acoustic/wake gates entirely and treat the
        # whole transcript as the prompt.
        bridge = session.pending_bridge.pop(segment.user_id, None)
        if bridge is not None:
            bridge.cancel()
            result = await transcribe_pcm(segment.pcm, display)
            if not result.text:
                return
            logger.info(f"[AI Voice] Bridged pause-continuation from {display}: {result.text}")
            await self._announce_and_respond(
                segment.guild_id, session, display, result.text, member
            )
            return

        # Cheap pre-filter: is this worth transcribing at all? Runs on every
        # segment — there is no standing "awake" state that skips it.
        heard, acoustic_score = await acoustic_wake.detect(segment.pcm)
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

        result = await transcribe_pcm(segment.pcm, display)
        if not result.text:
            return

        text_threshold = config.stt_wake_threshold
        if acoustic_score >= config.stt_wake_acoustic_confident_score:
            text_threshold = min(text_threshold, config.stt_wake_relaxed_threshold)

        match = wake.detect(
            result.text,
            config.stt_wake_words,
            threshold=text_threshold,
            head_chars=config.stt_wake_head_chars,
        )
        if not match:
            # Logged at debug with the score so STT_WAKE_THRESHOLD can be
            # tuned against what these speakers' mics actually produce.
            logger.debug(
                f"[AI Voice] No wake word from {display} "
                f"(best {match.score:.0f} vs {match.word or '—'}, threshold {text_threshold}): {result.text}"
            )
            return

        logger.info(
            f"[AI Voice] Wake word '{match.word}' matched at {match.score:.0f} "
            f"(threshold {text_threshold}) from {display}"
        )

        if match.remainder:
            await self._announce_and_respond(
                segment.guild_id, session, display, match.remainder, member,
                heard=result.text,
            )
            return

        # Just her name and nothing else — wait briefly for a continuation
        # (the natural pause before the actual sentence, which the segmenter
        # cuts into its own segment). This bridges exactly one gap, not a
        # standing "awake" window: consumed above the moment a continuation
        # lands. If nothing follows, it's dropped rather than acknowledged —
        # a bare name with no question is far more often a stray acoustic
        # hit than someone deliberately calling her just to say hi.
        session.pending_bridge[segment.user_id] = asyncio.create_task(
            self._bridge_timeout(session, segment.user_id, display),
            name=f"wake_bridge_{segment.guild_id}_{segment.user_id}",
        )

    async def _bridge_timeout(
        self, session: VoiceChatSession, user_id: int, display: str
    ) -> None:
        """Drops the bare-name segment if no continuation arrives in time."""
        try:
            await asyncio.sleep(config.stt_wake_bridge_window_s)
        except asyncio.CancelledError:
            return
        session.pending_bridge.pop(user_id, None)
        logger.debug(f"[AI Voice] No continuation from {display} after bare wake word, dropping")

    async def _announce_and_respond(
        self,
        guild_id: int,
        session: VoiceChatSession,
        display: str,
        prompt: str,
        member: discord.Member | None = None,
        heard: str | None = None,
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

        await self._respond(guild_id, session, display, prompt, member)

    # ──────────────────────────────────────────────────────────────────────
    # Shared reply path — used by both spoken and typed input
    # ──────────────────────────────────────────────────────────────────────

    async def _remember(self, session: VoiceChatSession, speaker: str, text: str) -> None:
        """Append a user turn to history, trimming to the configured window."""
        timestamp = discord.utils.utcnow().strftime("%Y-%m-%d %H:%M UTC")
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

    async def _post_unspoken(self, session: VoiceChatSession, text: str) -> None:
        """Deliver in text what she could not say out loud.

        Reached whenever the audio slot is unavailable — most often because a
        track is playing. Silently dropping the line makes her look broken; the
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
            body = "-# 🔇 มีเพลงเล่นอยู่ หนูขอพิมพ์ตอบแทนพูดนะคะ\n" + text
            session.text_fallback_announced = True

        try:
            await session.text_channel.send(body)
        except discord.HTTPException as exc:
            logger.warning(f"[AI Voice] Could not post an unspoken line: {exc}")

    async def _speak(self, session: VoiceChatSession, text: str) -> None:
        """Say `text` out loud, or post it if the voice slot is taken.

        The check here is an optimisation, not the safety net: synthesizing an
        MP3 the worker is only going to discard costs an Edge-TTS round trip and
        a temp file for nothing. The worker still re-checks, because music can
        start in the gap between this line and playback.
        """
        if not text.strip():
            return

        vc = session.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            logger.info("[AI Voice] Voice slot taken, answering in text without synthesizing")
            await self._post_unspoken(session, text)
            return

        try:
            mp3_path = await synthesize_speech(text)
            # The text rides along so the worker can still deliver the answer if
            # it turns out it cannot play the audio.
            await session.queue.put((mp3_path, text))
            logger.debug(f"[AI Voice] Enqueued audio (queue size: {session.queue.qsize()})")
        except Exception as exc:
            logger.error(f"[AI Voice] TTS synthesis failed: {exc}")

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

    async def _respond(
        self,
        guild_id: int,
        session: VoiceChatSession,
        speaker: str,
        text: str,
        member: discord.Member | None = None,
    ) -> None:
        """Generate a reply and speak it, or run the command it asks for."""
        await self._remember(session, speaker, text)

        if session.busy:
            # Their words are in history, so she has the context next turn —
            # we just don't start a second generation on top of the first.
            logger.debug(f"[AI Voice] Busy in guild {guild_id}, not replying to {speaker}")
            return

        # Without a resolved Member there is nobody to run a command on behalf
        # of, so the model is not told actions exist and cannot ask for one.
        catalog = ai_actions.catalog_for(self.bot) if member is not None else ""

        session.busy = True
        action: dict[str, str] | None = None
        full_response = ""
        try:
            try:
                async with session.text_channel.typing():
                    async for msg_type, chunk in generate_chat_stream_response(
                        session.history, action_catalog=catalog
                    ):
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
                        elif msg_type == "action":
                            action = chunk
                        # "status" chunks (web search) are silently ignored in voice mode
            except Exception as exc:
                logger.error(f"[AI Voice] LLM error in guild {guild_id}: {exc}")
                await session.text_channel.send(embed=error_embed("AI Error", str(exc)))
                return

            if not full_response and action is None:
                logger.warning(f"[AI Voice] Empty response in guild {guild_id}")
                return

            if full_response:
                logger.debug(f"[AI Voice] LLM response ({len(full_response)} chars): {full_response}")
                session.history.append({"role": "assistant", "content": full_response})

            if action is None:
                await self._speak(session, full_response)
            else:
                # Deliberately still inside the busy window: an action runs for
                # seconds and ends by tearing the session down, and a second
                # generation starting on top of that would race the teardown.
                await self._run_action(guild_id, session, member, action, full_response)
        finally:
            session.busy = False

    async def _run_action(
        self,
        guild_id: int,
        session: VoiceChatSession,
        member: discord.Member | None,
        action: dict[str, str],
        ack: str,
    ) -> None:
        """Speak the acknowledgement, then run the command it asked for."""
        if member is None:
            logger.warning(
                f"[AI Voice] Action '{action['name']}' in guild {guild_id} "
                "has no resolved requester, ignoring"
            )
            return

        # Said before the command runs, and awaited: the room hears something
        # during the yt-dlp lookup, and — since a track and her voice share one
        # VoiceClient — playback cannot start while she is still mid-sentence.
        if ack:
            await self._speak(session, ack)
            await self._await_speech(session)

        result = await ai_actions.run_action(
            self.bot,
            name=action["name"],
            arg=action["arg"],
            guild=member.guild,
            member=member,
            fallback_channel=session.text_channel,
        )

        if result is None:
            # A name the model invented. Nothing ran, nothing was posted.
            return

        # Either way she reports back — out loud if the slot is free, in text if
        # a track has taken it. The session keeps running regardless.
        if not result.ok or not ack:
            await self._speak(session, result.spoken_fallback)

    # ──────────────────────────────────────────────────────────────────────
    # Public API — called by AIChatCog
    # ──────────────────────────────────────────────────────────────────────

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
                "ต้องเรียกชื่อหนูทุกครั้งที่อยากคุยนะคะ หนูไม่ได้ฟังต่อเนื่องหลังตอบแล้วค่ะ\n"
                f"หรือจะ `@mention` ในช่อง **{ctx.channel.name}** ก็ได้ค่ะ!\n\n"
                "🎵 สั่งเปิดเพลงด้วยเสียงได้ด้วยนะคะ เช่น *«ยูกะ เปิดเพลง YOASOBI ให้หน่อย»* "
                "หนูจะเรียก `/music` ให้เอง แล้วบอกในช่องนี้ว่าใช้คำสั่งอะไรไปค่ะ\n"
                "(ระหว่างมีเพลงเล่นอยู่หนูยังฟังอยู่นะคะ แต่พูดออกเสียงไม่ได้ "
                "หนูจะพิมพ์ตอบในช่องนี้แทนค่ะ)"
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

        for task in session.pending_bridge.values():
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
                for task in session.pending_bridge.values():
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
