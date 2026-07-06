"""
cogs/general/info.py
General information commands.

Slash Commands (to be implemented):
  /ping     — Show bot latency (WebSocket ping)
  /botinfo  — Show bot version, uptime, guild count, etc.
  /serverinfo — Show current server information
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import build_embed


class InfoCog(commands.Cog, name="Info"):
    """General information commands — ping, bot info, server info."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # TODO: Implement slash commands below
    # ------------------------------------------------------------------

    # @discord.slash_command(name="ping", description="Check the bot's latency")
    # async def ping(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="botinfo", description="Show information about the bot")
    # async def botinfo(self, ctx: discord.ApplicationContext) -> None: ...

    # @discord.slash_command(name="serverinfo", description="Show information about this server")
    # async def serverinfo(self, ctx: discord.ApplicationContext) -> None: ...


def setup(bot: discord.Bot) -> None:
    bot.add_cog(InfoCog(bot))
