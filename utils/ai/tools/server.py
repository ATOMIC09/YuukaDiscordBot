"""
utils/ai/tools/server.py
Read-only questions about voice rooms, people and the server.

These read straight from the guild's cached objects and return plain text for
the model; they do not post the embeds of the matching slash commands.
"""

from __future__ import annotations

from langchain_core.tools import tool

from utils.ai.context import Ctx
from utils.ai.tools.resolve import resolve_member, resolve_voice_channel
from utils.errors import UserWarning

_DATE = "%Y-%m-%d"
_LOADING = "<a:AppleLoadingGIF:1052465926487953428>"


@tool
async def voice_members(ctx: Ctx, channel: str | None = None) -> str:
    """List who is in a voice channel. Defaults to the voice channel the requester is in."""
    if channel:
        target = resolve_voice_channel(ctx, channel)
    elif ctx.requester and ctx.requester.voice and ctx.requester.voice.channel:
        target = ctx.requester.voice.channel
    else:
        raise UserWarning("ไม่ได้ระบุห้องค่ะ", "เซนเซย์ไม่ได้อยู่ในห้องเสียง และไม่ได้บอกชื่อห้องมาด้วยนะคะ")

    people = [m.display_name for m in target.members if not m.bot]
    if not people:
        return f"Nobody is in {target.name}."
    return f"{target.name}: {len(people)} people: {', '.join(people)}"


@tool
async def user_info(member: str, ctx: Ctx) -> str:
    """Look up a server member by name, mention or id: account age, join date, top role, voice channel."""
    m = resolve_member(ctx, member)
    voice = m.voice.channel.name if m.voice and m.voice.channel else "not in a voice channel"
    return (
        f"Display name: {m.display_name}. Username: {m.name}"
        f"{' (bot)' if m.bot else ''}. "
        f"Account created: {m.created_at.strftime(_DATE)}. "
        f"Joined this server: {m.joined_at.strftime(_DATE) if m.joined_at else 'unknown'}. "
        f"Top role: {m.top_role.name}. Voice: {voice}."
    )


@tool
async def server_info(ctx: Ctx) -> str:
    """Basic facts about this server: members, owner, creation date, channel counts."""
    g = ctx.guild
    owner = g.owner.display_name if g.owner else "unknown"
    return (
        f"Name: {g.name}. Members: {g.member_count}. Owner: {owner}. "
        f"Created: {g.created_at.strftime(_DATE)}. "
        f"Text channels: {len(g.text_channels)}. Voice channels: {len(g.voice_channels)}."
    )


TOOLS = [voice_members, user_info, server_info]
STATUS = {
    "voice_members": lambda a: f"{_LOADING} กำลังดูว่าใครอยู่ในห้องเสียง...",
    "user_info": lambda a: f"{_LOADING} กำลังดูข้อมูลของ {a.get('member', '')}...",
    "server_info": lambda a: f"{_LOADING} กำลังดูข้อมูลเซิร์ฟเวอร์...",
}
