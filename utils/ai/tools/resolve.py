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


_USER_MENTION = re.compile(r"^<@!?(\d+)>$")


def _names(member: discord.Member) -> set[str]:
    names = {member.display_name, member.name, member.global_name or ""}
    return {n.casefold() for n in names if n}


def resolve_member(ctx: YuukaContext, text: str) -> discord.Member:
    """A member of the requester's guild, by mention, id, or display/user name."""
    guild = ctx.guild
    raw = text.strip()

    match = _USER_MENTION.match(raw)
    if match or raw.isdigit():
        member = guild.get_member(int(match.group(1) if match else raw))
        if member:
            return member

    wanted = raw.lstrip("@").strip().casefold()

    exact = [m for m in guild.members if wanted in _names(m)]
    if len(exact) == 1:
        return exact[0]

    found = exact or [m for m in guild.members if any(wanted in n for n in _names(m))]
    if len(found) == 1:
        return found[0]
    if found:
        listed = ", ".join(m.display_name for m in found[:5])
        raise UserWarning("หลายคนชื่อคล้ายกันค่ะ", f"'{raw}' ตรงกับหลายคน: {listed} ช่วยระบุให้ชัดขึ้นหน่อยนะคะ")

    close = difflib.get_close_matches(wanted, [m.display_name.casefold() for m in guild.members], n=3, cutoff=0.5)
    hint = f" ใกล้เคียง: {', '.join(close)}" if close else ""
    raise UserWarning("หาคนนั้นไม่เจอค่ะ", f"ไม่มีสมาชิกชื่อ '{raw}' ในเซิร์ฟเวอร์นี้นะคะ.{hint}")


def resolve_voice_channel(ctx: YuukaContext, text: str) -> discord.VoiceChannel:
    """A voice channel of the requester's guild, by mention, id or name."""
    guild = ctx.guild
    raw = text.strip()

    match = _CHANNEL_MENTION.match(raw)
    if match or raw.isdigit():
        channel = guild.get_channel(int(match.group(1) if match else raw))
        if isinstance(channel, discord.VoiceChannel):
            return channel

    wanted = _clean(raw)
    for channel in guild.voice_channels:
        if channel.name.casefold() == wanted:
            return channel

    close = difflib.get_close_matches(wanted, [c.name.casefold() for c in guild.voice_channels], n=3, cutoff=0.5)
    hint = f" ช่องที่ใกล้เคียง: {', '.join(close)}" if close else ""
    raise UserWarning("หาห้องเสียงนั้นไม่เจอค่ะ", f"ไม่มีห้องเสียง '{raw}' นะคะ.{hint}")
