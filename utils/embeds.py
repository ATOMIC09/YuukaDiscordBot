"""
utils/embeds.py
Embed builder helpers for consistent, styled Discord embeds across all cogs.

Usage:
    from utils.embeds import build_embed, success_embed, error_embed

Color palette:
    SUCCESS  — Green  (#2ecc71)
    ERROR    — Red    (#e74c3c)
    INFO     — Blurple (#5865F2, Discord brand)
    WARNING  — Yellow (#f39c12)
    NEUTRAL  — Dark   (#2c2f33)
"""

from __future__ import annotations

import discord

# Standard color palette
COLOR_SUCCESS = discord.Color(0x2ECC71)  # Green
COLOR_ERROR   = discord.Color(0xE74C3C)  # Red
COLOR_INFO    = discord.Color(0x5865F2)  # Blurple (Discord brand)
COLOR_WARNING = discord.Color(0xF39C12)  # Yellow
COLOR_NEUTRAL = discord.Color(0x2C2F33)  # Dark grey


def build_embed(
    title: str,
    description: str = "",
    color: discord.Color = COLOR_NEUTRAL,
    *,
    footer: str | None = None,
    thumbnail_url: str | None = None,
    image_url: str | None = None,
    fields: list[tuple[str, str, bool]] | None = None,
) -> discord.Embed:
    """
    Build a styled Discord embed.

    Args:
        title: Embed title.
        description: Embed description.
        color: Embed color (use COLOR_* constants from this module).
        footer: Optional footer text.
        thumbnail_url: Optional thumbnail image URL.
        image_url: Optional large image URL.
        fields: Optional list of (name, value, inline) tuples.

    Returns:
        A discord.Embed instance.
    """
    embed = discord.Embed(title=title, description=description, color=color)
    if footer:
        embed.set_footer(text=footer)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    if image_url:
        embed.set_image(url=image_url)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    return embed


def success_embed(title: str, description: str = "") -> discord.Embed:
    """Green success embed."""
    return build_embed(title=f"{title}", description=description, color=COLOR_SUCCESS)


def error_embed(title: str, description: str = "") -> discord.Embed:
    """Red error embed."""
    return build_embed(title=f"{title}", description=description, color=COLOR_ERROR)


def info_embed(title: str, description: str = "") -> discord.Embed:
    """Blurple info embed."""
    return build_embed(title=f"{title}", description=description, color=COLOR_INFO)


def warning_embed(title: str, description: str = "") -> discord.Embed:
    """Yellow warning embed."""
    return build_embed(title=f"{title}", description=description, color=COLOR_WARNING)
