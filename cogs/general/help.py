"""
cogs/general/help.py
Custom /help slash command.

Responsibilities:
  - Dynamically list all loaded cogs and their commands
  - Allow filtering by cog/category
  - Show command descriptions, parameters, and usage examples

Slash Commands (to be implemented):
  /help           — Show all available commands grouped by category
  /help <command> — Show detailed help for a specific command
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import build_embed


class HelpCog(commands.Cog, name="Help"):
    """Displays help information for bot commands."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # TODO: Implement /help command
    # ------------------------------------------------------------------

    # @discord.slash_command(name="help", description="Show available commands")
    # async def help_command(
    #     self,
    #     ctx: discord.ApplicationContext,
    #     command: str | None = None,
    # ) -> None: ...


def setup(bot: discord.Bot) -> None:
    bot.add_cog(HelpCog(bot))
