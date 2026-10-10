"""
utils/ai/tools/resolve.py
Turn what the model wrote ("#general", a mention, an id) into a real object.

Names come from a model reading a human's message, so they are matched loosely
(case, a leading #) and a miss lists the nearest names instead of just failing.
Channel names are often decorated ("💬・main-chat"), so a channel also matches on
its letters and digits alone, and a miss suggests mentions the model can pass back
verbatim instead of retyping the decoration.

Channels are only ever matched or suggested if the REQUESTER can see them. The
bot usually sees far more than the person asking, and a channel they cannot see
is reported exactly like one that does not exist.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

import discord

from utils.ai.context import YuukaContext
from utils.errors import UserWarning

_CHANNEL_MENTION = re.compile(r"^<#(\d+)>$")


def _clean(text: str) -> str:
    return text.strip().lstrip("#").strip().casefold()


def channel_key(name: str) -> str:
    """Only the letters, digits and marks of a name: emoji, separators and dashes go."""
    text = unicodedata.normalize("NFKC", name).casefold()
    # Marks (M*) carry Thai vowels and tones, so they are part of the name.
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LNM")


def _only_partial(key: str, channels: list):
    """The one channel whose name contains `key` ("johny" in "〈🤖〉﹕johny-channel"), if exactly one does."""
    if len(key) < 3:
        return None
    found = [c for c in channels if key in channel_key(c.name)]
    return found[0] if len(found) == 1 else None


def _suggest(raw: str, channels: list) -> str:
    """The nearest channel names, each with a mention the model can pass back."""
    by_key: dict[str, discord.abc.GuildChannel] = {}
    for channel in channels:
        by_key.setdefault(channel_key(channel.name), channel)
    close = difflib.get_close_matches(channel_key(raw), list(by_key), n=3, cutoff=0.5)
    if not close:
        return ""
    listed = ", ".join(f"#{by_key[k].name} = {by_key[k].mention}" for k in close)
    return f" ช่องที่ใกล้เคียง: {listed} (ส่ง <#id> แทนชื่อได้เลยค่ะ)"


async def can_view(member: discord.Member, channel: discord.TextChannel | discord.Thread) -> bool:
    """Whether `member` can see `channel` in their own Discord client."""
    perms = channel.permissions_for(member)
    if not perms.view_channel:
        return False
    if isinstance(channel, discord.Thread) and channel.is_private():
        # A thread takes its permissions from the parent channel, but a private
        # one is also hidden from everyone who is neither in it nor allowed to
        # manage threads there. The member cache is rarely complete, so a miss
        # is confirmed with the API.
        if perms.manage_threads or any(m.id == member.id for m in channel.members):
            return True
        try:
            return any(m.id == member.id for m in await channel.fetch_members())
        except discord.HTTPException:
            return False
    return True


async def resolve_text_channel(ctx: YuukaContext, text: str) -> discord.TextChannel | discord.Thread:
    """A text channel or active thread the requester can see, by mention, id or name."""
    guild, member = ctx.guild, ctx.requester
    raw = text.strip()

    match = _CHANNEL_MENTION.match(raw)
    if match or raw.isdigit():
        channel = guild.get_channel_or_thread(int(match.group(1) if match else raw))
        if isinstance(channel, (discord.TextChannel, discord.Thread)) and await can_view(member, channel):
            return channel

    wanted, key = _clean(raw), channel_key(raw)
    candidates = [*guild.text_channels, *guild.threads]
    for channel in candidates:
        if channel.name.casefold() == wanted and await can_view(member, channel):
            return channel
    if key:
        for channel in candidates:
            if channel_key(channel.name) == key and await can_view(member, channel):
                return channel

    # Partial matches and suggestions come only from channels the requester can
    # already see. Private threads are left out: checking each one could cost an API call.
    visible = [c for c in guild.text_channels if c.permissions_for(member).view_channel]
    visible += [t for t in guild.threads if not t.is_private() and t.permissions_for(member).view_channel]
    if partial := _only_partial(key, visible):
        return partial
    raise UserWarning("หาช่องนั้นไม่เจอค่ะ", f"ไม่มีช่อง '{raw}' ในเซิร์ฟเวอร์นี้นะคะ.{_suggest(raw, visible)}")


_USER_MENTION = re.compile(r"^<@!?(\d+)>$")

# What the model writes when the requester means themselves ("kick me", "เตะตัวเอง").
_SELF = frozenset({"me", "myself", "self", "i", "ผม", "ฉัน", "เรา", "กู", "ตัวเอง", "ตัวผม", "ตัวฉัน"})


def _names(member: discord.Member) -> set[str]:
    names = {member.display_name, member.name, member.global_name or ""}
    return {n.casefold() for n in names if n}


def exact_member(guild: discord.Guild, text: str) -> discord.Member | None:
    """The member `text` names exactly (a mention, an id, or the whole display, user or global
    name), or None. Unlike `resolve_member`, a part of a name or a name two members share is not
    a match: it is for deciding whether a word is a person at all."""
    raw = text.strip()
    match = _USER_MENTION.match(raw)
    if match or raw.isdigit():
        member = guild.get_member(int(match.group(1) if match else raw))
        if member:
            return member
    wanted = raw.lstrip("@").strip().casefold()
    if not wanted:
        return None
    found = [m for m in guild.members if wanted in _names(m)]
    return found[0] if len(found) == 1 else None


def resolve_member(ctx: YuukaContext, text: str) -> discord.Member:
    """A member of the requester's guild, by mention, id, or display/user name; "me" is the requester."""
    guild = ctx.guild
    raw = text.strip()

    match = _USER_MENTION.match(raw)
    if match or raw.isdigit():
        member = guild.get_member(int(match.group(1) if match else raw))
        if member:
            return member

    wanted = raw.lstrip("@").strip().casefold()
    if wanted in _SELF and ctx.requester is not None:
        return ctx.requester

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


def resolve_member_in(ctx: YuukaContext, text: str, members: list[discord.Member]) -> discord.Member:
    """Like `resolve_member`, but tried among `members` first (the people in a voice channel), so a
    short or partial name picks the one in the room over namesakes elsewhere in the server."""
    wanted = text.strip().lstrip("@").strip().casefold()
    if wanted and wanted not in _SELF and not _USER_MENTION.match(text.strip()) and not wanted.isdigit():
        here = [m for m in members if wanted in _names(m)]
        here = here or [m for m in members if any(wanted in n for n in _names(m))]
        if len(here) == 1:
            return here[0]
        if here:
            listed = ", ".join(m.display_name for m in here[:5])
            raise UserWarning("หลายคนชื่อคล้ายกันค่ะ", f"'{text.strip()}' ตรงกับหลายคนในห้อง: {listed} ช่วยระบุให้ชัดขึ้นหน่อยนะคะ")
    return resolve_member(ctx, text)


_ROLE_MENTION = re.compile(r"^<@&(\d+)>$")


def resolve_role(ctx: YuukaContext, text: str) -> discord.Role:
    """A role of the requester's guild, by mention, id or name."""
    guild = ctx.guild
    raw = text.strip()

    match = _ROLE_MENTION.match(raw)
    if match or raw.isdigit():
        role = guild.get_role(int(match.group(1) if match else raw))
        if role:
            return role

    wanted = raw.lstrip("@").strip().casefold()
    exact = [r for r in guild.roles if r.name.lstrip("@").casefold() == wanted]
    found = exact or [r for r in guild.roles if wanted and wanted in r.name.casefold()]
    if len(found) == 1:
        return found[0]
    if found:
        listed = ", ".join(r.name for r in found[:5])
        raise UserWarning("หลายยศชื่อคล้ายกันค่ะ", f"'{raw}' ตรงกับหลายยศ: {listed} ช่วยระบุให้ชัดขึ้นหน่อยนะคะ")

    close = difflib.get_close_matches(wanted, [r.name.casefold() for r in guild.roles], n=3, cutoff=0.5)
    hint = f" ใกล้เคียง: {', '.join(close)}" if close else ""
    raise UserWarning("หายศนั้นไม่เจอค่ะ", f"ไม่มียศชื่อ '{raw}' ในเซิร์ฟเวอร์นี้นะคะ.{hint}")


def resolve_voice_channel(ctx: YuukaContext, text: str) -> discord.VoiceChannel:
    """A voice channel the requester can see, by mention, id or name."""
    visible = [c for c in ctx.guild.voice_channels if c.permissions_for(ctx.requester).view_channel]
    raw = text.strip()

    match = _CHANNEL_MENTION.match(raw)
    if match or raw.isdigit():
        wanted_id = int(match.group(1) if match else raw)
        for channel in visible:
            if channel.id == wanted_id:
                return channel

    wanted, key = _clean(raw), channel_key(raw)
    for channel in visible:
        if channel.name.casefold() == wanted:
            return channel
    if key:
        for channel in visible:
            if channel_key(channel.name) == key:
                return channel
    if partial := _only_partial(key, visible):
        return partial

    raise UserWarning("หาห้องเสียงนั้นไม่เจอค่ะ", f"ไม่มีห้องเสียง '{raw}' นะคะ.{_suggest(raw, visible)}")
