"""
utils/errors.py
Global error handler for application commands.

This module provides `setup_error_handler(bot)` which registers an
`on_application_command_error` listener on the bot. Call this from bot.py.

Handled errors:
  - commands.CheckFailure      → User-friendly message (permission denied, wrong channel, etc.)
  - commands.NoPrivateMessage  → "This command can only be used in a server."
  - commands.MissingPermissions → "You don't have permission to do that."
  - discord.HTTPException      → "Discord API error. Please try again."
  - Exception (catch-all)      → Logs the full traceback, shows generic error to user.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from utils.embeds import error_embed


def setup_error_handler(bot: discord.Bot) -> None:
    """Register the global application command error handler on the bot instance."""

    @bot.event
    async def on_application_command_error(
        ctx: discord.ApplicationContext,
        error: discord.DiscordException,
    ) -> None:
        # Unwrap the original error if wrapped by discord
        error = getattr(error, "original", error)

        if isinstance(error, commands.CheckFailure):
            embed = error_embed("Permission Denied", str(error) or "You don't have permission to run this command.")
        elif isinstance(error, commands.NoPrivateMessage):
            embed = error_embed("Server Only", "This command can only be used in a server, not in DMs.")
        elif isinstance(error, commands.MissingPermissions):
            missing = ", ".join(f"`{p}`" for p in error.missing_permissions)
            embed = error_embed("Missing Permissions", f"You need the following permissions: {missing}")
        elif isinstance(error, discord.HTTPException):
            logger.warning(f"HTTPException in command '{ctx.command}': {error}")
            embed = error_embed("Discord Error", "A Discord API error occurred. Please try again.")
        else:
            logger.exception(f"Unhandled error in command '{ctx.command}': {error}")
            embed = error_embed("Unexpected Error", "Something went wrong. The issue has been logged.")

        try:
            if ctx.response.is_done():
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.respond(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass  # If we can't even send the error embed, just swallow it
