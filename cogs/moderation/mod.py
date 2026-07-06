"""
cogs/moderation/mod.py
Moderation commands.

Slash Commands (to be implemented):
  /kick   <member> [reason]             — Kick a member from the server
  /ban    <member> [reason] [delete_days] — Ban a member
  /unban  <user_id>                     — Unban a user by ID
  /timeout <member> <duration> [reason] — Timeout (mute) a member
  /untimeout <member>                   — Remove timeout from a member
  /purge  <amount>                      — Delete N messages from channel

All commands require appropriate permissions (checks via utils.checks).
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from utils.checks import is_moderator
from utils.embeds import build_embed


class ModerationCog(commands.Cog, name="Moderation"):
    """Moderation commands — manage members and messages."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # TODO: Implement slash commands below
    # ------------------------------------------------------------------

    # @discord.slash_command(name="kick", description="Kick a member from the server")
    # @commands.has_permissions(kick_members=True)
    # async def kick(self, ctx: discord.ApplicationContext, member: discord.Member, reason: str = "No reason provided") -> None: ...

    # @discord.slash_command(name="ban", description="Ban a member from the server")
    # @commands.has_permissions(ban_members=True)
    # async def ban(self, ctx: discord.ApplicationContext, member: discord.Member, reason: str = "No reason provided") -> None: ...

    # @discord.slash_command(name="purge", description="Delete a number of messages")
    # @commands.has_permissions(manage_messages=True)
    # async def purge(self, ctx: discord.ApplicationContext, amount: int) -> None: ...


def setup(bot: discord.Bot) -> None:
    bot.add_cog(ModerationCog(bot))
