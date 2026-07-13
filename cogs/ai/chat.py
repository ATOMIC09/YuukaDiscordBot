"""
cogs/ai/chat.py
Cog for stateful AI chat commands.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.config import config
from bot.logger import logger
from utils.embeds import error_embed, success_embed
from utils.llm import generate_chat_response

# Safe maximum to keep history well within limits. 
MAX_HISTORY_LENGTH = 50


class AIChatCog(commands.Cog, name="AI Chat"):
    """Stateful AI chat functionality."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        # Maps channel_id to a list of message dicts: [{"role": "user", "content": "..."}]
        self.active_channels: dict[int, list[dict]] = {}

    ai = discord.SlashCommandGroup("ai", "AI related commands")

    @ai.command(name="chat", description="Start an AI chat session in this channel")
    async def ai_chat(self, ctx: discord.ApplicationContext) -> None:
        await ctx.defer()
        channel_id = ctx.channel.id
        
        if channel_id in self.active_channels:
            await ctx.respond("The AI is already listening in this channel!", ephemeral=True)
            return

        # Initialize the history with the system prompt
        history = [{"role": "system", "content": config.ollama_system_prompt}]
        
        # Fetch the recent messages to build immediate context up to MAX_HISTORY_LENGTH
        recent_messages = []
        async for msg in ctx.channel.history(limit=MAX_HISTORY_LENGTH):
            recent_messages.append(msg)
            
        # History yields newest to oldest. Reverse it so it's chronological.
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
            await ctx.respond("The AI is not currently active in this channel.", ephemeral=True)
            return

        del self.active_channels[channel_id]
        
        logger.info(f"[AI Chat] Stopped session in channel {channel_id}")
        await ctx.respond(embed=success_embed("AI Chat Stopped", "Yuuka is no longer listening to this channel."))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore bots (including ourselves)
        if message.author.bot:
            return
            
        channel_id = message.channel.id
        if channel_id not in self.active_channels:
            return

        history = self.active_channels[channel_id]
        
        content = message.clean_content.strip()
        if not content:
            return
        
        # Append the new user message to the context history.
        # We prepend their username and timestamp so the AI knows who is speaking and when.
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
        user_content = f"[{timestamp}] {message.author.display_name}: {content}"
        history.append({"role": "user", "content": user_content})

        # Prune history if it gets too large (keep the system prompt at index 0)
        while len(history) > MAX_HISTORY_LENGTH:
            history.pop(1)

        # Only trigger the LLM to generate a response if the bot is explicitly mentioned
        if self.bot.user in message.mentions:
            # Show the typing indicator while the CPU thinks
            async with message.channel.typing():
                logger.info(f"[AI Chat] Triggered by {message.author} in {channel_id}")
                
                response = await generate_chat_response(history)
                
                if response.startswith("❌"):
                    await message.reply(embed=error_embed("AI Error", response))
                    return
                
                # Append the AI's response to the history so it remembers what it said
                history.append({"role": "assistant", "content": response})

                # Handle Discord's 2000 character limit per message
                if len(response) <= 2000:
                    await message.reply(response)
                else:
                    # If the response is too long, slice into chunks
                    chunks = [response[i:i+1997] for i in range(0, len(response), 1997)]
                    await message.reply(chunks[0])
                    for chunk in chunks[1:]:
                        await message.channel.send(chunk)


def setup(bot: discord.Bot) -> None:
    bot.add_cog(AIChatCog(bot))
