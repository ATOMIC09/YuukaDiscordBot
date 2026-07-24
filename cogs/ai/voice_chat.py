"""
cogs/ai/voice_chat.py
AI voice chat logic — session state, audio queue, and event listeners.

This cog has NO slash commands. All /ai commands are owned by AIChatCog (chat.py)
to avoid duplicate SlashCommandGroup registration. This cog exposes:
  - start_session(ctx)     called by AIChatCog.ai_voice
  - stop_session(guild_id) called by AIChatCog.ai_stop

Listeners:
  - on_message            — generates LLM reply + TTS when @mentioned
  - on_voice_state_update — auto-cleanup if bot is kicked from voice
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

import discord
from discord.ext import commands

from bot.config import config
from bot.logger import logger
from utils.embeds import error_embed, info_embed, success_embed
from utils.errors import UserError, UserWarning
from utils.llm import generate_chat_stream_response
from utils.tts import synthesize_speech

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
    "4. DO NOT use markdown, code blocks, asterisks, or special formatting."
)


@dataclass
class VoiceChatSession:
    """All state for a single active voice-chat session (one per guild)."""
    text_channel: discord.TextChannel
    voice_client: discord.VoiceClient
    history: list[dict] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None


class AIVoiceChatCog(commands.Cog, name="AI Voice Chat"):
    """
    AI voice chat logic.

    No slash commands here — all /ai commands live in AIChatCog (chat.py).
    This cog exposes start_session() and stop_session() as public methods
    that AIChatCog calls via self.bot.cogs.get("AI Voice Chat").
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

                source = discord.FFmpegPCMAudio(mp3_path)
                vc.play(source, after=_after)

                await play_done.wait()

                try:
                    os.unlink(mp3_path)
                    logger.debug(f"[AI Voice] Deleted temp file {mp3_path}")
                except OSError as e:
                    logger.warning(f"[AI Voice] Could not delete temp file {mp3_path}: {e}")

                session.queue.task_done()

        except asyncio.CancelledError:
            logger.debug(f"[AI Voice] Audio worker cancelled for guild {guild_id}")

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

        logger.info(
            f"[AI Voice] Session started in guild {guild_id}, "
            f"voice='{voice_channel.name}', text='{ctx.channel.name}'"
        )
        await ctx.respond(embed=success_embed(
            "🎙️ AI Voice Chat เริ่มแล้วค่ะ",
            f"หนูเข้ามาอยู่ในห้อง **{voice_channel.name}** แล้วนะคะ 🎧\n\n"
            f"ถ้าอยากคุยกับหนู ให้ `@mention` ในช่อง **{ctx.channel.name}** ได้เลยค่า!\n"
            "หนูจะพูดตอบในห้องเสียงนะคะ ใช้ `/ai stop` เมื่อต้องการหยุดน้า",
        ))

    async def stop_session(self, guild_id: int) -> bool:
        """
        Stop the voice session for *guild_id*.
        Returns True if a session was active and stopped, False otherwise.
        """
        if guild_id not in self.active_sessions:
            return False

        session = self.active_sessions.pop(guild_id)

        # Cancel the audio worker
        if session.worker and not session.worker.done():
            session.worker.cancel()
            try:
                await session.worker
            except asyncio.CancelledError:
                pass

        # Stop playback and disconnect
        vc = session.voice_client
        if vc:
            if vc.is_playing():
                vc.stop()
            if vc.is_connected():
                await vc.disconnect()

        logger.info(f"[AI Voice] Session stopped in guild {guild_id}")
        return True

    # ──────────────────────────────────────────────────────────────────────
    # on_message — generate + speak response when @mentioned
    # ──────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        session = self.active_sessions.get(guild_id)
        if session is None:
            return

        # Only respond to messages in the linked text channel
        if message.channel.id != session.text_channel.id:
            return

        content = message.clean_content.strip()
        if not content:
            return

        # Always add to history for context, even without a mention
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
        user_content = f"[{timestamp}] {message.author.display_name}: {content}"
        session.history.append({"role": "user", "content": user_content})

        while len(session.history) > config.max_history_length:
            session.history.pop(1)  # preserve system prompt at index 0

        # Only generate a spoken response when @mentioned
        if self.bot.user not in message.mentions:
            return

        logger.info(f"[AI Voice] Triggered by {message.author} in guild {guild_id}")

        # Collect the full LLM response before TTS (can't synthesize partial text)
        full_response = ""
        try:
            async with message.channel.typing():
                async for msg_type, chunk in generate_chat_stream_response(session.history):
                    if msg_type == "error":
                        logger.error(f"[AI Voice] LLM error in guild {guild_id}: {chunk}")
                        await message.channel.send(embed=error_embed("AI Error", chunk))
                        return
                    elif msg_type == "content":
                        full_response += chunk
                    # "status" chunks (web search) are silently ignored in voice mode
        except Exception as exc:
            logger.error(f"[AI Voice] LLM error in guild {guild_id}: {exc}")
            await message.channel.send(embed=error_embed("AI Error", str(exc)))
            return

        if not full_response:
            logger.warning(f"[AI Voice] Empty response in guild {guild_id}")
            return

        logger.debug(f"[AI Voice] LLM response ({len(full_response)} chars): {full_response}")

        # Append assistant turn to history
        session.history.append({"role": "assistant", "content": full_response})

        # Synthesize speech and enqueue for playback
        try:
            mp3_path = await synthesize_speech(full_response)
            await session.queue.put(mp3_path)
            logger.debug(f"[AI Voice] Enqueued audio (queue size: {session.queue.qsize()})")
        except Exception as exc:
            logger.error(f"[AI Voice] TTS synthesis failed in guild {guild_id}: {exc}")

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
