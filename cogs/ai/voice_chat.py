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
2. `utils.stt` transcribes the segment with faster-whisper, which handles the
   Thai/English code-switching this server actually speaks.
3. `utils.wake` decides whether Yuuka was addressed. **This gate is the whole
   point**: without it she replies to every sentence anyone says in the room.
   A hit also opens a follow-up window for that speaker, so a back-and-forth
   does not require repeating her name every single turn.
4. The accepted text goes through the same LLM → TTS → playback path as a
   typed message.

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
from utils import wake
from utils.embeds import error_embed, info_embed, success_embed
from utils.errors import UserError, UserWarning
from utils.llm import generate_chat_stream_response
from utils.stt import ensure_loaded, model_description, transcribe_pcm
from utils.tts import synthesize_speech
from utils.voice_hub import SpeechSegment, voice_hub

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


@dataclass
class VoiceChatSession:
    """All state for a single active voice-chat session (one per guild)."""

    text_channel: discord.TextChannel
    voice_client: discord.VoiceClient
    history: list[dict] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None

    # Speakers who said the wake word recently, and may keep talking without
    # repeating it: user_id → perf_counter deadline.
    awake_until: dict[int, float] = field(default_factory=dict)

    # The interval during which Yuuka herself was audible, in perf_counter
    # terms. Segments overlapping it are echo and get dropped.
    speaking_from: float = 0.0
    speaking_until: float = 0.0

    # One in-flight generation per guild — a second speaker interrupting mid
    # thought gets their words remembered, not answered twice over.
    busy: bool = False


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
                mp3_path: str = await session.queue.get()

                vc = session.voice_client
                if not vc or not vc.is_connected():
                    logger.warning(f"[AI Voice] Voice client gone for guild {guild_id}, dropping audio.")
                    try:
                        os.unlink(mp3_path)
                    except OSError:
                        pass
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

        user = self.bot.get_user(segment.user_id)
        display = user.display_name if user else f"Unknown ({segment.user_id})"

        result = await transcribe_pcm(segment.pcm, display)
        if not result.text:
            return

        now = time.perf_counter()
        in_followup = session.awake_until.get(segment.user_id, 0.0) > now

        if in_followup:
            prompt = result.text
            logger.debug(f"[AI Voice] Follow-up window open for {display}")
        else:
            match = wake.detect(
                result.text,
                config.stt_wake_words,
                threshold=config.stt_wake_threshold,
                head_chars=config.stt_wake_head_chars,
            )
            if not match:
                # Logged at debug with the score so STT_WAKE_THRESHOLD can be
                # tuned against what these speakers' mics actually produce.
                logger.debug(
                    f"[AI Voice] No wake word from {display} "
                    f"(best {match.score:.0f} vs {match.word or '—'}): {result.text}"
                )
                return

            logger.info(
                f"[AI Voice] Wake word '{match.word}' matched at {match.score:.0f} from {display}"
            )
            prompt = match.remainder

        if not prompt:
            # Just her name and nothing else — answer the summons and open the
            # window so the actual request lands in the next utterance.
            session.awake_until[segment.user_id] = now + config.stt_followup_window_s
            prompt = "(เรียกชื่อเฉย ๆ ยังไม่ได้ถามอะไร)"

        # Show what she heard — invaluable when a wake word or a Thai/English
        # phrase gets misheard and the reply looks like a non-sequitur. The 💬
        # marks it as voice *chat*: /transcribe posts live captions in the same
        # format under 🎙️, and two identical-looking streams are impossible to
        # tell apart when one session ends and the other begins.
        try:
            await session.text_channel.send(f"💬 **{display}**: {prompt}")
        except discord.HTTPException:
            pass

        await self._respond(
            segment.guild_id, session, display, prompt, speaker_id=segment.user_id
        )

    # ──────────────────────────────────────────────────────────────────────
    # Shared reply path — used by both spoken and typed input
    # ──────────────────────────────────────────────────────────────────────

    async def _remember(self, session: VoiceChatSession, speaker: str, text: str) -> None:
        """Append a user turn to history, trimming to the configured window."""
        timestamp = discord.utils.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        session.history.append({"role": "user", "content": f"[{timestamp}] {speaker}: {text}"})
        while len(session.history) > config.max_history_length:
            session.history.pop(1)  # preserve system prompt at index 0

    async def _respond(
        self,
        guild_id: int,
        session: VoiceChatSession,
        speaker: str,
        text: str,
        *,
        speaker_id: int | None = None,
    ) -> None:
        """Generate a reply, speak it, and refresh the speaker's follow-up window."""
        await self._remember(session, speaker, text)

        if session.busy:
            # Their words are in history, so she has the context next turn —
            # we just don't start a second generation on top of the first.
            logger.debug(f"[AI Voice] Busy in guild {guild_id}, not replying to {speaker}")
            return

        session.busy = True
        try:
            full_response = ""
            try:
                async with session.text_channel.typing():
                    async for msg_type, chunk in generate_chat_stream_response(session.history):
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
                        # "status" chunks (web search) are silently ignored in voice mode
            except Exception as exc:
                logger.error(f"[AI Voice] LLM error in guild {guild_id}: {exc}")
                await session.text_channel.send(embed=error_embed("AI Error", str(exc)))
                return

            if not full_response:
                logger.warning(f"[AI Voice] Empty response in guild {guild_id}")
                return

            logger.debug(f"[AI Voice] LLM response ({len(full_response)} chars): {full_response}")
            session.history.append({"role": "assistant", "content": full_response})

            try:
                mp3_path = await synthesize_speech(full_response)
                await session.queue.put(mp3_path)
                logger.debug(f"[AI Voice] Enqueued audio (queue size: {session.queue.qsize()})")
            except Exception as exc:
                logger.error(f"[AI Voice] TTS synthesis failed in guild {guild_id}: {exc}")
        finally:
            session.busy = False
            if speaker_id is not None:
                # Measured from now, not from when they spoke, so the window
                # covers the reply itself rather than being eaten by it.
                session.awake_until[speaker_id] = (
                    time.perf_counter() + config.stt_followup_window_s
                )

    # ──────────────────────────────────────────────────────────────────────
    # Public API — called by AIChatCog
    # ──────────────────────────────────────────────────────────────────────

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

        # Loading the model can mean a multi-gigabyte download on first run.
        # Voice chat still works without it (typed input), so a failure here
        # degrades rather than aborts.
        stt_ready = await ensure_loaded()

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

        # Build history with voice-mode system prompt
        voice_system_prompt = config.openrouter_system_prompt + _VOICE_PROMPT_SUFFIX
        history: list[dict] = [{"role": "system", "content": voice_system_prompt}]

        session = VoiceChatSession(
            text_channel=ctx.channel,
            voice_client=voice_client,
            history=history,
        )
        self.active_sessions[guild_id] = session

        session.worker = asyncio.create_task(
            self._audio_worker(guild_id), name=f"voice_worker_{guild_id}"
        )

        if stt_ready:
            voice_hub.subscribe(voice_client, _HUB_KEY, on_segment=self._on_segment)

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
                f"หลังหนูตอบแล้ว คุยต่อได้เลยภายใน **{config.stt_followup_window_s} วินาที** "
                "ไม่ต้องเรียกชื่อซ้ำน้า\n"
                f"หรือจะ `@mention` ในช่อง **{ctx.channel.name}** ก็ได้ค่ะ!"
            )
        else:
            how = (
                "⚠️ ระบบฟังเสียงยังไม่พร้อมค่ะ (โหลดโมเดลไม่สำเร็จ)\n"
                f"ตอนนี้คุยกับหนูได้โดย `@mention` ในช่อง **{ctx.channel.name}** นะคะ"
            )

        await ctx.respond(embed=success_embed(
            "🎙️ AI Voice Chat เริ่มแล้วค่ะ",
            f"หนูเข้ามาอยู่ในห้อง **{voice_channel.name}** แล้วนะคะ 🎧\n\n"
            f"{how}\n\nใช้ `/ai stop` เมื่อต้องการหยุดน้า",
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
        vc = session.voice_client
        if vc and vc.is_playing():
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
            message.guild.id, session, message.author.display_name, content
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
