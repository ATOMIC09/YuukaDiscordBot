"""
cogs/ai/chat.py
Cog for all /ai slash commands — text chat AND voice chat commands live here
to avoid duplicate SlashCommandGroup registration across cogs.

The voice chat *logic* (session state, audio queue, on_message listener) lives in
voice_chat.py (AIVoiceChatCog). This cog delegates to it via self.bot.cogs.

Slash commands:
  /ai chat  — activate text chat session in this channel
  /ai voice — join voice channel, start voice chat session
  /ai stop  — stop any active AI session (text or voice) in this guild
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.config import config
from bot.logger import logger
from cogs.ai import ai_group
from utils.embeds import ai_disclosure_field, build_embed, COLOR_SUCCESS, error_embed, success_embed
from utils import ai_actions
from utils.errors import UserWarning
from utils.llm import generate_chat_stream_response


class AIChatCog(commands.Cog, name="AI Chat"):
    """Stateful AI text-chat functionality. Owns the shared /ai command group."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # channel_id → list[dict]  (OpenAI-format message history)
        self.active_channels: dict[int, list[dict]] = {}

    # This cog is the sole owner of the /ai SlashCommandGroup.
    # voice_chat.py (AIVoiceChatCog) has NO class-level ai attribute — it only
    # exposes start_session() / stop_session() methods that we call here.
    ai = ai_group

    # ──────────────────────────────────────────────────────────────────────
    # /ai chat
    # ──────────────────────────────────────────────────────────────────────

    def _build_ai_log_embed(self, user: discord.Member | discord.User, channel: discord.abc.Messageable, dev_msg: str, event_name: str) -> discord.Embed:
        embed = discord.Embed(
            title="⚠️ API Error",
            description=f"**Event : {event_name}**",
            color=discord.Color.red()
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url if user.display_avatar else None)
        
        guild = getattr(channel, "guild", None)
        if guild:
            embed.add_field(
                name="เซิร์ฟเวอร์",
                value=f"`{guild.name}`\n({guild.id})",
                inline=True
            )
        else:
            embed.add_field(
                name="เซิร์ฟเวอร์",
                value="`Direct Message`",
                inline=True
            )

        category = getattr(channel, "category", None)
        if category:
            embed.add_field(
                name="หมวดหมู่",
                value=f"`{category.name}`\n({category.id})",
                inline=True
            )
        else:
            embed.add_field(
                name="หมวดหมู่",
                value="`None`",
                inline=True
            )

        embed.add_field(
            name="ช่อง",
            value=f"{channel.mention if hasattr(channel, 'mention') else 'Unknown'}\n({getattr(channel, 'id', 'Unknown')})",
            inline=True
        )

        embed.add_field(
            name="ผู้เขียน",
            value=f"{user.mention} ({user.id})",
            inline=True
        )

        embed.add_field(
            name="เหตุการณ์",
            value=f"```\n{event_name}\n```",
            inline=True
        )

        embed.add_field(
            name="Error",
            value=f"```\n{dev_msg}\n```",
            inline=False
        )
        embed.timestamp = discord.utils.utcnow()
        return embed



    @ai.command(name="chat", description="💬 เริ่มการสนทนากับ AI ในช่องแชทนี้")
    async def ai_chat(self, ctx: discord.ApplicationContext) -> None:
        await ctx.defer()
        channel_id = ctx.channel.id

        if channel_id in self.active_channels:
            raise UserWarning("Already Listening", "หนูกำลังฟังอยู่นี่ไง (´･ω･`)?")

        # Initialize history with the system prompt
        history = [{"role": "system", "content": config.openrouter_system_prompt}]

        # Fetch recent messages for context
        recent_messages = []
        async for msg in ctx.channel.history(limit=config.max_history_length):
            recent_messages.append(msg)

        recent_messages.reverse()  # chronological order

        for msg in recent_messages:
            content = msg.clean_content.strip()
            if not content:
                continue

            if msg.author == self.bot.user:
                history.append({"role": "assistant", "content": content})
            elif not msg.author.bot:
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M UTC")
                user_content = f"[{timestamp}] {msg.author.display_name}: {content}"
                history.append({"role": "user", "content": user_content})

        self.active_channels[channel_id] = history

        logger.info(
            f"[AI Chat] Started session in channel {channel_id} by {ctx.author}. "
            f"Loaded {len(history) - 1} past messages."
        )
        await ctx.respond(embed=build_embed(
            "🌸 เริ่มต้นการสนทนา",
            "รับทราบค่ะ! หนูกำลังฟังทุกคนอยู่นะคะ (´｡• ᵕ •｡\`) \n\n"
            "หนูอ่านข้อความก่อนหน้านี้มาแล้วค่ะ ถ้าอยากคุยกับหนู อย่าลืม `@mention` เรียกหนูด้วยนะคะ!",
            COLOR_SUCCESS,
            fields=[ai_disclosure_field(config.openrouter_model)],
        ))

    # ──────────────────────────────────────────────────────────────────────
    # /ai voice  — delegates to AIVoiceChatCog.start_session()
    # ──────────────────────────────────────────────────────────────────────

    @ai.command(name="voice", description="🎙️ เข้าห้องเสียงและเริ่มการสนทนากับ AI ด้วยเสียง")
    async def ai_voice(self, ctx: discord.ApplicationContext) -> None:
        voice_cog = self.bot.cogs.get("AI Voice Chat")
        if voice_cog is None:
            raise UserWarning("ระบบขัดข้องค่ะ", "ไม่สามารถโหลด Voice Chat module ได้ค่ะ")
        await voice_cog.start_session(ctx)

    # ──────────────────────────────────────────────────────────────────────
    # /ai stop  — kills any active AI session (text or voice) in this guild
    # ──────────────────────────────────────────────────────────────────────

    @ai.command(name="stop", description="🛑 หยุดการทำงานของ AI ทั้งหมดในเซิร์ฟเวอร์นี้")
    async def ai_stop(self, ctx: discord.ApplicationContext) -> None:
        guild_id = ctx.guild.id
        stopped_something = False

        # ── Stop voice session via AIVoiceChatCog ─────────────────────────
        voice_cog = self.bot.cogs.get("AI Voice Chat")
        if voice_cog is not None:
            stopped_something = await voice_cog.stop_session(guild_id) or stopped_something

        # ── Stop text chat session(s) in this guild ───────────────────────
        channels_to_remove = []
        for ch_id in list(self.active_channels.keys()):
            ch = self.bot.get_channel(ch_id)
            if ch and getattr(ch, "guild", None) and ch.guild.id == guild_id:
                channels_to_remove.append(ch_id)

        for ch_id in channels_to_remove:
            self.active_channels.pop(ch_id, None)
            logger.info(f"[AI Chat] Stopped session in channel {ch_id} via /ai stop")
            stopped_something = True

        if not stopped_something:
            raise UserWarning(
                "ไม่มีเซสชั่นที่ใช้งานอยู่ค่ะ",
                "หนูไม่ได้ทำงานอยู่เลยนะคะ (⊙_⊙)？",
            )

        await ctx.respond(embed=success_embed(
            "💤 หยุดการทำงานแล้วค่ะ",
            "รับทราบค่ะ! หนูขอตัวไปพักก่อนนะคะ ถ้ามีอะไรเรียกหนูใหม่ได้เลยน้า (๑>◡<๑)",
        ))

    # ──────────────────────────────────────────────────────────────────────
    # on_message — respond when @mentioned in an active text-chat channel
    # ──────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        channel_id = message.channel.id
        if channel_id not in self.active_channels:
            return

        history = self.active_channels[channel_id]

        content = message.clean_content.strip()
        if not content:
            return

        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
        user_content = f"[{timestamp}] {message.author.display_name}: {content}"
        history.append({"role": "user", "content": user_content})

        while len(history) > config.max_history_length:
            history.pop(1)

        if self.bot.user in message.mentions:
            import time
            async with message.channel.typing():
                logger.info(f"[AI Chat] Triggered by {message.author} in {channel_id}")

                active_msg = None
                current_chunk_text = ""
                full_response = ""
                last_edit = time.time()
                error_occurred = False
                pending_action = None

                # No guild means no voice channel and no music player, so the
                # model is not told actions exist and cannot ask for one.
                catalog = ai_actions.catalog_for(self.bot) if message.guild else ""

                async for msg_type, chunk in generate_chat_stream_response(
                    history, action_catalog=catalog
                ):
                    if msg_type == "status":
                        embed = discord.Embed(description=chunk, color=discord.Color.blue())
                        if not active_msg:
                            active_msg = await message.reply(embed=embed)
                        else:
                            await active_msg.edit(content=current_chunk_text or None, embed=embed)
                    elif msg_type == "error":
                        error_occurred = True
                        if isinstance(chunk, dict):
                            user_msg = chunk.get("user", "AI Error")
                            dev_msg = chunk.get("dev", user_msg)
                        else:
                            user_msg = dev_msg = str(chunk)
                            
                        logger.error(f"[AI Chat] Stream error in on_message: {dev_msg}")
                        
                        if config.log_channel_id:
                            log_channel = self.bot.get_channel(config.log_channel_id)
                            if log_channel:
                                log_embed = self._build_ai_log_embed(message.author, message.channel, dev_msg, "on_message")
                                await log_channel.send(embed=log_embed)

                        if not active_msg:
                            active_msg = await message.reply(embed=error_embed("AI Error", user_msg))
                        else:
                            await active_msg.edit(content=current_chunk_text or None, embed=error_embed("AI Error", user_msg))
                        break
                    elif msg_type == "action":
                        pending_action = chunk
                    elif msg_type == "content":
                        current_chunk_text += chunk
                        full_response += chunk

                        if len(current_chunk_text) > 1950:
                            if active_msg:
                                await active_msg.edit(content=current_chunk_text, embed=None)
                            current_chunk_text = ""
                            active_msg = await message.reply("...")
                            last_edit = time.time()
                            continue

                        if not active_msg:
                            active_msg = await message.reply(current_chunk_text)
                        else:
                            if time.time() - last_edit > 1.0:
                                await active_msg.edit(content=current_chunk_text, embed=None)
                                last_edit = time.time()

                if not error_occurred and active_msg and current_chunk_text and active_msg.content != current_chunk_text:
                    await active_msg.edit(content=current_chunk_text, embed=None)

                if full_response and not full_response.startswith("❌"):
                    history.append({"role": "assistant", "content": full_response})

                if pending_action is not None:
                    await self._run_action(message, pending_action)

    # ──────────────────────────────────────────────────────────────────────
    # Model-requested commands
    # ──────────────────────────────────────────────────────────────────────

    async def _run_action(self, message: discord.Message, action: dict[str, str]) -> None:
        """Run a command the model asked for during a text-chat turn.

        Whatever she wrote before the tag was already posted as her reply, so
        all that is left is to run the thing and let `utils.ai_actions` post the
        embed documenting it.
        """
        await ai_actions.run_action(
            self.bot,
            name=action["name"],
            arg=action["arg"],
            guild=message.guild,
            member=message.author,
            fallback_channel=message.channel,
        )

    # ──────────────────────────────────────────────────────────────────────
    # on_reaction_add — short reaction to user emoji on bot's message
    # ──────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Member | discord.User) -> None:
        if user.bot:
            return

        message = reaction.message
        if message.author != self.bot.user:
            return

        channel_id = message.channel.id
        if channel_id not in self.active_channels:
            return

        import asyncio, time
        await asyncio.sleep(5)

        async with message.channel.typing():
            logger.info(f"[AI Chat] Reacting to {user.display_name}'s reaction {reaction.emoji} in {channel_id}")

            timestamp = discord.utils.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            react_content = f"[{timestamp}] {user.display_name} reacted with {reaction.emoji}"

            short_history = [
                {
                    "role": "system",
                    "content": config.openrouter_system_prompt
                    + "\n\nINSTRUCTION: The user just reacted to your last message. "
                    "Give a short response (1-3 sentences) reacting to their emoji. Keep it in character.",
                },
                {"role": "assistant", "content": message.clean_content},
                {"role": "user", "content": react_content},
            ]

            active_msg = None
            current_chunk_text = ""
            full_response = ""
            last_edit = time.time()
            error_occurred = False

            async for msg_type, chunk in generate_chat_stream_response(short_history):
                if msg_type == "status":
                    embed = discord.Embed(description=chunk, color=discord.Color.blue())
                    if not active_msg:
                        active_msg = await message.channel.send(embed=embed)
                    else:
                        await active_msg.edit(content=current_chunk_text or None, embed=embed)
                elif msg_type == "error":
                    error_occurred = True
                    if isinstance(chunk, dict):
                        user_msg = chunk.get("user", "AI Error")
                        dev_msg = chunk.get("dev", user_msg)
                    else:
                        user_msg = dev_msg = str(chunk)
                        
                    logger.error(f"[AI Chat] Stream error in on_reaction_add: {dev_msg}")
                    
                    if config.log_channel_id:
                        log_channel = self.bot.get_channel(config.log_channel_id)
                        if log_channel:
                            log_embed = self._build_ai_log_embed(user, message.channel, dev_msg, "on_reaction_add")
                            await log_channel.send(embed=log_embed)

                    if not active_msg:
                        active_msg = await message.channel.send(embed=error_embed("AI Error", user_msg))
                    else:
                        prefix = f"{user.mention} " if active_msg.content.startswith("<@") else ""
                        await active_msg.edit(content=f"{prefix}{current_chunk_text}" or None, embed=error_embed("AI Error", user_msg))
                    break
                elif msg_type == "content":
                    current_chunk_text += chunk
                    full_response += chunk

                    if len(current_chunk_text) > 1950:
                        if active_msg:
                            prefix = f"{user.mention} " if active_msg.content.startswith("<@") else ""
                            await active_msg.edit(content=f"{prefix}{current_chunk_text}", embed=None)
                        current_chunk_text = ""
                        active_msg = await message.channel.send("...")
                        last_edit = time.time()
                        continue

                    if not active_msg:
                        active_msg = await message.channel.send(f"{user.mention} {current_chunk_text}")
                    else:
                        if time.time() - last_edit > 1.5:
                            prefix = f"{user.mention} " if active_msg.content.startswith("<@") else ""
                            await active_msg.edit(content=f"{prefix}{current_chunk_text}", embed=None)
                            last_edit = time.time()

            if not error_occurred and active_msg and current_chunk_text:
                prefix = f"{user.mention} " if active_msg.content.startswith("<@") else ""
                if active_msg.content != f"{prefix}{current_chunk_text}":
                    await active_msg.edit(content=f"{prefix}{current_chunk_text}", embed=None)

            if full_response and not full_response.startswith("❌"):
                history = self.active_channels[channel_id]
                history.append({"role": "user", "content": react_content})
                history.append({"role": "assistant", "content": full_response})

                while len(history) > config.max_history_length:
                    history.pop(1)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(AIChatCog(bot))
