"""
cogs/voice/transcribe.py
Live captions — transcribes everything said in a voice channel and posts it
to a text channel.

Relationship to /ai voice
-------------------------
This cog deliberately has **no wake word**: it is a captioning tool, so
transcribing every utterance is the point. `/ai voice` (cogs/ai/voice_chat.py)
uses the same segments but gates them behind a wake word, because *there* an
ungated bot is one that talks over every conversation in the room.

Both subscribe to `utils.voice_hub`, which owns the single sink a VoiceClient
allows and closes an utterance after a short run of packet silence. See
utils/voice_hub.py for why that beats polling a sink's buffer size.

Slash Commands
--------------
  /transcribe start — Join voice channel and start live captioning
  /transcribe stop  — Stop captioning
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import info_embed, success_embed, warning_embed
from utils.errors import UserError, UserWarning
from utils.stt import ensure_loaded, model_description, transcribe_pcm
from utils.voice_hub import SpeechSegment, voice_hub

_HUB_KEY = "transcribe"


class STTCog(commands.Cog, name="Realtime STT"):
    """Voice receive — transcribe everyone in the channel as they speak."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # guild_id → text channel to post captions into
        self._sessions: dict[int, discord.TextChannel] = {}

    # ------------------------------------------------------------------
    # Segment handler
    # ------------------------------------------------------------------

    async def _on_segment(self, segment: SpeechSegment) -> None:
        channel = self._sessions.get(segment.guild_id)
        if channel is None:
            return

        user = self.bot.get_user(segment.user_id)
        display = user.display_name if user else f"Unknown ({segment.user_id})"

        result = await transcribe_pcm(segment.pcm, display)
        if not result.text:
            return

        # Tag the language so a Thai/English mix is legible in the log, but
        # only when detection was not confident — a tag on every line is noise.
        suffix = "" if result.language_probability >= 0.75 else f"  ·  `{result.language}?`"
        try:
            await channel.send(f"🎙️ **{display}**: {result.text}{suffix}")
        except discord.HTTPException as exc:
            logger.error(f"[STT] Failed to post caption in guild {segment.guild_id}: {exc}")

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    transcribe = discord.SlashCommandGroup("transcribe", "🎙️ คำสั่งถอดเสียงแบบเรียลไทม์")

    @transcribe.command(name="start", description="🎙️ เข้าห้องเสียงและเริ่มถอดเสียงแบบเรียลไทม์")
    async def transcribe_start(self, ctx: discord.ApplicationContext) -> None:
        """Start live captioning the invoker's voice channel."""
        await ctx.defer()

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError(
                "ยังไม่ได้เข้าห้องเสียงค่ะ",
                "เข้าห้องเสียงก่อนนะคะ แล้วค่อยเรียกหนูมาน้า (・`ω´・)",
            )

        guild_id = ctx.guild.id

        if guild_id in self._sessions:
            raise UserWarning(
                "หนูกำลังถอดเสียงอยู่ค่ะ",
                "หนูถอดเสียงอยู่ในเซิร์ฟเวอร์นี้แล้วนะคะ ใช้ `/transcribe stop` ก่อนน้า",
            )

        # First run downloads the model, which can take a while — say so rather
        # than leaving the interaction hanging.
        if not await ensure_loaded():
            raise UserError(
                "ระบบถอดเสียงไม่พร้อมค่ะ",
                "หนูโหลดโมเดลถอดเสียงไม่สำเร็จค่ะ (´-ω-`) ลองดู log ของบอทนะคะ",
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
                    f"หนูเข้าห้อง **{voice_channel.name}** ไม่ได้ค่ะ: `{exc}`",
                )
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)

        self._sessions[guild_id] = ctx.channel
        voice_hub.subscribe(voice_client, _HUB_KEY, on_segment=self._on_segment)

        logger.info(
            f"Started live captions in guild {guild_id}, channel '{voice_channel.name}' "
            f"using {model_description()}"
        )
        await ctx.respond(embed=info_embed(
            "🔴 เริ่มถอดเสียงแล้วค่ะ",
            f"หนูกำลังฟังทุกคนในห้อง **{voice_channel.name}** อยู่นะคะ 🎧\n"
            f"หนูจะพิมพ์สิ่งที่ได้ยินลงในช่อง **{ctx.channel.name}** ให้ค่า\n\n"
            "ใช้ `/transcribe stop` เมื่อต้องการหยุดน้า",
        ))

    @transcribe.command(name="stop", description="⏹️ หยุดการถอดเสียงแบบเรียลไทม์")
    async def transcribe_stop(self, ctx: discord.ApplicationContext) -> None:
        """Stop captioning and clean up."""
        await ctx.defer()

        guild_id = ctx.guild.id

        if guild_id not in self._sessions:
            raise UserWarning(
                "ยังไม่ได้ถอดเสียงค่ะ",
                "หนูยังไม่ได้ถอดเสียงเลยนะคะ ใช้ `/transcribe start` ก่อนน้า (・_・;)",
            )

        self._sessions.pop(guild_id, None)
        voice_hub.unsubscribe(guild_id, _HUB_KEY)

        logger.info(f"Stopped live captions in guild {guild_id}")
        await ctx.respond(embed=success_embed(
            "⏹️ หยุดถอดเสียงแล้วค่ะ",
            "หนูหยุดถอดเสียงแล้วนะคะ ขอบคุณที่เรียกใช้หนูน้า (´• ω •`) ♡",
        ))

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
        """Drop the subscription if the bot gets disconnected mid-session."""
        if member != self.bot.user:
            return
        if before.channel is None or after.channel is not None:
            return

        guild_id = member.guild.id
        channel = self._sessions.pop(guild_id, None)
        if channel is None:
            return

        logger.info(f"Bot left voice in guild {guild_id} — stopping live captions")
        voice_hub.unsubscribe(guild_id, _HUB_KEY)
        await channel.send(embed=warning_embed(
            "🔇 ถูกตัดการเชื่อมต่อค่ะ",
            "หนูหลุดจากห้องเสียง เลยหยุดถอดเสียงอัตโนมัติแล้วน้า",
        ))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(STTCog(bot))
