"""
utils/checks.py
Custom permission and role checks for use as command decorators.

Usage:
    from utils.checks import is_moderator, is_in_voice_channel

    @discord.slash_command(...)
    @is_moderator()
    async def my_command(self, ctx): ...
"""

from __future__ import annotations

import discord
from discord.ext import commands


def is_moderator():
    """
    Check that the invoking user has 'kick_members' permission.
    Intended as a rough proxy for "moderator" role. Adjust as needed.
    """
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage("This command cannot be used in DMs.")
        if not ctx.author.guild_permissions.kick_members:
            raise commands.MissingPermissions(["kick_members"])
        return True
    return commands.check(predicate)


def is_in_voice_channel():
    """
    Check that the invoking user is currently in a voice channel.
    Use this on all voice-related commands.
    """
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            raise commands.CheckFailure("You must be in a voice channel to use this command.")
        return True
    return commands.check(predicate)


def is_bot_in_voice_channel():
    """
    Check that the bot is currently connected to a voice channel in this guild.
    """
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage("This command cannot be used in DMs.")
        if ctx.guild.voice_client is None:
            raise commands.CheckFailure("I'm not connected to any voice channel in this server.")
        return True
    return commands.check(predicate)
