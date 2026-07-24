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
from utils.embeds import error_embed, warning_embed

class UserError(discord.ApplicationCommandError):
    """Raised when a user doesn't meet the requirements or provides invalid input."""
    def __init__(self, title: str, description: str):
        self.title = title
        self.description = description
        super().__init__(f"{title}: {description}")

class UserWarning(discord.ApplicationCommandError):
    """Raised for soft warnings (e.g. stopping a command that isn't running)."""
    def __init__(self, title: str, description: str):
        self.title = title
        self.description = description
        super().__init__(f"{title}: {description}")


def setup_error_handler(bot: discord.Bot) -> None:
    """Register the global application command error handler on the bot instance."""

    @bot.event
    async def on_application_command_error(
        ctx: discord.ApplicationContext,
        error: discord.DiscordException,
    ) -> None:
        # Unwrap the original error if wrapped by discord
        error = getattr(error, "original", error)

        if isinstance(error, UserError):
            logger.warning(f"UserError in command '{ctx.command}': {error.title} - {error.description}")
            embed = error_embed(error.title, error.description)
        elif isinstance(error, UserWarning):
            logger.warning(f"UserWarning in command '{ctx.command}': {error.title} - {error.description}")
            embed = warning_embed(error.title, error.description)
        elif isinstance(error, commands.CheckFailure):
            logger.warning(f"CheckFailure in command '{ctx.command}': {error}")
            embed = error_embed("ไม่มีสิทธิ์ค่ะ", str(error) or "แง... ตัวเองไม่มีสิทธิ์ใช้คำสั่งนี้นะคะ (╥﹏╥)")
        elif isinstance(error, commands.NoPrivateMessage):
            logger.warning(f"NoPrivateMessage in command '{ctx.command}': {error}")
            embed = error_embed("ใช้ในนี้ไม่ได้ค่ะ", "คำสั่งนี้ใช้ในแชทส่วนตัวไม่ได้นะคะ ต้องไปใช้ในเซิร์ฟเวอร์น้า (´・ω・)")
        elif isinstance(error, commands.MissingPermissions):
            missing = ", ".join(f"`{p}`" for p in error.missing_permissions)
            logger.warning(f"MissingPermissions in command '{ctx.command}': {missing}")
            embed = error_embed("สิทธิ์ไม่พอนะคะ", f"หนูหรือตัวเองอาจจะขาดสิทธิ์บางอย่างนะคะ: {missing} (｡>﹏<)")
        elif isinstance(error, discord.HTTPException):
            logger.warning(f"HTTPException in command '{ctx.command}': {error}")
            embed = error_embed("Discord มีปัญหาค่ะ", "เซิร์ฟเวอร์ของ Discord ดื้อนิดหน่อยค่ะ ลองใหม่อีกทีน้า (｀ε´ )")
        else:
            logger.exception(f"Unhandled error in command '{ctx.command}': {error}")
            embed = error_embed("เกิดข้อผิดพลาดค่ะ", "อ๊ะ! มีอะไรบางอย่างผิดพลาดแหละค่ะ... หนูจดบันทึกไว้ให้ผู้พัฒนาดูแล้วน้า ขอโทษด้วยนะคะ (´-ω-`)")

        try:
            if ctx.response.is_done():
                await ctx.followup.send(embed=embed)
            else:
                await ctx.respond(embed=embed)
        except discord.HTTPException:
            pass  # If we can't even send the error embed, just swallow it
