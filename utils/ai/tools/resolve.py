"""
utils/ai/tools/resolve.py
Turn what the model wrote ("#general", a mention, an id) into a real object.

Names come from a model reading a human's message, so they are matched loosely
(case, a leading #) and a miss lists the nearest names instead of just failing.
"""

from __future__ import annotations

import difflib
import re

import discord

from utils.ai.context import YuukaContext
from utils.errors import UserWarning

_CHANNEL_MENTION = re.compile(r"^<#(\d+)>$")


def _clean(text: str) -> str:
    return text.strip().lstrip("#").strip().casefold()


def resolve_text_channel(ctx: YuukaContext, text: str) -> discord.abc.Messageable:
    """A text channel or active thread in the requester's guild, by mention, id or name."""
    guild = ctx.guild
    raw = text.strip()

    match = _CHANNEL_MENTION.match(raw)
    if match or raw.isdigit():
        channel = guild.get_channel_or_thread(int(match.group(1) if match else raw))
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel

    candidates = [*guild.text_channels, *guild.threads]
    wanted = _clean(raw)
    for channel in candidates:
        if channel.name.casefold() == wanted:
            return channel

    close = difflib.get_close_matches(wanted, [c.name.casefold() for c in candidates], n=3, cutoff=0.5)
    hint = f" ช่องที่ใกล้เคียง: {', '.join('#' + n for n in close)}" if close else ""
    raise UserWarning("หาช่องนั้นไม่เจอค่ะ", f"ไม่มีช่อง '{raw}' ในเซิร์ฟเวอร์นี้นะคะ.{hint}")
