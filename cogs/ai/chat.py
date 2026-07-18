"""
cogs/ai/chat.py
Cog for stateful AI chat commands.
"""

from __future__ import annotations

import asyncio
import discord
from discord.ext import commands

from bot.config import config
from bot.logger import logger
from utils.embeds import error_embed, success_embed
from utils.errors import UserWarning
from utils.llm import generate_chat_response


class AIChatCog(commands.Cog, name="AI Chat"):
    """Stateful AI chat functionality."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self.active_channels: dict[int, list[dict]] = {}

    ai = discord.SlashCommandGroup("ai", "AI related commands")

    @ai.command(name="chat", description="Start an AI chat session in this channel")
    async def ai_chat(self, ctx: discord.ApplicationContext) -> None:
        await ctx.defer()
        channel_id = ctx.channel.id
        
        if channel_id in self.active_channels:
            raise UserWarning("Already Listening", "หนูกำลังฟังอยู่นี่ไง (´･ω･`)?")

        # Initialize history with the system prompt
        history = [{"role": "system", "content": config.openrouter_system_prompt}]
        
        # Fetch recent messages
        recent_messages = []
        async for msg in ctx.channel.history(limit=config.max_history_length):
            recent_messages.append(msg)
            
        # Chrorological order
        recent_messages.reverse()
        
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
        
        logger.info(f"[AI Chat] Started session in channel {channel_id} by {ctx.author}. Loaded {len(history)-1} past messages.")
        await ctx.respond(embed=success_embed(
            "AI Chat Started", 
            "Yuuka is now listening to this channel.\n\n"
            "She has read the recent channel history for context, but will **only** reply if you `@mention` her."
        ))

    @ai.command(name="stop", description="Stop the AI chat session in this channel")
    async def ai_stop(self, ctx: discord.ApplicationContext) -> None:
        """Deactivates the AI listener and clears the history for the current channel."""
        channel_id = ctx.channel.id
        
        if channel_id not in self.active_channels:
            raise UserWarning("Not Listening", "หนูไม่ได้คุยอยู่สักหน่อย (⊙_⊙)？")

        del self.active_channels[channel_id]
        
        logger.info(f"[AI Chat] Stopped session in channel {channel_id}")
        await ctx.respond(embed=success_embed("AI Chat Stopped", "Yuuka is no longer listening to this channel."))

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
            async with message.channel.typing():
                logger.info(f"[AI Chat] Triggered by {message.author} in {channel_id}")
                
                response = await generate_chat_response(history)
                
                if response.startswith("❌"):
                    await message.reply(embed=error_embed("AI Error", response))
                    return
                
                history.append({"role": "assistant", "content": response})

                if len(response) <= 2000:
                    await message.reply(response)
                else:
                    # If the response is too long, slice into chunks
                    chunks = [response[i:i+1997] for i in range(0, len(response), 1997)]
                    await message.reply(chunks[0])
                    for chunk in chunks[1:]:
                        await message.channel.send(chunk)

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

        await asyncio.sleep(5)
        
        async with message.channel.typing():
            logger.info(f"[AI Chat] Reacting to {user.display_name}'s reaction {reaction.emoji} in {channel_id}")
            
            timestamp = discord.utils.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            react_content = f"[{timestamp}] {user.display_name} reacted with {reaction.emoji}"
            
            short_history = [
                {"role": "system", "content": config.openrouter_system_prompt + "\n\nINSTRUCTION: The user just reacted to your last message. Give a short response (1-3 sentences) reacting to their emoji. Keep it in character."},
                {"role": "assistant", "content": message.clean_content},
                {"role": "user", "content": react_content}
            ]
            
            response = await generate_chat_response(short_history)
            
            if response.startswith("❌"):
                return

            history = self.active_channels[channel_id]
            history.append({"role": "user", "content": react_content})
            history.append({"role": "assistant", "content": response})
            
            while len(history) > config.max_history_length:
                history.pop(1)
                
            await message.channel.send(f"{user.mention} {response}")


def setup(bot: discord.Bot) -> None:
    bot.add_cog(AIChatCog(bot))
